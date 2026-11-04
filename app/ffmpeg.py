from __future__ import annotations

import shutil
from .runtime import DESKTOP, RESOURCE_ROOT


_HOMEBREW_BINARIES = ("/opt/homebrew/bin", "/usr/local/bin")


def _binary_path(name: str) -> str:
    """Resolve media tools when a GUI-launched process has a minimal PATH."""
    if DESKTOP:
        bundled = RESOURCE_ROOT.parent / "tools" / name
        if not bundled.is_file():
            raise FileNotFoundError(f"安装包缺少 {name}，请重新安装墨鱼工作台。")
        return str(bundled)
    for candidate in (name, *(f"{directory}/{name}" for directory in _HOMEBREW_BINARIES)):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return name


def ffmpeg_path() -> str:
    return _binary_path("ffmpeg")


def ffprobe_path() -> str:
    return _binary_path("ffprobe")
