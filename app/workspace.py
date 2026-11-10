from __future__ import annotations

from . import post_edit_automation as post_edit

import hmac
import json
import logging
import re
import shutil
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .breakdown_materials import normalize_details

from .writing_assets import (
    ASSET_LIMIT_PER_KIND,
    HOOK_KIND,
    ENDING_KIND,
    STRUCTURE_KIND,
    WRITING_ASSET_FORMATS,
    WRITING_ASSET_KINDS,
    asset_view,
    builtin_assets,
    is_builtin_asset_id,
    normalize_asset_fields,
)

from .upstream_errors import public_error, sanitize_message

from .memory_store import MemoryLibrary, MemoryStoreError, TITLE_LIMIT, derive_title
from . import onboarding


def _public_error(code: object, message: object) -> dict[str, str]:
    """写入/回读工作区里保存的错误：不带上游品牌、域名和原始返回内容。"""
    safe_code, safe_message = public_error(code, message)
    return {"code": str(safe_code)[:100], "message": str(safe_message)[:500]}


def _public_error_view(value: object) -> dict[str, str]:
    """回读历史数据里的错误对象；兼容旧记录里已经落盘的供应商文案。"""
    if not isinstance(value, dict) or not value:
        return {}
    return _public_error(value.get("code"), value.get("message"))


PLATFORMS = {"douyin", "channels", "both"}
TITLE_PLATFORMS = {"douyin", "channels"}
STAGES = {"edit", "split", "write", "title", "cover", "publish"}
WRITING_NODES = {"structure", "content"}
DEFAULT_ACCOUNT_PROFILE = {
    "businessPositioning": "【待完善】商业定位：这个账号卖什么产品或服务、为谁解决什么问题、靠什么方式变现。",
    "targetAudience": "【待完善】目标人群：他们的身份与处境、最核心的痛点、最想要达成的结果。",
}
ACCOUNT_PROFILE_FIELD_LIMIT = 2000
WRITING_PROMPT_LIMIT = 12000
WRITING_MEMORY_TEXT_LIMIT = 4000
WRITING_MEMORY_LIMIT = 30
WRITING_PROMPT_HISTORY_LIMIT = 30
DEFAULT_WRITING_PROMPTS = {
    "structure": (
        "你是一名爆款短视频结构分析师。请阅读原视频文案，拆解它的选题与整体结构，"
        "给出这条视频的选题，以及按播放顺序排列的各个结构环节。"
    ),
    "content": (
        "你是一名短视频口播编导。请根据已确认的选题与脚本结构，写出完整、可直接录制的短视频口播脚本。"
    ),
}
PROCESSING_STATUSES = {"processing", "failed", "ready"}
WORKFLOW_STATUSES = {"pending", "editing", "ready_to_publish", "published"}
CREATION_FORMATS = ("video", "article")
CREATION_TOPIC_LIMIT = 200
CREATION_DURATION_LIMIT = 60
CREATION_POINTS_LIMIT = 4000
CREATION_ADVANCED_LIMIT = 2000
AGENT_RETURN_LIMIT = 100000
PENDING_EXPERIENCE_LIMIT = 200
UNCLASSIFIED_ACCOUNT_ID = "unclassified"
DEFAULT_REWRITE_SYSTEM_PROMPT = "请根据原脚本文案，生成一份主题相同、表达方式不同的视频仿写脚本。"
REWRITE_PROMPT_TEMPLATE_DEFINITIONS = (
    ("general", "通用仿写", DEFAULT_REWRITE_SYSTEM_PROMPT),
    (
        "retention",
        "高留存口播",
        "你是一名资深短视频高留存口播编导。请基于原口播稿创作一份可直接录制的仿写脚本。"
        "保留原稿的核心主题、目标受众、关键观点与论证逻辑，但重写全部表达方式、句式、叙述节奏和案例细节。"
        "开场用最能让目标受众停留的钩子切入，随后依次呈现痛点、核心价值或证明，最后给出自然明确的行动号召。"
        "避免逐句改写、复制原句或照搬原有比喻。",
    ),
    (
        "story",
        "故事化表达",
        "你是一名擅长故事化表达的短视频口播编导。请基于原口播稿创作一份可直接录制的仿写脚本。"
        "保留原稿的核心主题、目标受众、关键观点与论证逻辑，但重写全部表达方式、句式、叙述节奏和案例细节。"
        "以具体场景或冲突开场，逐步展开人物或处境的变化，在转折处给出关键洞察，最后用自然有余味的总结收束。"
        "避免逐句改写、复制原句或照搬原有比喻。",
    ),
)
REWRITE_PROMPT_TEMPLATE_IDS = {template_id for template_id, _name, _prompt in REWRITE_PROMPT_TEMPLATE_DEFINITIONS}
COVER_ASPECTS = ("3:4", "4:3")

# Weekly topic planning (选题). Categories describe the production intent, and
# status is the shared operator state owned by the linked script when there is one.
# A topic that has no script yet uses its own 待创作 state instead of the script
# page's default 待处理, so the two lists do not look like the same backlog.
TOPIC_CATEGORIES = ("highlight", "daily", "series", "test")
TOPIC_FORMATS = ("video", "article")
TOPIC_FIELD_NAMES = ("title", "outline", "category", "format", "publishDate", "materials")
TOPIC_PENDING_CREATION = "pending_creation"
TOPIC_STATUSES = WORKFLOW_STATUSES | {TOPIC_PENDING_CREATION}
DEFAULT_TOPIC_TARGETS = {"highlight": 2, "daily": 2, "series": 0, "test": 1}
TOPIC_TARGET_LIMIT = 50
TOPIC_TITLE_LIMIT = 160
TOPIC_TEXT_LIMIT = 2000

# 拆解视频 (video breakdown): one record per analysed reference video. The record
# owns the download task, the operator-owned analysis, and the topic it fed.
BREAKDOWN_TITLE_LIMIT = 160
BREAKDOWN_SHARE_TEXT_LIMIT = 2000
BREAKDOWN_ANALYSIS_TEXT_LIMIT = 400
BREAKDOWN_ANALYSIS_STATUSES = ("idle", "pending", "running", "complete", "failed")
BREAKDOWN_ANALYSIS_FIELDS = ("topic", "audience", "hook")

# Creator home (首页): the daily action list and the inspiration notebook.
# Manual tasks are the operator's own reminders; the home page merges them with
# the publish-date reminders derived from topics so nothing is stored twice.
MANUAL_TASK_TITLE_LIMIT = 160
MANUAL_TASK_LINK_TYPES = ("topic", "script")
INSPIRATION_TEXT_LIMIT = 2000
INSPIRATION_SOURCE_LIMIT = 500
HOME_TASK_PREVIEW_LIMIT = 5
HOME_TASK_PAGE_LIMIT = 50
HOME_INSPIRATION_PREVIEW_LIMIT = 20

# Sentinel for "the downloads directory has not been scanned yet in this process".
_UNCHECKED_DOWNLOADS = object()

logger = logging.getLogger("douyin-downloader")


def _locked(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def locked(self: "WorkspaceStore", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


class WorkspaceStore:
    def __init__(self, workspace_dir: Path, download_dir: Path) -> None:
        from .return_notifications import ReturnNotifications
        self.return_notifications = ReturnNotifications(workspace_dir)
        self._workspace_dir = workspace_dir
        self._download_dir = download_dir
        self._accounts_path = workspace_dir / "accounts.json"
        self._onboarding_path = workspace_dir / "onboarding.json"
        self._scripts_dir = workspace_dir / "scripts"
        self._cover_templates_path = workspace_dir / "cover-templates.json"
        self._deleted_link_tasks_path = workspace_dir / "deleted-link-tasks.json"
        self._account_profiles_path = workspace_dir / "account-profiles.json"
        self._account_memory_path = workspace_dir / "account-memory.json"
        self._memory_config_path = workspace_dir / "memory-config.json"
        self._memory_library = MemoryLibrary(workspace_dir, self._memory_config_path, reference_title_resolver=self._reference_copy_title)
        self._memories_migrated = False
        self._topic_plans_path = workspace_dir / "topic-plans.json"
        self._breakdowns_path = workspace_dir / "breakdowns.json"
        self._manual_tasks_path = workspace_dir / "manual-tasks.json"
        self._inspirations_path = workspace_dir / "inspirations.json"
        self._writing_assets_path = workspace_dir / "writing-assets.json"
        self._writing_pending_path = workspace_dir / "writing-pending.json"
        self._writing_agent_tasks_dir = workspace_dir / "writing-agent-tasks"
        self._lock = threading.RLock()
        self._migrated = False
        self._scripts_cache: dict[str, dict[str, Any]] | None = None
        self._task_script_index: dict[str, str] | None = None
        self._downloads_signature: object = _UNCHECKED_DOWNLOADS

    @_locked
    def list_accounts(self) -> list[dict[str, Any]]:
        self._ensure_migrated()
        return self._read_accounts()

    @_locked
    def create_account(self, name: str, platform: str, onboarding_stage: str = "existing") -> dict[str, Any]:
        self._ensure_migrated()
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("账号名称不能为空。")
        self._validate_platform(platform)
        now = self._now()
        account = {
            "id": str(uuid.uuid4()),
            "name": normalized_name,
            "platform": platform,
            "createdAt": now,
            "updatedAt": now,
            "isSystem": False,
        }
        account.update(self._default_rewrite_prompt_config())
        accounts = self._read_accounts()
        self._memory_library.ensure_account_directory(account["id"])
        accounts.append(account)
        self._write_json(self._accounts_path, accounts)
        data = onboarding.load(self)
        data["accounts"][account["id"]] = onboarding.initial(new=True, stage=onboarding_stage)
        self._write_json(self._onboarding_path, data)
        return account

    @_locked
    def onboarding_view(self, account_id: str, works: list[dict], *, content_sources: dict | None = None) -> dict:
        return onboarding.view(self, account_id, works, content_sources=content_sources)

    @_locked
    def save_onboarding(self, account_id: str, patch: dict) -> None:
        onboarding.save_preferences(self, account_id, patch)

    @_locked
    def update_account_platform(self, account_id: str, platform: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._validate_platform(platform)
        accounts = self._read_accounts()
        for account in accounts:
            if account.get("id") == account_id:
                account["platform"] = platform
                account["updatedAt"] = self._now()
                self._write_json(self._accounts_path, accounts)
                return account
        raise ValueError("账号不存在。")

    @_locked
    def rename_account(self, account_id: str, name: str) -> dict[str, Any]:
        self._ensure_migrated()
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("账号名称不能为空。")
        if len(normalized_name) > 80:
            raise ValueError("账号名称不能超过80个字符。")
        accounts = self._read_accounts()
        for account in accounts:
            if account.get("id") != account_id:
                continue
            if account.get("isSystem"):
                raise ValueError("系统账号不能编辑。")
            account["name"] = normalized_name
            account["updatedAt"] = self._now()
            self._write_json(self._accounts_path, accounts)
            return account
        raise ValueError("账号不存在。")

    @_locked
    def get_account_rewrite_prompt(self, account_id: str) -> str:
        self._ensure_migrated()
        return self._rewrite_prompt_config_for_account(self._require_account(account_id))["systemPrompt"]

    @_locked
    def save_account_rewrite_prompt(self, account_id: str, system_prompt: str) -> str:
        return self.save_account_rewrite_prompt_config(account_id, system_prompt)["systemPrompt"]

    @_locked
    def get_account_rewrite_prompt_config(self, account_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        return self._rewrite_prompt_config_for_account(self._require_account(account_id))

    @_locked
    def save_account_rewrite_prompt_config(
        self,
        account_id: str,
        system_prompt: str,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_migrated()
        normalized_prompt = system_prompt.strip()
        if not normalized_prompt:
            raise ValueError("仿写提示词不能为空。")
        if len(normalized_prompt) > 12000:
            raise ValueError("仿写提示词不能超过12000个字符。")
        accounts = self._read_accounts()
        for account in accounts:
            if account.get("id") == account_id:
                config = self._rewrite_prompt_config_for_account(account)
                selected_template_id = template_id or config["selectedTemplateId"]
                if selected_template_id not in REWRITE_PROMPT_TEMPLATE_IDS:
                    raise ValueError("仿写模板无效。")
                templates = [dict(template) for template in config["templates"]]
                for template in templates:
                    if template["id"] == selected_template_id:
                        template["systemPrompt"] = normalized_prompt
                        break
                account["rewritePromptTemplates"] = templates
                account["selectedRewritePromptTemplateId"] = selected_template_id
                account["rewriteSystemPrompt"] = normalized_prompt
                account["updatedAt"] = self._now()
                self._write_json(self._accounts_path, accounts)
                return self._rewrite_prompt_config_for_account(account)
        raise ValueError("账号不存在。")

    @_locked
    def get_account_deletion_summary(self, account_id: str) -> dict[str, Any]:
        """Return the user-facing counts required before permanently deleting an account."""
        self._ensure_migrated()
        account = self._require_account(account_id)
        scripts = self.list_scripts(account_id)
        templates = self._read_cover_templates().get(account_id, [])
        manual_tasks = self._read_item_store(self._manual_tasks_path)["accounts"].get(account_id, {}).get("items", [])
        inspirations = self._read_item_store(self._inspirations_path)["accounts"].get(account_id, {}).get("items", [])
        return {
            "account": {"id": account["id"], "name": str(account.get("name") or "未命名账号")},
            "scriptCount": len(scripts),
            "coverTemplateCount": len(templates),
            "topicCount": len(self.list_topics(account_id)["items"]),
            "manualTaskCount": len(manual_tasks),
            "inspirationCount": len(inspirations),
        }

    @_locked
    def delete_account(self, account_id: str) -> dict[str, Any]:
        """Permanently remove one user account and all workspace records it owns."""
        self._ensure_migrated()
        account = self._require_account(account_id)
        if account.get("isSystem"):
            raise ValueError("系统账号不能删除。")
        scripts = self.list_scripts(account_id)
        templates_by_account = self._read_cover_templates()
        deleted_cover_template_count = len(templates_by_account.get(account_id, []))
        deleted_topic_count = len(self.list_topics(account_id)["items"])
        topic_data = self._read_topic_data()
        if topic_data["accounts"].pop(account_id, None) is not None:
            self._write_topic_data(topic_data)

        manual_task_data = self._read_item_store(self._manual_tasks_path)
        deleted_manual_task_count = len(manual_task_data["accounts"].get(account_id, {}).get("items", []))
        if manual_task_data["accounts"].pop(account_id, None) is not None:
            self._write_json(self._manual_tasks_path, manual_task_data)

        inspiration_data = self._read_item_store(self._inspirations_path)
        deleted_inspiration_count = len(inspiration_data["accounts"].get(account_id, {}).get("items", []))
        if inspiration_data["accounts"].pop(account_id, None) is not None:
            self._write_json(self._inspirations_path, inspiration_data)

        for script in scripts:
            self.delete_script(str(script["id"]))
        onboarding_data = onboarding.load(self)
        onboarding_data["accounts"].pop(account_id, None)
        self._write_json(self._onboarding_path, onboarding_data)
        accounts = [item for item in self._read_accounts() if item.get("id") != account_id]
        self._write_json(self._accounts_path, accounts)
        if account_id in templates_by_account:
            del templates_by_account[account_id]
            self._write_json(self._cover_templates_path, templates_by_account)

        return {
            "deletedAccountId": account_id,
            "deletedScriptIds": [str(script["id"]) for script in scripts],
            "deletedScriptCount": len(scripts),
            "deletedCoverTemplateCount": deleted_cover_template_count,
            "deletedTopicCount": deleted_topic_count,
            "deletedManualTaskCount": deleted_manual_task_count,
            "deletedInspirationCount": deleted_inspiration_count,
        }

    @_locked
    def list_scripts(self, account_id: str) -> list[dict[str, Any]]:
        self._ensure_migrated()
        self._require_account(account_id)
        scripts = [
            dict(script)
            for script in self._load_scripts().values()
            if script.get("accountId") == account_id and not script.get("retiredAsBreakdown")
        ]
        scripts.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
        return scripts

    @_locked
    def writing_return_notifications(self) -> list[dict[str, Any]]:
        """Small snapshot across local accounts; never include content or task tokens."""
        self._ensure_migrated()
        accounts = {item["id"] for item in self._read_accounts()}
        items = []
        for script in self._load_scripts().values():
            task = script.get("writingAgentTask") or {}
            if (not task.get("taskId") or script.get("retiredAsBreakdown")
                    or script.get("accountId") not in accounts):
                continue
            items.append({
                "accountId": script["accountId"], "scriptId": script["id"],
                "title": script.get("title") or "未命名脚本",
                "taskId": task["taskId"], "status": task.get("status", ""),
                "appliedAt": task.get("appliedAt", ""),
                "submissionIds": list(task.get("submissionIds") or []),
            })
        return items

    @_locked
    def create_blank_script(self, account_id: str, title: str | None = None) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        normalized_title = title.strip() if title else ""
        if not normalized_title:
            normalized_title = self._default_script_title()
        return self._create_script(
            account_id=account_id,
            title=normalized_title,
            source="blank",
            processing_status="ready",
            content="",
        )

    @_locked
    def create_link_script(self, account_id: str, task_id: str, share_text: str | None = None) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        existing = self._find_link_script(task_id)
        if existing is not None:
            return existing
        return self._create_script(
            account_id=account_id,
            title=self._default_script_title(),
            source="link",
            processing_status="processing",
            task_id=task_id,
            share_text=share_text,
        )

    @_locked
    def save_selected_rewrite_model(self, script_id: str, model: str) -> dict[str, Any]:
        if model not in {"text-default", "text-option-2", "text-option-3"}:
            raise ValueError("仿写模型无效。")
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以选择仿写模型。")
        script["selectedRewriteModel"] = model
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    @_locked
    def get_script(self, script_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        script_path = self._script_path(script_id)
        try:
            script = self._read_json(script_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("脚本不存在。") from exc
        if not isinstance(script, dict):
            raise ValueError("脚本不存在。")
        return script

    @_locked
    def move_script(self, script_id: str, target_account_id: str) -> dict[str, Any]:
        """Reassign one script without moving its task or script-owned assets."""
        self._ensure_migrated()
        script = self.get_script(script_id)
        target_account = self._require_account(target_account_id)
        if script.get("accountId") == target_account["id"]:
            raise ValueError("脚本已归属该账号。")
        source_account_id = str(script.get("accountId") or "")
        script["accountId"] = target_account["id"]
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        self._unlink_topics_for_script(
            script_id,
            account_id=source_account_id,
            status=str(script.get("workflowStatus") or ""),
        )
        return script

    @_locked
    def save_blank_content(self, script_id: str, content: str) -> dict[str, Any]:
        self._ensure_migrated()
        script = self.get_script(script_id)
        if script.get("source") == "link":
            raise ValueError("链接脚本请通过任务接口保存仿写稿。")
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("空白脚本文案不能为空。")
        script["content"] = normalized_content
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        onboarding.remember_script(self, script)
        return script

    @_locked
    def rename_blank_script(self, script_id: str, title: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        if script.get("source") == "link":
            raise ValueError("只有空白脚本可以修改标题。")
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("脚本标题不能为空。")
        if len(normalized_title) > 160:
            raise ValueError("脚本标题不能超过160个字符。")
        script["title"] = normalized_title
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    # ------------------------------------------------------------------
    # 拆解视频 (video breakdown)
    # ------------------------------------------------------------------

    @_locked
    def list_breakdowns(self, account_id: str) -> dict[str, Any]:
        """Return one account's 拆解记录, newest first."""
        self._ensure_migrated()
        self._require_account(account_id)
        bucket = self._account_breakdown_bucket(self._read_breakdown_data(), account_id)
        titles = self._breakdown_source_titles()
        items = [self._breakdown_view(record, titles) for record in bucket["items"]]
        items.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return {"items": items}

    @_locked
    def create_breakdown(self, account_id: str, task_id: str, share_text: str = "") -> dict[str, Any]:
        """One record per link task so re-submitting the same task never duplicates it."""
        self._ensure_migrated()
        self._require_account(account_id)
        normalized_task_id = self._normalize_breakdown_task_id(task_id)
        data = self._read_breakdown_data()
        bucket = self._account_breakdown_bucket(data, account_id)
        for record in bucket["items"]:
            if str(record.get("taskId") or "") == normalized_task_id:
                return self._breakdown_view(record)
        now = self._now()
        record = {
            "id": str(uuid.uuid4()),
            "accountId": account_id,
            "title": "",
            "shareText": str(share_text or "").strip()[:BREAKDOWN_SHARE_TEXT_LIMIT],
            "taskId": normalized_task_id,
            "analysis": None,
            "analysisStatus": "idle",
            "analysisError": "",
            "topicId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        bucket["items"].append(record)
        self._write_breakdown_data(data)
        return self._breakdown_view(record)

    @_locked
    def get_breakdown(self, breakdown_id: str) -> dict[str, Any]:
        data = self._read_breakdown_data()
        _bucket, record = self._locate_breakdown(data, breakdown_id)
        return self._breakdown_view(record)

    @_locked
    def delete_breakdown(self, breakdown_id: str) -> dict[str, Any]:
        """Remove one 拆解记录; its task materials, topic, and script stay untouched."""
        self._ensure_migrated()
        data = self._read_breakdown_data()
        bucket, record = self._locate_breakdown(data, breakdown_id)
        view = self._breakdown_view(record)
        bucket["items"].remove(record)
        self._write_breakdown_data(data)
        return view

    @_locked
    def rename_breakdown(self, breakdown_id: str, title: str) -> dict[str, Any]:
        """Fill in the reference video's title once the download metadata exists."""
        normalized_title = str(title or "").strip()[:BREAKDOWN_TITLE_LIMIT]
        if not normalized_title:
            raise ValueError("拆解记录标题不能为空。")
        data = self._read_breakdown_data()
        _bucket, record = self._locate_breakdown(data, breakdown_id)
        if normalized_title == str(record.get("title") or ""):
            return self._breakdown_view(record)
        record["title"] = normalized_title
        record["updatedAt"] = self._now()
        self._write_breakdown_data(data)
        return self._breakdown_view(record)

    @_locked
    def set_breakdown_analysis_status(
        self, breakdown_id: str, status: str, *, error: str = "",
    ) -> dict[str, Any]:
        """Track the analysis job so the page can show a real running/failed state."""
        if status not in BREAKDOWN_ANALYSIS_STATUSES:
            raise ValueError("拆解分析状态无效。")
        data = self._read_breakdown_data()
        _bucket, record = self._locate_breakdown(data, breakdown_id)
        record["analysisStatus"] = status
        record["analysisError"] = sanitize_message(str(error or ""))[:BREAKDOWN_ANALYSIS_TEXT_LIMIT]
        record["updatedAt"] = self._now()
        self._write_breakdown_data(data)
        return self._breakdown_view(record)

    @_locked
    def interrupt_running_breakdown_analyses(self) -> list[dict[str, Any]]:
        data = self._read_breakdown_data()
        interrupted = []
        for bucket in data["accounts"].values():
            for record in bucket["items"]:
                if record.get("analysisStatus") in {"pending", "running"}:
                    record.update(analysisStatus="failed", analysisError="服务重启，分析已中断，请重试分析。", updatedAt=self._now())
                    interrupted.append(self._breakdown_view(record))
        if interrupted:
            self._write_breakdown_data(data)
        return interrupted

    @_locked
    def save_breakdown_analysis(self, breakdown_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
        """Store a validated analysis; an invalid payload is rejected, never half-written."""
        normalized = self._normalize_breakdown_analysis(analysis)
        if normalized is None:
            raise ValueError("拆解分析结果无效。")
        data = self._read_breakdown_data()
        _bucket, record = self._locate_breakdown(data, breakdown_id)
        record["analysis"] = normalized
        record["analysisStatus"] = "complete"
        record["analysisError"] = ""
        record["updatedAt"] = self._now()
        self._write_breakdown_data(data)
        return self._breakdown_view(record)

    @_locked
    def link_breakdown_topic(self, breakdown_id: str, topic_id: str) -> dict[str, Any]:
        """Remember which topic this record fed so the UI can stop offering a duplicate."""
        normalized_topic_id = str(topic_id or "").strip()[:120]
        if not normalized_topic_id:
            raise ValueError("选题标识无效。")
        data = self._read_breakdown_data()
        _bucket, record = self._locate_breakdown(data, breakdown_id)
        record["topicId"] = normalized_topic_id
        record["updatedAt"] = self._now()
        self._write_breakdown_data(data)
        return self._breakdown_view(record)

    @_locked
    def breakdown_for_topic(self, topic_id: str) -> dict[str, Any] | None:
        """Return the 拆解记录 that produced one topic, if the topic came from 拆解视频."""
        normalized_topic_id = str(topic_id or "").strip()
        if not normalized_topic_id:
            return None
        data = self._read_breakdown_data()
        for bucket in data["accounts"].values():
            for record in bucket["items"]:
                if str(record.get("topicId") or "") == normalized_topic_id:
                    return self._breakdown_view(record)
        return None

    def _read_breakdown_data(self) -> dict[str, Any]:
        """Read the breakdown file defensively so a damaged file cannot break the workbench."""
        try:
            raw = self._read_json(self._breakdowns_path)
        except (OSError, json.JSONDecodeError):
            raw = None
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                items = bucket.get("items") if isinstance(bucket.get("items"), list) else []
                accounts[str(account_id)] = {"items": [item for item in items if isinstance(item, dict)]}
        return {"version": 1, "accounts": accounts}

    def _write_breakdown_data(self, data: dict[str, Any]) -> None:
        self._write_json(self._breakdowns_path, data)

    @staticmethod
    def _account_breakdown_bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(account_id)
        if not isinstance(bucket, dict):
            bucket = {"items": []}
            data["accounts"][account_id] = bucket
        if not isinstance(bucket.get("items"), list):
            bucket["items"] = []
        return bucket

    @staticmethod
    def _locate_breakdown(data: dict[str, Any], breakdown_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_id = str(breakdown_id or "").strip()
        if normalized_id:
            for bucket in data["accounts"].values():
                for record in bucket["items"]:
                    if str(record.get("id") or "") == normalized_id:
                        return bucket, record
        raise KeyError("拆解记录不存在。")

    @staticmethod
    def _normalize_breakdown_task_id(task_id: str) -> str:
        normalized = str(task_id or "").strip()
        if not normalized or Path(normalized).name != normalized:
            raise ValueError("拆解任务标识无效。")
        return normalized

    @staticmethod
    def _normalize_breakdown_analysis(analysis: Any) -> dict[str, Any] | None:
        """Accept only a complete analysis so the page never renders a half result."""
        if not isinstance(analysis, dict):
            return None
        fields: dict[str, str] = {}
        for name in BREAKDOWN_ANALYSIS_FIELDS:
            value = " ".join(str(analysis.get(name) or "").split())[:BREAKDOWN_ANALYSIS_TEXT_LIMIT]
            if not value:
                return None
            fields[name] = value
        raw_sections = analysis.get("sections")
        if not isinstance(raw_sections, list):
            return None
        sections: list[dict[str, str]] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            name = " ".join(str(item.get("name") or "").split())[:40]
            purpose = " ".join(str(item.get("purpose") or "").split())[:200]
            key_point = " ".join(str(item.get("keyPoint") or "").split())[:400]
            if not name:
                continue
            if set(item) == {"name"}:
                sections.append({"name": name})
            elif purpose and key_point:
                sections.append({"name": name, "purpose": purpose, "keyPoint": key_point})
        if not sections:
            return None
        try:
            details = normalize_details(analysis)
        except ValueError:
            return None
        return {**fields, "sections": sections, **details}

    @staticmethod
    def breakdown_topic_draft(record: dict[str, Any]) -> dict[str, Any]:
        """加入选题弹窗的推荐初稿：标题与大纲都按拆解分析拼出来。

        弹窗用它预填、服务端在用户没改时也回落到它，两边共用同一份拼装规则，
        界面上看到的大纲和真正写进选题库的不会对不上。
        """
        analysis = WorkspaceStore._normalize_breakdown_analysis(record.get("analysis")) or {}
        title = str(analysis.get("topic") or "").strip() or str(record.get("title") or "").strip() or "拆解选题"
        sections = analysis.get("sections") if isinstance(analysis.get("sections"), list) else []
        outline_parts = [
            f"受众：{analysis.get('audience')}" if analysis.get("audience") else "",
            f"开头钩子：{analysis.get('hook')}" if analysis.get("hook") else "",
        ]
        if sections:
            outline_parts.append("结构：" + " → ".join(str(section.get("name") or "") for section in sections if isinstance(section, dict)))
        return {
            "title": title[:TOPIC_TITLE_LIMIT],
            "outline": "\n".join(part for part in outline_parts if part)[:2000],
        }

    def _breakdown_source_titles(self) -> dict[str, str]:
        """Read cached source titles only; never resolve links through a paid API."""
        titles = {}
        for name in ("monitor-data.json", "radar-data.json"):
            try:
                data = json.loads((self._workspace_dir / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            works = data.get("works", {}) if isinstance(data, dict) else {}
            for work in works.values() if isinstance(works, dict) else []:
                if not isinstance(work, dict):
                    continue
                title = str(work.get("title") or "").strip()
                if title and title not in {"未命名视频", "未命名拆解"}:
                    for key in (work.get("id"), work.get("shareUrl")):
                        if key:
                            titles[str(key)] = title
        return titles

    def _breakdown_title(self, record: dict[str, Any], titles: dict[str, str] | None = None) -> str:
        title = str(record.get("title") or "").strip()
        if title and title not in {"未命名视频", "未命名拆解"}:
            return title
        titles = self._breakdown_source_titles() if titles is None else titles
        share = str(record.get("shareText") or "").strip()
        work_id = re.search(r"(?:/video/|/note/|[?&](?:modal_id|aweme_id|item_id)=)(\d+)", share)
        title = titles.get(share) or (titles.get(work_id.group(1)) if work_id else "")
        if title:
            return title
        task_id = str(record.get("taskId") or "")
        if task_id and Path(task_id).name == task_id:
            try:
                metadata = json.loads((self._download_dir / task_id / "video.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
            if isinstance(metadata, dict):
                title = str(metadata.get("title") or metadata.get("desc") or "").strip()
                if title and title not in {"未命名视频", "douyin_video"}:
                    return title
        # Douyin copy text retains the original caption even when transcription
        # omitted metadata. Strip only the recognized share-code prefix.
        if "https://v.douyin.com/" in share and "复制此链接" in share:
            caption = share.split("https://v.douyin.com/", 1)[0].strip()
            caption = re.sub(r"^(?:(?:\d+\.\d+|\d{2}/\d{2}|[A-Za-z]+:/|[A-Za-z]@[A-Za-z]\.[A-Za-z]+|:\d+(?:am|pm))\s+)+", "", caption)
            if caption and not re.fullmatch(r"[\d\W]+", caption):
                return caption
        return ""

    def _breakdown_view(self, record: dict[str, Any], titles: dict[str, str] | None = None) -> dict[str, Any]:
        analysis = WorkspaceStore._normalize_breakdown_analysis(record.get("analysis"))
        status = str(record.get("analysisStatus") or "idle")
        if status not in BREAKDOWN_ANALYSIS_STATUSES:
            status = "idle"
        return {
            "id": str(record.get("id") or ""),
            "accountId": str(record.get("accountId") or ""),
            "title": self._breakdown_title(record, titles),
            "shareText": str(record.get("shareText") or ""),
            "taskId": str(record.get("taskId") or ""),
            "analysis": analysis,
            "topicDraft": WorkspaceStore.breakdown_topic_draft(record),
            "analysisStatus": status,
            "analysisError": sanitize_message(str(record.get("analysisError") or "")),
            "topicId": str(record.get("topicId") or ""),
            "createdAt": str(record.get("createdAt") or ""),
            "updatedAt": str(record.get("updatedAt") or ""),
        }

    # ------------------------------------------------------------------
    # Weekly topic planning
    # ------------------------------------------------------------------

    @_locked
    def list_topics(self, account_id: str) -> dict[str, Any]:
        """Return one account's topics together with every weekly plan it owns."""
        self._ensure_migrated()
        self._require_account(account_id)
        bucket = self._read_topic_data()["accounts"].get(account_id) or {}
        topics = [self._topic_view(topic) for topic in bucket.get("topics", [])]
        topics.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        plans = {
            str(week): self._topic_plan_view(str(week), plan)
            for week, plan in (bucket.get("plans") or {}).items()
            if isinstance(plan, dict)
        }
        return {"items": topics, "plans": plans, "defaultTargets": dict(DEFAULT_TOPIC_TARGETS)}

    @staticmethod
    def _source_link_ids(text: str) -> set[str]:
        """Only exact supported video URLs carry identity; never infer from titles."""
        return set(re.findall(r"https?://(?:www\.)?(?:douyin\.com/(?:video|note)|iesdouyin\.com/share/(?:video|slides))/(\d+)(?=[/?#\s，。；、）)]|$)", text)) | set(re.findall(r"https?://(?:www\.)?douyin\.com/jingxuan\?[^\s]*?modal_id=(\d+)(?=[&#\s，。；、）)]|$)", text))

    @_locked
    def find_topic_for_source(self, account_id: str, source: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_migrated()
        self._require_account(account_id)
        source_id = str(source.get("id") or "")
        link = str(source.get("shareUrl") or "").strip()
        ids = self._source_link_ids(link)
        if source_id:
            ids.add(source_id)
        platform = str(source.get("platform") or "")
        for topic in self.list_topics(account_id)["items"]:
            topic_platform = str((topic.get("sourceWork") or {}).get("platform") or "")
            if platform and topic_platform and platform != topic_platform:
                continue
            if ids.intersection(str(value) for value in topic.get("sourceWorkIds") or []):
                return topic
            material = str(topic.get("materials") or "")
            if ids.intersection(self._source_link_ids(material)):
                return topic
            if link and link in re.findall(r"https?://[^\s<>\"，。；、）)]+", material):
                return topic
        return None

    @_locked
    def restore_recommendation_topic_sources(self, records: dict[str, list[dict]]) -> int:
        """Restore only unambiguous single-reference adoption links before legacy cleanup."""
        self._ensure_migrated()
        data = self._read_topic_data()
        changed = 0
        account_ids = {str(account["id"]) for account in self.list_accounts()}
        for account_id, items in records.items():
            if account_id not in account_ids:
                continue
            topics = self._account_topic_bucket(data, account_id)["topics"]
            for item in items:
                topic_id = str(item.get("topicId") or "")
                refs = item.get("references") or []
                source_id = str(item.get("sourceWorkId") or "")
                if not source_id and len(refs) == 1:
                    source_id = str(refs[0].get("id") or "") if isinstance(refs[0], dict) else str(refs[0])
                if not source_id or not topic_id:
                    continue
                for topic in topics:
                    if topic.get("id") == topic_id and not topic.get("sourceWorkIds"):
                        topic["sourceWorkIds"] = [source_id]
                        changed += 1
        if changed:
            if self._topic_plans_path.exists():
                backup = self._topic_plans_path.with_name("topic-plans.before-original-recommendations.json")
                if not backup.exists():
                    shutil.copy2(self._topic_plans_path, backup)
            self._write_topic_data(data)
        return changed

    @_locked
    def create_topic(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Add one topic to the week the client is looking at."""
        self._ensure_migrated()
        self._require_account(account_id)
        source_recommendation = str(fields.get("sourceRecommendationId") or "")
        if source_recommendation:
            for source_id in fields.get("sourceWorkIds") or [(fields.get("sourceWork") or {}).get("id")]:
                existing = self.find_topic_for_source(account_id, {**(fields.get("sourceWork") or {}), "id": str(source_id or "")})
                if existing:
                    return existing
        source_advice = str(fields.get("sourceAdviceId") or "")
        if source_advice:
            for existing in self.list_topics(account_id)["items"]:
                if existing.get("sourceAdviceId") == source_advice:
                    return existing
        week = self._normalize_week_start(fields.get("weekStart"))
        now = self._now()
        topic = {
            "id": str(uuid.uuid4()),
            "accountId": account_id,
            "weekStart": week,
            "title": self._normalize_topic_title(fields.get("title"), allow_long=bool(source_recommendation)),
            "outline": self._normalize_topic_text(fields.get("outline"), "一句话大纲"),
            "category": self._normalize_topic_category(fields.get("category")),
            "format": self._normalize_topic_format(fields.get("format")),
            "publishDate": self._normalize_publish_date(fields.get("publishDate")),
            "materials": self._normalize_topic_text(fields.get("materials"), "准备素材"),
            "sourceAdviceId": source_advice,
            "sourceWorkIds": list(fields.get("sourceWorkIds") or ([str((fields.get("sourceWork") or {}).get("id"))] if (fields.get("sourceWork") or {}).get("id") else [])) if source_advice or source_recommendation else [],
            "sourceRecommendationId": source_recommendation,
            "sourceWork": json.loads(json.dumps(fields.get("sourceWork") or {})),
            "hook": self._asset_selection(fields.get("hook"), HOOK_KIND),
            "hookId": str(fields.get("hookId") or (fields.get("hook") or {}).get("id") or ""),
            "status": TOPIC_PENDING_CREATION,
            "scriptId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        data = self._read_topic_data()
        bucket = self._account_topic_bucket(data, account_id)
        bucket["topics"].append(topic)
        self._unconfirm_topic_plan(bucket, week)
        self._write_topic_data(data)
        return self._topic_view(topic)

    @_locked
    def update_topic(self, topic_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch one topic; a linked script stays the single source for its status."""
        self._ensure_migrated()
        unknown_fields = set(fields) - (set(TOPIC_FIELD_NAMES) | {"weekStart", "status"})
        if unknown_fields:
            raise ValueError("选题字段无效。")
        data = self._read_topic_data()
        bucket, topic = self._locate_topic(data, topic_id)
        self._require_account(str(topic.get("accountId") or ""))
        now = self._now()

        if "weekStart" in fields:
            week = self._normalize_week_start(fields["weekStart"])
            if week != str(topic.get("weekStart") or ""):
                self._unconfirm_topic_plan(bucket, str(topic.get("weekStart") or ""))
                topic["weekStart"] = week
        if "title" in fields:
            topic["title"] = self._normalize_topic_title(fields["title"], allow_long=bool(topic.get("sourceRecommendationId")))
        if "outline" in fields:
            topic["outline"] = self._normalize_topic_text(fields["outline"], "一句话大纲")
        if "category" in fields:
            topic["category"] = self._normalize_topic_category(fields["category"])
        if "format" in fields:
            topic["format"] = self._normalize_topic_format(fields["format"])
        if "publishDate" in fields:
            topic["publishDate"] = self._normalize_publish_date(fields["publishDate"])
        if "materials" in fields:
            topic["materials"] = self._normalize_topic_text(fields["materials"], "准备素材")

        status = ""
        if "status" in fields:
            status = str(fields["status"] or "")
            if status not in TOPIC_STATUSES:
                raise ValueError("选题状态无效。")
            topic["status"] = status
        if set(fields) - {"status"}:
            self._unconfirm_topic_plan(bucket, str(topic.get("weekStart") or ""))
        topic["updatedAt"] = now

        linked_script_id = str(topic.get("scriptId") or "")
        if status and status != TOPIC_PENDING_CREATION and linked_script_id:
            script = self._script_record(linked_script_id)
            if script is not None and str(script.get("accountId") or "") == str(topic.get("accountId") or ""):
                script["workflowStatus"] = status
                script["updatedAt"] = now
                self._write_json(self._script_path(linked_script_id), script)
        self._write_topic_data(data)
        return self._topic_view(topic)

    @_locked
    def delete_topic(self, topic_id: str) -> dict[str, Any]:
        """Remove one topic; its linked script and assets are left untouched."""
        self._ensure_migrated()
        data = self._read_topic_data()
        bucket, topic = self._locate_topic(data, topic_id)
        view = self._topic_view(topic)
        bucket["topics"].remove(topic)
        self._unconfirm_topic_plan(bucket, str(topic.get("weekStart") or ""))
        self._write_topic_data(data)
        return view

    @_locked
    def save_topic_plan(self, account_id: str, week_start: str, targets: dict[str, Any]) -> dict[str, Any]:
        """Store the week's category targets, which always invalidates confirmation."""
        self._ensure_migrated()
        self._require_account(account_id)
        week = self._normalize_week_start(week_start)
        normalized_targets = self._normalize_topic_targets(targets)
        data = self._read_topic_data()
        bucket = self._account_topic_bucket(data, account_id)
        stored = bucket["plans"].get(week)
        plan = dict(stored) if isinstance(stored, dict) else {}
        plan["targets"] = normalized_targets
        plan["confirmedAt"] = ""
        plan["updatedAt"] = self._now()
        bucket["plans"][week] = plan
        self._write_topic_data(data)
        return self._topic_plan_view(week, plan)

    @_locked
    def confirm_topic_plan(self, account_id: str, week_start: str) -> dict[str, Any]:
        """Mark one week's plan as reviewed so later edits can flag it as stale."""
        self._ensure_migrated()
        self._require_account(account_id)
        week = self._normalize_week_start(week_start)
        data = self._read_topic_data()
        bucket = self._account_topic_bucket(data, account_id)
        if not any(str(topic.get("weekStart") or "") == week for topic in bucket["topics"]):
            raise ValueError("本周还没有选题，先添加选题再确认。")
        stored = bucket["plans"].get(week)
        plan = dict(stored) if isinstance(stored, dict) else {}
        plan["targets"] = self._normalize_topic_targets(plan.get("targets"))
        plan["confirmedAt"] = self._now()
        plan["updatedAt"] = plan["confirmedAt"]
        bucket["plans"][week] = plan
        self._write_topic_data(data)
        return self._topic_plan_view(week, plan)

    @_locked
    def create_script_from_topic(self, topic_id: str) -> dict[str, Any]:
        """Create the topic's script once, then keep opening that same script."""
        self._ensure_migrated()
        data = self._read_topic_data()
        _bucket, topic = self._locate_topic(data, topic_id)
        account_id = str(topic.get("accountId") or "")
        self._require_account(account_id)
        view = self._topic_view(topic)
        if view["scriptId"]:
            linked = self._script_record(view["scriptId"])
            if linked is not None:
                return {"topic": view, "script": linked, "created": False}
        # 待创作 has no script state of its own; new scripts start at 待处理.
        initial_status = "pending" if view["status"] == TOPIC_PENDING_CREATION else view["status"]
        script = self._create_script(
            account_id=account_id,
            title=view["title"] or "未命名选题",
            source="blank",
            processing_status="ready",
            content=self._topic_reference_content(view),
            workflow_status=initial_status,
        )
        script["creation"] = self._normalize_creation(self._topic_creation_fields(account_id, {
            "topicId": topic_id, "topic": view["title"], "contentFormat": view["format"],
        }))
        self._write_json(self._script_path(script["id"]), script)
        # A topic that came from 拆解视频 keeps its reference transcript usable by
        # the 编写 stage, so the breakdown is what drives 脚本结构/脚本内容 generation.
        breakdown = self.breakdown_for_topic(str(view.get("id") or ""))
        if breakdown:
            script["breakdownId"] = breakdown["id"]
            self._write_json(self._script_path(script["id"]), script)
        topic["scriptId"] = script["id"]
        topic["status"] = initial_status
        topic["updatedAt"] = self._now()
        self._write_topic_data(data)
        return {"topic": self._topic_view(topic), "script": script, "created": True}

    def _link_script_to_topic(
        self,
        script: dict[str, Any],
        topic_id: str,
        *,
        adopt_topic_status: bool = False,
    ) -> None:
        """Attach a script created from 去创作 to its topic; the script then owns the status.

        A topic that has not reached the script list yet is 待创作, so it carries no script
        state of its own. Creating its script starts both sides at 待处理. Topics already carrying a script state keep it.
        """
        normalized_id = str(topic_id or "").strip()
        if not normalized_id:
            return
        account_id = str(script.get("accountId") or "")
        data = self._read_topic_data()
        try:
            _bucket, topic = self._locate_topic(data, normalized_id)
        except ValueError:
            # A stale topic id must not break script creation.
            return
        if str(topic.get("accountId") or "") != account_id:
            return
        existing_id = str(topic.get("scriptId") or "").strip()
        if existing_id and existing_id != str(script.get("id") or ""):
            existing = self._script_record(existing_id)
            if existing is not None and str(existing.get("accountId") or "") == account_id:
                # The topic already has a script; keep that link instead of orphaning it.
                return
        topic_status = str(topic.get("status") or "")
        if topic_status not in TOPIC_STATUSES:
            topic_status = TOPIC_PENDING_CREATION
        if adopt_topic_status and topic_status != TOPIC_PENDING_CREATION:
            # The topic keeps a state from a script that is gone; hand that state back.
            script["workflowStatus"] = topic_status
            script["updatedAt"] = self._now()
            self._write_json(self._script_path(str(script.get("id") or "")), script)
        elif adopt_topic_status:
            script["workflowStatus"] = "pending"
            topic_status = "pending"
            script["updatedAt"] = self._now()
            self._write_json(self._script_path(str(script.get("id") or "")), script)
        else:
            script_status = str(script.get("workflowStatus") or "")
            topic_status = script_status if script_status in WORKFLOW_STATUSES else "pending"
        topic["scriptId"] = str(script.get("id") or "")
        topic["status"] = topic_status
        topic["updatedAt"] = self._now()
        self._write_topic_data(data)

    def _read_topic_data(self) -> dict[str, Any]:
        """Read the topic file defensively so a damaged file cannot break the workbench."""
        try:
            raw = self._read_json(self._topic_plans_path)
        except (OSError, json.JSONDecodeError):
            raw = None
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                plans = bucket.get("plans") if isinstance(bucket.get("plans"), dict) else {}
                topics = bucket.get("topics") if isinstance(bucket.get("topics"), list) else []
                accounts[str(account_id)] = {
                    "plans": {str(week): plan for week, plan in plans.items() if isinstance(plan, dict)},
                    "topics": [topic for topic in topics if isinstance(topic, dict)],
                }
        return {"version": 1, "accounts": accounts}

    def _write_topic_data(self, data: dict[str, Any]) -> None:
        self._write_json(self._topic_plans_path, data)

    @staticmethod
    def _account_topic_bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(account_id)
        if not isinstance(bucket, dict):
            bucket = {"plans": {}, "topics": []}
            data["accounts"][account_id] = bucket
        if not isinstance(bucket.get("plans"), dict):
            bucket["plans"] = {}
        if not isinstance(bucket.get("topics"), list):
            bucket["topics"] = []
        return bucket

    @staticmethod
    def _locate_topic(data: dict[str, Any], topic_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_id = str(topic_id or "").strip()
        if normalized_id:
            for bucket in data["accounts"].values():
                for topic in bucket["topics"]:
                    if str(topic.get("id") or "") == normalized_id:
                        return bucket, topic
        raise ValueError("选题不存在。")

    def _unconfirm_topic_plan(self, bucket: dict[str, Any], week_start: str) -> None:
        """Drop a stale confirmation once the week's plan changes."""
        plan = (bucket.get("plans") or {}).get(week_start)
        if not isinstance(plan, dict) or not plan.get("confirmedAt"):
            return
        plan["confirmedAt"] = ""
        plan["updatedAt"] = self._now()

    def _unlink_topics_for_script(
        self,
        script_id: str,
        *,
        account_id: str | None = None,
        status: str | None = None,
    ) -> None:
        """Detach topics from a script that was deleted or handed to another account."""
        normalized_id = str(script_id or "").strip()
        if not normalized_id:
            return
        data = self._read_topic_data()
        changed = False
        for account_key, bucket in data["accounts"].items():
            if account_id is not None and account_key != account_id:
                continue
            for topic in bucket["topics"]:
                if str(topic.get("scriptId") or "") != normalized_id:
                    continue
                topic["scriptId"] = ""
                if status in WORKFLOW_STATUSES:
                    topic["status"] = str(status)
                topic["updatedAt"] = self._now()
                changed = True
        if changed:
            self._write_topic_data(data)

    def _topic_view(self, topic: dict[str, Any]) -> dict[str, Any]:
        """Normalize one stored topic; a live linked script owns the shown status."""
        account_id = str(topic.get("accountId") or "")
        status = str(topic.get("status") or "")
        if status not in TOPIC_STATUSES:
            status = TOPIC_PENDING_CREATION
        script_id = ""
        linked_script_id = str(topic.get("scriptId") or "").strip()
        if linked_script_id:
            script = self._script_record(linked_script_id)
            if script is not None and str(script.get("accountId") or "") == account_id:
                script_id = linked_script_id
                script_status = str(script.get("workflowStatus") or "")
                if script_status in WORKFLOW_STATUSES:
                    status = script_status
        if not script_id and status == "pending":
            # Stored legacy topics default to 待处理; without a script they are 待创作.
            status = TOPIC_PENDING_CREATION
        return {
            "id": str(topic.get("id") or ""),
            "accountId": account_id,
            "weekStart": str(topic.get("weekStart") or ""),
            "title": str(topic.get("title") or ""),
            "outline": str(topic.get("outline") or ""),
            "category": topic.get("category") if topic.get("category") in TOPIC_CATEGORIES else "highlight",
            "format": topic.get("format") if topic.get("format") in TOPIC_FORMATS else "video",
            "publishDate": str(topic.get("publishDate") or ""),
            "materials": str(topic.get("materials") or ""),
            "sourceAdviceId": str(topic.get("sourceAdviceId") or ""),
            "sourceRecommendationId": str(topic.get("sourceRecommendationId") or ""),
            "sourceWorkIds": list(topic.get("sourceWorkIds") or []),
            "sourceWork": json.loads(json.dumps(topic.get("sourceWork") or {})),
            "hook": self._asset_selection(topic.get("hook"), HOOK_KIND),
            "hookId": str(topic.get("hookId") or (topic.get("hook") or {}).get("id") or ""),
            "hookAvailability": self._topic_hook_selection(account_id, topic)[1],
            "status": status,
            "scriptId": script_id,
            "createdAt": str(topic.get("createdAt") or ""),
            "updatedAt": str(topic.get("updatedAt") or ""),
        }

    @staticmethod
    def _topic_plan_view(week_start: str, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "weekStart": week_start,
            "targets": WorkspaceStore._normalize_topic_targets(plan.get("targets")),
            "confirmedAt": str(plan.get("confirmedAt") or ""),
            "updatedAt": str(plan.get("updatedAt") or ""),
        }

    def _script_record(self, script_id: str) -> dict[str, Any] | None:
        try:
            return self.get_script(script_id)
        except ValueError:
            return None

    @staticmethod
    def _topic_reference_content(topic: dict[str, Any]) -> str:
        """Seed a new script with clearly labeled topic notes instead of an empty body."""
        outline = str(topic.get("outline") or "").strip()
        materials = str(topic.get("materials") or "").strip()
        return "\n".join([
            f"选题：{str(topic.get('title') or '').strip()}",
            f"一句话大纲：{outline}" if outline else "一句话大纲：（未填写）",
            f"准备素材：{materials}" if materials else "准备素材：（未填写）",
        ])

    @staticmethod
    def _normalize_topic_title(value: Any, *, allow_long: bool = False) -> str:
        title = str(value or "").strip()
        if not title:
            raise ValueError("选题标题不能为空。")
        if len(title) > TOPIC_TITLE_LIMIT and not allow_long:
            raise ValueError(f"选题标题不能超过{TOPIC_TITLE_LIMIT}个字符。")
        return title

    @staticmethod
    def _normalize_topic_text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if len(text) > TOPIC_TEXT_LIMIT:
            raise ValueError(f"{label}不能超过{TOPIC_TEXT_LIMIT}个字符。")
        return text

    @staticmethod
    def _normalize_topic_category(value: Any) -> str:
        category = str(value or "").strip() or "highlight"
        if category not in TOPIC_CATEGORIES:
            raise ValueError("选题分类无效。")
        return category

    @staticmethod
    def _normalize_topic_format(value: Any) -> str:
        content_format = str(value or "").strip() or "video"
        if content_format not in TOPIC_FORMATS:
            raise ValueError("内容形式无效。")
        return content_format

    @staticmethod
    def _normalize_publish_date(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError("计划发布日期无效。") from exc

    @staticmethod
    def _normalize_topic_targets(value: Any) -> dict[str, int]:
        if value is not None and not isinstance(value, dict):
            raise ValueError("周目标无效。")
        raw_targets = value or {}
        targets: dict[str, int] = {}
        for category in TOPIC_CATEGORIES:
            raw = raw_targets.get(category, DEFAULT_TOPIC_TARGETS[category])
            try:
                number = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("周目标必须是整数。") from exc
            if number < 0 or number > TOPIC_TARGET_LIMIT:
                raise ValueError(f"每个分类的目标不能超过{TOPIC_TARGET_LIMIT}条。")
            targets[category] = number
        return targets

    @staticmethod
    def _current_week_start() -> str:
        today = datetime.now().date()
        return (today - timedelta(days=today.weekday())).isoformat()

    @classmethod
    def _normalize_week_start(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return cls._current_week_start()
        try:
            day = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("周起始日期无效。") from exc
        if day.weekday() != 0:
            raise ValueError("周起始日期必须是周一。")
        return day.isoformat()

    # ------------------------------------------------------------------
    # Creator home (首页): manual tasks, inspirations, and the daily overview
    # ------------------------------------------------------------------

    def _read_item_store(self, path: Path) -> dict[str, Any]:
        """Read one per-account item file defensively so a damaged file cannot break the page."""
        try:
            raw = self._read_json(path)
        except (OSError, json.JSONDecodeError):
            raw = None
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                items = bucket.get("items") if isinstance(bucket.get("items"), list) else []
                accounts[str(account_id)] = {"items": [item for item in items if isinstance(item, dict)]}
        return {"version": 1, "accounts": accounts}

    @staticmethod
    def _item_store_bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(account_id)
        if not isinstance(bucket, dict):
            bucket = {"items": []}
            data["accounts"][account_id] = bucket
        if not isinstance(bucket.get("items"), list):
            bucket["items"] = []
        return bucket

    @staticmethod
    def _locate_item(data: dict[str, Any], item_id: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_id = str(item_id or "").strip()
        if normalized_id:
            for bucket in data["accounts"].values():
                for item in bucket["items"]:
                    if str(item.get("id") or "") == normalized_id:
                        return bucket, item
        raise ValueError(f"{label}不存在。")

    def _title_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """Titles for every topic and script, so lists resolve links without extra reads."""
        topic_data = self._read_topic_data()
        topic_titles = {
            str(topic.get("id") or ""): str(topic.get("title") or "")
            for bucket in topic_data["accounts"].values()
            for topic in bucket["topics"]
        }
        script_titles = {
            str(script.get("id") or ""): str(script.get("title") or "")
            for script in self._load_scripts().values()
        }
        return topic_titles, script_titles

    @staticmethod
    def _normalize_day(value: Any) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("日期无效。") from exc

    @staticmethod
    def _overdue_days(day_text: str, today_iso: str) -> int:
        try:
            return max(0, (date.fromisoformat(today_iso) - date.fromisoformat(day_text)).days)
        except ValueError:
            return 0

    @staticmethod
    def _normalize_task_title(value: Any) -> str:
        title = str(value or "").strip()
        if not title:
            raise ValueError("任务标题不能为空。")
        if len(title) > MANUAL_TASK_TITLE_LIMIT:
            raise ValueError(f"任务标题不能超过{MANUAL_TASK_TITLE_LIMIT}个字符。")
        return title

    @staticmethod
    def _normalize_task_note(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_task_date(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return datetime.now().date().isoformat()
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError("任务日期无效。") from exc

    @staticmethod
    def _normalize_inspiration_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("灵感内容不能为空。")
        if len(text) > INSPIRATION_TEXT_LIMIT:
            raise ValueError(f"灵感内容不能超过{INSPIRATION_TEXT_LIMIT}个字符。")
        return text

    @staticmethod
    def _normalize_inspiration_source(value: Any) -> str:
        source = str(value or "").strip()
        if len(source) > INSPIRATION_SOURCE_LIMIT:
            raise ValueError(f"来源不能超过{INSPIRATION_SOURCE_LIMIT}个字符。")
        return source

    def _normalize_task_link(self, account_id: str, link_type: Any, link_id: Any) -> tuple[str, str]:
        normalized_type = str(link_type or "").strip()
        normalized_id = str(link_id or "").strip()
        if not normalized_type:
            return "", ""
        if normalized_type not in MANUAL_TASK_LINK_TYPES:
            raise ValueError("任务关联类型无效。")
        if not normalized_id:
            raise ValueError("任务关联的内容无效。")
        if normalized_type == "topic":
            data = self._read_topic_data()
            _bucket, topic = self._locate_topic(data, normalized_id)
            if str(topic.get("accountId") or "") != account_id:
                raise ValueError("任务关联的选题不属于当前账号。")
            return normalized_type, normalized_id
        script = self._script_record(normalized_id)
        if script is None or str(script.get("accountId") or "") != account_id:
            raise ValueError("任务关联的脚本不属于当前账号。")
        return normalized_type, normalized_id

    def _manual_task_view(
        self,
        task: dict[str, Any],
        topic_titles: dict[str, str] | None = None,
        script_titles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if topic_titles is None or script_titles is None:
            topic_titles, script_titles = self._title_maps()
        link_type = str(task.get("linkType") or "")
        link_id = str(task.get("linkId") or "")
        link_title = ""
        if link_type == "topic":
            link_title = topic_titles.get(link_id, "")
        elif link_type == "script":
            link_title = script_titles.get(link_id, "")
        return {
            "id": str(task.get("id") or ""),
            "accountId": str(task.get("accountId") or ""),
            "kind": "manual",
            "title": str(task.get("title") or ""),
            "date": str(task.get("date") or ""),
            "note": str(task.get("note") or ""),
            "linkType": link_type,
            "linkId": link_id,
            "linkTitle": link_title,
            "linkMissing": bool(link_id) and not link_title,
            "done": bool(task.get("done")),
            "completedAt": str(task.get("completedAt") or ""),
            "createdAt": str(task.get("createdAt") or ""),
            "updatedAt": str(task.get("updatedAt") or ""),
        }

    def _inspiration_view(self, item: dict[str, Any], topic_titles: dict[str, str] | None = None) -> dict[str, Any]:
        if topic_titles is None:
            topic_titles, _script_titles = self._title_maps()
        topic_id = str(item.get("topicId") or "")
        topic_title = topic_titles.get(topic_id, "") if topic_id else ""
        return {
            "id": str(item.get("id") or ""),
            "accountId": str(item.get("accountId") or ""),
            "text": str(item.get("text") or ""),
            "source": str(item.get("source") or ""),
            "topicId": topic_id,
            "topicTitle": topic_title,
            "topicMissing": bool(topic_id) and not topic_title,
            "convertedAt": str(item.get("convertedAt") or ""),
            "createdAt": str(item.get("createdAt") or ""),
            "updatedAt": str(item.get("updatedAt") or ""),
        }

    @_locked
    def list_manual_tasks(self, account_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        topic_titles, script_titles = self._title_maps()
        data = self._read_item_store(self._manual_tasks_path)
        bucket = self._item_store_bucket(data, account_id)
        items = [self._manual_task_view(task, topic_titles, script_titles) for task in bucket["items"]]
        return {"items": items, "total": len(items)}

    @_locked
    def create_manual_task(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        link_type, link_id = self._normalize_task_link(account_id, fields.get("linkType"), fields.get("linkId"))
        now = self._now()
        task = {
            "id": str(uuid.uuid4()),
            "accountId": account_id,
            "title": self._normalize_task_title(fields.get("title")),
            "date": self._normalize_task_date(fields.get("date")),
            "note": self._normalize_task_note(fields.get("note")),
            "linkType": link_type,
            "linkId": link_id,
            "done": False,
            "completedAt": "",
            "createdAt": now,
            "updatedAt": now,
        }
        data = self._read_item_store(self._manual_tasks_path)
        bucket = self._item_store_bucket(data, account_id)
        bucket["items"].append(task)
        self._write_json(self._manual_tasks_path, data)
        topic_titles, script_titles = self._title_maps()
        return self._manual_task_view(task, topic_titles, script_titles)

    @_locked
    def update_manual_task(self, task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        unknown_fields = set(fields) - {"title", "date", "note", "linkType", "linkId", "done"}
        if unknown_fields:
            raise ValueError("任务字段无效。")
        data = self._read_item_store(self._manual_tasks_path)
        _bucket, task = self._locate_item(data, task_id, "任务")
        account_id = str(task.get("accountId") or "")
        self._require_account(account_id)
        if "title" in fields:
            task["title"] = self._normalize_task_title(fields["title"])
        if "date" in fields:
            task["date"] = self._normalize_task_date(fields["date"])
        if "note" in fields:
            task["note"] = self._normalize_task_note(fields["note"])
        if "linkType" in fields or "linkId" in fields:
            link_type, link_id = self._normalize_task_link(
                account_id,
                fields.get("linkType", task.get("linkType")),
                fields.get("linkId", task.get("linkId")),
            )
            task["linkType"] = link_type
            task["linkId"] = link_id
        if "done" in fields:
            finished = bool(fields["done"])
            task["done"] = finished
            task["completedAt"] = self._now() if finished else ""
        task["updatedAt"] = self._now()
        self._write_json(self._manual_tasks_path, data)
        topic_titles, script_titles = self._title_maps()
        return self._manual_task_view(task, topic_titles, script_titles)

    @_locked
    def delete_manual_task(self, task_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        data = self._read_item_store(self._manual_tasks_path)
        bucket, task = self._locate_item(data, task_id, "任务")
        self._require_account(str(task.get("accountId") or ""))
        view = self._manual_task_view(task)
        bucket["items"].remove(task)
        self._write_json(self._manual_tasks_path, data)
        return view

    @_locked
    def list_inspirations(self, account_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        topic_titles, _script_titles = self._title_maps()
        data = self._read_item_store(self._inspirations_path)
        bucket = self._item_store_bucket(data, account_id)
        items = [self._inspiration_view(item, topic_titles) for item in bucket["items"]]
        items.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return {"items": items, "total": len(items)}

    @_locked
    def create_inspiration(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        now = self._now()
        item = {
            "id": str(uuid.uuid4()),
            "accountId": account_id,
            "text": self._normalize_inspiration_text(fields.get("text")),
            "source": self._normalize_inspiration_source(fields.get("source")),
            "topicId": "",
            "convertedAt": "",
            "createdAt": now,
            "updatedAt": now,
        }
        data = self._read_item_store(self._inspirations_path)
        bucket = self._item_store_bucket(data, account_id)
        bucket["items"].append(item)
        self._write_json(self._inspirations_path, data)
        return self._inspiration_view(item)

    @_locked
    def update_inspiration(self, inspiration_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        unknown_fields = set(fields) - {"text", "source"}
        if unknown_fields:
            raise ValueError("灵感字段无效。")
        data = self._read_item_store(self._inspirations_path)
        _bucket, item = self._locate_item(data, inspiration_id, "灵感")
        self._require_account(str(item.get("accountId") or ""))
        if "text" in fields:
            item["text"] = self._normalize_inspiration_text(fields["text"])
        if "source" in fields:
            item["source"] = self._normalize_inspiration_source(fields["source"])
        item["updatedAt"] = self._now()
        self._write_json(self._inspirations_path, data)
        return self._inspiration_view(item)

    @_locked
    def delete_inspiration(self, inspiration_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        data = self._read_item_store(self._inspirations_path)
        bucket, item = self._locate_item(data, inspiration_id, "灵感")
        self._require_account(str(item.get("accountId") or ""))
        view = self._inspiration_view(item)
        bucket["items"].remove(item)
        self._write_json(self._inspirations_path, data)
        return view

    @_locked
    def convert_inspiration(self, inspiration_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Turn one saved idea into a topic, once, keeping both records linked."""
        self._ensure_migrated()
        data = self._read_item_store(self._inspirations_path)
        _bucket, item = self._locate_item(data, inspiration_id, "灵感")
        account_id = str(item.get("accountId") or "")
        self._require_account(account_id)
        topic_titles, _script_titles = self._title_maps()
        existing_id = str(item.get("topicId") or "")
        if existing_id and topic_titles.get(existing_id):
            return {
                "inspiration": self._inspiration_view(item, topic_titles),
                "topic": self._topic_view_by_id(existing_id),
                "created": False,
            }
        # A topic that was deleted afterwards lets the idea be converted again.
        text = str(item.get("text") or "").strip()
        source = str(item.get("source") or "").strip()
        default_title = next((line.strip() for line in text.splitlines() if line.strip()), "")
        topic_fields = {
            "title": str(fields.get("title") or "").strip() or default_title[:TOPIC_TITLE_LIMIT],
            "outline": str(fields.get("outline") or "").strip() or text,
            "category": fields.get("category") or "daily",
            "format": fields.get("format") or "video",
            "publishDate": fields.get("publishDate") or "",
            "materials": str(fields.get("materials") or "").strip() if "materials" in fields else source,
            "weekStart": fields.get("weekStart"),
        }
        topic = self.create_topic(account_id, topic_fields)
        item["topicId"] = str(topic["id"])
        item["convertedAt"] = self._now()
        item["updatedAt"] = item["convertedAt"]
        try:
            self._write_json(self._inspirations_path, data)
        except Exception:
            # Compensate so a retry cannot leave an orphan topic behind.
            try:
                self.delete_topic(str(topic["id"]))
            except Exception:
                logger.warning("inspiration_convert_rollback_failed inspiration=%s topic=%s", inspiration_id, topic["id"])
            raise
        topic_titles, _script_titles = self._title_maps()
        return {"inspiration": self._inspiration_view(item, topic_titles), "topic": topic, "created": True}

    def _topic_view_by_id(self, topic_id: str) -> dict[str, Any]:
        data = self._read_topic_data()
        _bucket, topic = self._locate_topic(data, topic_id)
        return self._topic_view(topic)

    def _pending_home_tasks(
        self,
        topics: list[dict[str, Any]],
        manual_items: list[dict[str, Any]],
        today_iso: str,
    ) -> list[dict[str, Any]]:
        """Unfinished items: publish reminders derived from topics plus manual tasks."""
        items: list[dict[str, Any]] = []
        for topic in topics:
            status = str(topic.get("status") or "pending")
            publish_date = str(topic.get("publishDate") or "").strip()
            if not publish_date or status == "published":
                continue
            items.append({
                "id": f"topic:{topic.get('id')}",
                "kind": "topic",
                "title": str(topic.get("title") or ""),
                "date": publish_date,
                "status": status,
                "topicId": str(topic.get("id") or ""),
                "scriptId": str(topic.get("scriptId") or ""),
                "note": "",
                "linkType": "",
                "linkId": "",
                "linkTitle": "",
                "linkMissing": False,
                "done": False,
                "completedAt": "",
                "overdueDays": self._overdue_days(publish_date, today_iso),
                "createdAt": str(topic.get("createdAt") or ""),
                "updatedAt": str(topic.get("updatedAt") or ""),
            })
        for task in manual_items:
            if task.get("done"):
                continue
            items.append({**task, "overdueDays": self._overdue_days(str(task.get("date") or ""), today_iso)})
        items.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("createdAt") or "")))
        return items

    @_locked
    def home_overview(
        self,
        account_id: str,
        *,
        today: str | None = None,
        week_start: str | None = None,
    ) -> dict[str, Any]:
        """Everything the 首页 needs: account totals, today's tasks, ideas, and the week."""
        self._ensure_migrated()
        self._require_account(account_id)
        today_iso = (self._normalize_day(today) or datetime.now().date()).isoformat()
        week = self._normalize_week_start(week_start)
        topic_data = self.list_topics(account_id)
        topics = list(topic_data["items"])
        scripts = self.list_scripts(account_id)
        status_counts = {status: 0 for status in ("pending", "editing", "ready_to_publish", "published")}
        for script in scripts:
            status = str(script.get("workflowStatus") or "pending")
            status_counts[status if status in status_counts else "pending"] += 1
        topic_titles = {str(topic.get("id") or ""): str(topic.get("title") or "") for topic in topics}
        script_titles = {str(script.get("id") or ""): str(script.get("title") or "") for script in scripts}
        manual_data = self._read_item_store(self._manual_tasks_path)
        manual_items = [
            self._manual_task_view(task, topic_titles, script_titles)
            for task in self._item_store_bucket(manual_data, account_id)["items"]
        ]
        inspiration_data = self._read_item_store(self._inspirations_path)
        inspirations = [
            self._inspiration_view(item, topic_titles)
            for item in self._item_store_bucket(inspiration_data, account_id)["items"]
        ]
        inspirations.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)

        pending = self._pending_home_tasks(topics, manual_items, today_iso)
        due = [item for item in pending if str(item.get("date") or "") <= today_iso]
        plan = (topic_data.get("plans") or {}).get(week) or {}
        targets = plan.get("targets") or dict(DEFAULT_TOPIC_TARGETS)
        target_total = sum(int(value) for value in targets.values())
        week_topics = [topic for topic in topics if str(topic.get("weekStart") or "") == week]
        week_published = sum(1 for topic in week_topics if str(topic.get("status")) == "published")
        week_editing = sum(1 for topic in week_topics if str(topic.get("status")) == "editing")
        week_ready = sum(1 for topic in week_topics if str(topic.get("status")) == "ready_to_publish")
        return {
            "accountId": account_id,
            "date": today_iso,
            "weekStart": week,
            "stats": {
                "topicCount": len(topics),
                "scriptCount": len(scripts),
                "statusCounts": status_counts,
                "pendingInspirationCount": sum(1 for item in inspirations if not item["topicId"]),
            },
            "todayTasks": {
                "items": due[:HOME_TASK_PREVIEW_LIMIT],
                "allItems": due,
                "count": len(due),
                "previewLimit": HOME_TASK_PREVIEW_LIMIT,
            },
            "inspirations": {
                "items": inspirations[:HOME_INSPIRATION_PREVIEW_LIMIT],
                "total": len(inspirations),
                "pendingCount": sum(1 for item in inspirations if not item["topicId"]),
            },
            "linkOptions": {
                "topics": [{"id": str(topic.get("id") or ""), "title": str(topic.get("title") or "")} for topic in topics],
                "scripts": [{"id": str(script.get("id") or ""), "title": str(script.get("title") or "")} for script in scripts],
            },
            "week": {
                "weekStart": week,
                "target": target_total,
                "published": week_published,
                "editing": week_editing,
                "readyToPublish": week_ready,
                "percent": None if target_total <= 0 else min(100, round(week_published * 100 / target_total)),
            },
        }

    @_locked
    def list_home_tasks(
        self,
        account_id: str,
        *,
        scope: str = "pending",
        page: int = 1,
        page_size: int = 8,
        today: str | None = None,
    ) -> dict[str, Any]:
        """The 全部任务 dialog: pending reminders plus the completed manual tasks."""
        self._ensure_migrated()
        self._require_account(account_id)
        today_iso = (self._normalize_day(today) or datetime.now().date()).isoformat()
        normalized_scope = scope if scope in ("pending", "done") else "pending"
        topic_data = self.list_topics(account_id)
        topics = list(topic_data["items"])
        scripts = self.list_scripts(account_id)
        topic_titles = {str(topic.get("id") or ""): str(topic.get("title") or "") for topic in topics}
        script_titles = {str(script.get("id") or ""): str(script.get("title") or "") for script in scripts}
        manual_data = self._read_item_store(self._manual_tasks_path)
        manual_items = [
            self._manual_task_view(task, topic_titles, script_titles)
            for task in self._item_store_bucket(manual_data, account_id)["items"]
        ]
        if normalized_scope == "done":
            items = [{**item, "overdueDays": 0} for item in manual_items if item.get("done")]
            items.sort(key=lambda item: str(item.get("completedAt") or ""), reverse=True)
        else:
            items = self._pending_home_tasks(topics, manual_items, today_iso)
        try:
            size = int(page_size)
        except (TypeError, ValueError):
            size = 8
        size = max(1, min(size, HOME_TASK_PAGE_LIMIT))
        total = len(items)
        page_count = max(1, (total + size - 1) // size)
        try:
            current = int(page)
        except (TypeError, ValueError):
            current = 1
        current = max(1, min(current, page_count))
        start = (current - 1) * size
        return {
            "items": items[start:start + size],
            "total": total,
            "page": current,
            "pageCount": page_count,
            "pageSize": size,
            "scope": normalized_scope,
        }

    @_locked
    def get_cover_state(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        state = script.get("coverState")
        return state if isinstance(state, dict) else {}

    @_locked
    def start_cover_title_generation(self, script_id: str, job_id: str, *, reference_id: str = "") -> None:
        script = self.get_script(script_id)
        current = script.get("coverTitleGeneration")
        if isinstance(current, dict) and current.get("status") == "running":
            raise ValueError("封面标题正在生成，请稍候。")
        now = self._now()
        script["coverTitleGeneration"] = {
            "jobId": job_id,
            "status": "running",
            "startedAt": now,
            "referenceId": reference_id,
            "inputSnapshot": self._cover_title_input_snapshot(script),
            "updatedAt": now,
        }
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)

    @_locked
    def complete_cover_title_generation(self, script_id: str, job_id: str, result: dict[str, Any]) -> bool:
        script = self.get_script(script_id)
        generation = script.get("coverTitleGeneration")
        if not isinstance(generation, dict) or generation.get("jobId") != job_id or generation.get("status") != "running":
            return False
        main_title = str(result.get("mainTitle") or "").strip()
        subtitle = str(result.get("subtitle") or "").strip()
        if not main_title or not subtitle:
            return False
        state = script.get("coverState") if isinstance(script.get("coverState"), dict) else {}
        applied = (post_edit.allowed(script, job_id, self)
                   and generation.get("inputSnapshot") == self._cover_title_input_snapshot(script))
        if applied:
            state["prompt"] = self._cover_title_prompt(state, main_title, subtitle, generation.get("referenceId", ""))
        script["coverState"] = state
        if applied:
            post_edit.accepted(script, job_id, promptDone=True)
        now = self._now()
        script["coverTitleGeneration"] = {
            "jobId": job_id,
            "status": "completed",
            "result": {"mainTitle": main_title, "subtitle": subtitle},
            "referenceId": generation.get("referenceId", ""),
            "applied": applied,
            "startedAt": generation.get("startedAt"),
            "updatedAt": now,
        }
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return applied

    @_locked
    def fail_cover_title_generation(self, script_id: str, job_id: str, *, code: str, message: str) -> bool:
        script = self.get_script(script_id)
        generation = script.get("coverTitleGeneration")
        if not isinstance(generation, dict) or generation.get("jobId") != job_id or generation.get("status") != "running":
            return False
        now = self._now()
        script["coverTitleGeneration"] = {
            "jobId": job_id,
            "status": "failed",
            "error": _public_error(code, message),
            "startedAt": generation.get("startedAt"),
            "updatedAt": now,
        }
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return True

    @_locked
    def interrupt_running_cover_title_generations(self) -> int:
        self._ensure_migrated()
        count = 0
        for path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            generation = script.get("coverTitleGeneration") if isinstance(script, dict) else None
            if not isinstance(generation, dict) or generation.get("status") != "running":
                continue
            now = self._now()
            script["coverTitleGeneration"] = {
                "jobId": str(generation.get("jobId") or ""),
                "status": "interrupted",
                "error": {
                    "code": "cover_title_generation_interrupted",
                    "message": "服务重启，封面标题生成已中断，请重试。",
                },
                "startedAt": generation.get("startedAt"),
                "updatedAt": now,
            }
            script["updatedAt"] = now
            self._write_json(path, script)
            count += 1
        return count

    @staticmethod
    def _cover_generation_view(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        job_id = str(value.get("jobId") or "").strip()
        status = str(value.get("status") or "").strip()
        if status not in {"running", "completed", "failed", "interrupted", "cancelled"}:
            return None
        aspects: list[dict[str, Any]] = []
        for item in value.get("aspects", []):
            if not isinstance(item, dict) or item.get("aspect") not in COVER_ASPECTS:
                continue
            aspect_job_id = str(item.get("jobId") or job_id).strip()
            if not aspect_job_id:
                continue
            item_status = str(item.get("status") or "pending")
            if item_status not in {"pending", "submitted", "success", "error", "interrupted", "cancelled"}:
                continue
            normalized = {
                "aspect": item["aspect"],
                "jobId": aspect_job_id,
                "status": item_status,
                "imageTaskId": str(item.get("imageTaskId") or "")[:200],
                "imageUrl": str(item.get("imageUrl") or "")[:4096],
                "message": sanitize_message(str(item.get("message") or ""))[:500],
                "error": _public_error_view(item.get("error")),
            }
            aspects.append(normalized)
        if not aspects:
            return None
        return {
            # Kept for consumers of the legacy single-job payload.  New code
            # must use each aspect's jobId, because the two aspect slots may
            # now belong to different concurrent jobs.
            "jobId": job_id or aspects[-1]["jobId"],
            "status": status,
            "aspects": sorted(aspects, key=lambda item: COVER_ASPECTS.index(item["aspect"])),
            "error": _public_error_view(value.get("error")),
            "startedAt": str(value.get("startedAt") or "")[:100],
            "updatedAt": str(value.get("updatedAt") or "")[:100],
        }

    @staticmethod
    def _cover_generation_job_view(generation: dict[str, Any] | None, job_id: str) -> dict[str, Any] | None:
        """Return the active record for one aspect-scoped cover job."""
        if not generation:
            return None
        normalized_job_id = str(job_id).strip()
        aspects = [item for item in generation["aspects"] if item.get("jobId") == normalized_job_id]
        if not aspects:
            return None
        terminal = all(item["status"] in {"success", "error", "interrupted", "cancelled"} for item in aspects)
        if not terminal:
            status = "running"
        elif any(item["status"] == "success" for item in aspects):
            status = "completed"
        elif all(item["status"] == "interrupted" for item in aspects):
            status = "interrupted"
        elif all(item["status"] == "cancelled" for item in aspects):
            status = "cancelled"
        else:
            status = "failed"
        job_error = next((_public_error_view(item["error"]) for item in aspects if item.get("error")), {})
        return {
            "jobId": normalized_job_id,
            "status": status,
            "aspects": aspects,
            "error": job_error,
            "startedAt": generation.get("startedAt", ""),
            "updatedAt": generation.get("updatedAt", ""),
        }

    @staticmethod
    def _merge_cover_result(state: dict[str, Any], aspect: str, image_url: str) -> None:
        results = state.get("results") if isinstance(state.get("results"), list) else []
        retained = [
            item for item in results
            if isinstance(item, dict) and item.get("aspect") in COVER_ASPECTS and item.get("aspect") != aspect
        ]
        retained.append({"aspect": aspect, "imageUrl": image_url, "status": "success", "message": ""})
        state["results"] = sorted(retained, key=lambda item: COVER_ASPECTS.index(item["aspect"]))

    @staticmethod
    def _merge_cover_failure(state: dict[str, Any], aspect: str, message: str) -> None:
        results = state.get("results") if isinstance(state.get("results"), list) else []
        retained = [
            item for item in results
            if isinstance(item, dict) and item.get("aspect") in COVER_ASPECTS and item.get("aspect") != aspect
        ]
        retained.append({"aspect": aspect, "imageUrl": "", "status": "error", "message": str(message)[:500]})
        state["results"] = sorted(retained, key=lambda item: COVER_ASPECTS.index(item["aspect"]))

    @staticmethod
    def _merge_cover_cancellation(state: dict[str, Any], aspect: str) -> None:
        results = state.get("results") if isinstance(state.get("results"), list) else []
        retained = [
            item for item in results
            if isinstance(item, dict) and item.get("aspect") in COVER_ASPECTS and item.get("aspect") != aspect
        ]
        retained.append({"aspect": aspect, "imageUrl": "", "status": "cancelled", "message": "已取消，可重新生成"})
        state["results"] = sorted(retained, key=lambda item: COVER_ASPECTS.index(item["aspect"]))

    @staticmethod
    def _cover_generation_is_terminal(generation: dict[str, Any]) -> bool:
        return all(item.get("status") in {"success", "error", "interrupted", "cancelled"} for item in generation["aspects"])

    @classmethod
    def _refresh_cover_generation_status(cls, generation: dict[str, Any], *, error: dict[str, str] | None = None) -> None:
        if not cls._cover_generation_is_terminal(generation):
            generation["status"] = "running"
            return
        if any(item["status"] == "success" for item in generation["aspects"]):
            generation["status"] = "completed"
        elif all(item["status"] == "interrupted" for item in generation["aspects"]):
            generation["status"] = "interrupted"
        elif all(item["status"] == "cancelled" for item in generation["aspects"]):
            generation["status"] = "cancelled"
        else:
            generation["status"] = "failed"
        if error:
            generation["error"] = error

    @_locked
    def get_cover_generation(self, script_id: str, job_id: str | None = None) -> dict[str, Any] | None:
        generation = self._cover_generation_view(self.get_script(script_id).get("coverGeneration"))
        return self._cover_generation_job_view(generation, job_id) if job_id else generation

    @_locked
    def get_cover_status(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        if self._restore_completed_cover_title_prompt(script):
            script["updatedAt"] = self._now()
            self._write_json(self._script_path(script_id), script)
        return {
            "state": script.get("coverState") if isinstance(script.get("coverState"), dict) else {},
            "generation": self._cover_generation_view(script.get("coverGeneration")),
            "titleGeneration": script.get("coverTitleGeneration") if isinstance(script.get("coverTitleGeneration"), dict) else None,
        }

    @_locked
    def start_cover_generation(self, script_id: str, job_id: str, aspects: list[str]) -> dict[str, Any]:
        script = self.get_script(script_id)
        current = self._cover_generation_view(script.get("coverGeneration"))
        normalized_job_id = str(job_id).strip()
        normalized_aspects = [aspect for aspect in COVER_ASPECTS if aspect in aspects]
        if not normalized_job_id or not normalized_aspects:
            raise ValueError("封面生成任务无效。")
        active_aspects = {
            item["aspect"]
            for item in (current or {}).get("aspects", [])
            if item["status"] in {"pending", "submitted"}
        }
        requested_aspects = [aspect for aspect in normalized_aspects if aspect not in active_aspects]
        if not requested_aspects:
            raise ValueError(f"{'、'.join(normalized_aspects)} 尺寸正在生成中，请稍候。")
        now = self._now()
        started_aspects = [
            {
                "aspect": aspect,
                "jobId": normalized_job_id,
                "status": "pending",
                "imageTaskId": "",
                "imageUrl": "",
                "message": "",
                "error": {},
            }
            for aspect in requested_aspects
        ]
        if current and current["status"] == "running":
            generation = {
                **current,
                "jobId": normalized_job_id,
                "status": "running",
                "aspects": [
                    item for item in current["aspects"] if item["aspect"] not in requested_aspects
                ] + started_aspects,
                "updatedAt": now,
            }
        else:
            generation = {
                "jobId": normalized_job_id,
                "status": "running",
                "aspects": started_aspects,
                "startedAt": now,
                "updatedAt": now,
            }
        script["coverGeneration"] = generation
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return self._cover_generation_job_view(self._cover_generation_view(generation), normalized_job_id) or {}

    @_locked
    def record_cover_task(self, script_id: str, job_id: str, aspect: str, image_task_id: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return None
        task_id = str(image_task_id).strip()
        if aspect not in COVER_ASPECTS or not task_id:
            raise ValueError("封面生成任务无效。")
        for item in generation["aspects"]:
            if item["aspect"] == aspect and item["jobId"] == job_id and item["status"] == "pending":
                item.update(status="submitted", imageTaskId=task_id, message="")
                break
        else:
            return None
        generation["updatedAt"] = self._now()
        script["coverGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._cover_generation_job_view(generation, job_id)

    @_locked
    def mark_cover_status_unconfirmed(self, script_id: str, job_id: str, aspect: str) -> None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return
        for item in generation["aspects"]:
            if item["aspect"] == aspect and item["jobId"] == job_id and item["status"] == "submitted":
                item["message"] = "状态暂无法确认，正在查询原任务；平台提交超过 30 分钟将超时收尾。"
                script["coverGeneration"] = generation
                self._write_json(self._script_path(script_id), script)
                return

    @_locked
    def reserve_cover_output(self, script_id: str, job_id: str, aspect: str, image_url: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return None
        for item in generation["aspects"]:
            if item["aspect"] == aspect and item["jobId"] == job_id and item["status"] == "submitted":
                item["imageUrl"] = str(image_url)[:4096]
                generation["updatedAt"] = self._now()
                script["coverGeneration"] = generation
                script["updatedAt"] = generation["updatedAt"]
                self._write_json(self._script_path(script_id), script)
                return self._cover_generation_job_view(generation, job_id)
        return None

    @_locked
    def complete_cover_aspect(self, script_id: str, job_id: str, aspect: str, image_url: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return None
        for item in generation["aspects"]:
            if item["aspect"] == aspect and item["jobId"] == job_id and item["status"] in {"pending", "submitted"}:
                item.update(status="success", imageUrl=str(image_url)[:4096], message="", error={})
                break
        else:
            return None
        if not post_edit.allowed(script, job_id, self):
            item.update(status="cancelled", message=post_edit.CONFLICT)
            self._refresh_cover_generation_status(generation)
            script["coverGeneration"] = generation
            self._write_json(self._script_path(script_id), script)
            return None
        state = script.get("coverState") if isinstance(script.get("coverState"), dict) else {}
        self._merge_cover_result(state, aspect, str(image_url)[:4096])
        script["coverState"] = state
        self._refresh_cover_generation_status(generation)
        generation["updatedAt"] = self._now()
        script["coverGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._cover_generation_job_view(generation, job_id)

    @_locked
    def fail_cover_aspect(self, script_id: str, job_id: str, aspect: str, *, code: str, message: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return None
        for item in generation["aspects"]:
            if item["aspect"] == aspect and item["jobId"] == job_id and item["status"] in {"pending", "submitted"}:
                item.update(
                    status="error",
                    message=sanitize_message(message)[:500],
                    error=_public_error(code, message),
                )
                break
        else:
            return None
        state = script.get("coverState") if isinstance(script.get("coverState"), dict) else {}
        if not post_edit.owner(script, job_id):
            self._merge_cover_failure(state, aspect, sanitize_message(message))
        script["coverState"] = state
        self._refresh_cover_generation_status(
            generation,
            error=_public_error(code, message),
        )
        generation["updatedAt"] = self._now()
        script["coverGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._cover_generation_job_view(generation, job_id)

    @_locked
    def cancel_cover_generation(self, script_id: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation:
            return None
        state = script.get("coverState") if isinstance(script.get("coverState"), dict) else {}
        changed = False
        for item in generation["aspects"]:
            if item["status"] not in {"pending", "submitted"}:
                continue
            item.update(
                status="cancelled",
                message="已取消，可重新生成",
                error={"code": "cover_generation_cancelled", "message": "已停止接收本次生成结果。"},
            )
            self._merge_cover_cancellation(state, item["aspect"])
            changed = True
        if not changed:
            return generation
        self._refresh_cover_generation_status(generation)
        generation["updatedAt"] = self._now()
        script["coverState"] = state
        script["coverGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._cover_generation_view(generation)

    @_locked
    def interrupt_unsubmitted_cover_aspects(self, script_id: str, job_id: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        if not generation or generation["status"] != "running":
            return None
        changed = False
        for item in generation["aspects"]:
            if item["jobId"] == job_id and item["status"] == "pending" and not item["imageTaskId"]:
                item.update(status="interrupted", message="服务重启时任务尚未提交，请重新生成。")
                changed = True
        if changed:
            self._refresh_cover_generation_status(
                generation,
                error={"code": "cover_generation_interrupted", "message": "服务重启，未提交的封面生成已中断，请重新生成。"},
            )
            generation["updatedAt"] = self._now()
            script["coverGeneration"] = generation
            script["updatedAt"] = generation["updatedAt"]
            self._write_json(self._script_path(script_id), script)
        return self._cover_generation_job_view(generation, job_id)

    @_locked
    def list_running_cover_generations(self) -> list[dict[str, Any]]:
        self._ensure_migrated()
        jobs: list[dict[str, Any]] = []
        for script_path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(script, dict):
                continue
            generation = self._cover_generation_view(script.get("coverGeneration"))
            if not generation or generation["status"] != "running":
                continue
            active_job_ids = {
                item["jobId"] for item in generation["aspects"]
                if item["status"] in {"pending", "submitted"}
            }
            for job_id in active_job_ids:
                job = self._cover_generation_job_view(generation, job_id)
                if job and job["status"] == "running":
                    jobs.append({"scriptId": str(script.get("id") or ""), "generation": job})
        return jobs

    @_locked
    def save_cover_state(self, script_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Persist cover module state per script so it is shared across browsers."""
        script = self.get_script(script_id)
        current = script.get("coverState") if isinstance(script.get("coverState"), dict) else {}
        if not str(state.get("prompt") or "").strip():
            self._restore_completed_cover_title_prompt(script, state)
        generation = self._cover_generation_view(script.get("coverGeneration"))
        current_results = current.get("results") if isinstance(current.get("results"), list) else []
        if current_results:
            # Generated results belong to the server. A delayed browser
            # snapshot may contain an older URL for the same aspect, so it
            # must never replace an already persisted result.
            state["results"] = [dict(item) for item in current_results if isinstance(item, dict)]
        if generation:
            for item in generation["aspects"]:
                if item["status"] == "success" and item["imageUrl"]:
                    self._merge_cover_result(state, item["aspect"], item["imageUrl"])
                elif item["status"] == "error" and not post_edit.owner(script, item["jobId"]):
                    self._merge_cover_failure(state, item["aspect"], item["message"])
                elif item["status"] == "cancelled" and not post_edit.owner(script, item["jobId"]):
                    self._merge_cover_cancellation(state, item["aspect"])
        script["coverState"] = state
        self._write_json(self._script_path(script_id), script)
        return state

    @staticmethod
    def _cover_title_input_snapshot(script: dict[str, Any]) -> str:
        state = script.get("coverState") or {}
        return json.dumps({"prompt": state.get("prompt", ""), "images": state.get("uploadedImages", []),
                           "video": (script.get("publishAssets") or {}).get("video")}, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _cover_title_prompt(state: dict[str, Any], main_title: str, subtitle: str, reference_id: str) -> str:
        prefix = ""
        if reference_id:
            for index, image in enumerate(state.get("uploadedImages") or []):
                if image.get("id") == reference_id and image.get("source") == "publish-video":
                    prefix = f"参考 @{image['name']}（第{index + 1}张参考图） 视频画面的色调风格生成用于发布抖音/视频号平台的视频封面：\n"
                    break
        return prefix + f"主标题：“{main_title}”\n副标题：“{subtitle}”"

    @staticmethod
    def _restore_completed_cover_title_prompt(script: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
        generation = script.get("coverTitleGeneration")
        if not isinstance(generation, dict) or generation.get("status") != "completed" or generation.get("applied") is False:
            return False
        result = generation.get("result")
        if not isinstance(result, dict):
            return False
        main_title = str(result.get("mainTitle") or "").strip()
        subtitle = str(result.get("subtitle") or "").strip()
        if not main_title or not subtitle:
            return False
        target = state if state is not None else script.get("coverState")
        if not isinstance(target, dict) or str(target.get("prompt") or "").strip():
            return False
        target["prompt"] = WorkspaceStore._cover_title_prompt(target, main_title, subtitle, generation.get("referenceId", ""))
        if state is None:
            script["coverState"] = target
        return True

    @_locked
    def list_cover_templates(self, account_id: str) -> list[dict[str, Any]]:
        self._ensure_migrated()
        self._require_account(account_id)
        return self._read_cover_templates().get(account_id, [])

    @_locked
    def create_cover_template(self, account_id: str, template: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        templates_by_account = self._read_cover_templates()
        templates = templates_by_account.setdefault(account_id, [])
        legacy_id = str(template.get("legacyId") or "").strip()
        if legacy_id:
            existing = next((item for item in templates if item.get("legacyId") == legacy_id), None)
            if existing is not None:
                return existing
        now = self._now()
        created = {
            "id": str(uuid.uuid4()),
            "label": template["label"],
            "prompt": template["prompt"],
            "accent": template["accent"],
            "images": template["images"],
            "createdAt": now,
            "updatedAt": now,
        }
        if legacy_id:
            created["legacyId"] = legacy_id
        templates.append(created)
        self._write_json(self._cover_templates_path, templates_by_account)
        return created

    @_locked
    def update_cover_template(self, account_id: str, template_id: str, template: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        templates_by_account = self._read_cover_templates()
        templates = templates_by_account.get(account_id, [])
        for index, existing in enumerate(templates):
            if existing.get("id") != template_id:
                continue
            updated = {
                **existing,
                "label": template["label"],
                "prompt": template["prompt"],
                "accent": template["accent"],
                "images": template["images"],
                "updatedAt": self._now(),
            }
            templates[index] = updated
            templates_by_account[account_id] = templates
            self._write_json(self._cover_templates_path, templates_by_account)
            return updated
        raise ValueError("模板不存在。")

    @_locked
    def delete_cover_template(self, account_id: str, template_id: str) -> None:
        self._ensure_migrated()
        self._require_account(account_id)
        templates_by_account = self._read_cover_templates()
        templates = templates_by_account.get(account_id, [])
        next_templates = [item for item in templates if item.get("id") != template_id]
        if len(next_templates) == len(templates):
            raise ValueError("模板不存在。")
        templates_by_account[account_id] = next_templates
        self._write_json(self._cover_templates_path, templates_by_account)

    @_locked
    def get_publish_assets(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        assets = script.get("publishAssets")
        if not isinstance(assets, dict):
            return {"video": None, "covers": {}}
        return self._normalize_publish_assets(script_id, assets)

    @_locked
    def save_publish_assets(self, script_id: str, assets: dict[str, Any], *, automation_job_id: str = "") -> dict[str, Any]:
        script = self.get_script(script_id)
        normalized = self._normalize_publish_assets(script_id, assets)
        if not automation_job_id and normalized != script.get("publishAssets"):
            post_edit.pause(script)
        script["publishAssets"] = normalized
        if automation_job_id:
            post_edit.accepted(script, automation_job_id)
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return normalized

    @_locked
    def pause_post_edit_automations(self, script_id: str) -> None:
        script = self.get_script(script_id)
        if any(state.get("stage") not in post_edit.TERMINAL for state in (script.get("postEditAutomations") or {}).values()):
            post_edit.pause(script)
            self._write_json(self._script_path(script_id), script)

    @_locked
    def post_edit_generation_allowed(self, script_id: str, job_id: str, *, recover_output: bool = False) -> bool:
        script = self.get_script(script_id)
        result = post_edit.allowed(script, job_id, self, recover_output=recover_output)
        if not result:
            self._write_json(self._script_path(script_id), script)
        return result

    @_locked
    def resolve_publish_asset_path(self, script_id: str, raw_path: str) -> Path:
        """Resolve only metadata paths owned by the requested script."""
        self.get_script(script_id)
        relative = Path(raw_path)
        expected_parent = Path("scripts") / script_id / "publish-assets"
        if (
            relative.is_absolute()
            or relative.parent != expected_parent
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("发布素材路径无效。")
        workspace = self._workspace_dir.resolve()
        asset_dir = (workspace / expected_parent).resolve()
        candidate = workspace / relative
        try:
            asset_dir.relative_to(workspace)
            candidate.resolve().relative_to(asset_dir)
        except ValueError as exc:
            raise ValueError("发布素材路径无效。") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("发布素材文件不存在。")
        return candidate.resolve()

    @_locked
    def validate_publish_platform(self, account_id: str, platform: str) -> dict[str, Any]:
        if platform not in TITLE_PLATFORMS:
            raise ValueError("发布平台无效。")
        self._ensure_migrated()
        account = self._require_account(account_id)
        return account

    @_locked
    def get_publish_draft(self, script_id: str, platform: str) -> dict[str, Any]:
        self._validate_title_platform(platform)
        state = self.get_title_state(script_id)
        if not isinstance(state, dict):
            raise ValueError("请先保存该平台的发布文案。")
        group = self._title_platform_state(state, platform)
        draft = group.get("publishDraft")
        main_field = "title" if platform == "douyin" else "shortTitle"
        if (
            not isinstance(draft, dict)
            or not str(draft.get(main_field) or "").strip()
            or (platform == "channels" and not str(draft.get("description") or "").strip())
        ):
            raise ValueError("请先保存该平台的发布文案。")
        self._validate_publish_title_length(platform, str(draft[main_field]).strip())
        return {
            main_field: str(draft[main_field]).strip(),
            "description": str(draft.get("description") or "").strip(),
            "topics": self._normalize_topics(draft.get("topics")),
        }

    @_locked
    def get_title_state(self, script_id: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        state = script.get("titleState")
        if not isinstance(state, dict):
            return None
        if isinstance(state.get("platforms"), dict):
            # Normalize old generated drafts on read; preserve manual edits and disk data.
            group = state["platforms"].get("douyin")
            draft = group.get("publishDraft") if isinstance(group, dict) else None
            if isinstance(draft, dict) and not draft.get("isCustomized"):
                draft["description"] = ""
            return state
        migrated = self._migrate_legacy_title_state(state)
        script["titleState"] = migrated
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return migrated

    @staticmethod
    def _title_generation_view(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        job_id = str(value.get("jobId") or "").strip()
        status = str(value.get("status") or "").strip()
        if not job_id or status not in {"running", "failed", "interrupted"}:
            return None
        generation: dict[str, Any] = {"jobId": job_id, "status": status}
        error = value.get("error")
        if status != "running" and isinstance(error, dict):
            generation["error"] = _public_error(
                error.get("code") or "title_generation_failed",
                error.get("message") or "标题生成失败，已保留现有结果。",
            )
        return generation

    def _save_title_candidates_to_script(self, script: dict[str, Any], candidates_by_platform: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        if not isinstance(candidates_by_platform, dict) or set(candidates_by_platform) != TITLE_PLATFORMS:
            raise ValueError("标题候选状态无效。")
        if any(not isinstance(candidates_by_platform[platform], list) or len(candidates_by_platform[platform]) != 3 for platform in TITLE_PLATFORMS):
            raise ValueError("每个平台的标题候选必须恰好为三个。")
        old_state = script.get("titleState")
        if not isinstance(old_state, dict):
            old_state = None
        elif not isinstance(old_state.get("platforms"), dict):
            old_state = self._migrate_legacy_title_state(old_state)
        previous_platforms = old_state.get("platforms") if isinstance(old_state, dict) else {}
        state = {"platforms": {}}
        for platform in TITLE_PLATFORMS:
            candidates = candidates_by_platform[platform]
            selected = candidates[0]
            old_group = previous_platforms.get(platform) if isinstance(previous_platforms, dict) else None
            old_draft = old_group.get("publishDraft") if isinstance(old_group, dict) else None
            draft = self._candidate_to_publish_draft(platform, selected)
            if isinstance(old_draft, dict) and old_draft.get("isCustomized") is True:
                draft = self._custom_publish_draft(platform, old_draft)
            state["platforms"][platform] = {
                "candidates": candidates,
                "selectedId": selected.get("id"),
                "publishDraft": draft,
            }
        script["titleState"] = state
        return state

    @_locked
    def get_title_generation(self, script_id: str) -> dict[str, Any] | None:
        return self._title_generation_view(self.get_script(script_id).get("titleGeneration"))

    @_locked
    def get_title_status(self, script_id: str) -> dict[str, Any]:
        """Read title candidates and generation metadata from one script snapshot."""
        return {
            "state": self.get_title_state(script_id),
            "generation": self.get_title_generation(script_id),
        }

    @_locked
    def start_title_generation(self, script_id: str, job_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        current = self._title_generation_view(script.get("titleGeneration"))
        if current and current["status"] == "running":
            raise ValueError("标题正在生成中，请稍候。")
        normalized_job_id = str(job_id).strip()
        if not normalized_job_id:
            raise ValueError("标题生成任务无效。")
        now = self._now()
        generation = {"jobId": normalized_job_id, "status": "running", "startedAt": now, "updatedAt": now}
        script["titleGeneration"] = generation
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return self._title_generation_view(generation) or {}

    @_locked
    def complete_title_generation(self, script_id: str, job_id: str, candidates_by_platform: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        current = self._title_generation_view(script.get("titleGeneration"))
        if not current or current["status"] != "running" or current["jobId"] != job_id:
            return None
        if not post_edit.allowed(script, job_id, self):
            script["titleGeneration"].update(status="interrupted", error={"code": "post_edit_paused", "message": post_edit.CONFLICT})
            self._write_json(self._script_path(script_id), script)
            return None
        if post_edit.owner(script, job_id):
            # This opt-in workflow explicitly replaces even customized old drafts.
            script.pop("titleState", None)
        state = self._save_title_candidates_to_script(script, candidates_by_platform)
        post_edit.accepted(script, job_id, titleDone=True)
        script.pop("titleGeneration", None)
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return state

    @_locked
    def fail_title_generation(self, script_id: str, job_id: str, *, code: str, message: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        current = self._title_generation_view(script.get("titleGeneration"))
        if not current or current["status"] != "running" or current["jobId"] != job_id:
            return None
        generation = {
            "jobId": job_id,
            "status": "failed",
            "error": _public_error(code, message),
            "startedAt": script["titleGeneration"].get("startedAt"),
            "updatedAt": self._now(),
        }
        script["titleGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._title_generation_view(generation)

    @_locked
    def interrupt_running_title_generations(self) -> int:
        self._ensure_migrated()
        interrupted = 0
        for script_path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                continue
            current = self._title_generation_view(script.get("titleGeneration")) if isinstance(script, dict) else None
            if not current or current["status"] != "running":
                continue
            now = self._now()
            script["titleGeneration"] = {
                "jobId": current["jobId"],
                "status": "interrupted",
                "error": {"code": "title_generation_interrupted", "message": "服务重启，标题生成已中断，请重试。"},
                "startedAt": script["titleGeneration"].get("startedAt"),
                "updatedAt": now,
            }
            script["updatedAt"] = now
            self._write_json(script_path, script)
            interrupted += 1
        return interrupted

    @_locked
    def save_title_candidates(self, script_id: str, candidates_by_platform: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        script = self.get_script(script_id)
        state = self._save_title_candidates_to_script(script, candidates_by_platform)
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return state

    @_locked
    def select_title_candidate(self, script_id: str, platform: str, candidate_id: str) -> dict[str, Any]:
        self._validate_title_platform(platform)
        script = self.get_script(script_id)
        state = self.get_title_state(script_id)
        if not state:
            raise ValueError("请先生成标题候选。")
        group = self._title_platform_state(state, platform)
        candidates = group.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 3:
            raise ValueError("标题候选状态无效。")
        selected = next((item for item in candidates if isinstance(item, dict) and item.get("id") == candidate_id), None)
        if selected is None:
            raise ValueError("标题候选不存在。")
        group["selectedId"] = candidate_id
        draft = group.get("publishDraft")
        if not isinstance(draft, dict) or not draft.get("isCustomized"):
            group["publishDraft"] = self._candidate_to_publish_draft(platform, selected)
        script["titleState"] = state
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return state

    @_locked
    def save_publish_draft(self, script_id: str, platform: str, *, title: str | None, short_title: str | None, description: str, topics: list[str]) -> dict[str, Any]:
        self._validate_title_platform(platform)
        script = self.get_script(script_id)
        state = self.get_title_state(script_id)
        if not state:
            state = {"platforms": {item: self._empty_title_platform_state() for item in TITLE_PLATFORMS}}
        group = self._title_platform_state(state, platform)
        main_field = "title" if platform == "douyin" else "shortTitle"
        main_value = title if platform == "douyin" else short_title
        if not isinstance(main_value, str) or not main_value.strip():
            raise ValueError("发布标题不能为空。")
        self._validate_publish_title_length(platform, main_value.strip())
        if not isinstance(description, str) or (platform == "channels" and not description.strip()):
            raise ValueError("发布描述不能为空。")
        group["publishDraft"] = {
            main_field: main_value.strip(),
            "description": description.strip(),
            "topics": self._normalize_topics(topics),
            "isCustomized": True,
        }
        script["titleState"] = state
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return state

    @_locked
    def restore_selected_title_to_publish_draft(self, script_id: str, platform: str) -> dict[str, Any]:
        self._validate_title_platform(platform)
        script = self.get_script(script_id)
        state = self.get_title_state(script_id)
        if not state:
            raise ValueError("请先生成标题候选。")
        group = self._title_platform_state(state, platform)
        selected_id = group.get("selectedId")
        candidates = group.get("candidates")
        selected = next(
            (item for item in candidates if isinstance(item, dict) and item.get("id") == selected_id),
            None,
        ) if isinstance(candidates, list) else None
        if selected is None:
            raise ValueError("当前已选标题不存在。")
        group["publishDraft"] = self._candidate_to_publish_draft(platform, selected)
        script["titleState"] = state
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return state

    @staticmethod
    def _empty_title_platform_state() -> dict[str, Any]:
        return {"candidates": [], "selectedId": None, "publishDraft": None}

    def _migrate_legacy_title_state(self, legacy_state: dict[str, Any]) -> dict[str, Any]:
        candidates = legacy_state.get("candidates")
        normalized_candidates: list[dict[str, Any]] = []
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                normalized_candidates.append({
                    "id": str(candidate.get("id") or ""),
                    "title": str(candidate.get("title") or ""),
                    "description": str(candidate.get("description") or ""),
                    "topics": self._normalize_topics(candidate.get("topics")),
                })
        draft = legacy_state.get("publishDraft")
        douyin_draft = self._custom_publish_draft("douyin", draft) if isinstance(draft, dict) else None
        if isinstance(draft, dict) and draft.get("isCustomized") is not True:
            selected = next((item for item in normalized_candidates if item.get("id") == legacy_state.get("selectedId")), None)
            douyin_draft = self._candidate_to_publish_draft("douyin", selected) if selected else douyin_draft
        return {
            "platforms": {
                "douyin": {
                    "candidates": normalized_candidates,
                    "selectedId": legacy_state.get("selectedId"),
                    "publishDraft": douyin_draft,
                },
                "channels": self._empty_title_platform_state(),
            },
        }

    @staticmethod
    def _validate_title_platform(platform: str) -> None:
        if platform not in TITLE_PLATFORMS:
            raise ValueError("标题平台无效。")

    def _title_platform_state(self, state: dict[str, Any], platform: str) -> dict[str, Any]:
        platforms = state.get("platforms")
        if not isinstance(platforms, dict):
            raise ValueError("标题候选状态无效。")
        group = platforms.get(platform)
        if not isinstance(group, dict):
            raise ValueError("标题候选状态无效。")
        return group

    @staticmethod
    def _validate_publish_title_length(platform: str, title: str) -> None:
        limit = 30 if platform == "douyin" else 16
        if len(title) > limit:
            label = "抖音标题" if platform == "douyin" else "视频号短标题"
            raise ValueError(f"{label}不能超过 {limit} 字，请修改后再保存或填充。")

    def _candidate_to_publish_draft(self, platform: str, candidate: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise ValueError("当前已选标题不存在。")
        main_field = "title" if platform == "douyin" else "shortTitle"
        return {
            main_field: str(candidate.get(main_field) or "").strip(),
            "description": "" if platform == "douyin" else str(candidate.get("description") or "").strip(),
            "topics": self._normalize_topics(candidate.get("topics")),
            "isCustomized": False,
        }

    def _custom_publish_draft(self, platform: str, draft: dict[str, Any]) -> dict[str, Any]:
        main_field = "title" if platform == "douyin" else "shortTitle"
        return {
            main_field: str(draft.get(main_field) or "").strip(),
            "description": str(draft.get("description") or "")[:2000].strip(),
            "topics": self._normalize_topics(draft.get("topics")),
            "isCustomized": True,
        }

    # --- 编写（脚本结构 / 脚本内容）与环节记忆 ---

    def _read_account_profiles(self) -> dict[str, Any]:
        if not self._account_profiles_path.exists():
            return {}
        raw = self._read_json(self._account_profiles_path)
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _normalize_account_profile(value: Any) -> dict[str, str]:
        profile = value if isinstance(value, dict) else {}
        return {
            field: str(profile.get(field) or "").strip()[:ACCOUNT_PROFILE_FIELD_LIMIT] or DEFAULT_ACCOUNT_PROFILE[field]
            for field in ("businessPositioning", "targetAudience")
        }

    @_locked
    def read_account_profile(self, account_id: str) -> dict[str, str]:
        """Return one account profile, persisting preset placeholders on first read."""
        self._ensure_migrated()
        profiles = self._read_account_profiles()
        existing = profiles.get(account_id)
        normalized = self._normalize_account_profile(existing)
        if not isinstance(existing, dict) or existing != normalized:
            profiles[account_id] = normalized
            self._write_json(self._account_profiles_path, profiles)
        return normalized

    @_locked
    def read_account_positioning(self, account_id: str) -> dict[str, str]:
        """项目设置读取定位：先确认账号存在，避免给不存在的账号写入占位档案。"""
        self._ensure_migrated()
        self._require_account(account_id)
        return self.read_account_profile(account_id)

    @_locked
    def save_account_positioning(
        self,
        account_id: str,
        business_positioning: Any,
        target_audience: Any,
    ) -> dict[str, str]:
        """按账号保存商业定位与面向人群；留空沿用「待完善」占位，超长直接报错不截断。"""
        self._ensure_migrated()
        self._require_account(account_id)
        labels = {"businessPositioning": "商业定位", "targetAudience": "面向人群"}
        submitted = {"businessPositioning": business_positioning, "targetAudience": target_audience}
        normalized: dict[str, str] = {}
        for field, raw in submitted.items():
            text = str(raw or "").strip()
            if len(text) > ACCOUNT_PROFILE_FIELD_LIMIT:
                raise ValueError(f"{labels[field]}不能超过{ACCOUNT_PROFILE_FIELD_LIMIT}个字符。")
            normalized[field] = text or DEFAULT_ACCOUNT_PROFILE[field]
        profiles = self._read_account_profiles()
        profiles[account_id] = normalized
        self._write_json(self._account_profiles_path, profiles)
        self.onboarding_view(account_id, [])
        return normalized

    def _read_account_memory_all(self) -> dict[str, Any]:
        if not self._account_memory_path.exists():
            return {}
        raw = self._read_json(self._account_memory_path)
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _memory_text_entries(value: Any, limit: int) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for item in value if isinstance(value, list) else []:
            raw_text = item.get("text") if isinstance(item, dict) else item
            text = str(raw_text or "").strip()[:limit]
            if not text:
                continue
            created_at = str(item.get("createdAt") or "") if isinstance(item, dict) else ""
            entries.append({"text": text, "createdAt": created_at})
        return entries

    @_locked
    def read_account_memory(self, account_id: str) -> dict[str, Any]:
        """读取一个账号的编写记忆。

        记忆正文（preferences）只来自 Markdown 记忆库；提示词、提示词历史和
        防同质化开关仍保存在 account-memory.json 里。目录不可用时不假装没有记忆，
        而是把原因放进 ``memoryError``，由生成入口决定是否阻止本次写作。
        """
        self._ensure_memories_migrated()
        memory = self._read_account_memory_all()
        raw = memory.get(account_id) if isinstance(memory, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        result: dict[str, Any] = {}
        for node in ("structure", "content"):
            node_raw = raw.get(node) if isinstance(raw.get(node), dict) else {}
            prompt = str(node_raw.get("prompt") or "").strip()[:WRITING_PROMPT_LIMIT] or DEFAULT_WRITING_PROMPTS[node]
            preferences: list[dict[str, Any]] = []
            memory_error = ""
            try:
                preferences = self._memory_library.read_entries(account_id, scope=node)
            except MemoryStoreError as exc:
                memory_error = exc.message
            result[node] = {
                "prompt": prompt,
                "antiSimilarity": node_raw.get("antiSimilarity") is not False,
                "preferences": preferences,
                "promptHistory": self._memory_text_entries(node_raw.get("promptHistory"), WRITING_PROMPT_LIMIT)[-WRITING_PROMPT_HISTORY_LIMIT:],
                "memoryError": memory_error,
            }
        return result

    def _ensure_memories_migrated(self) -> None:
        """把历史 JSON 偏好正文一次性迁移成 MD；迁移前备份原文件。"""
        self._ensure_migrated()
        if self._memories_migrated:
            return
        self._memories_migrated = True
        library = self._memory_library
        if library.migrated_at():
            return
        legacy = self._read_account_memory_all()
        has_legacy = any(
            isinstance(nodes, dict)
            and any(isinstance(nodes.get(node), dict) and (nodes[node].get("preferences") or []) for node in WRITING_NODES)
            for nodes in legacy.values()
        )
        try:
            if has_legacy:
                backup_path = self._workspace_dir / "account-memory.migrated-backup.json"
                if not backup_path.exists():
                    self._write_json(backup_path, legacy)
                result = library.migrate_from_json(legacy)
                logger.info(
                    "记忆迁移完成 created=%s skipped=%s",
                    result["created"], result["skipped"],
                )
            library.mark_migrated(source="account-memory.json")
        except MemoryStoreError as exc:
            # 迁移失败不阻塞读取；记忆目录本身不可用时由生成入口报错。
            logger.warning("记忆迁移暂未完成：%s", exc.code)

    @staticmethod
    def _account_memory_node(memory: dict[str, Any], account_id: str, node: str) -> dict[str, Any]:
        account_memory = memory.get(account_id) if isinstance(memory.get(account_id), dict) else {}
        node_memory = account_memory.get(node) if isinstance(account_memory.get(node), dict) else {}
        return node_memory

    @_locked
    def writing_prompt(self, account_id: str, node: str) -> str:
        if node not in WRITING_NODES:
            raise ValueError("编写环节无效。")
        return self.read_account_memory(account_id)[node]["prompt"]

    @_locked
    def record_writing_prompt(
        self,
        account_id: str,
        node: str,
        prompt: str,
        anti_similarity: bool | None = None,
    ) -> str:
        if node not in WRITING_NODES:
            raise ValueError("编写环节无效。")
        normalized = str(prompt or "").strip()[:WRITING_PROMPT_LIMIT]
        if not normalized:
            raise ValueError("提示词不能为空。")
        memory = self._read_account_memory_all()
        node_memory = dict(self._account_memory_node(memory, account_id, node))
        node_memory["prompt"] = normalized
        if anti_similarity is not None:
            node_memory["antiSimilarity"] = anti_similarity is not False
        history = self._memory_text_entries(node_memory.get("promptHistory"), WRITING_PROMPT_LIMIT)
        history.append({"text": normalized, "createdAt": self._now()})
        node_memory["promptHistory"] = history[-WRITING_PROMPT_HISTORY_LIMIT:]
        node_memory["preferences"] = self._memory_text_entries(node_memory.get("preferences"), WRITING_MEMORY_TEXT_LIMIT)[-WRITING_MEMORY_LIMIT:]
        memory.setdefault(account_id, {})[node] = node_memory
        self._write_json(self._account_memory_path, memory)
        return normalized

    @_locked
    def append_writing_memory(
        self,
        account_id: str,
        node: str,
        text: str,
        *,
        title: str = "",
        evidence: str = "",
        source: str = "manual",
    ) -> list[dict[str, Any]]:
        """把当前环节的内容沉淀成一条写作偏好 MD，并返回该环节的最新偏好列表。"""
        if node not in WRITING_NODES:
            raise ValueError("编写环节无效。")
        self._ensure_memories_migrated()
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("当前环节还没有可沉淀的内容。")
        if len(normalized) > WRITING_MEMORY_TEXT_LIMIT:
            raise ValueError(f"单条记忆最多 {WRITING_MEMORY_TEXT_LIMIT} 个字，请精简后再沉淀。")
        try:
            self._memory_library.create_memory(
                account_id,
                title=title or derive_title(normalized),
                category="preference",
                scope=node,
                content=normalized,
                evidence=evidence,
                source=source,
                dedupe=True,
            )
        except MemoryStoreError as exc:
            raise ValueError(exc.message) from None
        return self.read_account_memory(account_id)[node]["preferences"]

    # ------------------------------------------------------------------ 记忆管理

    @_locked
    def memory_settings_view(self, account_id: str = "") -> dict[str, Any]:
        self._ensure_memories_migrated()
        account = self._require_account(account_id) if account_id else None
        view = self._memory_library.settings_view(account_id)
        if account:
            view["accountName"] = account["name"]
        return view

    @_locked
    def save_memory_settings(self, directory: str, account_id: str = "") -> dict[str, Any]:
        """切换记忆目录；已有记忆会先复制到新目录，校验通过后才生效。"""
        self._ensure_memories_migrated()
        owners = [a["id"] for a in self._read_accounts()]
        if account_id:
            self._require_account(account_id)
            return self._memory_library.save_account_settings(account_id, directory, owners)
        view = self._memory_library.save_settings(directory, account_ids=owners)
        self._memory_library.initialize_accounts(owners)
        view.update(self._memory_library.settings_view())
        return view

    @_locked
    def list_memories(self, account_id: str) -> dict[str, Any]:
        self._ensure_memories_migrated()
        self._require_account(account_id)
        return self._memory_library.list_memories(account_id)

    @_locked
    def create_memory(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_memories_migrated()
        self._require_account(account_id)
        return self._memory_library.create_memory(account_id, **fields)

    @_locked
    def update_memory(self, account_id: str, memory_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_memories_migrated()
        self._require_account(account_id)
        return self._memory_library.update_memory(account_id, memory_id, **fields)

    @_locked
    def set_memory_enabled(self, account_id: str, memory_id: str, enabled: bool) -> dict[str, Any]:
        self._ensure_memories_migrated()
        self._require_account(account_id)
        return self._memory_library.set_enabled(account_id, memory_id, enabled)

    def _reference_copy_title(self, account_id: str, breakdown_id: str) -> str:
        """Recover old title metadata only from the owning account's local source."""
        if not breakdown_id:
            return ""
        try:
            record = self.get_breakdown(breakdown_id)
        except KeyError:
            return ""
        if record["accountId"] != account_id:
            return ""
        return " ".join(str(record.get("title") or "").split())[:TITLE_LIMIT]

    @_locked
    def collect_reference_copy(self, account_id: str, breakdown_id: str, transcript: str, title: str = "") -> dict[str, Any]:
        self._require_account(account_id)
        record = self.get_breakdown(breakdown_id)
        if record["accountId"] != account_id:
            raise KeyError("拆解记录不属于当前账号。")
        self._ensure_memories_migrated()
        library = self._memory_library
        for item in library._account_memories(account_id):
            if item["category"] == "reference_copy" and item.get("sourceBreakdownId") == breakdown_id:
                return item
        share = str(record.get("shareText") or "")
        match = re.search(r"https?://[^\s]+", share)
        return library.create_memory(
            account_id,
            category="reference_copy", scope="content", content=transcript,
            title=" ".join(str(record.get("title") or title or "").split())[:TITLE_LIMIT],
            source="breakdown", sourceBreakdownId=breakdown_id,
            sourceUrl=match.group(0) if match else "",
            evidence=share[:2000],
        )

    @_locked
    def delete_memory(self, account_id: str, memory_id: str) -> dict[str, str]:
        self._require_account(account_id)
        self._ensure_memories_migrated()
        return self._memory_library.delete_memory(account_id, memory_id)

    @_locked
    def read_reference_copies(self, account_id: str, ids: list[str]) -> dict[str, Any]:
        self._require_account(account_id)
        self._ensure_memories_migrated()
        return self._memory_library.read_experiences(account_id, ids, category="reference_copy")

    @_locked
    def read_memory_experiences(self, account_id: str, ids: list[str]) -> dict[str, Any]:
        """读取本篇选中的个人经历；停用与已删除的条目如实回报，供生成前提示。"""
        self._ensure_memories_migrated()
        return self._memory_library.read_experiences(account_id, ids)

    @_locked
    def list_memory_experiences(self, account_id: str) -> list[dict[str, Any]]:
        """列出当前账号已启用的个人经历，供「本篇使用哪几条」勾选。"""
        self._ensure_memories_migrated()
        try:
            return self._memory_library.read_entries(account_id, scope="content", category="experience")
        except MemoryStoreError:
            return []

    @staticmethod
    def _memory_selection_ids(script: dict[str, Any], key: str = "experienceIds") -> list[str]:
        raw = script.get("memorySelections") if isinstance(script.get("memorySelections"), dict) else {}
        return [str(item) for item in raw.get(key) or [] if str(item).strip()]

    @_locked
    def get_memory_selections(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        return {key: self._memory_selection_ids(script, key) for key in ("experienceIds", "referenceCopyIds")}

    @_locked
    def save_memory_selections(self, script_id: str, ids: list[str] | None = None, reference_copy_ids: list[str] | None = None) -> dict[str, Any]:
        script = self.get_script(script_id)
        selections = self.get_memory_selections(script_id)
        for key, values in (("experienceIds", ids), ("referenceCopyIds", reference_copy_ids)):
            if values is None:
                continue
            wanted = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
            if len(wanted) > 50:
                raise ValueError("一次最多选择 50 条参考素材。")
            selections[key] = wanted
        script["memorySelections"] = selections
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return selections

    @staticmethod
    def _writing_structure_view(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        topic = str(value.get("topic") or "").strip()
        raw_sections = value.get("sections")
        if not topic or not isinstance(raw_sections, list):
            return None
        sections: list[dict[str, str]] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            key_point = str(item.get("keyPoint") or "").strip()
            if not (name and purpose and key_point):
                continue
            sections.append({"name": name, "purpose": purpose, "keyPoint": key_point})
        if not sections:
            return None
        view: dict[str, Any] = {"topic": topic, "sections": sections}
        updated_at = str(value.get("updatedAt") or "").strip()
        if updated_at:
            view["updatedAt"] = updated_at
        return view

    @_locked
    def get_writing_state(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
        return {
            "structure": self._writing_structure_view(state.get("structure")),
            "content": str(state.get("content") or ""),
        }

    @staticmethod
    def _writing_generation_view(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        job_id = str(value.get("jobId") or "").strip()
        status = str(value.get("status") or "").strip()
        node = str(value.get("node") or "").strip()
        if not job_id or status not in {"running", "failed", "interrupted"} or node not in WRITING_NODES:
            return None
        generation: dict[str, Any] = {"jobId": job_id, "status": status, "node": node}
        error = value.get("error")
        if status != "running" and isinstance(error, dict):
            generation["error"] = _public_error(
                error.get("code") or "writing_generation_failed",
                error.get("message") or "脚本生成失败，已保留现有结果。",
            )
        return generation

    @_locked
    def get_writing_generation(self, script_id: str) -> dict[str, Any] | None:
        return self._writing_generation_view(self.get_script(script_id).get("writingGeneration"))

    @_locked
    def get_writing_status(self, script_id: str) -> dict[str, Any]:
        return {
            "state": self.get_writing_state(script_id),
            "generation": self.get_writing_generation(script_id),
        }

    @_locked
    def start_writing_generation(
        self, script_id: str, job_id: str, node: str, *, only_if_empty: bool = False,
    ) -> dict[str, Any] | None:
        if node not in WRITING_NODES:
            raise ValueError("编写环节无效。")
        script = self.get_script(script_id)
        current = self._writing_generation_view(script.get("writingGeneration"))
        # Reserve automatic work atomically with manual generations and edits.
        if only_if_empty and (current or (script.get("writingState") or {}).get("structure")):
            return None
        if current and current["status"] == "running":
            raise ValueError("脚本正在生成中，请稍候。")
        normalized_job_id = str(job_id).strip()
        if not normalized_job_id:
            raise ValueError("脚本生成任务无效。")
        now = self._now()
        generation = {"jobId": normalized_job_id, "status": "running", "node": node, "startedAt": now, "updatedAt": now}
        script["writingGeneration"] = generation
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return self._writing_generation_view(generation) or {}

    @_locked
    def complete_writing_generation(
        self,
        script_id: str,
        job_id: str,
        *,
        node: str,
        structure: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        current = self._writing_generation_view(script.get("writingGeneration"))
        if not current or current["status"] != "running" or current["jobId"] != job_id or current["node"] != node:
            return None
        state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
        now = self._now()
        if node == "structure":
            payload = dict(structure) if isinstance(structure, dict) else {}
            payload["updatedAt"] = now
            view = self._writing_structure_view(payload)
            if view is None:
                return None
            state["structure"] = view
        else:
            text = str(content or "").strip()
            if not text:
                return None
            state["content"] = text
        script["writingState"] = state
        script.pop("writingGeneration", None)
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        onboarding.remember_script(self, script)
        return self.get_writing_state(script_id)

    @_locked
    def fail_writing_generation(self, script_id: str, job_id: str, *, code: str, message: str) -> dict[str, Any] | None:
        script = self.get_script(script_id)
        current = self._writing_generation_view(script.get("writingGeneration"))
        if not current or current["status"] != "running" or current["jobId"] != job_id:
            return None
        generation = {
            "jobId": job_id,
            "status": "failed",
            "node": current["node"],
            "error": _public_error(code, message),
            "startedAt": script["writingGeneration"].get("startedAt"),
            "updatedAt": self._now(),
        }
        script["writingGeneration"] = generation
        script["updatedAt"] = generation["updatedAt"]
        self._write_json(self._script_path(script_id), script)
        return self._writing_generation_view(generation)

    @_locked
    def save_writing_structure(self, script_id: str, structure: dict[str, Any]) -> dict[str, Any]:
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以保存脚本结构。")
        generation = self._writing_generation_view(script.get("writingGeneration"))
        if generation and generation["status"] == "running":
            raise ValueError("正在生成，请等待完成后再保存结构。")
        view = self._writing_structure_view(structure)
        if view is None or len(view["sections"]) != len(structure.get("sections", [])):
            raise ValueError("请完整填写选题和至少一个段落。")
        now = self._now()
        view["updatedAt"] = now
        state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
        state["structure"] = view
        script["writingState"] = state
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return self.get_writing_state(script_id)

    @_locked
    def save_writing_content(self, script_id: str, content: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以保存编写内容。")
        state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
        state["content"] = str(content or "")[:100000]
        script["writingState"] = state
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        onboarding.remember_script(self, script)
        return self.get_writing_state(script_id)

    @_locked
    def interrupt_running_writing_generations(self) -> int:
        self._ensure_migrated()
        interrupted = 0
        for script_path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                continue
            current = self._writing_generation_view(script.get("writingGeneration")) if isinstance(script, dict) else None
            if not current or current["status"] != "running":
                continue
            now = self._now()
            script["writingGeneration"] = {
                "jobId": current["jobId"],
                "status": "interrupted",
                "node": current["node"],
                "error": {"code": "writing_generation_interrupted", "message": "服务重启，脚本生成已中断，请重试。"},
                "startedAt": script["writingGeneration"].get("startedAt"),
                "updatedAt": now,
            }
            script["updatedAt"] = now
            self._write_json(script_path, script)
            interrupted += 1
        return interrupted

    # ------------------------------------------------------------------
    # Writing material library (开头钩子 / 结构模板 / 结尾引导)
    # ------------------------------------------------------------------

    def _read_writing_assets(self) -> dict[str, Any]:
        """Read the asset file defensively so a damaged file cannot break the workbench."""
        try:
            raw = self._read_json(self._writing_assets_path)
        except (OSError, json.JSONDecodeError):
            raw = None
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                accounts[str(account_id)] = {
                    kind: [item for item in (bucket.get(kind) if isinstance(bucket.get(kind), list) else []) if isinstance(item, dict)]
                    for kind in WRITING_ASSET_KINDS
                }
                accounts[str(account_id)]["overrides"] = bucket.get("overrides") if isinstance(bucket.get("overrides"), dict) else {}
                accounts[str(account_id)]["deleted"] = [str(x) for x in bucket.get("deleted", [])] if isinstance(bucket.get("deleted"), list) else []
        return {"accounts": accounts}

    def _write_writing_assets(self, data: dict[str, Any]) -> None:
        self._write_json(self._writing_assets_path, data)

    @staticmethod
    def _account_asset_bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        accounts = data.setdefault("accounts", {})
        bucket = accounts.get(account_id)
        if not isinstance(bucket, dict):
            bucket = {}
            accounts[account_id] = bucket
        for kind in WRITING_ASSET_KINDS:
            if not isinstance(bucket.get(kind), list):
                bucket[kind] = []
        return bucket

    @_locked
    def list_writing_assets(self, account_id: str) -> dict[str, Any]:
        """Return the built-in library merged with this account's own assets."""
        self._ensure_migrated()
        self._require_account(account_id)
        bucket = self._read_writing_assets()["accounts"].get(account_id) or {}
        result = {}
        overrides = bucket.get("overrides", {})
        deleted = set(bucket.get("deleted", []))
        for kind, key in ((HOOK_KIND, "hooks"), (STRUCTURE_KIND, "structures"), (ENDING_KIND, "endings")):
            presets = []
            for item in builtin_assets(kind):
                if item["id"] in deleted:
                    continue
                override = overrides.get(item["id"])
                presets.append(asset_view({**item, **override}, builtin=True) if isinstance(override, dict) else item)
            custom = [asset_view(item, builtin=False) for item in bucket.get(kind, [])]
            custom.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
            result[key] = [*presets, *custom]
        return result

    def _account_writing_asset(self, account_id: str, asset_id: str) -> dict[str, Any]:
        for items in self.list_writing_assets(account_id).values():
            for item in items:
                if item["id"] == asset_id:
                    return item
        raise KeyError("素材不存在。")

    @_locked
    def update_account_writing_asset(self, account_id: str, asset_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        asset = self._account_writing_asset(account_id, asset_id)
        if not asset["builtin"]:
            return self.update_writing_asset(asset_id, fields)
        # Store a complete account-owned override without changing the stable preset ID.
        merged = {**asset, "note": asset.get("note") or asset.get("description", ""), **fields}
        normalized = normalize_asset_fields(asset["kind"], merged)
        data = self._read_writing_assets()
        bucket = self._account_asset_bucket(data, account_id)
        updated = {**asset, **normalized, "description": normalized["note"], "updatedAt": self._now()}
        bucket.setdefault("overrides", {})[asset_id] = updated
        self._write_writing_assets(data)
        return asset_view(updated, builtin=True)

    @_locked
    def delete_account_writing_asset(self, account_id: str, asset_id: str) -> dict[str, Any]:
        asset = self._account_writing_asset(account_id, asset_id)
        if not asset["builtin"]:
            return self.delete_writing_asset(asset_id)
        data = self._read_writing_assets()
        bucket = self._account_asset_bucket(data, account_id)
        bucket.setdefault("deleted", []).append(asset_id)
        bucket.setdefault("overrides", {}).pop(asset_id, None)
        self._write_writing_assets(data)
        return asset

    @_locked
    def create_writing_asset(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        kind = str(fields.get("kind") or "").strip()
        asset = normalize_asset_fields(kind, fields)
        data = self._read_writing_assets()
        bucket = self._account_asset_bucket(data, account_id)
        if len(bucket[kind]) >= ASSET_LIMIT_PER_KIND:
            raise ValueError("自定义素材数量已达上限，请先清理不再使用的素材。")
        now = self._now()
        asset["id"] = str(uuid.uuid4())
        asset["accountId"] = account_id
        asset["createdAt"] = now
        asset["updatedAt"] = now
        bucket[kind].append(asset)
        self._write_writing_assets(data)
        return asset_view(asset, builtin=False)

    @_locked
    def collect_breakdown_asset(self, account_id: str, breakdown_id: str, kind: str, edited_fields: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_account(account_id)
        record = self.get_breakdown(breakdown_id)
        if record.get("accountId") != account_id:
            raise KeyError("拆解记录不存在。")
        if kind not in WRITING_ASSET_KINDS:
            raise ValueError("素材类型无效。")
        analysis = record.get("analysis")
        if not analysis or record.get("analysisStatus") != "complete":
            raise ValueError("请先完成拆解分析。")
        data = self._read_writing_assets()
        bucket = self._account_asset_bucket(data, account_id)
        for asset in bucket[kind]:
            if asset.get("sourceBreakdownId") == breakdown_id:
                return asset_view(asset, builtin=False)
        draft = (analysis.get("templates") or {}).get(kind)
        if not draft:
            raise ValueError("请先补充分析，生成模板草稿后再添加。")
        if kind == "ending" and not (analysis.get("cta") or {}).get("present"):
            raise ValueError("当前视频没有可保存的结尾引导。")
        fields = dict(draft if edited_fields is None else edited_fields)
        if kind == "structure":
            fields["format"] = "video"
        else:
            fields["note"] = fields.get("content", "")
        asset = normalize_asset_fields(kind, fields)
        if len(bucket[kind]) >= ASSET_LIMIT_PER_KIND:
            raise ValueError("自定义素材数量已达上限，请先清理不再使用的素材。")
        now = self._now()
        asset.update(id=str(uuid.uuid4()), accountId=account_id, createdAt=now, updatedAt=now,
                     sourceBreakdownId=breakdown_id, sourceTitle=record.get("title") or analysis["topic"])
        bucket[kind].append(asset)
        self._write_writing_assets(data)
        return asset_view(asset, builtin=False)

    def _locate_writing_asset(self, asset_id: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        normalized = str(asset_id or "").strip()
        if not normalized or Path(normalized).name != normalized:
            raise KeyError("素材不存在。")
        data = self._read_writing_assets()
        for account_id, bucket in data["accounts"].items():
            for kind in WRITING_ASSET_KINDS:
                for asset in bucket.get(kind, []):
                    if isinstance(asset, dict) and str(asset.get("id") or "") == normalized:
                        return data, account_id, asset
        raise KeyError("素材不存在。")

    @staticmethod
    def _require_custom_asset(asset: dict[str, Any]) -> None:
        if asset.get("builtin") is True or not str(asset.get("id") or ""):
            raise ValueError("内置素材不能修改或删除。")

    def _locate_editable_writing_asset(self, asset_id: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        """Reject shipped library entries with a clear message instead of 'not found'."""
        try:
            return self._locate_writing_asset(asset_id)
        except KeyError:
            if is_builtin_asset_id(asset_id):
                raise ValueError("内置素材不能修改或删除。") from None
            raise

    @_locked
    def update_writing_asset(self, asset_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._ensure_migrated()
        data, account_id, asset = self._locate_editable_writing_asset(asset_id)
        self._require_custom_asset(asset)
        kind = str(asset.get("kind") or "")
        merged = {
            "name": fields.get("name", asset.get("name")),
            "content": fields.get("content", asset.get("content")),
            "note": fields.get("note", asset.get("note")),
            "example": fields.get("example", asset.get("example")),
            "format": fields.get("format", asset.get("format")),
        }
        normalized = normalize_asset_fields(kind, merged)
        asset.update(normalized)
        asset["updatedAt"] = self._now()
        self._write_writing_assets(data)
        return asset_view(asset, builtin=False)

    @_locked
    def delete_writing_asset(self, asset_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        data, account_id, asset = self._locate_editable_writing_asset(asset_id)
        self._require_custom_asset(asset)
        bucket = self._account_asset_bucket(data, account_id)
        bucket[str(asset.get("kind"))].remove(asset)
        self._write_writing_assets(data)
        return asset_view(asset, builtin=False)

    # ------------------------------------------------------------------
    # Script creation parameters (直接创建)
    # ------------------------------------------------------------------

    @staticmethod
    def _asset_selection(value: Any, kind: str) -> dict[str, Any]:
        """Freeze the chosen hook / structure so later library edits cannot rewrite a task."""
        if not isinstance(value, dict):
            return {}
        content = str(value.get("content") or "").strip()[:CREATION_POINTS_LIMIT]
        name = str(value.get("name") or "").strip()[:120]
        if not content and not name:
            return {}
        steps = value.get("steps") if isinstance(value.get("steps"), list) else []
        return {
            "id": str(value.get("id") or "")[:120],
            "kind": kind,
            "name": name,
            "content": content,
            "note": str(value.get("note") or "")[:400],
            "example": str(value.get("example") or "")[:400],
            "steps": [str(step)[:80] for step in steps if str(step).strip()][:24],
            "format": str(value.get("format") or "")[:20],
        }

    def _topic_hook_selection(self, account_id: str, topic: dict[str, Any]) -> tuple[dict, str]:
        snapshot = self._asset_selection(topic.get("hook"), HOOK_KIND)
        hook_id = str(topic.get("hookId") or snapshot.get("id") or "")
        if not snapshot and not hook_id:
            return {}, ""
        current = next((asset for asset in self.list_writing_assets(account_id)["hooks"] if asset["id"] == hook_id), None)
        if current is None:
            return {}, "historical"
        selected = self._asset_selection(current, HOOK_KIND)
        return selected, "current" if selected == snapshot else "changed"

    def _topic_creation_fields(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        fields = dict(fields)
        topic_id = str(fields.get("topicId") or "")
        if not topic_id:
            return fields
        try:
            _, topic = self._locate_topic(self._read_topic_data(), topic_id)
        except ValueError:
            return fields
        if str(topic.get("accountId") or "") != account_id:
            fields["topicId"] = ""
            return fields
        selected, status = self._topic_hook_selection(account_id, topic)
        fields["topicHookSnapshot"] = self._asset_selection(topic.get("hook"), HOOK_KIND)
        fields["topicHookStatus"] = status
        if "hook" not in fields:
            fields["hook"] = selected
        elif isinstance(fields.get("hook"), dict) and fields["hook"].get("id"):
            # Validate against this account's current library at the handoff boundary.
            hook_id = fields["hook"]["id"]
            current = next((asset for asset in self.list_writing_assets(account_id)["hooks"] if asset["id"] == hook_id), None)
            fields["hook"] = current or {}
        return fields

    def _normalize_creation(self, fields: dict[str, Any]) -> dict[str, Any]:
        content_format = str(fields.get("contentFormat") or "video").strip()
        if content_format not in CREATION_FORMATS:
            raise ValueError("内容形式无效。")
        points = str(fields.get("points") or "").replace("\r\n", "\n").strip()[:CREATION_POINTS_LIMIT]
        advanced = str(fields.get("advanced") or "").replace("\r\n", "\n").strip()[:CREATION_ADVANCED_LIMIT]
        structure = self._asset_selection(fields.get("structure"), STRUCTURE_KIND)
        if structure and content_format == "video" and structure.get("format") == "article":
            raise ValueError("图文结构模板不能用于视频脚本。")
        if structure and content_format == "article" and structure.get("format") == "video":
            raise ValueError("视频结构模板不能用于图文脚本。")
        return {
            "topicId": str(fields.get("topicId") or "")[:120],
            "topic": " ".join(str(fields.get("topic") or "").split())[:CREATION_TOPIC_LIMIT],
            "contentFormat": content_format,
            "platform": str(fields.get("platform") or "")[:40],
            "duration": " ".join(str(fields.get("duration") or "").split())[:CREATION_DURATION_LIMIT],
            "points": points,
            "advanced": advanced,
            "hook": self._asset_selection(fields.get("hook"), HOOK_KIND),
            "topicHookSnapshot": self._asset_selection(fields.get("topicHookSnapshot"), HOOK_KIND),
            "topicHookStatus": str(fields.get("topicHookStatus") or ""),
            "ending": self._asset_selection(fields.get("ending"), ENDING_KIND),
            "structure": structure,
            "updatedAt": self._now(),
        }

    @_locked
    def create_script_draft(self, account_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Create the script record that 直接创建 / Agent生成 works on."""
        self._ensure_migrated()
        self._require_account(account_id)
        creation = self._normalize_creation(self._topic_creation_fields(account_id, fields))
        title = " ".join(str(fields.get("title") or "").split())[:120] or creation["topic"]
        script = self._create_script(
            account_id=account_id,
            title=title or self._default_script_title(),
            source="blank",
            processing_status="ready",
            content="",
        )
        script["creation"] = creation
        script["memorySelections"] = {key: list(dict.fromkeys(fields.get(key) or []))[:50] for key in ("experienceIds", "referenceCopyIds")}
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script["id"]), script)
        # 去创作 creates the script for a 待创作 topic, so the handoff rule still applies.
        self._link_script_to_topic(script, creation["topicId"], adopt_topic_status=True)
        return script

    @_locked
    def save_script_creation(self, script_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        script = self.get_script(script_id)
        script["creation"] = self._normalize_creation(self._topic_creation_fields(script["accountId"], fields))
        selections = self.get_memory_selections(script_id)
        for key in ("experienceIds", "referenceCopyIds"):
            if key in fields:
                selections[key] = list(dict.fromkeys(fields[key] or []))[:50]
        script["memorySelections"] = selections
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        self._link_script_to_topic(script, script["creation"]["topicId"])
        return script

    @staticmethod
    def _set_script_content(script: dict[str, Any], text: str) -> None:
        if script.get("source") == "link":
            state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
            state["content"] = text
            script["writingState"] = state
        else:
            script["content"] = text

    @_locked
    def apply_script_content(self, script_id: str, content: str) -> dict[str, Any]:
        """Write finished text back to 脚本内容, whichever stage owns it."""
        script = self.get_script(script_id)
        text = str(content or "")[:AGENT_RETURN_LIMIT]
        now = self._now()
        self._set_script_content(script, text)
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        onboarding.remember_script(self, script)
        return script

    # ------------------------------------------------------------------
    # Agent generation tasks and 定稿回传
    # ------------------------------------------------------------------

    @staticmethod
    def _agent_task_view(task: Any) -> dict[str, Any]:
        raw = task if isinstance(task, dict) else {}
        pending = raw.get("pendingReturn") if isinstance(raw.get("pendingReturn"), dict) else None
        return {
            "taskId": str(raw.get("taskId") or ""),
            "status": str(raw.get("status") or ""),
            "launchedAt": str(raw.get("launchedAt") or ""),
            "launchedContent": str(raw.get("launchedContent") or ""),
            "appliedAt": str(raw.get("appliedAt") or ""),
            "submissionIds": [str(item) for item in raw.get("submissionIds") or []],
            "pendingReturn": {
                "content": str(pending.get("content") or ""),
                "submissionId": str(pending.get("submissionId") or ""),
                "createdAt": str(pending.get("createdAt") or ""),
            } if pending else None,
        }

    @_locked
    def get_writing_agent_task(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        return self._agent_task_view(script.get("writingAgentTask"))

    @staticmethod
    def _script_content(script: dict[str, Any]) -> str:
        if script.get("source") == "link":
            state = script.get("writingState") if isinstance(script.get("writingState"), dict) else {}
            return str(state.get("content") or "")
        return str(script.get("content") or "")

    def writing_agent_descriptor_path(self, task_id: str) -> Path:
        """Return the descriptor path so the prompt can name it before the file exists."""
        normalized = str(task_id or "").strip()
        if not normalized or Path(normalized).name != normalized:
            raise ValueError("Agent 任务标识无效。")
        return self._writing_agent_tasks_dir / f"{normalized}.json"

    @_locked
    def create_writing_agent_task(
        self, script_id: str, *, task_id: str, endpoint: str, token: str,
        context: str = "", assistant_id: str = "",
    ) -> dict[str, Any]:
        """Write the descriptor the return Skill reads, and mark the script as awaiting."""
        script = self.get_script(script_id)
        account_id = str(script.get("accountId") or "")
        self._require_account(account_id)
        descriptor_path = self.writing_agent_descriptor_path(task_id)
        task_id = descriptor_path.stem
        now = self._now()
        descriptor = {
            "id": task_id,
            "endpoint": str(endpoint),
            "token": str(token),
            "context": context,
            "assistantId": assistant_id,
            "scriptId": script_id,
            "accountId": account_id,
            "title": str(script.get("title") or ""),
            "createdAt": now,
        }
        self._write_json(descriptor_path, descriptor)
        previous = script.get("writingAgentTask") if isinstance(script.get("writingAgentTask"), dict) else {}
        script["writingAgentTask"] = {
            "taskId": task_id,
            "status": "awaiting",
            "launchedAt": now,
            "launchedContent": self._script_content(script),
            "submissionIds": [str(item) for item in previous.get("submissionIds") or []],
        }
        script["updatedAt"] = now
        self._write_json(self._script_path(script_id), script)
        return {
            "descriptorPath": str(descriptor_path),
            "task": self._agent_task_view(script["writingAgentTask"]),
        }

    def _read_agent_descriptor(self, task_id: str) -> dict[str, Any]:
        normalized = str(task_id or "").strip()
        if not normalized or Path(normalized).name != normalized:
            raise KeyError("Agent 任务不存在。")
        try:
            descriptor = self._read_json(self._writing_agent_tasks_dir / f"{normalized}.json")
        except (OSError, json.JSONDecodeError) as exc:
            raise KeyError("Agent 任务不存在。") from exc
        if not isinstance(descriptor, dict):
            raise KeyError("Agent 任务不存在。")
        return descriptor

    @_locked
    def verify_writing_agent_token(self, task_id: str, token: str) -> dict[str, Any]:
        """Validate one return credential and report the bound script without echoing it."""
        descriptor = self._read_agent_descriptor(task_id)
        expected = str(descriptor.get("token") or "")
        if not expected or not hmac.compare_digest(expected, str(token or "")):
            raise PermissionError("回传凭证无效，请从工作台重新发起 Agent 生成。")
        return {
            "taskId": str(descriptor.get("id") or ""),
            "scriptId": str(descriptor.get("scriptId") or ""),
            "accountId": str(descriptor.get("accountId") or ""),
        }

    def _read_writing_pending(self) -> dict[str, Any]:
        try:
            raw = self._read_json(self._writing_pending_path)
        except (OSError, json.JSONDecodeError):
            raw = None
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                accounts[str(account_id)] = {
                    node: [item for item in bucket.get(node) if isinstance(item, dict)]
                    for node in ("structure", "content")
                }
        return {"accounts": accounts}

    def _store_pending_experiences(self, account_id: str, raw: Any) -> tuple[int, int]:
        """Queue returned preferences as 待确认经验 instead of activating them."""
        items = raw if isinstance(raw, list) else []
        if not items:
            return 0, 0
        data = self._read_writing_pending()
        bucket = data["accounts"].setdefault(account_id, {"structure": [], "content": []})
        memory = self.read_account_memory(account_id)
        existing = {
            (node, str(entry.get("text") or ""))
            for node, entries in bucket.items()
            for entry in entries
        }
        active = {
            (node, str(entry.get("text") or ""))
            for node in ("structure", "content")
            for entry in memory[node]["preferences"]
        }
        created = 0
        duplicated = 0
        for entry in items:
            item = entry if isinstance(entry, dict) else {}
            rule = " ".join(str(item.get("rule") or "").split())[:300]
            if not rule:
                continue
            node = str(item.get("node") or "content")
            if node not in {"structure", "content"}:
                node = "content"
            if (node, rule) in existing or (node, rule) in active:
                duplicated += 1
                continue
            bucket[node].append({
                "id": str(uuid.uuid4()),
                "text": rule,
                "evidence": " ".join(str(item.get("evidence") or "").split())[:600],
                "createdAt": self._now(),
            })
            existing.add((node, rule))
            created += 1
        if created:
            for node in ("structure", "content"):
                bucket[node] = bucket[node][-PENDING_EXPERIENCE_LIMIT:]
            self._write_json(self._writing_pending_path, data)
        return created, duplicated

    @_locked
    def submit_writing_agent_return(self, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Apply each new 定稿回传 directly to its bound script."""
        descriptor = self._read_agent_descriptor(task_id)
        script_id = str(descriptor.get("scriptId") or "")
        try:
            script = self.get_script(script_id)
        except ValueError as exc:
            raise KeyError("脚本已被删除，回传内容没有写入任何脚本。") from exc
        account_id = str(descriptor.get("accountId") or "")
        self._require_account(account_id)
        if str(script.get("accountId") or "") != account_id:
            raise ValueError("脚本已归属其他账号，请从工作台重新发起 Agent 生成。")
        task = script.get("writingAgentTask") if isinstance(script.get("writingAgentTask"), dict) else {}
        if str(task.get("taskId") or "") != str(descriptor.get("id") or ""):
            raise ValueError("这是一次已失效的 Agent 任务，请从工作台重新发起。")

        content = str(body.get("content") or "")[:AGENT_RETURN_LIMIT]
        if not content.strip():
            raise ValueError("回传脚本内容为空。")
        submission_id = str(body.get("submissionId") or "")[:200]
        created, duplicated = self._store_pending_experiences(account_id, body.get("experiences"))
        known = [str(item) for item in task.get("submissionIds") or []]
        if submission_id and submission_id in known:
            return {
                "message": "这次回传已经处理过，未重复写入。",
                "applied": str(task.get("status") or "") == "applied",
                "candidateCreated": created,
                "candidateDuplicated": duplicated,
            }

        now = self._now()
        applied = self.apply_script_content(script_id, content)
        updated_task = applied.get("writingAgentTask") if isinstance(applied.get("writingAgentTask"), dict) else task
        updated_task["status"] = "applied"
        updated_task["appliedAt"] = now
        updated_task["submissionIds"] = [*known, *([submission_id] if submission_id else [])][-20:]
        updated_task.pop("pendingReturn", None)
        applied["writingAgentTask"] = updated_task
        applied["updatedAt"] = now
        self._write_json(self._script_path(script_id), applied)
        self.return_notifications.record(
            json.dumps(['writing', account_id, script_id, task_id, submission_id or now]),
            account_id=account_id, script_id=script_id,
            message=f"✓《{applied.get('title') or '未命名脚本'}》脚本已回传", kind='script')
        return {
            "message": "已把回传稿写入工作台的脚本内容。",
            "applied": True,
            "candidateCreated": created,
            "candidateDuplicated": duplicated,
        }

    @_locked
    def adopt_writing_return(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        task = script.get("writingAgentTask") if isinstance(script.get("writingAgentTask"), dict) else {}
        pending = task.get("pendingReturn") if isinstance(task.get("pendingReturn"), dict) else None
        if not pending:
            raise ValueError("当前没有待采用的回传稿。")
        applied = self.apply_script_content(script_id, str(pending.get("content") or ""))
        updated_task = applied.get("writingAgentTask") if isinstance(applied.get("writingAgentTask"), dict) else task
        updated_task["status"] = "applied"
        updated_task["appliedAt"] = self._now()
        submission_id = str(pending.get("submissionId") or "")
        known = [str(item) for item in updated_task.get("submissionIds") or []]
        if submission_id and submission_id not in known:
            known.append(submission_id)
        updated_task["submissionIds"] = known[-20:]
        updated_task.pop("pendingReturn", None)
        applied["writingAgentTask"] = updated_task
        applied["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), applied)
        self.return_notifications.record(
            json.dumps(['writing', applied['accountId'], script_id, updated_task.get('taskId'), submission_id or updated_task['appliedAt']]),
            account_id=applied['accountId'], script_id=script_id,
            message=f"✓《{applied.get('title') or '未命名脚本'}》脚本已回传", kind='script')
        return applied

    @_locked
    def discard_writing_return(self, script_id: str) -> dict[str, Any]:
        script = self.get_script(script_id)
        task = script.get("writingAgentTask") if isinstance(script.get("writingAgentTask"), dict) else {}
        if not isinstance(task.get("pendingReturn"), dict):
            raise ValueError("当前没有待采用的回传稿。")
        task.pop("pendingReturn", None)
        task["status"] = "applied" if task.get("appliedAt") else "awaiting"
        script["writingAgentTask"] = task
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    @_locked
    def list_pending_experiences(self, account_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._require_account(account_id)
        bucket = self._read_writing_pending()["accounts"].get(account_id) or {}
        return {
            node: [dict(item) for item in bucket.get(node, [])]
            for node in ("structure", "content")
        }

    @_locked
    def queue_pending_experience(
        self,
        account_id: str,
        *,
        node: str,
        text: str,
        evidence: str = "",
    ) -> dict[str, Any]:
        """把复盘结论存成待确认经验：确认之前不参与后续写作。"""
        self._ensure_migrated()
        self._require_account(account_id)
        normalized_node = node if node in WRITING_NODES else "content"
        rule = " ".join(str(text or "").split())
        if not rule:
            raise ValueError("候选经验内容不能为空。")
        created, duplicated = self._store_pending_experiences(
            account_id,
            [{"node": normalized_node, "rule": rule, "evidence": evidence}],
        )
        return {
            "node": normalized_node,
            "created": created,
            "duplicated": duplicated,
            "pending": self.list_pending_experiences(account_id),
        }

    @_locked
    def resolve_pending_experiences(self, account_id: str, ids: list[str], *, adopt: bool) -> dict[str, Any]:
        """Confirm or drop 待确认经验; only an adopted rule reaches the account memory."""
        self._ensure_migrated()
        self._require_account(account_id)
        wanted = {str(item) for item in ids if str(item).strip()}
        if not wanted:
            raise ValueError("请选择要处理的待确认经验。")
        data = self._read_writing_pending()
        bucket = data["accounts"].get(account_id) or {"structure": [], "content": []}
        handled: list[dict[str, str]] = []
        for node in ("structure", "content"):
            entries = bucket.get(node) if isinstance(bucket.get(node), list) else []
            remaining: list[dict[str, Any]] = []
            for entry in entries:
                if str(entry.get("id") or "") in wanted:
                    handled.append({
                        "node": node,
                        "text": str(entry.get("text") or ""),
                        "evidence": str(entry.get("evidence") or ""),
                    })
                else:
                    remaining.append(entry)
            bucket[node] = remaining
        data["accounts"][account_id] = bucket
        self._write_json(self._writing_pending_path, data)
        if adopt:
            for item in handled:
                self.append_writing_memory(
                    account_id, item["node"], item["text"],
                    evidence=item.get("evidence", ""), source="pending-experience",
                )
        return {"handled": handled}

    @_locked
    def update_stage(self, script_id: str, stage: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._validate_stage(stage)
        script = self.get_script(script_id)
        if stage == "edit" and script.get("source") == "link":
            raise ValueError("链接脚本没有编辑阶段。")
        if stage == "split":
            raise ValueError("拆片已经移到「拆解视频」模块。")
        if stage == "write":
            # 编写 needs a reference transcript: a legacy link task, or the 拆解记录
            # that the topic was created from.
            has_reference = (
                script.get("source") == "link" and script.get("processingStatus") == "ready"
            ) or bool(script.get("breakdownId"))
            if not has_reference:
                raise ValueError("这条脚本还没有可用的原视频文案，先从「拆解视频」加入选题。")
        script["stage"] = stage
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    @_locked
    def update_workflow_status(self, script_id: str, workflow_status: str) -> dict[str, Any]:
        self._ensure_migrated()
        self._validate_workflow_status(workflow_status)
        script = self.get_script(script_id)
        script["workflowStatus"] = workflow_status
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        onboarding.remember_script(self, script)
        return script

    @_locked
    def mark_link_script(self, script_id: str, status: str, title: str | None = None) -> dict[str, Any]:
        self._ensure_migrated()
        if status not in PROCESSING_STATUSES:
            raise ValueError("处理状态无效。")
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("脚本不存在。")
        script["processingStatus"] = status
        if title is not None and title.strip():
            script["title"] = title.strip()
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    @_locked
    def interrupt_processing_link_scripts(self) -> list[str]:
        """Make restart-interrupted imports safely retryable instead of leaving them stuck."""
        self._ensure_migrated()
        interrupted: list[str] = []
        for script_path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(script, dict) or script.get("source") != "link" or script.get("processingStatus") != "processing":
                continue
            script["processingStatus"] = "failed"
            script["updatedAt"] = self._now()
            self._write_json(script_path, script)
            interrupted.append(str(script.get("id") or ""))
        return [script_id for script_id in interrupted if script_id]

    @_locked
    def list_ready_link_task_ids(self) -> list[str]:
        self._ensure_migrated()
        task_ids: list[str] = []
        for script_path in self._scripts_dir.glob("*.json"):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(script, dict) or script.get("source") != "link" or script.get("processingStatus") != "ready":
                continue
            task_id = str(script.get("taskId") or "").strip()
            if task_id and task_id not in task_ids:
                task_ids.append(task_id)
        return task_ids

    @_locked
    def retry_link_script(self, script_id: str, task_id: str) -> dict[str, Any]:
        """Attach a fresh task to a failed link script without creating another card."""
        self._ensure_migrated()
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以重试。")
        if script.get("processingStatus") != "failed":
            raise ValueError("仅可重试处理失败的链接脚本。")
        if not str(script.get("shareText") or "").strip():
            raise ValueError("该历史链接脚本未保存原分享链接，无法重试。")
        script["taskId"] = task_id
        script["processingStatus"] = "processing"
        script["updatedAt"] = self._now()
        self._write_json(self._script_path(script_id), script)
        return script

    @_locked
    def delete_failed_link_script(self, script_id: str) -> dict[str, Any]:
        self._ensure_migrated()
        script = self.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以删除任务。")
        if script.get("processingStatus") != "failed":
            raise ValueError("仅可删除处理失败的链接脚本。")
        self._script_path(script_id).unlink()
        self._invalidate_script_cache()
        return script

    @_locked
    def delete_script(self, script_id: str) -> dict[str, Any]:
        """Remove a script together with all files stored under its ID."""
        self._ensure_migrated()
        script = self.get_script(script_id)
        workflow_status = str(script.get("workflowStatus") or "")
        script_account_id = str(script.get("accountId") or "")
        if script.get("source") == "link":
            task_id = str(script.get("taskId") or "").strip()
            if task_id:
                deleted_task_ids = self._deleted_link_task_ids()
                deleted_task_ids.add(task_id)
                self._write_json(self._deleted_link_tasks_path, sorted(deleted_task_ids))
        self._script_path(script_id).unlink()
        script_assets_dir = self._scripts_dir / script_id
        if script_assets_dir.exists():
            shutil.rmtree(script_assets_dir)
        self._invalidate_script_cache()
        self._unlink_topics_for_script(script_id, account_id=script_account_id, status=workflow_status)
        return script

    @_locked
    def delete_link_task_materials(self, task_id: str) -> None:
        """Remove a link-task download directory, including legacy tasks without task.json."""
        if not task_id or Path(task_id).name != task_id:
            raise ValueError("任务不存在。")
        if not self._download_dir.is_dir():
            return
        download_root = self._download_dir.resolve()
        candidates = [self._download_dir / task_id, *self._download_dir.iterdir()]
        for directory in candidates:
            if not directory.is_dir() or directory.is_symlink():
                continue
            if self._task_id_for_directory(directory) != task_id:
                continue
            try:
                directory.resolve().relative_to(download_root)
            except ValueError as exc:
                raise ValueError("任务素材路径不安全。") from exc
            shutil.rmtree(directory)
            return

    def _ensure_migrated(self) -> None:
        """Keep stored data up to date without rescanning the workspace on every read.

        The one-time record migration runs once per store instance, so a read-heavy
        session never rescans the workspace for records it has already converted.
        """
        if not self._migrated:
            self._run_record_migration()
            self._migrated = True
            try:
                self._memory_library.initialize_accounts(a["id"] for a in self._read_accounts())
            except (MemoryStoreError, OSError) as exc:
                logger.warning("工作台记忆目录初始化失败：%s", type(exc).__name__)

    def _run_record_migration(self) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._scripts_dir.mkdir(parents=True, exist_ok=True)
        if not self._accounts_path.exists():
            now = self._now()
            self._write_json(
                self._accounts_path,
                [{
                    "id": UNCLASSIFIED_ACCOUNT_ID,
                    "name": "我的工作台",
                    "platform": "both",
                    "createdAt": now,
                    "updatedAt": now,
                    "isSystem": False,
                }],
            )
        else:
            self._migrate_default_account()

        self._migrate_rewrite_prompt_templates()

        self._migrate_script_records()

        self._migrate_link_scripts_to_breakdowns()

    def _migrate_script_records(self) -> None:
        """Read every script once, applying all record migrations, and seed the index."""
        migrated: dict[str, dict[str, Any]] = {}
        for script_path in sorted(self._scripts_dir.glob("*.json")):
            try:
                script = self._read_json(script_path)
            except (OSError, json.JSONDecodeError):
                logger.warning("workspace_script_unreadable path=%s", script_path)
                continue
            if not isinstance(script, dict):
                continue
            migrated[script_path.stem] = script
            changed = False
            # Legacy scripts keep a pending operator status instead of an inferred one.
            if script.get("workflowStatus") not in WORKFLOW_STATUSES:
                script["workflowStatus"] = "pending"
                changed = True
            task = script.get("writingAgentTask")
            pending = task.get("pendingReturn") if isinstance(task, dict) else None
            if isinstance(pending, dict) and str(pending.get("content") or "").strip():
                self._set_script_content(script, str(pending["content"])[:AGENT_RETURN_LIMIT])
                task["status"] = "applied"
                task["appliedAt"] = self._now()
                known = [str(item) for item in task.get("submissionIds") or []]
                submission_id = str(pending.get("submissionId") or "")
                if submission_id and submission_id not in known:
                    known.append(submission_id)
                task["submissionIds"] = known[-20:]
                task.pop("pendingReturn", None)
                script["updatedAt"] = task["appliedAt"]
                changed = True
            if changed:
                self._write_json(script_path, script)
        self._scripts_cache = migrated
        self._task_script_index = None

    def _migrate_link_scripts_to_breakdowns(self) -> None:
        """Convert legacy link scripts into 拆解记录 and retire them from the script list.

        The script record stays on disk for review links and task history, but it
        carries a retiredAsBreakdown marker so it stops showing up as a script.
        The conversion is idempotent: a retired script is skipped, and an existing
        record for the same task is reused instead of duplicated.
        """
        data = self._read_breakdown_data()
        breakdowns_changed = False
        for script_id, script in list(self._load_scripts().items()):
            if script.get("source") != "link" or script.get("retiredAsBreakdown"):
                continue
            task_id = str(script.get("taskId") or "").strip()
            account_id = str(script.get("accountId") or "")
            record: dict[str, Any] | None = None
            if task_id and Path(task_id).name == task_id:
                bucket = self._account_breakdown_bucket(data, account_id)
                record = next(
                    (item for item in bucket["items"] if str(item.get("taskId") or "") == task_id),
                    None,
                )
                if record is None:
                    now = self._now()
                    record = {
                        "id": str(uuid.uuid4()),
                        "accountId": account_id,
                        "title": str(script.get("title") or ""),
                        "shareText": str(script.get("shareText") or ""),
                        "taskId": task_id,
                        "analysis": None,
                        "analysisStatus": "idle",
                        "analysisError": "",
                        "topicId": "",
                        "createdAt": str(script.get("createdAt") or now),
                        "updatedAt": now,
                    }
                    bucket["items"].append(record)
                    breakdowns_changed = True
                elif not str(record.get("title") or "").strip():
                    record["title"] = str(script.get("title") or "")
            script["retiredAsBreakdown"] = str(record.get("id") or "") if record else "unrecorded"
            script["updatedAt"] = self._now()
            self._write_json(self._script_path(script_id), script)
        if breakdowns_changed:
            self._write_breakdown_data(data)

    def _migrate_default_account(self) -> None:
        """Make the legacy default editable without recreating deleted accounts."""
        accounts = self._read_accounts()
        changed = False
        for account in accounts:
            if account.get("id") == UNCLASSIFIED_ACCOUNT_ID and account.get("isSystem"):
                account["isSystem"] = False
                changed = True
        if changed:
            self._write_json(self._accounts_path, accounts)

    @staticmethod
    def _default_rewrite_prompt_config(general_prompt: str = DEFAULT_REWRITE_SYSTEM_PROMPT) -> dict[str, Any]:
        return {
            "rewritePromptTemplates": [
                {
                    "id": template_id,
                    "name": name,
                    "systemPrompt": general_prompt if template_id == "general" else prompt,
                }
                for template_id, name, prompt in REWRITE_PROMPT_TEMPLATE_DEFINITIONS
            ],
            "selectedRewritePromptTemplateId": "general",
            "rewriteSystemPrompt": general_prompt,
        }

    @staticmethod
    def _rewrite_prompt_config_for_account(account: dict[str, Any]) -> dict[str, Any]:
        legacy_prompt = str(account.get("rewriteSystemPrompt") or "").strip() or DEFAULT_REWRITE_SYSTEM_PROMPT
        saved_templates = account.get("rewritePromptTemplates")
        saved_by_id = {
            str(template.get("id")): str(template.get("systemPrompt") or "").strip()
            for template in saved_templates
            if isinstance(template, dict) and str(template.get("id")) in REWRITE_PROMPT_TEMPLATE_IDS
            and str(template.get("systemPrompt") or "").strip()
        } if isinstance(saved_templates, list) else {}
        templates = [
            {
                "id": template_id,
                "name": name,
                "systemPrompt": saved_by_id.get(template_id, legacy_prompt if template_id == "general" else prompt),
            }
            for template_id, name, prompt in REWRITE_PROMPT_TEMPLATE_DEFINITIONS
        ]
        selected_template_id = str(account.get("selectedRewritePromptTemplateId") or "")
        if selected_template_id not in REWRITE_PROMPT_TEMPLATE_IDS:
            selected_template_id = "general"
        active_prompt = next(template["systemPrompt"] for template in templates if template["id"] == selected_template_id)
        return {
            "systemPrompt": active_prompt,
            "templates": templates,
            "selectedTemplateId": selected_template_id,
        }

    def _migrate_rewrite_prompt_templates(self) -> None:
        accounts = self._read_accounts()
        changed = False
        for account in accounts:
            config = self._rewrite_prompt_config_for_account(account)
            if (
                account.get("rewritePromptTemplates") != config["templates"]
                or account.get("selectedRewritePromptTemplateId") != config["selectedTemplateId"]
                or account.get("rewriteSystemPrompt") != config["systemPrompt"]
            ):
                account["rewritePromptTemplates"] = config["templates"]
                account["selectedRewritePromptTemplateId"] = config["selectedTemplateId"]
                account["rewriteSystemPrompt"] = config["systemPrompt"]
                changed = True
        if changed:
            self._write_json(self._accounts_path, accounts)

    def _read_accounts(self) -> list[dict[str, Any]]:
        accounts = self._read_json(self._accounts_path)
        if not isinstance(accounts, list):
            raise ValueError("账号不存在。")
        return [account for account in accounts if isinstance(account, dict)]

    def _read_cover_templates(self) -> dict[str, list[dict[str, Any]]]:
        if not self._cover_templates_path.exists():
            return {}
        raw = self._read_json(self._cover_templates_path)
        if not isinstance(raw, dict):
            return {}
        return {
            str(account_id): [item for item in templates if isinstance(item, dict)]
            for account_id, templates in raw.items()
            if isinstance(templates, list)
        }

    def _require_account(self, account_id: str) -> dict[str, Any]:
        for account in self._read_accounts():
            if account.get("id") == account_id:
                return account
        raise ValueError("账号不存在。")

    def _create_script(
        self,
        *,
        account_id: str,
        title: str,
        source: str,
        processing_status: str,
        task_id: str | None = None,
        content: str | None = None,
        share_text: str | None = None,
        workflow_status: str = "pending",
    ) -> dict[str, Any]:
        now = self._now()
        script: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "accountId": account_id,
            "title": title,
            "source": source,
            "stage": "split" if source == "link" else "edit",
            "processingStatus": processing_status,
            "workflowStatus": workflow_status if workflow_status in WORKFLOW_STATUSES else "pending",
            "createdAt": now,
            "updatedAt": now,
        }
        if source == "link":
            script["selectedRewriteModel"] = "text-default"
        if task_id is not None:
            script["taskId"] = task_id
        if content is not None:
            script["content"] = content
        if share_text is not None:
            script["shareText"] = share_text
        self._write_json(self._script_path(script["id"]), script)
        self._invalidate_script_cache()
        return script

    @staticmethod
    def _default_script_title() -> str:
        return f"未命名脚本 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    def _find_link_script(self, task_id: str) -> dict[str, Any] | None:
        script_id = self._link_script_by_task().get(task_id)
        if script_id is None:
            return None
        script = self._load_scripts().get(script_id)
        return dict(script) if isinstance(script, dict) else None

    def _load_scripts(self) -> dict[str, dict[str, Any]]:
        """Return every stored script keyed by filename stem, reading the directory once."""
        if self._scripts_cache is None:
            cache: dict[str, dict[str, Any]] = {}
            for script_path in sorted(self._scripts_dir.glob("*.json")):
                try:
                    script = self._read_json(script_path)
                except (OSError, json.JSONDecodeError):
                    logger.warning("workspace_script_unreadable path=%s", script_path)
                    continue
                if isinstance(script, dict):
                    cache[script_path.stem] = script
            self._scripts_cache = cache
        return self._scripts_cache

    def _link_script_by_task(self) -> dict[str, str]:
        """Index link scripts by task id so a task lookup never rescans the directory."""
        if self._task_script_index is None:
            index: dict[str, str] = {}
            for script_id, script in self._load_scripts().items():
                if script.get("source") != "link":
                    continue
                task_id = str(script.get("taskId") or "").strip()
                if task_id and task_id not in index:
                    index[task_id] = script_id
            self._task_script_index = index
        return self._task_script_index

    def _invalidate_script_cache(self) -> None:
        self._scripts_cache = None
        self._task_script_index = None

    def _task_id_for_directory(self, directory: Path) -> str:
        try:
            task = self._read_json(directory / "task.json")
        except (OSError, json.JSONDecodeError):
            task = None
        if isinstance(task, dict):
            task_id = str(task.get("taskId") or "").strip()
            if task_id:
                return task_id
        return directory.name

    def _deleted_link_task_ids(self) -> set[str]:
        try:
            value = self._read_json(self._deleted_link_tasks_path)
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(value, list):
            return set()
        return {item for item in value if isinstance(item, str) and item and Path(item).name == item}

    @staticmethod
    def _video_title(video: dict[str, Any]) -> str:
        return str(video.get("title") or video.get("desc") or "未命名视频").strip() or "未命名视频"

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in PLATFORMS:
            raise ValueError("账号平台无效。")

    @staticmethod
    def _validate_stage(stage: str) -> None:
        if stage not in STAGES:
            raise ValueError("创作阶段无效。")

    @staticmethod
    def _validate_workflow_status(workflow_status: str) -> None:
        if workflow_status not in WORKFLOW_STATUSES:
            raise ValueError("运营状态无效。")

    @staticmethod
    def _normalize_topics(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value[:10] if isinstance(item, str) and item.strip()][:10]

    @staticmethod
    def _normalize_publish_assets(script_id: str, assets: Any) -> dict[str, Any]:
        if not isinstance(assets, dict):
            raise ValueError("发布素材无效。")
        expected_parent = Path("scripts") / script_id / "publish-assets"

        def normalize_asset(value: Any) -> dict[str, str] | None:
            if value is None:
                return None
            if not isinstance(value, dict):
                raise ValueError("发布素材无效。")
            name = value.get("name")
            raw_path = value.get("path")
            if (
                not isinstance(name, str)
                or not name.strip()
                or Path(name).name != name
                or not isinstance(raw_path, str)
                or not raw_path
            ):
                raise ValueError("发布素材路径无效。")
            path = Path(raw_path)
            if path.is_absolute() or path.parent != expected_parent or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("发布素材路径无效。")
            return {"name": name.strip(), "path": path.as_posix()}

        covers = assets.get("covers")
        if covers is None:
            covers = {}
        if not isinstance(covers, dict) or any(aspect not in {"3:4", "4:3"} for aspect in covers):
            raise ValueError("发布素材无效。")
        normalized_covers = {
            aspect: normalized
            for aspect in ("3:4", "4:3")
            if (normalized := normalize_asset(covers.get(aspect))) is not None
        }
        normalized_assets = {
            "video": normalize_asset(assets.get("video")),
            "covers": normalized_covers,
        }
        raw_cover_sources = assets.get("coverSources")
        if raw_cover_sources is None:
            return normalized_assets
        if not isinstance(raw_cover_sources, dict) or any(aspect not in {"3:4", "4:3"} for aspect in raw_cover_sources):
            raise ValueError("发布素材无效。")
        cover_sources: dict[str, dict[str, str]] = {}
        for aspect, cover in normalized_covers.items():
            source = raw_cover_sources.get(aspect)
            if not isinstance(source, dict):
                continue
            source_type = source.get("type")
            if source_type == "manual":
                cover_sources[aspect] = {"type": "manual"}
                continue
            image_url = source.get("imageUrl")
            if source_type == "generated" and isinstance(image_url, str) and image_url.strip():
                cover_sources[aspect] = {"type": "generated", "imageUrl": image_url[:4096]}
        if cover_sources:
            normalized_assets["coverSources"] = cover_sources
        return normalized_assets

    def _script_path(self, script_id: str) -> Path:
        if not script_id or Path(script_id).name != script_id:
            raise ValueError("脚本不存在。")
        return self._scripts_dir / f"{script_id}.json"

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_json(self, path: Path, value: Any) -> None:
        """Atomically persist JSON, dropping the script cache for script records."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(path)
        if self._is_script_path(path):
            self._invalidate_script_cache()

    def _is_script_path(self, path: Path) -> bool:
        """True when a path is a top-level script record rather than nested assets."""
        return path.parent == self._scripts_dir and path.suffix == ".json"
