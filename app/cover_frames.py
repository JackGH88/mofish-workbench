"""Local cover-reference extraction; no image libraries or remote model calls."""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from .ffmpeg import ffmpeg_path, ffprobe_path


class CoverFrameError(Exception):
    pass


def frame_score(pixels: bytes, width: int = 160) -> tuple[bool, float]:
    if not pixels or len(pixels) < width * 2 or len(pixels) % width:
        raise CoverFrameError("视频帧数据无效。")
    count = len(pixels)
    mean = sum(pixels) / count
    contrast = math.sqrt(sum((value - mean) ** 2 for value in pixels) / count)
    edges = sum(abs(pixels[i] - pixels[i - 1]) for i in range(1, count) if i % width)
    edges += sum(abs(pixels[i] - pixels[i - width]) for i in range(width, count))
    sharpness = edges / (2 * count - width - count // width)
    extreme = sum(value < 16 or value > 239 for value in pixels) / count
    usable = extreme < 0.95 and 12 < mean < 243 and contrast > 3
    exposure = max(0, 1 - abs(mean - 127.5) / 127.5)
    return usable, sharpness * 0.6 + contrast * 0.3 + exposure * 10


def extract_cover_frame(source: Path, destination: Path) -> float:
    """Select from integer timestamps in [0, 5), preserving source aspect ratio."""
    try:
        probe = subprocess.run(
            [ffprobe_path(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
            check=True, capture_output=True, timeout=10,
        )
        duration = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
        timestamps = [0] + [second for second in range(1, 5) if second < duration]
        best = None
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cover-frames-", dir=destination.parent) as temporary:
            for second in timestamps:
                frame = Path(temporary) / f"{second}.jpg"
                command = [ffmpeg_path(), "-nostdin", "-v", "error", "-ss", str(second), "-i", str(source),
                           "-map", "0:v:0", "-t", str(5 - second), "-frames:v", "1"]
                subprocess.run(command + ["-q:v", "2", str(frame)], check=True, capture_output=True, timeout=15)
                if not frame.is_file():
                    continue
                raw = subprocess.run(
                    [ffmpeg_path(), "-nostdin", "-v", "error", "-i", str(frame), "-vf", "scale=160:-1,format=gray",
                     "-frames:v", "1", "-f", "rawvideo", "pipe:1"],
                    check=True, capture_output=True, timeout=10,
                )
                score = frame_score(raw.stdout)
                if best is None or score > best[0]:
                    best = (score, second, frame)
            if best is None:
                raise CoverFrameError("未能从关联视频提取有效画面。")
            best[2].replace(destination)
            return float(best[1])
    except FileNotFoundError as exc:
        raise CoverFrameError("未找到 FFmpeg 或 ffprobe，请检查工作台安装。") from exc
    except subprocess.TimeoutExpired as exc:
        raise CoverFrameError("视频抽帧超时，请检查关联视频后重试。") from exc
    except (subprocess.CalledProcessError, OSError, ValueError, TypeError) as exc:
        raise CoverFrameError("关联视频无法读取或解码，请重新关联有效视频。") from exc
