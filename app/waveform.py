from __future__ import annotations

import json
import math
import struct
import subprocess
from pathlib import Path

from .ffmpeg import ffmpeg_path


DEFAULT_BUCKET_COUNT = 240


def _cache_path(audio_path: Path) -> Path:
    return audio_path.with_name("waveform.json")


def _source_marker(audio_path: Path, bucket_count: int) -> dict[str, int | str]:
    stat = audio_path.stat()
    return {
        "audioFile": audio_path.name,
        "audioMtimeNs": stat.st_mtime_ns,
        "audioSize": stat.st_size,
        "bucketCount": bucket_count,
    }


def _read_cached_peaks(audio_path: Path, marker: dict[str, int | str]) -> list[float] | None:
    try:
        payload = json.loads(_cache_path(audio_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in marker.items()):
        return None
    peaks = payload.get("peaks")
    if not isinstance(peaks, list) or not peaks:
        return None
    normalized = []
    for peak in peaks:
        if isinstance(peak, bool):
            return None
        try:
            numeric = float(peak)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric) or numeric < 0 or numeric > 1:
            return None
        normalized.append(round(numeric, 4))
    return normalized


def _decode_mono_samples(audio_path: Path) -> list[float]:
    completed = subprocess.run(
        [
            ffmpeg_path(), "-v", "error", "-i", str(audio_path),
            "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    usable_bytes = len(completed.stdout) - (len(completed.stdout) % 4)
    if usable_bytes <= 0:
        return []
    return [sample[0] for sample in struct.iter_unpack("<f", completed.stdout[:usable_bytes])]


def _bucket_peaks(samples: list[float], bucket_count: int) -> list[float]:
    if not samples:
        return []
    absolute = [abs(sample) if math.isfinite(sample) else 0.0 for sample in samples]
    maximum = max(absolute, default=0.0)
    if maximum <= 0:
        return [0.0] * bucket_count
    peaks = []
    sample_count = len(absolute)
    for index in range(bucket_count):
        start = math.floor(index * sample_count / bucket_count)
        end = max(start + 1, math.floor((index + 1) * sample_count / bucket_count))
        peaks.append(round(min(1.0, max(absolute[start:end]) / maximum), 4))
    return peaks


def audio_waveform_peaks(audio_path: Path, bucket_count: int = DEFAULT_BUCKET_COUNT) -> list[float]:
    """Return cached, normalized local-audio peaks for the split timeline."""
    if bucket_count <= 0 or not audio_path.is_file() or audio_path.stat().st_size <= 0:
        return []
    try:
        marker = _source_marker(audio_path, bucket_count)
        cached = _read_cached_peaks(audio_path, marker)
        if cached is not None:
            return cached
        peaks = _bucket_peaks(_decode_mono_samples(audio_path), bucket_count)
        if not peaks:
            return []
        _cache_path(audio_path).write_text(
            json.dumps({**marker, "peaks": peaks}, ensure_ascii=False), encoding="utf-8"
        )
        return peaks
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
