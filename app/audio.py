from __future__ import annotations

import subprocess
from pathlib import Path

from .ffmpeg import ffmpeg_path


class AudioPreparationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def extract_mp3(video_path: Path, output_path: Path) -> Path:
    """Extract a local MP3 for direct upload: mono, 16 kHz, 64 kbps.

    与平台转写接口的音频直传限制对齐：单声道 16k / 64kbps 的 MP3 体积最小、
    识别效果稳定，避免把原视频交给平台。
    """
    try:
        subprocess.run(
            [
                ffmpeg_path(), "-y", "-i", str(video_path), "-vn",
                "-ac", "1", "-ar", "16000", "-codec:a", "libmp3lame", "-b:a", "64k",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AudioPreparationError("ffmpeg_not_available", "未检测到 ffmpeg，无法从视频中提取音频。") from exc
    except subprocess.CalledProcessError as exc:
        raise AudioPreparationError("audio_extract_failed", "未能从视频中提取可用音频。") from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise AudioPreparationError("audio_extract_failed", "未能从视频中提取可用音频。")
    return output_path


def prepare_audio(video_path: Path, independent_audio_path: Path | None) -> Path:
    """Keep media_service's independent audio when present, otherwise extract MP3."""
    if independent_audio_path and independent_audio_path.is_file() and independent_audio_path.stat().st_size:
        return independent_audio_path
    return extract_mp3(video_path, video_path.with_name("audio.mp3"))
