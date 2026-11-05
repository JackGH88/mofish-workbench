"""Resolve tools recorded by this project's installer, then the process PATH.

Record contract: {"tools": {"git": "/absolute/path/to/git", ...}}.
The record is local executable configuration, not a source of command arguments.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_tool(name: str, root=None) -> str | None:
    """Ignore malformed/stale records. Never interpret shell syntax or relative paths."""
    if not isinstance(name, str) or not name or any(c in name for c in '/\\\x00'):
        return None
    record = Path(root) if root is not None else PROJECT_ROOT
    try:
        with (record / 'workspace' / 'install' / 'state.json').open(encoding='utf-8') as handle:
            raw = handle.read(65537)
        value = json.loads(raw) if len(raw) <= 65536 else None
        mapping = value.get('tools') if isinstance(value, dict) else None
        candidate = mapping.get(name) if isinstance(mapping, dict) else None
        if isinstance(candidate, str) and '\x00' not in candidate:
            path = Path(candidate)
            if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
                return str(path)
    except (OSError, ValueError):
        pass
    return shutil.which(name)
