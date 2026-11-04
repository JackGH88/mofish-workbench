"""本地音视频素材的暂存与探测。

「视频转文案」的本地来源需要先把素材交给创作服务，平台再据此转写。这里只负责：

* 把用户选中的文件落到工作台自己的暂存目录，返回一个可复用的素材号；
* 用本地 ffprobe 探一次时长，用于给本次转写估算费用上限；
* 保证文件名与大小校验在本地先拦一道，避免把明显不支持的素材送到平台。

暂存文件不进入浏览器存储，也不写日志；真正上传到平台发生在提交任务时。
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .media_download import DOWNLOAD_DIR
from .ffmpeg import ffprobe_path

STAGING_DIR = DOWNLOAD_DIR / "_creation-media"
# 与创作服务 /v1/uploads 支持的格式保持一致，先在本地拦掉不支持的素材。
ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4a", ".mp3", ".wav", ".aac", ".flac", ".mkv", ".webm", ".avi"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


class MediaStagingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def safe_filename(name: str) -> str:
    """只保留基础文件名，避免路径穿越；校验扩展名是否可用。"""
    cleaned = Path(str(name or "")).name.strip()
    if not cleaned or cleaned in {".", ".."} or "\\" in cleaned:
        raise MediaStagingError("unsupported_input", "素材文件名无效，请重新选择文件。")
    if len(cleaned) > 160:
        cleaned = cleaned[:160]
    if Path(cleaned).suffix.lower() not in ALLOWED_SUFFIXES:
        raise MediaStagingError("unsupported_input", "不支持的媒体格式，请选择常见的音视频文件。")
    return cleaned


def probe_duration(path: Path) -> float:
    """用本地 ffprobe 探测时长；探测不到返回 0，由调用方退回默认上限。"""
    try:
        completed = subprocess.run(
            [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True,
        )
        value = float(str(completed.stdout).strip())
        return value if value > 0 else 0.0
    except Exception:  # noqa: BLE001 - 探测失败不是错误，按默认上限处理
        return 0.0


def stage_upload(stream: BinaryIO, filename: str) -> "dict[str, Any]":
    """把上传的素材落到暂存目录，返回素材号、时长与大小。"""
    name = safe_filename(filename)
    media_id = "CM-" + uuid.uuid4().hex[:12]
    suffix = Path(name).suffix.lower()
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    target = STAGING_DIR / (media_id + suffix)
    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = stream.read(_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise MediaStagingError("unsupported_input", "素材超过大小上限，请选择更小的文件。", 413)
                handle.write(chunk)
    except MediaStagingError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise MediaStagingError("media_stage_failed", "素材保存失败，请检查磁盘空间后重试。", 500) from exc
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    if written <= 0:
        target.unlink(missing_ok=True)
        raise MediaStagingError("unsupported_input", "素材内容为空，请重新选择文件。")
    return {
        "mediaId": media_id,
        "name": name,
        "path": str(target),
        "sizeBytes": written,
        "durationSeconds": round(probe_duration(target), 2),
    }


def resolve_staged(media_id: str) -> "dict[str, Any] | None":
    """按素材号找回已暂存的素材；找不到返回 None。"""
    cleaned = str(media_id or "").strip()
    if not cleaned or Path(cleaned).name != cleaned:
        return None
    if not STAGING_DIR.is_dir():
        return None
    for path in sorted(STAGING_DIR.glob(cleaned + ".*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
            return {
                "mediaId": cleaned,
                "name": path.name,
                "path": str(path),
                "sizeBytes": path.stat().st_size,
                "durationSeconds": round(probe_duration(path), 2),
            }
    return None


def discard_staged(path: "str | Path") -> None:
    """任务取消或素材失效时清掉暂存件；失败不影响主流程。"""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
