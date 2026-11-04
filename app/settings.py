from __future__ import annotations

import os
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .creation_service import normalize_base_url
from .subscription import normalize_platform_mode


from .runtime import RESOURCE_ROOT as PROJECT_ROOT, DATA_ROOT, DESKTOP, PLATFORM_ORIGIN
ENV_FILE = DATA_ROOT / ".env"
DEFAULT_REWRITE_SYSTEM_PROMPT = "请根据原口播稿，生成主题相同、表达方式不同的一份完整视频仿写脚本。仅输出这一份脚本，不要生成多个版本、候选稿或三份脚本。"
DEFAULT_TITLE_REWRITE_SYSTEM_PROMPT = (
    "根据原始标题和话题，生成双平台可直接发布的标题文案。"
    "必须仅输出 JSON 对象：douyin 和 channels 各包含恰好 3 条候选。"
    "抖音候选仅使用 26～30 个字的 title、topics，不生成作品描述；视频号候选使用 14～16 个字的 shortTitle、约 50 字的 description、topics。每个话题以一个 # 开头。"
    "输出前逐条自检标题字数，确保抖音 title 为 26～30 个字、视频号 shortTitle 为 14～16 个字，均包含上下限。"
)


@dataclass(frozen=True)
class AppSettings:
    # 工作台订阅与积分：平台接口空间地址与数据通路（mock 用于平台就绪前联调）。
    workbench_api_base_url: str = PLATFORM_ORIGIN
    workbench_platform_mode: str = "live"
    rewrite_system_prompt: str = DEFAULT_REWRITE_SYSTEM_PROMPT
    title_rewrite_system_prompt: str = DEFAULT_TITLE_REWRITE_SYSTEM_PROMPT


class SettingsUpdate(BaseModel):
    """Only explicitly supplied fields overwrite their local .env value."""

    model_config = ConfigDict(extra="forbid")

    rewriteSystemPrompt: Optional[str] = None
    titleRewriteSystemPrompt: Optional[str] = None

    @field_validator("rewriteSystemPrompt")
    @classmethod
    def reject_multiline_values(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("配置值不能包含换行符。")
        return value.strip() if value is not None else None

    @field_validator("titleRewriteSystemPrompt")
    @classmethod
    def normalize_title_prompt(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


_ENV_TO_ATTRIBUTE = {
    "WORKBENCH_API_BASE_URL": "workbench_api_base_url",
    "WORKBENCH_PLATFORM_MODE": "workbench_platform_mode",
    "REWRITE_SYSTEM_PROMPT": "rewrite_system_prompt",
    "TITLE_REWRITE_SYSTEM_PROMPT": "title_rewrite_system_prompt",
}

_UPDATE_TO_ENV = {
    "rewriteSystemPrompt": "REWRITE_SYSTEM_PROMPT",
    "titleRewriteSystemPrompt": "TITLE_REWRITE_SYSTEM_PROMPT",
}


def _read_env_values(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        return {}

    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in _ENV_TO_ATTRIBUTE:
            normalized_value = value.strip()
            if key == "TITLE_REWRITE_SYSTEM_PROMPT":
                try:
                    decoded = json.loads(normalized_value)
                except json.JSONDecodeError:
                    decoded = normalized_value
                if isinstance(decoded, str):
                    values[key] = decoded
                    continue
            values[key] = normalized_value.strip('"').strip("'")
    return values


def load_settings(env_file: Path = ENV_FILE) -> AppSettings:
    values = _read_env_values(env_file)
    defaults = AppSettings()
    # Only connection settings accept process environment overrides. Blank values
    # fall through; prompt loading and saving retain their existing semantics.
    for env_key in ("WORKBENCH_API_BASE_URL", "WORKBENCH_PLATFORM_MODE"):
        values[env_key] = (
            os.environ.get(env_key, "").strip()
            or values.get(env_key, "").strip()
            or getattr(defaults, _ENV_TO_ATTRIBUTE[env_key])
        )
    settings = AppSettings(
        **{
            attribute: values.get(env_key, getattr(defaults, attribute))
            for env_key, attribute in _ENV_TO_ATTRIBUTE.items()
        }
    )
    return replace(
        settings,
        workbench_platform_mode="live" if DESKTOP else normalize_platform_mode(settings.workbench_platform_mode),
        workbench_api_base_url=PLATFORM_ORIGIN if DESKTOP else normalize_base_url(settings.workbench_api_base_url),
    )


def save_settings(values: SettingsUpdate, env_file: Path = ENV_FILE) -> None:
    """Update only known .env entries and leave unrelated local settings intact."""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    updates = {
        _UPDATE_TO_ENV[field]: getattr(values, field)
        for field in values.model_fields_set
        if field in _UPDATE_TO_ENV
    }
    if not updates:
        return

    remaining = set(updates)
    updated_lines: list[str] = []
    for line in existing_lines:
        key, separator, _ = line.partition("=")
        if separator and key in updates:
            value = updates[key] or ""
            encoded = json.dumps(value, ensure_ascii=False) if key == "TITLE_REWRITE_SYSTEM_PROMPT" else value
            updated_lines.append(f"{key}={encoded}")
            remaining.discard(key)
        else:
            updated_lines.append(line)
    for key in sorted(remaining):
        value = updates[key] or ""
        encoded = json.dumps(value, ensure_ascii=False) if key == "TITLE_REWRITE_SYSTEM_PROMPT" else value
        updated_lines.append(f"{key}={encoded}")

    temporary_file = env_file.with_name(f".{env_file.name}.tmp")
    temporary_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    os.chmod(temporary_file, 0o600)
    temporary_file.replace(env_file)
    os.chmod(env_file, 0o600)




def project_settings_view(settings: AppSettings) -> dict[str, Any]:
    """工作台连接信息；鉴权由登录会话负责，不再提供旧 Key 入口。"""
    return {"workbench": {
        "baseUrl": settings.workbench_api_base_url,
        "mode": settings.workbench_platform_mode,
    }}
