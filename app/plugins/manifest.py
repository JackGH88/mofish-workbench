"""插件清单：宿主唯一需要理解的结构。

清单只描述通用信息（标识、版本、宿主兼容范围、能力声明），不含任何供应商字段。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import PLUGIN_HOST_API_VERSION

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")


class ManifestError(ValueError):
    """清单字段非法或与宿主不兼容。"""


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    host_api_version: str = PLUGIN_HOST_API_VERSION
    description: str = ""
    capabilities: tuple[str, ...] = ()
    # 是否需要一份宿主托管的通用凭据（例如供应商 API Key）。
    needs_credential: bool = False

    @property
    def compatible(self) -> bool:
        return str(self.host_api_version).split(".")[0] == PLUGIN_HOST_API_VERSION.split(".")[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "hostApiVersion": self.host_api_version,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "needsCredential": self.needs_credential,
        }


def build_manifest(data: Mapping[str, Any]) -> PluginManifest:
    """从插件包声明的映射构造并校验清单。"""
    plugin_id = str(data.get("id") or "").strip()
    if not _ID_PATTERN.match(plugin_id):
        raise ManifestError(f"插件标识不合法：{plugin_id!r}")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ManifestError(f"插件 {plugin_id} 缺少名称")
    version = str(data.get("version") or "").strip()
    if not version:
        raise ManifestError(f"插件 {plugin_id} 缺少版本")
    capabilities_raw: Sequence[Any] = data.get("capabilities") or ()
    capabilities = tuple(str(item).strip() for item in capabilities_raw if str(item).strip())
    manifest = PluginManifest(
        id=plugin_id,
        name=name,
        version=version,
        host_api_version=str(data.get("hostApiVersion") or PLUGIN_HOST_API_VERSION).strip(),
        description=str(data.get("description") or "").strip(),
        capabilities=capabilities,
        needs_credential=bool(data.get("needsCredential")),
    )
    if not manifest.compatible:
        raise ManifestError(
            f"插件 {plugin_id} 声明的宿主版本 {manifest.host_api_version}"
            f"与当前宿主 {PLUGIN_HOST_API_VERSION} 不兼容"
        )
    return manifest
