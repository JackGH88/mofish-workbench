"""通用插件管理路由：宿主对外暴露的插件接口，不含任何供应商字段。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .registry import PluginError, PluginRegistry


class CredentialPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=8192)


def _translate(exc: PluginError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def build_router(registry: PluginRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(registry.account_dependency)])

    @router.get("")
    def list_plugins() -> dict[str, Any]:
        return {"plugins": registry.packages.views() if hasattr(registry, "packages") else registry.list_views(),
                "failures": registry.health_snapshot()["failures"]}

    @router.get("/{plugin_id}")
    def get_plugin(plugin_id: str) -> dict[str, Any]:
        try:
            if hasattr(registry, "packages"):
                view = next((v for v in registry.packages.views() if v['id'] == plugin_id), None)
                if view is not None:
                    return view
            return registry.get_view(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.post("/{plugin_id}/install")
    def install_plugin(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.install(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.post("/{plugin_id}/enable")
    def enable_plugin(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.enable(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.post("/{plugin_id}/disable")
    def disable_plugin(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.disable(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.post("/{plugin_id}/uninstall")
    def uninstall_plugin(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.uninstall(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.get("/{plugin_id}/credentials")
    def credential_status(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.credential_status(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.put("/{plugin_id}/credentials")
    def set_credential(plugin_id: str, payload: CredentialPayload) -> dict[str, Any]:
        try:
            return registry.set_credential(plugin_id, payload.value)
        except PluginError as exc:
            raise _translate(exc)

    @router.delete("/{plugin_id}/credentials")
    def delete_credential(plugin_id: str) -> dict[str, Any]:
        try:
            return registry.delete_credential(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    @router.post("/{plugin_id}/credentials/verify")
    async def verify_credential(plugin_id: str) -> dict[str, Any]:
        try:
            return await registry.verify_credential(plugin_id)
        except PluginError as exc:
            raise _translate(exc)

    return router
