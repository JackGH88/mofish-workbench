"""插件注册表：加载内置插件、维护通用生命周期、托管凭据与路由挂载。

宿主在这里只处理通用概念（清单、安装/启用/配置、凭据引用、脚本快照、媒体目录），
不出现任何供应商字段；供应商能力由插件包自己的路由与适配器实现。
"""
from __future__ import annotations

import importlib
import inspect
import logging
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .manifest import PluginManifest, build_manifest
from .state import PluginStateStore

logger = logging.getLogger("workbench.plugins")


class PluginError(Exception):
    """可预期的插件操作错误，路由层翻译成中文 HTTP 提示。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class PluginContext:
    """宿主提供给插件的受控能力入口。

    插件只能通过这里与宿主交互：凭据引用、脚本快照、受控媒体目录与自己的路由。
    """

    def __init__(self, registry: "PluginRegistry", manifest: PluginManifest) -> None:
        self._registry = registry
        self.manifest = manifest
        self.router = APIRouter(dependencies=[Depends(registry.account_dependency)])

    @property
    def plugin_id(self) -> str:
        return self.manifest.id

    @property
    def account_id(self) -> str:
        return self._registry.account_id

    def notify_script_changed(self, script_id: str) -> None:
        """Publish a non-sensitive invalidation on the request event loop."""
        from .events import hub
        hub.publish(self.account_id, self.plugin_id, script_id)

    async def wait_script_changed(self, plugin_id: str, script_id: str, timeout: float = 30) -> None:
        """Wait for a scoped peer invalidation; timeout permits durable-state recovery."""
        import asyncio
        from .events import hub
        with hub.subscribe(self.account_id) as queue:
            async def wait():
                while True:
                    event = await queue.get()
                    if event.get('resync') or (event.get('pluginId') == plugin_id and event.get('scriptId') == script_id):
                        return
            try:
                await asyncio.wait_for(wait(), timeout)
            except asyncio.TimeoutError:
                pass

    def notify_return(self, script_id: str, notice: dict) -> None:
        from .events import hub
        keys = ('id', 'resultId', 'taskId', 'status', 'message', 'success')
        hub.publish(self.account_id, self.plugin_id, script_id,
                    {key: notice[key] for key in keys if key in notice})

    def installation_id(self) -> str:
        raw = self._registry._state.read(self._registry._state_key(self.plugin_id))
        return str(raw.get("installationId") or raw.get("installedAt") or "")

    def service(self, name: str):
        callback = self._registry.services.get(name)
        if callback is None:
            raise PluginError("host_upgrade_required", "请升级工作台后再使用此插件。", 409)
        return callback

    def credential(self, account_id: Optional[str] = None) -> Optional[str]:
        if account_id is not None:
            with self._registry.account_scope(account_id):
                return self._registry.credential_value(self.manifest.id)
        return self._registry.credential_value(self.manifest.id)

    def save_credential(self, value: str):
        """Persist this plugin's credentials through the existing account-scoped keychain."""
        return self._registry.set_credential(self.plugin_id, value)

    def peer_context(self, plugin_id: str):
        """Resolve a loaded peer in the same workspace registry, preserving account scope."""
        return self._registry._require_entry(plugin_id).context

    def require_credential(self) -> str:
        value = self.credential()
        if not value:
            raise PluginError("credential_missing", "尚未配置凭据，请先在插件详情中保存。", 409)
        return value

    def is_active(self) -> bool:
        view = self._registry.state_view(self.manifest.id)
        return bool(view.get("installed")) and bool(view.get("enabled"))

    def script_snapshot(self, script_id: str) -> Optional[dict[str, Any]]:
        return self._registry.script_snapshot(script_id)

    def media_dir(self) -> Path:
        return self._registry.plugin_media_dir(self.manifest.id)


class _Entry:
    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        self.manifest = manifest
        self.context = context
        self.verify: Optional[Callable[..., Any]] = None
        self.has_active_tasks: Optional[Callable[..., Any]] = None
        self.owns_media: Optional[Callable[..., bool]] = None
        self.load_error: Optional[str] = None


class PluginRegistry:
    def __init__(
        self,
        state_store: PluginStateStore,
        credential_store: Any,
        *,
        script_snapshot: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
        media_root: Optional[object] = None,
        clock: Optional[Callable[[], str]] = None,
        account_exists: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.services = {}
        self._account = ContextVar("plugin_account", default=None)
        self._account_exists = account_exists
        self._state = state_store
        self._credentials = credential_store
        self._local_entries: dict[str, _Entry] = {}
        # 加载失败的插件（目录存在但导入/清单/注册失败），供健康检查发现。
        self._failures: list[dict[str, Any]] = []
        self._script_snapshot = script_snapshot
        self._media_root = Path(media_root) if media_root else None  # type: ignore[arg-type]
        self._clock = clock or self._default_clock

    @property
    def _entries(self):
        if getattr(getattr(self, "packages", None), "workspace_scoped", False):
            account = self._account.get()
            return self.packages.for_account(account).registry._entries if account else {}
        return self._local_entries

    @property
    def account_id(self) -> str:
        account_id = self._account.get()
        if not account_id:
            raise PluginError("account_required", "请先选择工作台。", 422)
        return account_id

    @contextmanager
    def account_scope(self, account_id: str):
        if not account_id or (self._account_exists and not self._account_exists(account_id)):
            raise PluginError("account_not_found", "工作台不存在。", 404)
        token = self._account.set(account_id)
        try:
            yield
        finally:
            self._account.reset(token)

    async def account_dependency(self, accountId: str = Query(..., min_length=1, max_length=100)):
        # Async dependency preserves ContextVar through async handlers and worker threads.
        try:
            with self.account_scope(accountId):
                starter = getattr(getattr(self, 'packages', None), 'ensure_account_runtimes', None)
                if starter is not None:
                    await starter(accountId)
                yield accountId
        except PluginError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from None

    def _state_key(self, plugin_id: str) -> str:
        return json.dumps([self.account_id, plugin_id], ensure_ascii=True, separators=(",", ":"))

    def legacy_migration_owner(self) -> Optional[str]:
        return self._state.read("$workspaceMigration").get("accountId")

    def migrate_legacy(self, account_id: str) -> None:
        """Copy legacy configuration once; retain the original non-secret record as backup."""
        with self.account_scope(account_id):
            owner = self.legacy_migration_owner()
            if owner and owner != account_id:
                raise PluginError("migration_owner_conflict", "旧配置已指定给其他工作台。", 409)
            # Persist the explicit choice before copying credentials so startup can retry safely.
            self._state.update("$workspaceMigration", {"accountId": account_id})
            for plugin_id in self._entries:
                def prepare():
                    if not self._credentials.available():
                        raise PluginError("credential_store_unavailable", "密钥库不可用，旧配置迁移未完成。", 503)
                    secret = self._credentials.get(plugin_id)
                    ref = self._cred_ref(plugin_id)
                    if secret and not self._credentials.get(ref):
                        self._credentials.set(ref, secret)
                        if self._credentials.get(ref) != secret:
                            raise PluginError("migration_failed", "旧凭据迁移失败。", 503)
                self._state.migrate_legacy(plugin_id, self._state_key(plugin_id), prepare)

    @staticmethod
    def _default_clock() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ------------------------------------------------------------------ 加载

    def record_failure(self, source: str, stage: str, message: str) -> None:
        self._failures.append({"source": str(source), "stage": str(stage), "message": str(message)})

    def register_module(self, module: Any) -> Optional[str]:
        data = getattr(module, "PLUGIN", None)
        if not isinstance(data, dict):
            return None
        manifest = build_manifest(data)
        if manifest.id in self._entries:
            raise PluginError("duplicate_plugin", f"插件标识重复：{manifest.id}")
        context = PluginContext(self, manifest)
        entry = _Entry(manifest, context)
        register = getattr(module, "register", None)
        if callable(register):
            try:
                register(context)
            except Exception as exc:  # noqa: BLE001 - 单个插件加载失败不拖垮宿主
                logger.exception("plugin_register_failed id=%s", manifest.id)
                entry.load_error = "register_failed"
        verify = getattr(module, "verify", None)
        entry.verify = verify if callable(verify) else None
        active = getattr(module, "has_active_tasks", None)
        entry.has_active_tasks = active if callable(active) else None
        entry.owns_media = getattr(module, "owns_media", None)
        self._entries[manifest.id] = entry
        return manifest.id

    def discover(self, package_root: object) -> list[str]:
        root = Path(package_root)  # type: ignore[arg-type]
        loaded: list[str] = []
        if not root.is_dir():
            return loaded
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not (child / "plugin.py").is_file():
                continue
            module_name = f"app.plugins.{child.name}.plugin"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 - 坏插件不拖垮宿主
                logger.exception("plugin_import_failed module=%s", module_name)
                self.record_failure(child.name, "import", type(exc).__name__)
                continue
            try:
                plugin_id = self.register_module(module)
            except Exception as exc:  # noqa: BLE001
                logger.exception("plugin_manifest_failed module=%s", module_name)
                self.record_failure(child.name, "manifest", str(exc))
                continue
            if plugin_id:
                loaded.append(plugin_id)
        return loaded

    # ------------------------------------------------------------------ 视图

    def _require_entry(self, plugin_id: str) -> _Entry:
        entry = self._entries.get(plugin_id)
        if entry is None:
            raise PluginError("plugin_not_found", "插件不存在或未加载。", 404)
        return entry

    def _cred_ref(self, plugin_id: str) -> str:
        return "workspace:" + self._state_key(plugin_id)

    def _has_credential(self, plugin_id: str) -> bool:
        try:
            return bool(self._credentials.get(self._cred_ref(plugin_id)))
        except Exception:  # noqa: BLE001 - 凭据库异常按未配置处理
            return False

    def credential_value(self, plugin_id: str) -> Optional[str]:
        try:
            return self._credentials.get(self._cred_ref(plugin_id))
        except Exception:  # noqa: BLE001
            return None

    def _config_status(self, plugin_id: str, raw: dict[str, Any]) -> str:
        entry = self._entries.get(plugin_id)
        if entry is None or not entry.manifest.needs_credential:
            return "not_required"
        if raw.get("lastErrorCode"):
            return "invalid"
        if self._has_credential(plugin_id):
            return "configured"
        return "unconfigured"

    def state_view(self, plugin_id: str) -> dict[str, Any]:
        raw = self._state.read(self._state_key(plugin_id))
        return {
            "installed": bool(raw.get("installed")),
            "enabled": bool(raw.get("enabled")),
            "installedAt": raw.get("installedAt"),
            "updatedAt": raw.get("updatedAt"),
            "configStatus": self._config_status(plugin_id, raw),
            "credentialUpdatedAt": raw.get("credentialUpdatedAt"),
            "lastVerifiedAt": raw.get("lastVerifiedAt"),
            "lastErrorCode": raw.get("lastErrorCode"),
        }

    def list_views(self) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for plugin_id in sorted(self._entries):
            entry = self._entries[plugin_id]
            view = dict(entry.manifest.as_dict())
            view.update(self.state_view(plugin_id))
            if entry.load_error:
                view["loadError"] = entry.load_error
            views.append(view)
        return views

    def health_snapshot(self) -> dict[str, Any]:
        """供 /api/health 使用：插件整体是否健康 + 明细。"""
        if getattr(getattr(self, "packages", None), "workspace_scoped", False):
            return self.packages.health_snapshot(self._account.get())
        loaded: list[dict[str, Any]] = []
        for plugin_id in sorted(self._entries):
            entry = self._entries[plugin_id]
            loaded.append({
                "id": plugin_id,
                "version": entry.manifest.version,
                "hostApiVersion": entry.manifest.host_api_version,
                "compatible": entry.manifest.compatible,
                "loadError": entry.load_error,
            })
        broken = [item["id"] for item in loaded if item["loadError"]]
        package_records = self.packages.records() if hasattr(self, "packages") else {}
        failures = [dict(item) for item in self._failures]
        if hasattr(self, "packages"):
            for pid, record in package_records.items():
                if record.get("installError"):
                    failures.append({"source": pid, "stage": "package", "message": record["installError"]})
        return {
            "ok": not broken and not failures,
            "loaded": loaded,
            "failures": failures,
        }

    def get_view(self, plugin_id: str) -> dict[str, Any]:
        entry = self._require_entry(plugin_id)
        view = dict(entry.manifest.as_dict())
        view.update(self.state_view(plugin_id))
        if entry.load_error:
            view["loadError"] = entry.load_error
        return view

    # ------------------------------------------------------------------ 生命周期

    def install(self, plugin_id: str) -> dict[str, Any]:
        entry = self._require_entry(plugin_id)
        raw = self._state.read(self._state_key(plugin_id))
        if getattr(getattr(self, "packages", None), "global_packages", False) and raw.get("installed"):
            return self.get_view(plugin_id)
        changes = {"installed": True, "updatedAt": self._clock()}
        if not raw.get("installed"):
            changes["installationId"] = uuid.uuid4().hex
        if not raw.get("installedAt"):
            changes["installedAt"] = self._clock()
        # 建议默认：安装后停用，用户配置并启用后才开放能力。
        changes["enabled"] = False
        self._state.update(self._state_key(plugin_id), changes)
        return self.get_view(plugin_id)

    def enable(self, plugin_id: str) -> dict[str, Any]:
        entry = self._require_entry(plugin_id)
        if entry.load_error:
            raise PluginError("plugin_broken", "插件加载失败，暂不能启用。", 409)
        if not self._state.read(self._state_key(plugin_id)).get("installed"):
            raise PluginError("not_installed", "插件尚未安装，请先安装。", 409)
        self._state.update(self._state_key(plugin_id), {"enabled": True, "updatedAt": self._clock()})
        return self.get_view(plugin_id)

    def disable(self, plugin_id: str) -> dict[str, Any]:
        self._require_entry(plugin_id)
        self._state.update(self._state_key(plugin_id), {"enabled": False, "updatedAt": self._clock()})
        return self.get_view(plugin_id)

    def uninstall(self, plugin_id: str) -> dict[str, Any]:
        if getattr(getattr(self, "packages", None), "workspace_scoped", False):
            return self.packages.uninstall(plugin_id)
        entry = self._require_entry(plugin_id)
        if entry.has_active_tasks is not None:
            try:
                active = entry.has_active_tasks(entry.context)
                if inspect.isawaitable(active):
                    active = False
            except Exception:  # noqa: BLE001
                active = False
            if active:
                raise PluginError("active_tasks", "仍有进行中的任务，请等待完成后再卸载。", 409)
        try:
            self._credentials.delete(self._cred_ref(plugin_id))
        except Exception:  # noqa: BLE001 - 凭据库异常不阻塞卸载
            logger.warning("plugin_credential_delete_failed id=%s", plugin_id)
        # Retain an empty scoped record so an interrupted legacy migration cannot resurrect it.
        self._state.replace(self._state_key(plugin_id), {})
        if hasattr(self, 'packages'):
            self.packages.cancel_account_install(plugin_id, self.account_id)
        return self.state_view(plugin_id)

    # ------------------------------------------------------------------ 凭据

    def credential_status(self, plugin_id: str) -> dict[str, Any]:
        self._require_entry(plugin_id)
        raw = self._state.read(self._state_key(plugin_id))
        return {
            "configured": self._has_credential(plugin_id),
            "credentialUpdatedAt": raw.get("credentialUpdatedAt"),
            "lastVerifiedAt": raw.get("lastVerifiedAt"),
            "lastErrorCode": raw.get("lastErrorCode"),
        }

    def set_credential(self, plugin_id: str, value: str) -> dict[str, Any]:
        self._require_entry(plugin_id)
        secret = str(value or "")
        if not secret.strip():
            raise PluginError("credential_empty", "请填写凭据后再保存。", 400)
        self._credentials.set(self._cred_ref(plugin_id), secret)
        self._state.update(
            self._state_key(plugin_id),
            {
                "credentialUpdatedAt": self._clock(),
                "lastVerifiedAt": None,
                "lastErrorCode": None,
            },
        )
        return self.credential_status(plugin_id)

    def delete_credential(self, plugin_id: str) -> dict[str, Any]:
        self._require_entry(plugin_id)
        try:
            self._credentials.delete(self._cred_ref(plugin_id))
        except Exception:  # noqa: BLE001
            pass
        self._state.update(
            self._state_key(plugin_id),
            {"credentialUpdatedAt": self._clock(), "lastVerifiedAt": None, "lastErrorCode": None},
        )
        return self.credential_status(plugin_id)

    async def verify_credential(self, plugin_id: str) -> dict[str, Any]:
        entry = self._require_entry(plugin_id)
        if not self._has_credential(plugin_id):
            raise PluginError("credential_missing", "尚未配置凭据，请先保存。", 409)
        if entry.verify is None:
            return {"ok": True, "verified": False, "message": "该插件无需连接验证。"}
        try:
            result = entry.verify(entry.context)
            if inspect.isawaitable(result):
                result = await result
        except PluginError as exc:
            self._state.update(self._state_key(plugin_id), {"lastErrorCode": exc.code})
            return {"ok": False, "verified": True, "code": exc.code, "message": exc.message}
        except Exception:  # noqa: BLE001 - 上游异常不外泄原始内容
            logger.exception("plugin_verify_failed id=%s", plugin_id)
            self._state.update(self._state_key(plugin_id), {"lastErrorCode": "verify_failed"})
            return {"ok": False, "verified": True, "code": "verify_failed", "message": "连接验证失败，请稍后重试。"}
        if isinstance(result, dict):
            payload = dict(result)
            payload["verified"] = True
            if payload.get("ok") is False:
                self._state.update(
                    self._state_key(plugin_id), {"lastErrorCode": str(payload.get("code") or "verify_failed")}
                )
                return payload
            self._state.update(self._state_key(plugin_id), {"lastVerifiedAt": self._clock(), "lastErrorCode": None})
            payload.setdefault("ok", True)
            return payload
        self._state.update(self._state_key(plugin_id), {"lastVerifiedAt": self._clock(), "lastErrorCode": None})
        return {"ok": True, "verified": True}

    # ------------------------------------------------------------------ 路由

    def plugin_router(self, plugin_id: str) -> APIRouter:
        return self._require_entry(plugin_id).context.router

    def iter_routers(self) -> list[tuple[str, APIRouter]]:
        return [(pid, entry.context.router) for pid, entry in sorted(self._entries.items())]

    def script_snapshot(self, script_id: str) -> Optional[dict[str, Any]]:
        if self._script_snapshot is None:
            return None
        snapshot = self._script_snapshot(script_id)
        return snapshot if snapshot and snapshot.get("accountId") == self.account_id else None

    def owns_media(self, media: str) -> bool:
        entry = self._entries.get(media.split("/", 1)[0])
        return bool(entry and entry.owns_media and entry.owns_media(entry.context, media))

    def plugin_media_dir(self, plugin_id: str) -> Path:
        if self._media_root is None:
            raise PluginError("media_root_missing", "插件媒体目录未配置。", 500)
        path = self._media_root / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path
