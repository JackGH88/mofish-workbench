"""Local media helpers for platform-owned creation tasks."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any
from .runtime import RESOURCE_ROOT as PROJECT_ROOT, DATA_ROOT, LOG_ROOT
DOWNLOAD_DIR = DATA_ROOT / "downloads"
LOG_DIR = LOG_ROOT

class DownloadError(Exception):
    def __init__(self, code: str, message: str, suggestion: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.status_code = status_code



def extract_douyin_url(text: str) -> str | None:
    """Extract a supported Douyin or WeChat video-channel URL from share text."""
    if not text or not text.strip():
        return None

    # Collected Douyin shares use this landing-page URL. The platform accepts the
    # canonical video URL; omit device/tracking parameters from the API request.
    landing = re.search(
        r"https?://(?:www\.)?iesdouyin\.com/share/video/([0-9]+)(?=[/?#\s，。；;!！)）]|$)",
        text,
        re.IGNORECASE,
    )
    if landing:
        return f"https://www.douyin.com/video/{landing.group(1)}"

    patterns = (
        r"https?://v\.douyin\.com/[^\s]+",
        r"https?://(?:www\.)?douyin\.com/(?:video|note)/[^\s]+",
        r"https?://(?:www\.)?douyin\.com/user/[^\s]+modal_id=\d+[^\s]*",
        r"https?://(?:www\.)?weixin\.qq\.com/sph/[^\s]+",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).rstrip("，。；;,.!！?？)）]】\"'")

    return None



def extract_aweme_id_from_url(url: str) -> str | None:
    patterns = (
        r"douyin\.com/video/(\d+)",
        r"douyin\.com/note/(\d+)",
        r"douyin\.com/user/([^/?]+)\?modal_id=(\d+)",
        r"modal_id=(\d+)",
        r"aweme_id=(\d+)",
        r"video/(\d+)",
        r"item_id=(\d+)",
    )

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(2) if "modal_id" in pattern and match.lastindex and match.lastindex >= 2 else match.group(1)

    return None



def generate_unique_filename(output_dir: Path, base_name: str, extension: str = ".mp4") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[/\\:*?"<>|]', "_", base_name).strip()[:80] or "douyin_video"
    output_path = output_dir / f"{safe_name}{extension}"

    if not output_path.exists():
        return output_path

    digest = hashlib.sha1(base_name.encode("utf-8")).hexdigest()[:6]
    counter = 1
    while True:
        output_path = output_dir / f"{safe_name}_{digest}_{counter}{extension}"
        if not output_path.exists():
            return output_path
        counter += 1



def generate_download_video_path(output_dir: Path, base_name: str) -> Path:
    """Reserve a dedicated directory for one download and return its video path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[/\\:*?"<>|]', "_", base_name).strip()[:80] or "douyin_video"
    download_dir = output_dir / safe_name

    if download_dir.exists():
        digest = hashlib.sha1(base_name.encode("utf-8")).hexdigest()[:6]
        counter = 1
        while download_dir.exists():
            download_dir = output_dir / f"{safe_name}_{digest}_{counter}"
            counter += 1

    download_dir.mkdir(parents=True, exist_ok=False)
    return download_dir / "video.mp4"



def download_media_direct(media_url: str, output_path: Path, *, timeout: int = 180) -> tuple[bool, int]:
    """按上游直链把媒体下载到本地；返回 (是否成功, HTTP 状态码)。

    工作台负责本地下载：直链由平台下发、有有效期，过期会返回 401/403/404/410，
    调用方据此区分「暂时下载失败可重试」与「直链过期需重新解析」。
    """
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    try:
        with requests.get(str(media_url), headers=headers, stream=True, timeout=timeout) as response:
            status = int(response.status_code)
            if response.status_code != 200:
                return False, status
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=262144):
                    if chunk:
                        handle.write(chunk)
    except Exception:  # noqa: BLE001 - 网络抖动属可重试的下载失败
        output_path.unlink(missing_ok=True)
        return False, 0
    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return False, 0
    return True, 200



def health_status() -> dict[str, Any]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    writable_probe = DOWNLOAD_DIR / ".write-test"
    download_dir_writable = False
    try:
        writable_probe.write_text("ok", encoding="utf-8")
        writable_probe.unlink(missing_ok=True)
        download_dir_writable = True
    except Exception:
        download_dir_writable = False

    return {
        "status": "ok",
        "downloadDir": str(DOWNLOAD_DIR),
        "downloadDirWritable": download_dir_writable,
    }
