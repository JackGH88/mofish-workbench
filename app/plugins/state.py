"""插件生命周期状态的本地存储。

只保存安装、启用与配置等非机密状态；机密值一律交给系统凭据库，不落在这里。
文件权限 0600，写入使用原子替换，避免半截文件。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional


class PluginStateStore:
    def __init__(self, path: object) -> None:
        self._path = Path(path)  # type: ignore[arg-type]
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = value
        return result

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".plugins-", suffix=".json.tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read(self, plugin_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._read().get(plugin_id) or {})

    def read_all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._read()

    def update(self, plugin_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            current = dict(data.get(plugin_id) or {})
            current.update(changes)
            data[plugin_id] = current
            self._write(data)
            return current

    def replace(self, plugin_id: str, value: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data[plugin_id] = dict(value)
            self._write(data)

    def remove(self, plugin_id: str) -> None:
        with self._lock:
            data = self._read()
            if plugin_id in data:
                data.pop(plugin_id)
                self._write(data)

    def migrate_legacy(self, plugin_id: str, scoped_key: str, prepare) -> None:
        # Hold the same lock as ordinary writes, and commit the marker with the state.
        with self._lock:
            data = self._read()
            legacy = data.get(plugin_id)
            if not legacy or legacy.get("migratedTo"):
                return
            if scoped_key not in data:
                prepare()
                data[scoped_key] = dict(legacy)
            data[plugin_id] = {**legacy, "migratedTo": scoped_key}
            self._write(data)
