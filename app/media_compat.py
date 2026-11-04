from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ffmpeg import ffmpeg_path, ffprobe_path


@dataclass(frozen=True)
class SafariCompatibility:
    status: str
    playback_path: Path
    reason: str = ""


@dataclass(frozen=True)
class PreviewPoster:
    status: str
    poster_path: Path | None = None
    reason: str = ""


def _status_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}.safari.json")


def _poster_status_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}.poster.json")


def _write_poster_status(source_path: Path, result: PreviewPoster) -> None:
    status_path = _poster_status_path(source_path)
    temporary_path = status_path.with_name(f"{status_path.name}.{uuid.uuid4().hex}.partial")
    temporary_path.write_text(
        json.dumps(
            {
                "status": result.status,
                "posterFile": result.poster_path.name if result.poster_path else "",
                "reason": result.reason,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary_path.replace(status_path)


def _source_cover_path(source_path: Path) -> Path | None:
    """Return a task-local, browser-safe source cover when one was downloaded."""
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    try:
        metadata = json.loads(source_path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    cover_file = metadata.get("cover_file") if isinstance(metadata, dict) else None
    candidates: list[Path] = []
    if isinstance(cover_file, str) and cover_file:
        candidates.append(Path(cover_file))
    candidates.extend(source_path.with_name(f"{source_path.stem}.cover{extension}") for extension in allowed_extensions)
    task_directory = source_path.parent.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.parent != task_directory or resolved.suffix.lower() not in allowed_extensions:
            continue
        if resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def preview_poster_status(source_path: Path) -> PreviewPoster:
    source_cover = _source_cover_path(source_path)
    if source_cover:
        return PreviewPoster("ready", source_cover)
    poster_path = source_path.with_name(f"{source_path.stem}.poster.jpg")
    if poster_path.is_file() and poster_path.stat().st_size > 0:
        return PreviewPoster("ready", poster_path)
    try:
        payload = json.loads(_poster_status_path(source_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PreviewPoster("pending") if source_path.is_file() else PreviewPoster("unavailable")
    if not isinstance(payload, dict):
        return PreviewPoster("pending") if source_path.is_file() else PreviewPoster("unavailable")
    if str(payload.get("status") or "") == "failed":
        return PreviewPoster("failed", reason=str(payload.get("reason") or ""))
    return PreviewPoster("pending") if source_path.is_file() else PreviewPoster("unavailable")


def _extract_preview_frame(source_path: Path, destination: Path) -> None:
    subprocess.run(
        [ffmpeg_path(), "-y", "-i", str(source_path), "-frames:v", "1", "-q:v", "2", str(destination)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise OSError("ffmpeg 未生成视频首帧")


_publish_poster_lock = threading.Lock()


def ensure_publish_preview_poster(source_path: Path) -> Path:
    """Cache a first frame by source identity; never substitute a cover image."""
    with _publish_poster_lock:
        stat = source_path.stat()
        fingerprint = f"{source_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
        key = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
        poster = source_path.with_name(f".publish-preview-{key}.jpg")
        if poster.is_file() and not poster.is_symlink() and poster.stat().st_size:
            return poster
        temporary = source_path.with_name(f".publish-preview-{uuid.uuid4().hex}.partial.jpg")
        try:
            _extract_preview_frame(source_path, temporary)
            after = source_path.stat()
            if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                raise OSError("视频已替换，请重新加载预览")
            temporary.replace(poster)
        finally:
            temporary.unlink(missing_ok=True)
        return poster


def ensure_preview_poster(source_path: Path) -> PreviewPoster:
    """Create a stable JPEG first-frame poster only when no source cover exists."""
    existing = preview_poster_status(source_path)
    if existing.status == "ready" or not source_path.is_file():
        return existing
    poster_path = source_path.with_name(f"{source_path.stem}.poster.jpg")
    temporary_path = poster_path.with_name(f"{source_path.stem}.poster.{uuid.uuid4().hex}.partial.jpg")
    try:
        _extract_preview_frame(source_path, temporary_path)
        temporary_path.replace(poster_path)
        result = PreviewPoster("ready", poster_path)
        _write_poster_status(source_path, result)
        return result
    except (subprocess.SubprocessError, OSError) as exc:
        temporary_path.unlink(missing_ok=True)
        result = PreviewPoster("failed", reason=str(exc))
        _write_poster_status(source_path, result)
        return result


def _write_status(source_path: Path, result: SafariCompatibility) -> None:
    status_path = _status_path(source_path)
    temporary_path = status_path.with_name(f"{status_path.name}.{uuid.uuid4().hex}.partial")
    temporary_path.write_text(
        json.dumps(
            {
                "status": result.status,
                "playbackFile": result.playback_path.name,
                "reason": result.reason,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary_path.replace(status_path)


def safari_compatibility_status(source_path: Path) -> SafariCompatibility:
    compatible_path = source_path.with_name(f"{source_path.stem}.safari.mp4")
    if compatible_path.is_file() and compatible_path.stat().st_size > 0:
        return SafariCompatibility("ready", compatible_path)
    try:
        payload = json.loads(_status_path(source_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SafariCompatibility("pending", source_path)
    if not isinstance(payload, dict):
        return SafariCompatibility("pending", source_path)
    status = str(payload.get("status") or "pending")
    playback_path = source_path.parent / str(payload.get("playbackFile") or source_path.name)
    if status == "ready" and playback_path.is_file() and playback_path.stat().st_size > 0:
        return SafariCompatibility("ready", playback_path)
    if status == "failed":
        return SafariCompatibility("failed", source_path, str(payload.get("reason") or ""))
    return SafariCompatibility("pending", source_path)


def probe_media(video_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [ffprobe_path(), "-v", "error", "-show_streams", "-of", "json", str(video_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout or "{}")
    return payload if isinstance(payload, dict) else {}


def is_safari_compatible(probe: dict[str, Any]) -> bool:
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list):
        return False

    video = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"), None)
    if not isinstance(video, dict):
        return False

    video_ok = (
        str(video.get("codec_name") or "").lower() == "h264"
        and str(video.get("profile") or "") in {"Baseline", "Constrained Baseline", "Main", "High"}
        and int(video.get("level") or 0) <= 42
        and str(video.get("pix_fmt") or "").lower() == "yuv420p"
    )
    audio_ok = audio is None or (
        isinstance(audio, dict)
        and str(audio.get("codec_name") or "").lower() == "aac"
        and str(audio.get("profile") or "") == "LC"
    )
    return video_ok and audio_ok


def ensure_safari_compatible(source_path: Path) -> SafariCompatibility:
    """Return a Safari-safe copy for risky local MP4 media, preserving the source."""
    compatible_path = source_path.with_name(f"{source_path.stem}.safari.mp4")
    if compatible_path.is_file() and compatible_path.stat().st_size > 0:
        result = SafariCompatibility("ready", compatible_path)
        _write_status(source_path, result)
        return result

    try:
        if is_safari_compatible(probe_media(source_path)):
            result = SafariCompatibility("ready", source_path)
            _write_status(source_path, result)
            return result
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        result = SafariCompatibility("failed", source_path, str(exc))
        _write_status(source_path, result)
        return result

    temporary_path = compatible_path.with_name(f"{compatible_path.stem}.partial.mp4")
    try:
        subprocess.run(
            [
                ffmpeg_path(), "-y", "-i", str(source_path),
                "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
                "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p",
                "-crf", "20", "-preset", "veryfast",
                "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "160k",
                "-movflags", "+faststart", str(temporary_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise OSError("ffmpeg 未生成兼容视频")
        temporary_path.replace(compatible_path)
        result = SafariCompatibility("ready", compatible_path)
        _write_status(source_path, result)
        return result
    except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
        temporary_path.unlink(missing_ok=True)
        result = SafariCompatibility("failed", source_path, str(exc))
        _write_status(source_path, result)
        return result
