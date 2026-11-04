from __future__ import annotations

import asyncio
import base64
import functools
import json
import logging
import math
import os
import re
import secrets
from app.writing_assistants import AssistantManager, AssistantError, read_json as read_assistant_json
import shutil
import subprocess
import sys
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Literal, Mapping, Optional
from urllib.parse import unquote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .media_download import (
    DOWNLOAD_DIR,
    LOG_DIR,
    PROJECT_ROOT,
    DownloadError,
    health_status,
)
from .blocking import run_generation, run_io
from .monitor_recovery import MonitorSubscriptionRecovery
from .topic_recommendations import TopicRecommendationStore
from .topic_recommendation_runtime import TopicRecommendationRuntime
from . import topic_recommendation_availability
from .topic_recommendation_routes import build_router as topic_recommendation_router
from .runtime import DATA_ROOT, DESKTOP, health_info, require_core_data_schema
require_core_data_schema(DATA_ROOT)
from .updates import UpdateManager, attach_update_routes
from .creation_media import (
    MediaStagingError,
    discard_staged,
    resolve_staged,
    stage_upload,
)
from .creation_data import (
    CAPABILITY_POSTS,
    CAPABILITY_PROFILE,
    CAPABILITY_SEARCH,
    CAPABILITY_SUGGESTIONS,
    CAPABILITY_TRENDS,
    CAPABILITY_LOW_FANS,
    PlatformDataClient,
    PlatformDataError,
    RoundUsage,
    low_fans_item_to_row,
    next_cursor,
    page_items,
    posts_item_to_aweme,
    profile_to_user,
    suggestion_words,
    trends_to_rows,
)
from .creation_service import (
    CreationServiceError,
    DEFAULT_LINK_MAX_SECONDS,
)
from .codex_agent import (
    CodexAgentError,
    build_writing_agent_prompt,
    ensure_prompt_fits,
    open_codex_prompt,
    with_return_instructions,
)
from .image_errors import ImageError
from .creation_image import CreationImageClient, CreationImageError
from .media_compat import ensure_preview_poster, ensure_publish_preview_poster, ensure_safari_compatible
from .monitor import (
    MONITOR_BLOGGER_PAGE_SIZE_MAX,
    MONITOR_INTERVAL_OPTIONS,
    MONITOR_MAX_PAGES_PER_ROUND,
    MONITOR_PRIORITY_LABELS,
    MONITOR_RECENT_WINDOW_DAYS,
    MONITOR_RECOMMENDATION_LIMIT,
    MONITOR_WORK_DATE_OPTIONS,
    MonitorStore,
    ai_due_at,
    build_recommendation_context,
    local_day,
    normalize_douyin_aweme,
    normalize_douyin_user,
    parse_iso,
    recommendation_key,
)
from .publisher import PublishAssetsStore, PublisherError, PublisherService
from .radar_trends import collect_trend
from .radar_ai import build_account_inputs
from .account_positioning import PROMPT as POSITIONING_PROMPT, positioning_input, positioning_result
from .radar import (
    RADAR_ANALYSIS_WINDOW_DAYS,
    RADAR_DATE_OPTIONS,
    RADAR_DEFAULT_DAY,
    RADAR_FILTERS,
    RADAR_RECOMMENDATION_MAX,
    RADAR_SUGGEST_LIMIT,
    RADAR_TABS,
    RadarStore,
    normalize_low_fans_work,
    normalize_search_work,
    plan_collection,
    recommendation_key as radar_recommendation_key,
)
from .review import (
    REVIEW_FACTOR_DEFAULT_DIMENSION,
    REVIEW_FACTOR_DEFAULT_METRIC,
    REVIEW_FACTOR_DEFAULT_RANGE_DAYS,
    REVIEW_TREND_DEFAULT_DAYS,
    REVIEW_TREND_DEFAULT_SCOPE,
    ReviewCollectionError,
    ReviewStore,
    build_manual_topic_fields,
    collect_douyin_works,
    normalize_origin,
    now_iso,
    options as review_options,
)
from .review_reports import (
    DOUYIN_CONTENT_MANAGE_URL,
    REPORT_RECENT_SCOPE_DAYS,
    REPORT_SYNC_TIME_BUDGET_SECONDS,
    REPORT_WORK_SYNC_LIMIT,
    REPORT_WORK_VIEWS,
    close_page,
    fetch_account_rows,
    fetch_work_rows,
    item_id_from_url,
    merge_work_rows,
    open_work_detail,
)
from .text_service import TextClient, TextServiceError
from .radar_billing import RadarBillingCache
from . import workbench
from .home_advice import AdviceStore, AdviceRuntime, router as advice_router
from .settings import AppSettings, SettingsUpdate, load_settings, project_settings_view, save_settings
from .subscription import (
    NEEDS_RELOGIN,
    RELOGIN_CODES,
    SubscriptionError,
    SubscriptionService,
    SubscriptionStore,
)
from .social_links import DataServiceError, resolve_creator_sec_user_id
from .upstream_errors import public_code, public_error, sanitize_message, public_details

from .memory_store import MemoryStoreError
from .social_links import BROWSER_UA
from .tasks import LocalTaskStore
from .workspace import ACCOUNT_PROFILE_FIELD_LIMIT, WorkspaceStore
from .writing_agent_task import build_draft_agent_prompt, build_breakdown_rewrite_prompt, reference_copy_section

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("douyin-downloader")

app = FastAPI(title="视频脚本工作台", version="1.0.0")
update_manager = UpdateManager(DATA_ROOT)
attach_update_routes(app, update_manager)


def _public_detail(detail: Any) -> Any:
    """接口错误详情对外脱敏：不出现上游品牌、域名和原始返回内容。

    只处理 error/code/message/suggestion 这几个已知字段，其余结构原样返回。
    """
    if not isinstance(detail, Mapping):
        return "请求失败"
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        if key == "code" and isinstance(value, str):
            cleaned[key] = public_code(value)
        elif key in ("message", "suggestion") and isinstance(value, str):
            cleaned[key] = sanitize_message(value)
        elif key == "details":
            cleaned[key] = public_details(value)
        elif key in {"needsSubscription"} and isinstance(value, bool):
            cleaned[key] = value
    return cleaned


@app.exception_handler(HTTPException)
async def _public_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    """兜底：任何接口错误响应都不会带出上游身份信息。"""
    detail = exc.detail if _request.url.path.startswith("/api/plugins/") else _public_detail(exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


download_lock = asyncio.Lock()
subscription_store = SubscriptionStore(DATA_ROOT / "workspace")
_monitor_subscription_recovery = MonitorSubscriptionRecovery()


def _workbench_service() -> SubscriptionService:
    """付费能力统一入口：只持有当前登录用户的会话凭证，不涉及任何供应商 Key。"""
    return SubscriptionService(subscription_store, load_settings())


# 平台类错误（未登录、模拟通路、积分或订阅不足等）自带可执行的中文文案，
# 直接透出给用户；其余按各调用点的兜底文案处理。
_PLATFORM_FACING_CODES = {
    "platform_mode_required", "unauthorized", "session_revoked", "account_disabled",
    "permission_denied", "subscription_required", "subscription_expired", "insufficient_points",
    "charge_limit_exceeded", "quote_changed", "result_expired", "service_unavailable",
    "rate_limited", "upstream_unavailable", "content_unavailable", "unsupported_input",
}


def _model_failure_message(exc: TextServiceError, fallback: str) -> str:
    if exc.code in _PLATFORM_FACING_CODES:
        return exc.message
    return fallback


def _workbench_ready() -> bool:
    """付费能力是否可用：真实通路且已登录，页面据此决定入口和提示。"""
    try:
        service = _workbench_service()
    except Exception:  # noqa: BLE001 - 配置读取失败按不可用处理
        return False
    view = service.session_view()
    return bool(view.get("loggedIn")) and service.mode == "live"


def _require_workbench() -> None:
    """付费能力的前置校验：必须登录且处于真实通路，否则给出可执行的中文提示。"""
    service = _workbench_service()
    if not service.session_view().get("loggedIn"):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "请先登录后再使用付费能力。"},
        )
    if service.mode != "live":
        raise HTTPException(
            status_code=409,
            detail={"code": "platform_mode_required",
                    "message": "当前为模拟通路，付费能力需要切换到真实创作服务平台后使用。"},
        )


async def _release_login_blocks(reason: str) -> None:
    """会话可用时清理登录前写入的阻断记录；登录成功与服务启动各调一次。

    只清提示、恢复为待采，不主动补采：何时重新采集仍由各自间隔决定。
    """
    if not _workbench_ready():
        return
    try:
        monitor_result = await run_io(monitor_store.release_login_blocks)
        radar_result = await run_io(radar_store.release_login_blocks)
    except Exception:  # noqa: BLE001 - 清理失败不能影响登录或启动
        logger.exception("release_login_blocks_failed reason=%s", reason)
        return
    logger.info("login_blocks_released reason=%s monitor=%s radar=%s", reason, monitor_result, radar_result)


async def _text_service_via_platform(**kwargs: Any) -> dict[str, Any]:
    """把文本生成场景统一交给创作服务平台：按真实用量计费，凭据留在平台侧。

    连结束原因一起返回，让选题生成能区分「模型写完了」和「被长度上限截断」。
    """
    return await workbench.generate_text_result(_workbench_service(), **kwargs)


def _text_service_client() -> TextClient:
    """文本能力统一走创作服务平台；本地不再持有也不需要模型 Key。"""
    return TextClient(platform=_text_service_via_platform)

task_store = LocalTaskStore(load_settings, workbench_service=_workbench_service)
workspace_store = WorkspaceStore(DATA_ROOT / "workspace", DOWNLOAD_DIR)
publish_assets_store = PublishAssetsStore(DATA_ROOT / "workspace", DOWNLOAD_DIR)
publisher_service = PublisherService(DATA_ROOT / "workspace")
review_store = ReviewStore(DATA_ROOT / "workspace")
monitor_store = MonitorStore(DATA_ROOT / "workspace")
radar_store = RadarStore(DATA_ROOT / "workspace")
topic_recommendation_store = TopicRecommendationStore(DATA_ROOT / "workspace")
topic_recommendation_runtime = TopicRecommendationRuntime(lambda: sys.modules[__name__])
app.include_router(topic_recommendation_router(topic_recommendation_runtime))
app.add_event_handler("shutdown", topic_recommendation_runtime.stop)
radar_billing = RadarBillingCache(DATA_ROOT / "workspace")
home_advice_store = AdviceStore(DATA_ROOT / "workspace")
home_advice_runtime = AdviceRuntime(home_advice_store, sys.modules[__name__])
app.include_router(advice_router(home_advice_runtime))


# 通用插件宿主：加载内置插件，挂载通用管理接口与插件自有路由。
from .plugins.credentials import (  # noqa: E402 - 依赖上面的工作区路径
    CredentialStoreUnavailable,
    UnavailableCredentialStore,
    default_credential_store,
)
from .plugins.registry import PluginRegistry  # noqa: E402
from .plugins.router import build_router as build_plugin_router  # noqa: E402
from .plugins.state import PluginStateStore  # noqa: E402


def _plugin_script_snapshot(script_id: str) -> dict[str, Any] | None:
    """宿主提供的通用脚本快照：插件据此拿到已保存的正文与归属。"""
    try:
        script = workspace_store.get_script(script_id)
    except Exception:  # noqa: BLE001 - 不存在的脚本按无快照处理
        return None
    return {
        "id": script.get("id"),
        "accountId": script.get("accountId"),
        "title": script.get("title") or script.get("name") or "",
        "content": script.get("content") or "",
        "source": script.get("source"),
        "version": script.get("updatedAt"),
    }


try:
    plugin_credential_store = default_credential_store()
except CredentialStoreUnavailable:
    logger.warning("plugin_credential_store_unavailable")
    plugin_credential_store = UnavailableCredentialStore()

plugin_registry = PluginRegistry(
    PluginStateStore(DATA_ROOT / "workspace" / "plugins.json"),
    plugin_credential_store,
    account_exists=lambda account_id: any(a["id"] == account_id for a in workspace_store.list_accounts()),
    script_snapshot=_plugin_script_snapshot,
    media_root=DATA_ROOT / "workspace" / "plugins",
)
from .plugins.packages import PackageManager
from .plugins.package_routes import build_package_router, build_asset_router, PluginRequestGuard
plugin_packages = PackageManager(DATA_ROOT / "workspace" / "plugin-packages", plugin_registry)
from .restarts import RestartManager, attach_restart_routes
restart_manager = RestartManager(update_manager)
restart_manager.plugin_blockers = plugin_packages.restart_blockers
restart_manager.refresh_plugins = plugin_packages.refresh_restart_tasks
from .plugins.events import hub as plugin_event_hub
from .script_import_events import hub as script_import_event_hub

def _pause_return_notifications():
    plugin_event_hub.pause()
    script_import_event_hub.pause()

def _resume_return_notifications():
    plugin_event_hub.resume()
    script_import_event_hub.resume()

restart_manager.pause_notifications = _pause_return_notifications
restart_manager.resume_notifications = _resume_return_notifications
app.add_event_handler("shutdown", script_import_event_hub.pause)
app.add_event_handler("startup", script_import_event_hub.resume)
attach_restart_routes(app, restart_manager)
try:
    # Plugin registration may migrate/write stores, so recover before activation
    # as well as at startup (where tests may have replaced the workspace store).
    from .script_move import ScriptMoveService
    from .plugins.move_guard import move_guard
    try:
        ScriptMoveService(workspace_store, plugin_packages).recover()
    except Exception:
        # An unreadable journal cannot reliably identify its affected accounts.
        move_guard.set_blocked([account['id'] for account in workspace_store.list_accounts()], True)
        raise
    if not DESKTOP and not any(move_guard.is_blocked(account['id']) for account in workspace_store.list_accounts()):
        plugin_packages.migrate_existing(PROJECT_ROOT / "plugin_dist")
    plugin_packages.activate()
except Exception:
    logger.exception("plugin_package_startup_failed")
    plugin_registry.record_failure("packages", "startup", "插件初始化失败，原有数据已保留，请检查插件目录。")
app.add_middleware(PluginRequestGuard, manager=plugin_packages)
app.include_router(build_package_router(plugin_packages))
app.include_router(build_asset_router(plugin_packages))
from .plugins.events import build_router as build_plugin_events_router
app.include_router(build_plugin_events_router(plugin_registry))
def _migrate_legacy_plugins() -> None:
    owner = plugin_registry.legacy_migration_owner()
    if owner and not move_guard.is_blocked(owner):
        try:
            plugin_registry.migrate_legacy(owner)
        except Exception:  # Never fall back to global credentials or choose another workspace.
            logger.error("plugin_workspace_migration_failed")


_script_move_service = None
_script_move_service_dependencies = None
_script_move_service_lock = threading.Lock()


def _get_script_move_service():
    """Bind lazily to the current stores (including stores replaced by tests)."""
    from .script_move import ScriptMoveService
    global _script_move_service, _script_move_service_dependencies
    with _script_move_service_lock:
        dependencies = (workspace_store, plugin_packages)
        if (_script_move_service is None or _script_move_service_dependencies is None
                or any(old is not new for old, new in zip(_script_move_service_dependencies, dependencies))):
            _script_move_service = ScriptMoveService(*dependencies)
            _script_move_service_dependencies = dependencies
        return _script_move_service


async def _recover_script_moves():
    await asyncio.to_thread(lambda: _get_script_move_service().recover())


app.add_event_handler("startup", _migrate_legacy_plugins)
app.add_event_handler("startup", _recover_script_moves)
app.add_event_handler("startup", plugin_packages.start_runtimes)
app.add_event_handler("shutdown", plugin_packages.stop_runtimes)
app.include_router(build_plugin_router(plugin_registry))
app.add_event_handler("shutdown", home_advice_runtime.shutdown)
_review_jobs: dict[str, asyncio.Task] = {}
_review_jobs_lock = threading.Lock()
_REVIEW_PLATFORM = "douyin"
# 采集是后台任务，界面按这个间隔轮询账号状态。
_REVIEW_SCHEDULER_TICK_SECONDS = 60
# 浏览器采集会阻塞几分钟，单独用一个池，避免占用 IO 池和封面/ffmpeg 生成池。
_review_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="review-collect")
_review_scheduler_task: asyncio.Task | None = None
# 监控：每位博主一个采集任务，每个创作账号一个 AI 建议任务；数据走创作服务，不占浏览器。
_monitor_jobs: dict[str, asyncio.Task] = {}
_monitor_ai_jobs: dict[str, asyncio.Task] = {}
_MONITOR_SCHEDULER_TICK_SECONDS = 60
_monitor_scheduler_task: asyncio.Task | None = None
# 同时最多两路数据请求，避免把限流和额度一次打满。按事件循环保存：
# 测试和多客户端场景会先后创建不同的循环，绑定旧循环的信号量会直接报错。
_monitor_semaphores: dict[Any, asyncio.Semaphore] = {}
# 雷达：每个关键词一个采集任务，每个创作账号一个 AI 建议任务。搜索结果自带时间窗口，
# 所以按关键词各自排队即可，不需要像监控那样跨账号共享某位博主的采集。
_radar_jobs: dict[str, asyncio.Task] = {}
_radar_ai_jobs: dict[str, asyncio.Task] = {}
_radar_trend_retry_jobs: dict[str, asyncio.Task] = {}
_radar_scheduler_task: asyncio.Task | None = None
_RADAR_SCHEDULER_TICK_SECONDS = 60
_radar_semaphores: dict[Any, asyncio.Semaphore] = {}
_publish_assets_save_lock = threading.Lock()
_link_task_jobs: dict[str, asyncio.Task] = {}
_safari_compatibility_jobs: dict[str, asyncio.Task] = {}
_preview_poster_jobs: dict[str, asyncio.Task] = {}
_title_generation_jobs: dict[str, asyncio.Task] = {}
_writing_generation_jobs: dict[str, asyncio.Task] = {}
_writing_agent_lock = asyncio.Lock()
_cover_title_job_tasks: dict[str, asyncio.Task] = {}
_cover_generation_tasks: dict[str, asyncio.Task] = {}
_script_transition_locks: dict[str, threading.Lock] = {}
_script_transition_locks_guard = threading.Lock()
_account_deletion_lock = threading.RLock()
_accounts_being_deleted: set[str] = set()


def _script_transition_lock(script_id: str) -> threading.Lock:
    """Serialize publish starts and ownership changes for one script."""
    with _script_transition_locks_guard:
        lock = _script_transition_locks.get(script_id)
        if lock is None:
            lock = threading.Lock()
            _script_transition_locks[script_id] = lock
        return lock


def _reserve_account_deletion(account_id: str) -> None:
    with _account_deletion_lock:
        if account_id in _accounts_being_deleted:
            raise ValueError("账号正在删除，请稍后再试。")
        _accounts_being_deleted.add(account_id)


def _release_account_deletion(account_id: str) -> None:
    with _account_deletion_lock:
        _accounts_being_deleted.discard(account_id)


def _ensure_accounts_available_for_move(*account_ids: str) -> None:
    if any(account_id in _accounts_being_deleted for account_id in account_ids):
        raise ValueError("账号正在删除，暂时不能移动脚本。")


def _migrate_original_recommendations():
    for store in (monitor_store, radar_store):
        report = store.migrate_original_recommendations()
        if not report.get("sourcesRestored"):
            records = report.get("discardedItems")
            if records is None and report.get("backupPath"):
                try:
                    backup = json.loads(Path(report["backupPath"]).read_text(encoding="utf-8"))
                    records = {account: (bucket.get("recommendation") or {}).get("items", [])
                               for account, bucket in (backup.get("accounts") or {}).items()}
                except (OSError, ValueError):
                    logger.warning("original_recommendation_source_backup_unavailable")
                    continue
            if records:
                workspace_store.restore_recommendation_topic_sources(records)
            store.complete_original_source_restore()
        if report.get("migrated"):
            logger.info("original_recommendations_migrated backup=%s", report.get("backupPath"))


async def _start_publisher_service() -> None:
    global publisher_service, _review_scheduler_task, _monitor_scheduler_task, _radar_scheduler_task
    if update_manager.maintenance:
        # Verify the replacement process before resuming paid or browser work.
        async def after_update():
            while update_manager.maintenance:
                await asyncio.sleep(1)
            await _start_publisher_service()
        update_manager.resume_task = asyncio.create_task(after_update())
        return
    if getattr(publisher_service, "_closed", False):
        publisher_service = PublisherService(DATA_ROOT / "workspace")
    if not topic_recommendation_availability.TOPIC_RECOMMENDATIONS_PAUSED:
        for account in await run_io(workspace_store.list_accounts):
            await run_io(topic_recommendation_runtime.ensure, str(account["id"]))
    # Unified migration preserves old snapshots and in-flight recovery payloads.
    _resume_pending_creation_tasks()
    for interrupted in workspace_store.interrupt_running_breakdown_analyses():
        try:
            interrupted_task = task_store.get(interrupted["taskId"])
            if interrupted_task.phase in {"complete", "failed"}:
                continue
            platform = interrupted_task.platform if isinstance(interrupted_task.platform, dict) else {}
            if platform.get("taskId") or platform.get("parseTaskId") or platform.get("transcriptionTaskId"):
                # 已经提交给创作服务的任务由续查负责：不重复提交、也不按中断处理。
                continue
            task_store._fail(interrupted_task, "breakdown_interrupted", "服务重启，拆解已中断，请重新拆解。")
        except KeyError:
            pass
    home_advice_store.reset_running()
    interrupted_review = review_store.reset_running()
    if interrupted_review:
        logger.info("review_collections_reset_on_startup count=%s", len(interrupted_review))
    interrupted_monitor = monitor_store.reset_running()
    if interrupted_monitor:
        logger.info("monitor_collections_reset_on_startup count=%s", len(interrupted_monitor))
    interrupted_radar = radar_store.reset_running()
    if interrupted_radar:
        logger.info("radar_collections_reset_on_startup count=%s", len(interrupted_radar))
    interrupted = workspace_store.interrupt_running_title_generations()
    if interrupted:
        logger.info("title_generation_jobs_interrupted_on_startup count=%s", interrupted)
    interrupted_writing = workspace_store.interrupt_running_writing_generations()
    if interrupted_writing:
        logger.info("writing_generation_jobs_interrupted_on_startup count=%s", interrupted_writing)
    workspace_store.interrupt_running_cover_title_generations()
    interrupted_links = workspace_store.interrupt_processing_link_scripts()
    if interrupted_links:
        logger.info("link_tasks_interrupted_on_startup count=%s", len(interrupted_links))
    for task_id in workspace_store.list_ready_link_task_ids():
        _schedule_local_media_recovery(task_id)
    for record in workspace_store.list_running_cover_generations():
        script_id = record["scriptId"]
        generation = workspace_store.interrupt_unsubmitted_cover_aspects(script_id, record["generation"]["jobId"])
        if generation and generation["status"] == "running":
            _start_cover_generation_recovery(script_id, generation["jobId"])
    if _review_scheduler_task is None or _review_scheduler_task.done():
        _review_scheduler_task = asyncio.create_task(_review_scheduler_loop())
    # 启动时就检查一次：服务停止期间错过的采集在这里补一次。
    await _check_review_schedule()
    if _monitor_scheduler_task is None or _monitor_scheduler_task.done():
        _monitor_scheduler_task = asyncio.create_task(_monitor_scheduler_loop())
    await _check_monitor_schedule()
    if _radar_scheduler_task is None or _radar_scheduler_task.done():
        _radar_scheduler_task = asyncio.create_task(_radar_scheduler_loop())
    # 启动时就检查一次：服务停止期间错过的关键词采集和当天还没生成的建议在这里补。
    await _check_radar_schedule()
    # 会话仍然有效时清掉登录前写入的阻断记录（例如上一次未登录时留下的「请先登录」）。
    await _release_login_blocks("startup")


async def _stop_review_scheduler() -> None:
    global _review_scheduler_task
    task = _review_scheduler_task
    _review_scheduler_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _close_publisher_service() -> None:
    close = getattr(publisher_service, "close", None)
    if callable(close):
        close()


app.add_event_handler("startup", _start_publisher_service)
app.add_event_handler("shutdown", _close_publisher_service)
app.add_event_handler("shutdown", _stop_review_scheduler)

app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
app.mount("/ui-design-standard", StaticFiles(directory=PROJECT_ROOT / "ui-design-standard"), name="ui-design-standard")


class DownloadRequest(BaseModel):
    shareText: str = Field(min_length=1, max_length=5000)
    quality: Literal["best", "high", "medium", "low"] = "best"


class TaskRequest(BaseModel):
    shareText: str = Field(min_length=1, max_length=5000)


class BreakdownCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 链接来源填 shareText；本地音视频来源填 mediaId，两者二选一。
    shareText: str = Field(default="", max_length=5000)
    title: str = Field(default="", max_length=2000)
    mediaId: str = Field(default="", max_length=64)


class CreationMediaRequest(BaseModel):
    """本地素材可直接引用已暂存的素材号，不必重复上传。"""

    model_config = ConfigDict(extra="forbid")

    mediaId: str = Field(default="", max_length=64)


class BreakdownTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 空标题/空大纲回落到拆解分析给出的推荐初稿，所以两个字段都可以不传。
    title: str = Field(default="", max_length=160)
    outline: str = Field(default="", max_length=2000)
    category: Literal["highlight", "daily", "series", "test"] = "highlight"
    format: Literal["video", "article"] = "video"
    publishDate: str = Field(default="", max_length=10)
    weekStart: Optional[str] = Field(default=None, max_length=10)


class RewriteRequest(BaseModel):
    systemPrompt: str = Field(min_length=1, max_length=12000)
    model: Literal["text-default", "text-option-2", "text-option-3"] = "text-default"


class AccountRewritePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    systemPrompt: str = Field(min_length=1, max_length=12000)
    templateId: Optional[Literal["general", "retention", "story"]] = None

    @field_validator("systemPrompt")
    @classmethod
    def require_nonblank_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("仿写提示词不能为空。")
        return normalized


class SaveRewriteRequest(BaseModel):
    content: str = Field(max_length=100000)
    model: Literal["text-default", "text-option-2", "text-option-3"] = "text-default"


class RewriteModelRequest(BaseModel):
    model: Literal["text-default", "text-option-2", "text-option-3"]


class AccountRequest(BaseModel):
    onboardingStage: Literal["existing", "new"] = "existing"
    name: str = Field(min_length=1, max_length=80)
    platform: Literal["douyin", "channels", "both"]


class AccountCreateRequest(AccountRequest):
    platform: Literal["douyin", "channels", "both"] = "both"


class OnboardingDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer: Optional[str] = Field(default=None, max_length=2000)
    audience: Optional[str] = Field(default=None, max_length=2000)
    goal: Optional[str] = Field(default=None, max_length=2000)
    businessPositioning: Optional[str] = Field(default=None, max_length=2000)
    targetAudience: Optional[str] = Field(default=None, max_length=2000)


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collapsed: Optional[bool] = None
    dismissed: Optional[bool] = None
    stage: Optional[Literal["existing", "new"]] = None
    preparationStep: Optional[int] = Field(default=None, ge=0, le=2)
    connectionSkipped: Optional[bool] = None
    draft: Optional[OnboardingDraftRequest] = None


class AccountNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def require_nonblank_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("账号名称不能为空。")
        return normalized


class CoverTemplateImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=300)
    url: str = Field(min_length=1, max_length=4096)


class CoverTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=12000)
    accent: str = Field(default="linear-gradient(140deg, #bcd3d9, #7d9aa4 58%, #44545c)", max_length=500)
    images: list[CoverTemplateImageRequest] = Field(default_factory=list, max_length=5)
    legacyId: Optional[str] = Field(default=None, max_length=200)

    @field_validator("label", "prompt")
    @classmethod
    def require_nonblank_template_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("模板名称和提示词不能为空。")
        return normalized


class BlankScriptRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)


class ScriptContentRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100000)


class ScriptTitleRequest(BaseModel):
    title: str = Field(min_length=1)


class ScriptAccountMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetAccountId: str = Field(min_length=1, max_length=100)


class ScriptStageRequest(BaseModel):
    stage: Literal["edit", "split", "write", "title", "cover", "publish"]


class WritingGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: Literal["structure", "content"]
    prompt: str = Field(min_length=1, max_length=12000)
    antiSimilarity: bool = True

    @field_validator("prompt")
    @classmethod
    def require_nonblank_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("提示词不能为空。")
        return normalized


class WritingPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: Literal["structure", "content"]
    prompt: str = Field(min_length=1, max_length=12000)
    antiSimilarity: bool = True

    @field_validator("prompt")
    @classmethod
    def require_nonblank_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("提示词不能为空。")
        return normalized


class WritingStructureSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=10000)
    keyPoint: str = Field(min_length=1, max_length=10000)

    @field_validator("name", "purpose", "keyPoint")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写段落标题、作用说明和要点。")
        return value.strip()


class SaveWritingStructureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=10000)
    sections: list[WritingStructureSection] = Field(min_length=1, max_length=100)

    @field_validator("topic")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写选题。")
        return value.strip()


class SaveWritingContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=100000)


class WritingMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: Literal["structure", "content"]
    rule: str = Field(min_length=1, max_length=4000)


class ScriptWorkflowStatusRequest(BaseModel):
    workflowStatus: Literal["pending", "editing", "ready_to_publish", "published"]


class TopicCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    outline: str = Field(default="", max_length=2000)
    category: Literal["highlight", "daily", "series", "test"] = "highlight"
    format: Literal["video", "article"] = "video"
    publishDate: str = Field(default="", max_length=10)
    materials: str = Field(default="", max_length=2000)
    weekStart: Optional[str] = Field(default=None, max_length=10)


class TopicUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None)
    outline: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[Literal["highlight", "daily", "series", "test"]] = None
    format: Optional[Literal["video", "article"]] = None
    publishDate: Optional[str] = Field(default=None, max_length=10)
    materials: Optional[str] = Field(default=None, max_length=2000)
    weekStart: Optional[str] = Field(default=None, max_length=10)
    # pending_creation is the topic-only 待创作 state; the other four come from the script.
    status: Optional[Literal["pending_creation", "pending", "editing", "ready_to_publish", "published"]] = None


class TopicPlanTargetsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    highlight: int = Field(ge=0, le=50)
    daily: int = Field(ge=0, le=50)
    series: int = Field(ge=0, le=50)
    test: int = Field(ge=0, le=50)


class TopicPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: TopicPlanTargetsRequest


class ManualTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    date: str = Field(default="", max_length=10)
    note: str = ""
    linkType: Literal["", "topic", "script"] = ""
    linkId: str = Field(default="", max_length=120)


class ManualTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=160)
    date: Optional[str] = Field(default=None, max_length=10)
    note: Optional[str] = None
    linkType: Optional[Literal["", "topic", "script"]] = None
    linkId: Optional[str] = Field(default=None, max_length=120)
    done: Optional[bool] = None


class InspirationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="", max_length=500)


class InspirationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(default=None, max_length=2000)
    source: Optional[str] = Field(default=None, max_length=500)


class InspirationConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=160)
    outline: str = Field(default="", max_length=2000)
    category: Literal["highlight", "daily", "series", "test"] = "daily"
    format: Literal["video", "article"] = "video"
    publishDate: str = Field(default="", max_length=10)
    materials: str = Field(default="", max_length=2000)
    weekStart: Optional[str] = Field(default=None, max_length=10)


class TitleSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    systemPrompt: str = Field(min_length=1, max_length=12000)

    @field_validator("systemPrompt")
    @classmethod
    def require_nonblank_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题提示词不能为空。")
        return normalized


class TitleSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "channels"]
    candidateId: str = Field(min_length=1, max_length=80)


def _reject_multiline_api_key(value: Optional[str]) -> Optional[str]:
    """密钥只接受单行；空串保留原值由调用方判断，这里只负责格式与长度。"""
    if value is None:
        return None
    normalized = value.strip()
    if "\n" in normalized or "\r" in normalized:
        raise ValueError("配置值不能包含换行符。")
    if len(normalized) > 400:
        raise ValueError("API Key 长度超出预期，请确认复制是否完整。")
    return normalized


class ProjectSettingsRequest(BaseModel):
    """旧配置写入接口已停用，不再接收密钥。"""

    model_config = ConfigDict(extra="forbid")


class CreationConnectionTestRequest(BaseModel):
    """创作服务连接测试：带上新输入就测新值，留空则测服务端已保存的 Key。"""

    model_config = ConfigDict(extra="forbid")

    apiKey: Optional[str] = None

    @field_validator("apiKey")
    @classmethod
    def check_api_key(cls, value: Optional[str]) -> Optional[str]:
        return _reject_multiline_api_key(value)




class AccountPositioningRequest(BaseModel):
    """账号定位两项都可以留空（继续按未完善处理），超长由存储层报错而不截断。"""

    model_config = ConfigDict(extra="forbid")

    businessPositioning: Optional[str] = None
    targetAudience: Optional[str] = None

    @field_validator("businessPositioning", "targetAudience")
    @classmethod
    def require_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("定位内容必须是文本。")
        return value


class PublishDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "channels"]
    title: Optional[str] = Field(default=None, max_length=30)
    shortTitle: Optional[str] = Field(default=None, max_length=16)
    description: str = Field(default="", max_length=2000)
    topics: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("description")
    @classmethod
    def normalize_publish_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_platform_main_title(self) -> "PublishDraftRequest":
        if self.platform == "douyin":
            if self.shortTitle is not None or not isinstance(self.title, str) or not self.title.strip():
                raise ValueError("抖音发布草稿必须包含标题，且不能包含短标题。")
        elif self.title is not None or not isinstance(self.shortTitle, str) or not self.shortTitle.strip():
            raise ValueError("视频号发布草稿必须包含短标题，且不能包含抖音标题。")
        if self.platform == "channels" and not self.description:
            raise ValueError("视频号发布描述不能为空。")
        return self

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, topics: list[str]) -> list[str]:
        if any(not topic.strip() or len(topic.strip()) > 80 or "\n" in topic or "\r" in topic for topic in topics):
            raise ValueError("话题格式无效。")
        return topics


class RestoreSelectedTitleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "channels"]


class PublishPlatformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["douyin", "channels"]


class CoverImageUpload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1, max_length=20_000_000)


class CoverReferenceUpload(BaseModel):
    images: list[CoverImageUpload] = Field(default_factory=list, max_length=5)


class CoverImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    ratio: Literal["portrait", "landscape", "both"] = "both"
    imageUrls: list[str] = Field(default_factory=list, max_length=5)


class CoverStateRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)


class WritingAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["hook", "structure", "ending"]
    name: str = Field(min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=400)
    example: str = Field(default="", max_length=400)
    format: Optional[Literal["video", "article"]] = None


class BreakdownAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=400)
    example: str = Field(default="", max_length=400)
    format: Optional[Literal["video"]] = None


class WritingAssetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    content: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    note: Optional[str] = Field(default=None, max_length=400)
    example: Optional[str] = Field(default=None, max_length=400)
    format: Optional[Literal["video", "article"]] = None


class WritingSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=120)
    content: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=400)
    example: str = Field(default="", max_length=400)
    steps: list[str] = Field(default_factory=list, max_length=24)
    format: str = Field(default="", max_length=20)


class ScriptCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)
    topicId: str = Field(default="", max_length=120)
    topic: str = Field(default="", max_length=200)
    contentFormat: Literal["video", "article"] = "video"
    platform: str = Field(default="", max_length=40)
    duration: str = Field(default="", max_length=60)
    points: str = Field(default="", max_length=4000)
    advanced: str = Field(default="", max_length=2000)
    hook: Optional[WritingSelectionRequest] = None
    structure: Optional[WritingSelectionRequest] = None
    ending: Optional[WritingSelectionRequest] = None
    # 个人经历按篇选择：默认不选，只用于本篇的内容写作。
    experienceIds: list[str] = Field(default_factory=list, max_length=50)
    referenceCopyIds: list[str] = Field(default_factory=list, max_length=50)


class BreakdownRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: str = Field(default="", max_length=2000)
    agentId: Optional[Literal["codex", "workbuddy"]] = None
    requestId: uuid.UUID = Field(default_factory=uuid.uuid4)


class WritingAgentDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scriptId: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=120)
    topicId: str = Field(default="", max_length=120)
    topic: str = Field(default="", max_length=200)
    contentFormat: Literal["video", "article"] = "video"
    platform: str = Field(default="", max_length=40)
    duration: str = Field(default="", max_length=60)
    points: str = Field(default="", max_length=4000)
    advanced: str = Field(default="", max_length=2000)
    hook: Optional[WritingSelectionRequest] = None
    structure: Optional[WritingSelectionRequest] = None
    ending: Optional[WritingSelectionRequest] = None
    # 个人经历按篇选择：默认不选，只用于本篇的内容写作。
    experienceIds: list[str] = Field(default_factory=list, max_length=50)
    referenceCopyIds: list[str] = Field(default_factory=list, max_length=50)


class WritingAgentReturnExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule: str = Field(default="", max_length=300)
    evidence: str = Field(default="", max_length=600)
    node: str = Field(default="content", max_length=20)


class WritingAgentReturnRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    submissionId: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    experiences: list[WritingAgentReturnExperience] = Field(default_factory=list, max_length=20)
    temporaryRequirements: list[str] = Field(default_factory=list, max_length=20)


class PendingExperienceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1, max_length=200)
    adopt: bool = True


class MemoryDirectoryRequest(BaseModel):
    """记忆目录只接收一个本地路径；校验与迁移都在存储层完成。"""

    model_config = ConfigDict(extra="forbid")

    directory: str = Field(min_length=1, max_length=1000)
    accountId: str = Field(default="", max_length=100)


class MemoryDirectoryOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["folder", "obsidian"] = "folder"
    accountId: str = Field(min_length=1, max_length=100)


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=80)
    category: Literal["preference", "experience", "reference_copy"] = "preference"
    scope: Literal["structure", "content", "both"] = "content"
    content: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(default="", max_length=2000)
    # 新建时可以直接保存成停用状态；停用的记忆不会进入生成。
    enabled: bool = True


class MemoryUpdateRequest(BaseModel):
    """编辑记忆时只覆盖显式提交的字段。"""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=80)
    category: Optional[Literal["preference", "experience", "reference_copy"]] = None
    scope: Optional[Literal["structure", "content", "both"]] = None
    content: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    evidence: Optional[str] = Field(default=None, max_length=2000)
    enabled: Optional[bool] = None


class MemoryEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class MemorySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experienceIds: list[str] = Field(default_factory=list, max_length=50)
    referenceCopyIds: list[str] = Field(default_factory=list, max_length=50)


class ReviewConfigRequest(BaseModel):
    """复盘采集设置的部分更新；未提交的字段保持原值。"""

    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    mode: Optional[Literal["interval", "daily"]] = None
    intervalMinutes: Optional[int] = None
    dailyTime: Optional[str] = Field(default=None, max_length=5)
    scope: Optional[Literal["recent30", "recent90", "all"]] = None
    platform: Optional[Literal["douyin", "channels"]] = None


class ReviewNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=4000)
    reviewed: Optional[bool] = None


class ReviewScriptLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scriptId: str = Field(default="", max_length=200)


class ReviewTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekStart: Optional[str] = Field(default=None, max_length=10)


_COVER_IMAGE_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.DOTALL)
class ReviewFactorRequest(BaseModel):
    """作品因子确认：只更新提交的字段，其余沿用已有快照。"""

    model_config = ConfigDict(extra="forbid")

    topic: Optional[dict[str, Any]] = None
    hook: Optional[dict[str, Any]] = None
    structure: Optional[dict[str, Any]] = None
    origin: Optional[Literal["direct", "reference", "unknown"]] = None
    confirmed: Optional[bool] = None


class ReviewFactorSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["script", "ai"] = "script"



_COVER_IMAGE_MAX_BYTES = 8 * 1024 * 1024
_COVER_RATIOS = {"portrait", "landscape", "both"}
_COVER_ASPECTS = {"3:4", "4:3"}
_TITLE_HASHTAG_RE = re.compile(r"[#＃]([A-Za-z0-9_\-\u3400-\u4DBF\u4E00-\u9FFF]+)")
_PUBLISH_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
_PUBLISH_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_PUBLISH_VIDEO_MIME_TYPES = {
    ".mp4": {"video/mp4"},
    ".mov": {"video/quicktime"},
    ".m4v": {"video/x-m4v", "video/mp4"},
    ".webm": {"video/webm"},
}
_PUBLISH_IMAGE_MIME_TYPES = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg", "image/jpg"},
    ".jpeg": {"image/jpeg", "image/jpg"},
    ".webp": {"image/webp"},
}
_PUBLISH_VIDEO_MAX_BYTES = 1024 * 1024 * 1024
_PUBLISH_IMAGE_MAX_BYTES = 20 * 1024 * 1024
_PUBLISH_UPLOAD_CHUNK_BYTES = 1024 * 1024
_PUBLISH_LOGIN_STATUSES = {"logged_in", "login_required", "unknown", "login_opened"}
_PUBLISH_TASK_STATUSES = {"queued", "running", "waiting_for_review", "failed"}


def _require_local_origin(request: Request) -> None:
    """Only the local workbench page may start an Agent task."""
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(status_code=403, detail={"message": "请使用本机地址访问工作台。"})
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail={"message": "请从本地工作台打开助手。"})


def _require_loopback_client(request: Request) -> None:
    """Return submissions come from the local Skill script, never from the network."""
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail={"message": "回传只允许来自本机工作台。"})


def _writing_agent_endpoint(request: Request, task_id: str) -> str:
    """Build the loopback return URL written into the task descriptor."""
    port = request.url.port or 8001
    return f"http://127.0.0.1:{port}/api/writing-agent-tasks/{task_id}"


def _writing_agent_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AssistantError):
        return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, CodexAgentError):
        return HTTPException(
            status_code=503,
            detail={"code": "writing_agent_open_failed", "message": str(exc)},
        )
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail={"message": str(exc)})
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"message": str(exc.args[0] if exc.args else "资源不存在。")})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"message": str(exc)})
    raise exc


def _publisher_error_status(code: str) -> int:
    if code == "publish_task_not_found":
        return 404
    if code == "publish_task_active":
        return 409
    if code in {"browser_unavailable", "publisher_closed", "publish_task_start_failed"}:
        return 503
    return 400


def _raise_publisher_error(exc: PublisherError) -> None:
    raise HTTPException(
        status_code=_publisher_error_status(exc.code),
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _review_platform_for_account(account_id: str, requested: Any = None) -> str:
    """复盘第一版只采集抖音；账号不支持时直接报错，不静默换平台。"""
    platform = str(requested or _REVIEW_PLATFORM)
    workspace_store.validate_publish_platform(account_id, platform)
    return platform


def _review_work_or_404(work_id: str) -> dict[str, Any]:
    try:
        return review_store.get_work(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "review_work_not_found", "message": str(exc)}) from exc


async def _run_review_blocking(fn: Callable[..., Any], *args: Any) -> Any:
    """采集是阻塞调用，放到专门的线程池，避免占住事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_review_pool, functools.partial(fn, *args))


def _page_closed(page: Any) -> bool:
    closed = getattr(page, "is_closed", None)
    if not callable(closed):
        return False
    try:
        return bool(closed())
    except Exception:
        return True


def _review_collect_blocking(account_id: str, platform: str, scope: str) -> dict[str, Any]:
    """在线程里用账号独立无头会话读取作品列表（累计指标）。

    账号日报和作品逐日明细在入库后通过各自的后台会话补采。
    """

    def callback(page: Any) -> dict[str, Any]:
        try:
            outcome = collect_douyin_works(
                page,
                scope=scope,
                cover_dir=review_store.covers_dir,
                account_id=account_id,
            )
        except ReviewCollectionError as exc:
            if exc.code == "login_required":
                publisher_service.capture_account_identity(account_id, platform, page, status="login_required")
            raise
        publisher_service.capture_account_identity(account_id, platform, page)
        return outcome

    return publisher_service.run_on_account_background_page(account_id, platform, callback)


def _review_account_report_blocking(account_id: str, platform: str) -> dict[str, Any]:
    """读账号级的逐日数据（数据中心页面自己用的接口）。

    走接口而不是点「导出」：这台机器上的 Chrome 在点导出时会让浏览器进程崩溃，
    而接口返回的就是同一个页面上看到的数字。
    """

    def callback(page: Any) -> dict[str, Any]:
        return {"account": fetch_account_rows(page, days=REPORT_RECENT_SCOPE_DAYS)}

    return publisher_service.run_on_account_background_page(account_id, platform, callback)


async def _review_sync_account_reports(account_id: str, platform: str, stamp: str) -> tuple[dict[str, Any], str]:
    """采集账号逐日数据；失败只提示并保留旧数据，不影响作品列表。"""
    try:
        payload = await _run_review_blocking(_review_account_report_blocking, account_id, platform)
    except Exception as exc:
        logger.info(
            "review_account_api_failed account=%s code=%s",
            account_id,
            getattr(exc, "code", type(exc).__name__),
        )
        return {}, "账号逐日数据这次没取到，稍后会自动补。"
    account_rows = payload.get("account") or {}
    saved = await run_io(
        review_store.record_daily_reports,
        account_id,
        account_rows=account_rows,
        collected_at=stamp,
        scope={"days": REPORT_RECENT_SCOPE_DAYS, "kind": "recent"},
    )
    if saved.get("latestDay"):
        return saved, f"账号逐日数据已更新到 {saved['latestDay']}。"
    return saved, "账号逐日数据这次没有新增日期。"


def _review_work_reports_blocking(account_id: str, platform: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    """按缺口逐条读作品逐日数据：优先复用已验证的作品 ID，失败再打开详情。

    单条失败只记录原因，不影响其他作品；整段有时间上限，避免长时间占着浏览器。
    """

    def callback(page: Any) -> dict[str, Any]:
        rows: dict[str, Any] = {}
        reports: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        started = time.monotonic()
        for target in targets:
            work_id = str(target.get("workId") or "")
            title = str(target.get("title") or "")
            if not work_id or not title:
                continue
            if time.monotonic() - started > REPORT_SYNC_TIME_BUDGET_SECONDS:
                errors.append({"workId": work_id, "code": "time_budget", "message": "达到本次补采时间上限，剩余作品下次继续。"})
                break
            if _page_closed(page):
                errors.append({"workId": work_id, "code": "page_closed", "message": "采集页面已关闭，剩余作品下次继续。"})
                break
            detail = None
            try:
                item_id = str(target.get("itemId") or "")
                daily = {}
                if item_id.isascii() and item_id.isdigit():
                    try:
                        # 新标签页先进入同源页面，让接口携带账号登录状态。
                        if not str(getattr(page, "url", "")).startswith("https://creator.douyin.com/"):
                            page.goto(DOUYIN_CONTENT_MANAGE_URL)
                        daily = fetch_work_rows(page, item_id)
                    except ReviewCollectionError:
                        logger.info("review_cached_item_fallback account=%s work=%s", account_id, work_id)
                # 缓存仅省导航。接口为空、失败或缺少播放/涨粉时仍按原路径读取。
                if not daily or any(
                    metrics.get("views") is None or metrics.get("fansGained") is None
                    for metrics in daily.values()
                ):
                    detail = open_work_detail(page, title=title)
                    resolved_id = item_id_from_url(str(getattr(detail, "url", "")))
                    if resolved_id != item_id:
                        daily = {}  # 不能把旧 ID 的数据合到另一条作品。
                    item_id = resolved_id
                    if not item_id:
                        raise ReviewCollectionError("work_id_missing", "没有读到作品 ID，稍后重试。")
                    daily = merge_work_rows(daily, fetch_work_rows(detail, item_id))
            except ReviewCollectionError as exc:
                errors.append({"workId": work_id, "code": exc.code, "message": exc.message})
                logger.info(
                    "review_work_report_failed account=%s work=%s code=%s",
                    account_id, work_id, exc.code,
                )
                if not daily:
                    continue
            finally:
                close_page(detail)
            if not daily:
                errors.append({"workId": work_id, "code": "work_daily_empty", "message": "后台还没有这条作品的逐日数据。"})
                continue
            # 播放和涨粉来自两个接口，按同一种报表种类入库即可（存储层按字段合并）。
            rows[work_id] = {REPORT_WORK_VIEWS: daily}
            if any(metrics.get("views") is None or metrics.get("fansGained") is None for metrics in daily.values()):
                errors.append({"workId": work_id, "code": "work_daily_incomplete", "message": "部分日期缺少播放或涨粉指标，已保存现有数据，下次继续补。"})
            reports.append({"kind": REPORT_WORK_VIEWS, "workId": work_id, "itemId": item_id, "fetchedAt": now_iso()})
        return {"rows": rows, "reports": reports, "errors": errors}

    return publisher_service.run_on_account_background_page(account_id, platform, callback)


def _forget_review_job(account_id: str, task: Any) -> None:
    with _review_jobs_lock:
        if _review_jobs.get(account_id) is task:
            _review_jobs.pop(account_id, None)


async def _cancel_review_jobs(account_id: str) -> None:
    """账号删除或服务关闭时，取消该账号仍在跑的采集。"""
    with _review_jobs_lock:
        task = _review_jobs.pop(account_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.info("review_job_cancel_failed account=%s", account_id)


async def _review_sync_work_reports(account_id: str, platform: str, stamp: str, *, force: bool = False) -> str:
    """补作品逐日明细：先补缺口，再复查最近可能被后台修正的作品。

    逐日明细失败只记录一行说明，不影响已经入库的累计指标和账号日报表。
    """
    targets = await run_io(
        review_store.work_report_targets,
        account_id,
        limit=REPORT_WORK_SYNC_LIMIT,
        force=force,
    )
    if not targets:
        return ""
    try:
        payload = await _run_review_blocking(_review_work_reports_blocking, account_id, platform, targets)
    except (ReviewCollectionError, PublisherError) as exc:
        message = str(getattr(exc, "message", "") or exc)
        logger.info("review_work_reports_skipped account=%s reason=%s", account_id, message)
        return f"作品逐日明细这次没取到（{message}）"
    rows = payload.get("rows") or {}
    if rows:
        await run_io(
            review_store.record_daily_reports,
            account_id,
            work_rows=rows,
            reports=payload.get("reports") or [],
            collected_at=stamp,
        )
    errors = payload.get("errors") or []
    if errors:
        return f"作品逐日明细：更新 {len(rows)} 条，{len(errors)} 条留到下次补。"
    if rows:
        return f"作品逐日明细已更新 {len(rows)} 条。"
    return ""


REVIEW_TOPIC_CATEGORY_LABELS = {
    "highlight": "重点",
    "daily": "日常",
    "series": "系列",
    "test": "测试",
}


def _review_origin_map(account_id: str, works: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """创作来源只看关联脚本是哪种创建方式，不用内容因子推断。"""
    scripts = {str(script.get("id") or ""): script for script in workspace_store.list_scripts(account_id)}
    origins: dict[str, str] = {}
    for work in works:
        script = scripts.get(str(work.get("scriptId") or ""))
        if script is None:
            continue
        origins[str(work.get("id") or "")] = "reference" if str(script.get("source") or "") == "link" else "direct"
    return origins


def _review_factor_catalog(account_id: str) -> dict[str, list[dict[str, str]]]:
    """因子弹窗可选项：选题分类沿用选题库，钩子和结构沿用写作素材库。"""
    assets = workspace_store.list_writing_assets(account_id)

    def entries(items: Any) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for item in items or []:
            name = " ".join(str((item or {}).get("name") or "").split())
            if name:
                result.append({"id": str((item or {}).get("id") or ""), "name": name[:80]})
        return result

    return {
        "topic": [{"id": key, "name": label} for key, label in REVIEW_TOPIC_CATEGORY_LABELS.items()],
        "hook": entries(assets.get("hooks")),
        "structure": entries(assets.get("structures")),
    }


def _review_script_candidates(
    account_id: str,
    work: Mapping[str, Any],
    *,
    scripts: Mapping[str, Mapping[str, Any]],
    topics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """从这条作品关联的脚本里取出候选因子。

    直接创建的脚本带着当时的选题、钩子、结构选择，可以当作待确认候选；
    参考链接的脚本只有参考视频，不继承它的分类，需要按最终稿再确认。
    """
    script_id = str(work.get("scriptId") or "")
    script = scripts.get(script_id)
    if script is None:
        return {"source": "none", "origin": "unknown", "topic": "", "hook": "", "structure": "", "scriptTitle": "", "scriptContent": ""}
    creation = script.get("creation") if isinstance(script.get("creation"), dict) else {}
    origin = "reference" if str(script.get("source") or "") == "link" else "direct"
    topic = topics.get(str(creation.get("topicId") or "")) or {}
    topic_label = REVIEW_TOPIC_CATEGORY_LABELS.get(str(topic.get("category") or ""), "")
    hook = creation.get("hook") if isinstance(creation.get("hook"), dict) else {}
    structure = creation.get("structure") if isinstance(creation.get("structure"), dict) else {}
    return {
        "source": "reference" if origin == "reference" else "script",
        "origin": origin,
        "topic": topic_label,
        "hook": " ".join(str(hook.get("name") or "").split())[:80],
        "structure": " ".join(str(structure.get("name") or "").split())[:80],
        "scriptTitle": str(script.get("title") or ""),
        "scriptContent": str(script.get("content") or ""),
    }


async def _review_script_and_topic_lookups(account_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scripts = {str(script.get("id") or ""): script for script in await run_io(workspace_store.list_scripts, account_id)}
    payload = await run_io(workspace_store.list_topics, account_id)
    topics = {str(topic.get("id") or ""): topic for topic in (payload.get("items") or [])}
    return scripts, topics


async def _run_review_collection(account_id: str, *, trigger: str, scope_override: str | None = None) -> None:
    """一次采集：读设置 → 采集 → 入库 → 记录状态并推进下一次执行时间。"""
    try:
        config = await run_io(review_store.get_config, account_id)
        platform = str(config.get("platform") or _REVIEW_PLATFORM)
        scope = str(config.get("scope") or "recent30")
        # 首次采集先建立作品索引：账号最近没有作品落在所选范围里时，如果直接按
        # 范围过滤，第一次就会得到空列表，看起来像采集失败。
        first_run = not await run_io(review_store.list_works, account_id)
        effective_scope = scope_override or ("all" if first_run else scope)
        await run_io(
            review_store.record_status,
            account_id,
            "running",
            "正在用该账号的专用浏览器采集…",
            result={"trigger": trigger},
        )
        stamp = now_iso()
        outcome = await _run_review_blocking(_review_collect_blocking, account_id, platform, effective_scope)
        works = list(outcome.get("works") or [])
        merge = await run_io(review_store.upsert_works, account_id, works, collected_at=stamp)
        await run_io(_remember_review_onboarding, account_id)
        _, daily_note = await _review_sync_account_reports(account_id, platform, stamp)
        # 手动同步时把作品逐日明细整段重拉一遍；定时采集只补缺口并复查最近的作品。
        work_note = "" if first_run else await _review_sync_work_reports(
            account_id, platform, stamp, force=trigger == "manual"
        )
        # 各后台采集调用已释放自身资源，不关闭用户的登录/发布窗口。
        truncated = bool(outcome.get("truncated"))
        if not works:
            status, message = "success", "本次没有读到作品，请确认该账号已发布作品且后台可正常打开。"
        elif truncated:
            status = "partial"
            message = f"采集到 {len(works)} 条作品，达到时间上限，可能未覆盖全部作品。"
        else:
            status = "success"
            message = f"采集完成，共 {len(works)} 条作品（新增 {merge['created']} 条）。"
        message = " ".join(part for part in [message, daily_note, work_note] if part)
        await run_io(
            review_store.record_status,
            account_id,
            status,
            message,
            result={
                "trigger": trigger,
                "scope": effective_scope,
                "firstRun": first_run,
                "count": len(works),
                "created": merge["created"],
                "updated": merge["updated"],
                "unchanged": merge["unchanged"],
            },
            advance_schedule=True,
        )
        logger.info(
            "review_collection_done account=%s trigger=%s works=%s created=%s",
            account_id, trigger, len(works), merge["created"],
        )
    except ReviewCollectionError as exc:
        await run_io(
            review_store.record_status,
            account_id,
            "login_required" if exc.code == "login_required" else "failed",
            exc.message,
            result={"trigger": trigger, "code": exc.code},
            advance_schedule=True,
        )
        logger.info("review_collection_stopped account=%s code=%s", account_id, exc.code)
    except PublisherError as exc:
        await run_io(
            review_store.record_status,
            account_id,
            "failed",
            f"采集失败：{exc.message}",
            result={"trigger": trigger, "code": exc.code},
            advance_schedule=True,
        )
        logger.info("review_collection_browser_failed account=%s code=%s", account_id, exc.code)
    except asyncio.CancelledError:
        # 取消发生在服务关闭或账号删除时，此时写状态只是尽力而为，失败也无妨。
        try:
            await run_io(review_store.record_status, account_id, "idle", "采集已取消。", advance_schedule=True)
        except Exception:
            logger.info("review_collection_cancel_status_failed account=%s", account_id)
        raise
    except Exception:
        logger.exception("review_collection_error account=%s trigger=%s", account_id, trigger)
        await run_io(
            review_store.record_status,
            account_id,
            "failed",
            "采集出现未知错误，已保留上一次的数据。",
            result={"trigger": trigger},
            advance_schedule=True,
        )


def _start_review_collection(account_id: str, *, trigger: str, scope_override: str | None = None) -> str:
    """启动一次采集；同账号已有任务时返回 running，不重复排队。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return "unavailable"
    with _review_jobs_lock:
        existing = _review_jobs.get(account_id)
        if existing is not None and not existing.done():
            return "running"
        task = loop.create_task(_run_review_collection(account_id, trigger=trigger, scope_override=scope_override)
                                if scope_override else _run_review_collection(account_id, trigger=trigger))
        _review_jobs[account_id] = task
    task.add_done_callback(lambda finished, key=account_id: _forget_review_job(key, finished))
    return "started"


async def _check_review_schedule() -> None:
    """触发到点的账号；服务停止期间错过的任务在这里补一次。

    读取设置是阻塞的磁盘操作，放到 IO 线程；创建任务必须回到事件循环所在线程，
    否则线程池里没有 running loop，任务根本不会启动。
    """
    await home_advice_runtime.schedule()
    for account_id in await run_io(review_store.due_account_ids):
        _start_review_collection(account_id, trigger="schedule")


async def _review_scheduler_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_REVIEW_SCHEDULER_TICK_SECONDS)
            await _check_review_schedule()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("review_scheduler_tick_failed")


# ----------------------------------------------------------------------
# 监控：创作服务数据采集 + 今日 AI 选题建议
# ----------------------------------------------------------------------
#
# 监控和复盘是两条独立链路：复盘读的是当前账号自己的抖音后台（账号专用浏览器），
# 监控读的是外部博主（创作服务 HTTP 接口）。调用是异步的，不需要浏览器池；
# 只有本地 JSON 读写走 IO 池。

MONITOR_PROFILE_REFRESH_SECONDS = 20 * 3600
# 封面是抖音签名临时地址，而且多为 HEIC：下载后转成 JPEG 缓存到工作区，列表才显示得出来。
MONITOR_IMAGE_TIMEOUT_SECONDS = 15.0
MONITOR_IMAGE_MAGIC_HEIC = (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1", b"ftypmsf1", b"ftypheim", b"ftypheis")


def _monitor_image_suffix(body: bytes) -> str:
    if body[:4] == b"\x89PNG":
        return ".png"
    if body[:2] == b"\xff\xd8":
        return ".jpg"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return ".webp"
    if body[4:12] in MONITOR_IMAGE_MAGIC_HEIC:
        return ".heic"
    return ""


def _monitor_convert_image(source: Path, target: Path) -> bool:
    """HEIC 浏览器不能直接渲染，用项目已有的 ffmpeg 转成 JPEG。"""
    from .ffmpeg import ffmpeg_path

    try:
        result = subprocess.run(
            [ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(source), "-frames:v", "1", str(target)],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and target.is_file() and target.stat().st_size > 0


async def _cache_monitor_image(url: str, *, directory: Path, name: str) -> Path | None:
    """下载一张抖音图片并缓存成本地可显示格式（HEIC 转 JPEG）。"""
    controlled = str(url or "").startswith("/workbench/v1/")
    if not controlled and not str(url or "").startswith("http"):
        return None
    try:
        if controlled:
            directory.mkdir(parents=True, exist_ok=True)
            transfer = directory / f".{name}.{uuid.uuid4().hex}.transfer"
            try:
                await _workbench_service().business_client().download_asset(url, transfer, timeout=MONITOR_IMAGE_TIMEOUT_SECONDS)
                body = await run_io(transfer.read_bytes)
            finally:
                transfer.unlink(missing_ok=True)
        else:
            # Existing social CDN images may predate the controlled platform URLs.
            import httpx
            async with httpx.AsyncClient(timeout=MONITOR_IMAGE_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": BROWSER_UA, "Referer": "https://www.douyin.com/"})
            if response.status_code != 200:
                return None
            body = response.content
    except Exception:
        return None
    if not body:
        return None
    suffix = _monitor_image_suffix(body)
    if not suffix:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    staged = directory / f".{name}.{uuid.uuid4().hex}.src"
    try:
        staged.write_bytes(body)
        target = directory / f"{name}.jpg"
        if suffix == ".heic":
            converted = await run_io(_monitor_convert_image, staged, target)
            return target if converted else None
        target = directory / f"{name}{suffix}"
        os.replace(staged, target)
        return target
    except OSError:
        return None
    finally:
        if staged.exists():
            try:
                staged.unlink()
            except OSError:
                pass


async def _ensure_monitor_cover(work_id: str) -> Path | None:
    """返回可显示的封面；本地已有缓存就直接用，否则下载并在需要时转换。"""
    cached = await run_io(monitor_store.cover_file, work_id)
    if cached is not None:
        return cached
    try:
        work = await run_io(monitor_store.get_work, work_id)
    except ValueError:
        return None
    return await _cache_monitor_image(
        str(work.get("coverUrl") or "").strip(),
        directory=monitor_store.covers_dir,
        name=work_id,
    )


async def _ensure_monitor_avatar(blogger_id: str) -> Path | None:
    """返回可显示的博主头像；头像同样会过期，所以缓存到本地再提供。"""
    cached = await run_io(monitor_store.avatar_file, blogger_id)
    if cached is not None:
        return cached
    try:
        blogger = await run_io(monitor_store.get_blogger, blogger_id)
    except ValueError:
        return None
    return await _cache_monitor_image(
        str(blogger.get("avatarUrl") or "").strip(),
        directory=monitor_store.avatars_dir,
        name=blogger_id,
    )


@app.get("/api/monitor/covers/{work_id}")
async def get_monitor_cover(work_id: str) -> FileResponse:
    path = await _ensure_monitor_cover(work_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "monitor_cover_not_found", "message": "封面暂时不可用。"})
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/monitor/avatars/{blogger_id}")
async def get_monitor_avatar(blogger_id: str) -> FileResponse:
    path = await _ensure_monitor_avatar(blogger_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "monitor_avatar_not_found", "message": "头像暂时不可用。"})
    # 头像会随博主更新，缓存时间比封面短一些。
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


def _monitor_sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _monitor_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(2)
        _monitor_semaphores.clear()
        _monitor_semaphores[loop] = semaphore
    return semaphore


async def _business_context(source: str, *, account_id: str = "", trigger: str = "manual",
                            blogger: Optional[Mapping[str, Any]] = None, keyword: str = "") -> dict[str, str]:
    """Snapshot attribution from the initiating operation, never UI active-account state."""
    context = {"source": source, "trigger": trigger}
    if account_id:
        accounts = await run_io(workspace_store.list_accounts)
        context.update(accountId=account_id, accountName=next(
            (str(account.get("name") or "") for account in accounts if str(account.get("id")) == account_id), ""))
    if blogger:
        context.update(targetId=str(blogger.get("secUserId") or blogger.get("id") or ""),
                       targetName=str(blogger.get("nickname") or ""), targetHandle=str(blogger.get("uniqueId") or ""))
    if keyword:
        context["keyword"] = keyword
    return context


async def _script_business_context(script: Mapping[str, Any], action: str) -> dict[str, str]:
    context = await _business_context("script", account_id=str(script.get("accountId") or ""))
    context["action"] = action
    return context


def _data_client() -> PlatformDataClient:
    """数据采集统一走创作服务平台的 /workbench/v1，用当前登录用户的会话凭证。"""
    settings = load_settings()
    return PlatformDataClient.from_settings(settings, store=subscription_store)


def _data_error_status(exc: PlatformDataError) -> str:
    if exc.code in {"unauthorized", "session_revoked", "account_disabled", "permission_denied"}:
        return "auth_required"
    if exc.code in {"insufficient_points", "subscription_required", "subscription_expired"}:
        return "insufficient_points"
    if exc.code == "platform_mode_required":
        return "platform_mode_required"
    return "failed"


def _relogin_code(exc_code: object) -> str:
    """落盘的错误码：凭证类错误统一标记为 ``needs_relogin``，其余保留平台原始码。"""
    code = str(exc_code or "")
    return NEEDS_RELOGIN if code in RELOGIN_CODES else code


def _creation_failure_status(exc: PlatformDataError) -> int:
    """数据查询失败的 HTTP 状态：鉴权、余额、限流各自可辨，其余按上游不可用。"""
    if exc.code in {"unauthorized", "session_revoked", "permission_denied"}:
        return 401
    if exc.code in {"insufficient_points", "subscription_required", "subscription_expired"}:
        return 402
    if exc.code == "rate_limited":
        return 429
    if exc.code in {"invalid_cursor", "unsupported_input"}:
        return 400
    if exc.code == "platform_mode_required":
        return 409
    return 502


def _monitor_profile_due(blogger: Mapping[str, Any]) -> bool:
    """博主资料每天更新一次，不在每轮作品检查里重复付费。"""
    stamp = parse_iso(blogger.get("profileUpdatedAt"))
    if stamp is None:
        return True
    return (datetime.now(timezone.utc) - stamp).total_seconds() >= MONITOR_PROFILE_REFRESH_SECONDS


async def _monitor_fetch_works(
    data: PlatformDataClient,
    sec_user_id: str,
    *,
    usage: RoundUsage,
) -> tuple[list[Mapping[str, Any]], dict[str, Any], int]:
    """拉取主页最新第一页作品。

    监控判断的是最新发布数据的增量，第二页往后的作品已经过了时效，所以每轮固定只请求一次，
    不再翻页补查；同一响应里重复返回的作品仍然去重。

    平台返回的是归一化条目，这里还原成工作台内部的作品结构，下游规范化与去重逻辑不变。
    """
    result = await data.query(CAPABILITY_POSTS, {"sec_user_id": sec_user_id})
    page = result.get("page") or {}
    usage.add(result.get("chargedPoints"), frozen=result.get("frozenPoints"))
    batch = [posts_item_to_aweme(item) for item in page_items(page)]
    items: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for entry in batch:
        if not isinstance(entry, Mapping):
            continue
        work_id = str(entry.get("aweme_id") or "")
        if not work_id or work_id in seen:
            continue
        seen.add(work_id)
        items.append(entry)
    coverage = {
        "pages": 1,
        "fetched": len(items),
        "hasMore": bool(page.get("hasMore")),
    }
    return items, coverage, 1


async def _run_monitor_collection(blogger_id: str, *, trigger: str = "manual", account_id: str = "") -> dict[str, Any]:
    """采集一位博主的一轮作品数据。同一博主多账号共享，结果只写一份。"""
    if trigger == "schedule" and not _workbench_ready():
        # 未登录时不启动平台任务、也不写失败记录：登录后由调度自动补齐。
        return {"status": "skipped", "reason": "waiting_login"}
    try:
        blogger = await run_io(monitor_store.get_blogger, blogger_id)
    except ValueError as exc:
        return {"status": "failed", "message": str(exc)}
    # Freeze attribution before any upstream wait; later follow/UI changes do not move usage.
    usage_account_ids = tuple((blogger.get("follows") or {}).keys()) if trigger == "schedule" else ((account_id,) if account_id else ())
    sec_user_id = str(blogger.get("secUserId") or "")
    if not sec_user_id:
        await run_io(monitor_store.record_collection, blogger_id, status="failed", error="博主身份缺失，请重新添加。")
        return {"status": "failed", "message": "博主身份缺失，请重新添加。"}
    settings = await run_io(monitor_store.get_settings)
    _ = settings
    baseline = not str(blogger.get("baselineAt") or "")
    collected_at = now_iso()
    await run_io(monitor_store.mark_collect_started, blogger_id)
    usage = RoundUsage()
    try:
        data = _data_client()
        data.business_context = await _business_context("monitor", account_id=account_id, trigger=trigger, blogger=blogger)
        async with _monitor_sem():
            profile: dict[str, Any] = {}
            if _monitor_profile_due(blogger):
                profile_result = await data.query(CAPABILITY_PROFILE, {"sec_user_id": sec_user_id})
                usage.add(profile_result.get("chargedPoints"), frozen=profile_result.get("frozenPoints"))
                profile_page = profile_result.get("page") or {}
                profile = normalize_douyin_user(profile_to_user(profile_page.get("profile")))
            raw_works, coverage, _pages = await _monitor_fetch_works(data, sec_user_id, usage=usage)
    except PlatformDataError as exc:
        status = _data_error_status(exc)
        message = exc.message
        await run_io(monitor_store.record_collection, blogger_id, status=status, error=message,
                     error_code=_relogin_code(exc.code))
        logger.info("monitor_collection_failed blogger=%s code=%s trigger=%s", blogger_id, exc.code, trigger)
        return {"status": status, "message": message}
    except Exception as exc:  # pragma: no cover - 兜底，避免任务把调度器带崩
        await run_io(monitor_store.record_collection, blogger_id, status="failed", error="采集发生未预期错误。")
        logger.exception("monitor_collection_crashed blogger=%s trigger=%s", blogger_id, trigger)
        return {"status": "failed", "message": "采集发生未预期错误。"}

    if profile:
        await run_io(monitor_store.upsert_blogger, profile)
    normalized = [
        work
        for work in (normalize_douyin_aweme(item, blogger_id=blogger_id, discovered_at=collected_at) for item in raw_works)
        if work is not None
    ]
    merge = await run_io(
        monitor_store.upsert_works,
        blogger_id,
        normalized,
        collected_at=collected_at,
        baseline=baseline,
    )
    requested = usage.requests
    if requested:
        await run_io(monitor_store.record_requests, "posts", requested, account_ids=usage_account_ids)
    if usage.chargedPoints != "0.000":
        await run_io(monitor_store.record_charge, usage.chargedPoints, requested)
    await run_io(
        monitor_store.record_collection,
        blogger_id,
        status="success",
        error="",
        coverage=coverage,
        first_page_at=collected_at,
        baseline_at=collected_at if baseline else "",
    )
    logger.info(
        "monitor_collection_done blogger=%s trigger=%s added=%s updated=%s pages=%s",
        blogger_id,
        trigger,
        merge.get("added"),
        merge.get("updated"),
        coverage.get("pages"),
    )
    return {"status": "success", "coverage": coverage, "merge": merge, "requests": requested,
            "chargedPoints": usage.chargedPoints}


MONITOR_COLLECTION_TIMEOUT_SECONDS = 1800


async def _guard_monitor_collection(blogger_id: str, *, trigger: str, account_id: str = "") -> dict[str, Any]:
    """覆盖整轮采集（包括排队和结果落盘），确保异常退出不会留下 running。"""
    code = "collection_interrupted"
    message = "采集意外中断，将按设置的间隔再次检查。"
    try:
        return await asyncio.wait_for(
            _run_monitor_collection(blogger_id, trigger=trigger, account_id=account_id),
            timeout=MONITOR_COLLECTION_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        await run_io(monitor_store.record_collection, blogger_id, status="failed",
                     error="采集已中断，已提交任务的结果待确认。", error_code="status_pending")
        raise
    except asyncio.TimeoutError:
        code = "status_pending"
        message = "本轮采集等待超时，已提交任务的结果待确认；将按设置的间隔再次检查。"
        logger.warning("monitor_collection_timeout blogger=%s trigger=%s", blogger_id, trigger)
    except Exception:
        logger.exception("monitor_collection_unhandled blogger=%s trigger=%s", blogger_id, trigger)
    await run_io(monitor_store.record_collection, blogger_id, status="failed", error=message, error_code=code)
    return {"status": "failed", "message": message}


def _start_monitor_collection(blogger_id: str, *, trigger: str, account_id: str = "") -> str:
    """启动（或复用）一位博主的采集任务；同一博主同一时刻只跑一个。"""
    existing = _monitor_jobs.get(blogger_id)
    if existing is not None and not existing.done():
        return "running"
    loop = asyncio.get_running_loop()
    task = loop.create_task(_guard_monitor_collection(blogger_id, trigger=trigger, account_id=account_id))
    _monitor_jobs[blogger_id] = task

    def _forget(finished: asyncio.Task, key: str = blogger_id) -> None:
        if _monitor_jobs.get(key) is finished:
            _monitor_jobs.pop(key, None)
        if not finished.cancelled() and finished.exception() is not None:
            logger.error("monitor_collection_guard_failed blogger=%s", key,
                         exc_info=finished.exception())

    task.add_done_callback(_forget)
    return "started"


async def _start_monitor_collections_for_account(account_id: str, *, trigger: str) -> dict[str, int]:
    settings = await run_io(monitor_store.get_settings)
    if not settings.get("collectEnabled", True) and trigger == "schedule":
        return {"started": 0, "running": 0}
    blogger_ids = await run_io(monitor_store.account_blogger_ids, account_id)
    started = running = 0
    for blogger_id in blogger_ids:
        try:
            blogger = await run_io(monitor_store.get_blogger, blogger_id)
        except ValueError:
            continue
        follow = (blogger.get("follows") or {}).get(account_id) or {}
        if not follow.get("enabled", True):
            continue
        outcome = _start_monitor_collection(blogger_id, trigger=trigger, account_id=account_id)
        if outcome == "running":
            running += 1
        else:
            started += 1
    return {"started": started, "running": running}


async def _monitor_recommendation_context(account_id: str) -> dict[str, Any]:
    """准备一次 AI 生成所需的输入；返回 ``skip`` 表示这次不需要（也不应该）调用模型。"""
    follows = await run_io(monitor_store.list_follows, account_id, page_size=500)
    if not follows.get("items"):
        return {"skip": True, "reason": "当前账号还没有关注的博主，先在监控里添加博主。"}
    today = local_day()
    window_start = f"{today}T00:00:00+08:00"
    works = await run_io(monitor_store.recommendation_works, account_id, since=window_start, limit=200)
    note = "今天新发现的作品"
    if len(works) < 3:
        recent = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        works = await run_io(monitor_store.recommendation_works, account_id, since=recent, limit=200)
        note = "今天的新作品不足 3 条，本次参考最近 24 小时的新发现作品"
    if len(works) < 3:
        # 首次接入时当天通常只有刚导入的历史作品：候选太少就纳入它们，
        # 但必须在窗口说明里写清楚，不能让基线作品冒充今日热点。
        works = await run_io(
            monitor_store.recommendation_works,
            account_id,
            since=window_start,
            limit=200,
            include_baseline=True,
        )
        note = "最近 24 小时的新作品不足 3 条，本次把刚导入的历史作品也纳入参考"
    if not works:
        return {"skip": True, "reason": "最近 24 小时没有新的监控作品，跳过本次生成，已有建议保留。", "window": note}
    profile = await run_io(workspace_store.read_account_profile, account_id)
    accounts = await run_io(workspace_store.list_accounts)
    account_name = next((str(item.get("name") or "") for item in accounts if str(item.get("id")) == account_id), "")
    try:
        account_inputs = await run_io(build_account_inputs, account_id, workspace_store, review_store)
    except (ValueError, OSError, KeyError) as exc:
        raise TextServiceError("monitor_inputs_unavailable", "账号复盘数据读取失败，已有建议保留。") from exc
    topics = await run_io(workspace_store.list_topics, account_id)
    dismissed = await run_io(monitor_store.dismissed_recommendations, account_id)
    window = {"from": window_start, "to": now_iso(), "note": note, "today": today}
    context = build_recommendation_context(
        account_name=account_name,
        business_positioning=str(profile.get("businessPositioning") or ""),
        target_audience=str(profile.get("targetAudience") or ""),
        monitor_works=works,
        review_works=[],
        existing_topics=list((topics or {}).get("items") or []),
        dismissed=dismissed,
        window=window,
        today=today,
    )
    context.update(account_inputs)
    context.update(context["account"])
    inputs = {
        "monitorWorkCount": len(works),
        "reviewWorkCount": account_inputs["review"]["submitted"],
        "bloggerCount": follows.get("total") or 0,
        "hasPositioning": _monitor_profile_ready(profile.get("businessPositioning")),
        "hasAudience": _monitor_profile_ready(profile.get("targetAudience")),
    }
    # Only allow citations to external works actually submitted after context limits.
    works = context["monitorWorks"]
    inputs["monitorWorkCount"] = len(works)
    analysis = {"schemaVersion": 2, "review": account_inputs["review"],
                "gaps": account_inputs["review"]["gaps"], "monitorWorkCount": len(works)}
    return {"schemaVersion": 2, "context": context, "window": window, "inputs": inputs, "works": works, "analysis": analysis}


def _monitor_profile_ready(value: Any) -> bool:
    """账号档案里的占位文本不算已填写，避免把「待完善」当成真实定位。"""
    text = str(value or "").strip()
    return bool(text) and not text.startswith("【待完善】")


def _original_finalize_items(items, works, *, source, limit):
    """Bind every recommendation to authoritative input data, never model titles/links."""
    from copy import deepcopy
    by_id = {str(work.get("id")): work for work in works}
    finalized, seen = [], set()
    for item in items[:limit]:
        source_id = str(item.get("sourceWorkId") or "")
        work = by_id.get(source_id)
        if not work or not str(work.get("title") or "").strip():
            raise TextServiceError(f"{source}_topic_invalid", "推荐作品不在本次候选中或没有原标题，已有建议保留。")
        if source_id in seen:
            continue
        seen.add(source_id)
        snapshot = deepcopy(dict(work))
        snapshot["authorName"] = str(work.get("authorName") or work.get("bloggerName") or "")
        snapshot["bloggerName"] = str(work.get("bloggerName") or work.get("authorName") or "")
        snapshot["kind"] = str(work.get("kind") or "video")
        entry = {key: deepcopy(item.get(key)) for key in
                 ("reason", "angle", "priority", "evidence", "reviewEvidence", "reviewReferences", "relevance", "performance")}
        entry.update(schemaVersion=2, sourceWorkId=source_id, sourceWork=snapshot,
                     title=str(work["title"]), key=f"{source}:{source_id}")
        refs = list(dict.fromkeys([source_id] + [str(ref) for ref in item.get("references") or []]))
        refs = [ref for ref in refs if ref in by_id][:4]
        entry["referenceSnapshots"] = [deepcopy(dict(by_id[ref])) for ref in refs]
        entry["references"] = entry["referenceSnapshots"] if source == "monitor" else refs
        finalized.append(entry)
    return finalized


def _monitor_finalize_items(items: list[Mapping[str, Any]], works: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _original_finalize_items(items, works, source="monitor", limit=MONITOR_RECOMMENDATION_LIMIT)


async def _attach_original_topic_states(account_id, view):
    for item in view.get("items") or []:
        if item.get("sourceWorkId") and not item.get("topicId"):
            topic = await run_io(workspace_store.find_topic_for_source, account_id, item.get("sourceWork") or {"id": item["sourceWorkId"]})
            if isinstance(topic, dict) and topic.get("id"):
                item["topicId"] = topic["id"]
    return view


async def _run_monitor_recommendation(account_id: str, *, trigger: str = "manual") -> dict[str, Any]:
    """为当前创作账号生成一批今日选题建议。生成期间不阻塞其他账号。"""
    recovery = await run_io(monitor_store.recommendation_recovery, account_id)
    await run_io(monitor_store.set_recommendation_job, account_id, "running")
    try:
        prepared = recovery.get("prepared") or await _monitor_recommendation_context(account_id)
        if prepared.get("skip"):
            reason = str(prepared.get("reason") or "这次没有需要分析的新内容。")
            logger.info("monitor_recommendation_skipped account=%s reason=%s", account_id, reason)
            return await run_io(monitor_store.set_recommendation_job, account_id, "skipped", error=reason)
        works = prepared["works"]
        allowed = {str(work.get("id")) for work in works}
        client = _text_service_client()
        async def remember(task_id: str) -> None:
            await run_io(monitor_store.remember_recommendation_task, account_id, task_id, prepared)

        async def monitor_transport(**kwargs: Any) -> dict[str, Any]:
            return await workbench.generate_text_result(
                _workbench_service(), **kwargs,
                resume_task_id=recovery.get("taskId", ""), on_created=remember)

        client._platform = monitor_transport
        client.business_context = await _business_context("monitor", account_id=account_id, trigger=trigger)
        items = await client.suggest_monitor_topics(prepared["context"], allowed_references=allowed)
        finalized = _monitor_finalize_items(items, works)
        await _attach_original_topic_states(account_id, {"items": finalized})
        saved = await run_io(
            monitor_store.save_recommendation,
            account_id,
            items=finalized,
            schema_version=2,
            window=prepared["window"],
            inputs=prepared["inputs"],
            analysis=prepared["analysis"],
        )
        logger.info("monitor_recommendation_done account=%s trigger=%s items=%s", account_id, trigger, len(finalized))
        return saved
    except TextServiceError as exc:
        if exc.code == "status_pending":
            saved = await run_io(monitor_store.recommendation_recovery, account_id)
            status = "pending" if saved else "unconfirmed"
            message = ("上次生成结果待确认，正在继续查询。" if saved else
                       "上次生成结果未确认，旧建议已保留；可点击更新建议重新生成。")
            return await run_io(monitor_store.set_recommendation_job, account_id, status,
                                error=message, error_code=exc.code)
        logger.info("monitor_recommendation_failed account=%s code=%s", account_id, exc.code)
        return await run_io(monitor_store.set_recommendation_job, account_id, "failed", error=exc.message,
                            error_code=_relogin_code(exc.code))
    except Exception:
        logger.exception("monitor_recommendation_crashed account=%s trigger=%s", account_id, trigger)
        return await run_io(monitor_store.set_recommendation_job, account_id, "failed", error="生成选题建议时发生未预期错误。")


def _start_monitor_recommendation(account_id: str, *, trigger: str) -> str:
    existing = _monitor_ai_jobs.get(account_id)
    if existing is not None and not existing.done():
        return "running"
    loop = asyncio.get_running_loop()
    task = loop.create_task(_run_monitor_recommendation(account_id, trigger=trigger))
    _monitor_ai_jobs[account_id] = task

    def _forget(finished: asyncio.Task, key: str = account_id) -> None:
        if _monitor_ai_jobs.get(key) is finished:
            _monitor_ai_jobs.pop(key, None)

    task.add_done_callback(_forget)
    return "started"


async def _check_monitor_ai_schedule() -> None:
    """Legacy entry point delegates to the single account-owned scheduler."""
    await topic_recommendation_runtime.schedule()


async def _check_monitor_schedule() -> None:
    if not _workbench_ready():
        # 未登录（或处于模拟通路）时不启动任何采集，也不落失败记录。
        return
    # 在事件循环里一并核对内存任务和落盘状态，避免 await 间新任务启动的竞态。
    recovered = monitor_store.recover_orphaned_collections(
        [key for key, task in _monitor_jobs.items() if not task.done()])
    if recovered:
        logger.warning("monitor_orphaned_collections_recovered count=%s", len(recovered))
    await _monitor_subscription_recovery.check(monitor_store, _subscription_service())
    due = await run_io(monitor_store.due_bloggers)
    for blogger_id in due:
        _start_monitor_collection(blogger_id, trigger="schedule")
    await _check_monitor_ai_schedule()


async def _monitor_scheduler_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_MONITOR_SCHEDULER_TICK_SECONDS)
            await _check_monitor_schedule()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("monitor_scheduler_tick_failed")


async def _stop_monitor_scheduler() -> None:
    global _monitor_scheduler_task
    task = _monitor_scheduler_task
    _monitor_scheduler_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app.add_event_handler("shutdown", _stop_monitor_scheduler)


def _normalize_login_response(raw: Any, platform: str) -> dict[str, str]:
    value = raw if isinstance(raw, dict) else {}
    status = value.get("status")
    return {
        "platform": platform,
        "status": status if status in _PUBLISH_LOGIN_STATUSES else "unknown",
        "message": str(value.get("message") or "暂时无法确认登录状态。")[:500],
        "loginUrl": str(value.get("loginUrl") or "")[:4096],
    }


def _normalize_publish_task(raw: Any) -> dict[str, str]:
    value = raw if isinstance(raw, dict) else {}
    status = value.get("status")
    return {
        "taskId": str(value.get("taskId") or "")[:200],
        "accountId": str(value.get("accountId") or "")[:200],
        "scriptId": str(value.get("scriptId") or "")[:200],
        "platform": value.get("platform") if value.get("platform") in {"douyin", "channels"} else "douyin",
        "status": status if status in _PUBLISH_TASK_STATUSES else "failed",
        "message": str(value.get("message") or "发布任务状态无效。")[:500],
        "manualReviewUrl": str(value.get("manualReviewUrl") or "")[:4096],
        "createdAt": str(value.get("createdAt") or "")[:100],
        "updatedAt": str(value.get("updatedAt") or "")[:100],
    }


def _validate_publish_filename(name: str, allowed_extensions: set[str]) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 200
        or name in {".", ".."}
        or Path(name).name != name
        or "\\" in name
        or any(ord(character) < 32 for character in name)
        or Path(name).suffix.lower() not in allowed_extensions
    ):
        raise ValueError("发布素材文件名或扩展名无效。")
    return name


def _stage_publish_reference(
    reference_path: str | None,
    reference_name: str | None,
    slot_directory: Path,
    script_id: str,
    allowed_extensions: set[str],
    max_bytes: int,
    label: str,
) -> Path:
    name = _validate_publish_filename(reference_name or "", allowed_extensions)
    destination = slot_directory / name
    if not isinstance(reference_path, str) or not reference_path or len(reference_path) > 4096:
        raise ValueError("发布素材路径无效。")
    with _publish_assets_save_lock:
        source = workspace_store.resolve_publish_asset_path(script_id, reference_path)
        if not source.is_file():
            raise ValueError("发布素材文件不存在。")
        if source.stat().st_size <= 0 or source.stat().st_size > max_bytes:
            raise ValueError(f"发布{label}超出大小限制。")
        shutil.copy2(source, destination)
    return destination


async def _stage_publish_upload(
    upload: UploadFile | None,
    reference_path: str | None,
    reference_name: str | None,
    directory: Path,
    slot: str,
    script_id: str,
) -> Path:
    expected_family = "video" if slot == "video" else "image"
    allowed_extensions = (
        _PUBLISH_VIDEO_EXTENSIONS if expected_family == "video" else _PUBLISH_IMAGE_EXTENSIONS
    )
    if (upload is None) == (reference_path is None):
        raise ValueError("发布素材必须且只能提供上传文件或已保存路径。")
    max_bytes = _PUBLISH_VIDEO_MAX_BYTES if expected_family == "video" else _PUBLISH_IMAGE_MAX_BYTES
    slot_directory = directory / slot
    slot_directory.mkdir()
    if upload is None:
        return await run_generation(
            _stage_publish_reference,
            reference_path,
            reference_name,
            slot_directory,
            script_id,
            allowed_extensions,
            max_bytes,
            "视频" if expected_family == "video" else "图片",
        )

    name = _validate_publish_filename(upload.filename or "", allowed_extensions)
    suffix = Path(name).suffix.lower()
    allowed_mime_types = (
        _PUBLISH_VIDEO_MIME_TYPES if expected_family == "video" else _PUBLISH_IMAGE_MIME_TYPES
    )[suffix]
    content_type = str(upload.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in allowed_mime_types:
        raise ValueError("发布素材 MIME 类型与素材位置不匹配。")
    destination = slot_directory / name
    total_bytes = 0
    await upload.seek(0)
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(_PUBLISH_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise ValueError(f"发布{'视频' if expected_family == 'video' else '图片'}超出大小限制。")
            handle.write(chunk)
    if total_bytes == 0:
        raise ValueError("发布素材不能为空。")
    return destination


def _save_staged_publish_assets(
    script_id: str,
    video_source: Path | None,
    portrait_source: Path | None,
    landscape_source: Path | None,
    cover_sources: dict[str, dict[str, str]],
    staging_directory: Path,
) -> dict:
    try:
        with _publish_assets_save_lock:
            assets = publish_assets_store.save(
                script_id,
                video_source,
                portrait_source,
                landscape_source,
                workspace_store.get_cover_state(script_id),
            )
            if cover_sources:
                assets["coverSources"] = cover_sources
            return workspace_store.save_publish_assets(script_id, assets)
    finally:
        if staging_directory.is_dir():
            shutil.rmtree(staging_directory)


def _successful_generated_cover_urls(cover_state: dict[str, Any]) -> dict[str, str]:
    results = cover_state.get("results") if isinstance(cover_state.get("results"), list) else []
    return {
        str(result["aspect"]): str(result["imageUrl"])
        for result in results
        if (
            isinstance(result, dict)
            and result.get("aspect") in {"3:4", "4:3"}
            and result.get("status") == "success"
            and isinstance(result.get("imageUrl"), str)
            and result["imageUrl"].strip()
        )
    }


def _cover_sources_for_publish_save(
    current_assets: dict[str, Any],
    cover_state: dict[str, Any],
    *,
    portrait_uploaded: bool,
    portrait_path: str | None,
    landscape_uploaded: bool,
    landscape_path: str | None,
) -> dict[str, dict[str, str]]:
    current_sources = current_assets.get("coverSources") if isinstance(current_assets.get("coverSources"), dict) else {}
    generated_urls = _successful_generated_cover_urls(cover_state)
    next_sources: dict[str, dict[str, str]] = {}
    for aspect, uploaded, reference_path in (
        ("3:4", portrait_uploaded, portrait_path),
        ("4:3", landscape_uploaded, landscape_path),
    ):
        if uploaded:
            next_sources[aspect] = {"type": "manual"}
        elif reference_path is not None and isinstance(current_sources.get(aspect), dict):
            next_sources[aspect] = dict(current_sources[aspect])
        elif reference_path is None and aspect in generated_urls:
            next_sources[aspect] = {"type": "generated", "imageUrl": generated_urls[aspect]}
    return next_sources


def _sync_generated_publish_cover_aspects(script_id: str, aspects: set[str]) -> dict[str, Any]:
    """Copy selected generated covers while retaining every non-selected publish choice."""
    staging_directory: Path | None = None
    with _publish_assets_save_lock:
        current_assets = workspace_store.get_publish_assets(script_id)
        video = current_assets.get("video")
        cover_state = workspace_store.get_cover_state(script_id)
        generated_urls = _successful_generated_cover_urls(cover_state)
        selected_aspects = {aspect for aspect in aspects if aspect in generated_urls}
        if not selected_aspects or not isinstance(video, dict) or not video.get("path"):
            return current_assets
        asset_directory = publish_assets_store._safe_asset_dir(script_id, create=True)
        staging_directory = asset_directory / f".cover-refresh-{uuid.uuid4()}"
        staging_directory.mkdir()
        try:
            def stage_saved_asset(source: Path, slot: str, name: str) -> Path:
                destination = staging_directory / slot / Path(name).name
                destination.parent.mkdir()
                shutil.copy2(source, destination)
                return destination

            video_source = stage_saved_asset(
                workspace_store.resolve_publish_asset_path(script_id, video["path"]),
                "video",
                str(video.get("name") or "video.mp4"),
            )
            covers = current_assets.get("covers") if isinstance(current_assets.get("covers"), dict) else {}

            def retained_cover_source(aspect: str) -> Path | None:
                if aspect in selected_aspects:
                    return None
                asset = covers.get(aspect)
                if not isinstance(asset, dict) or not asset.get("path"):
                    return None
                return stage_saved_asset(
                    workspace_store.resolve_publish_asset_path(script_id, asset["path"]),
                    "portrait" if aspect == "3:4" else "landscape",
                    str(asset.get("name") or "cover.png"),
                )

            assets = publish_assets_store.save(
                script_id,
                video_source,
                retained_cover_source("3:4"),
                retained_cover_source("4:3"),
                cover_state,
            )
            current_sources = current_assets.get("coverSources") if isinstance(current_assets.get("coverSources"), dict) else {}
            cover_sources = {
                aspect: dict(current_sources[aspect])
                for aspect in assets["covers"]
                if isinstance(current_sources.get(aspect), dict)
            }
            for aspect in selected_aspects:
                if aspect in assets["covers"]:
                    cover_sources[aspect] = {"type": "generated", "imageUrl": generated_urls[aspect]}
            if cover_sources:
                assets["coverSources"] = cover_sources
            return workspace_store.save_publish_assets(script_id, assets)
        finally:
            if staging_directory.is_dir():
                shutil.rmtree(staging_directory)


def _refresh_publish_assets_after_cover_completion(script_id: str, completed_aspect: str) -> None:
    """A new generated result takes precedence over a manual choice for its own aspect."""
    if completed_aspect not in {"3:4", "4:3"}:
        return
    try:
        _sync_generated_publish_cover_aspects(script_id, {completed_aspect})
    except Exception:
        # The cover result is already durable. A publish copy failure must not
        # turn a successful generation into an error result.
        logger.exception(
            "publish_assets_cover_refresh_failed script_id=%s aspect=%s",
            script_id,
            completed_aspect,
        )


def _reconcile_generated_publish_covers(script_id: str) -> dict[str, Any]:
    """Backfill legacy/generated publish covers without replacing manual choices."""
    current_assets = workspace_store.get_publish_assets(script_id)
    cover_state = workspace_store.get_cover_state(script_id)
    generated_urls = _successful_generated_cover_urls(cover_state)
    cover_sources = current_assets.get("coverSources") if isinstance(current_assets.get("coverSources"), dict) else {}
    aspects_to_refresh = {
        aspect
        for aspect, image_url in generated_urls.items()
        if (
            not isinstance(cover_sources.get(aspect), dict)
            or cover_sources[aspect].get("type") != "manual"
        ) and cover_sources.get(aspect, {}).get("imageUrl") != image_url
    }
    if not aspects_to_refresh:
        return current_assets
    return _sync_generated_publish_cover_aspects(script_id, aspects_to_refresh)


def _sanitize_cover_state(raw: Any) -> dict[str, Any]:
    """Validate and bound cover module state before persisting it per script."""
    if not isinstance(raw, dict):
        return {}

    def _images(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        images: list[dict[str, str]] = []
        for item in value[:10]:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            images.append({
                "id": str(item.get("id") or "")[:200],
                "name": str(item.get("name") or "")[:300],
                "url": item["url"][:4096],
            })
        return images

    def _results(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        results: list[dict[str, Any]] = []
        for item in value[:20]:
            if (
                not isinstance(item, dict)
                or item.get("aspect") not in _COVER_ASPECTS
                or not isinstance(item.get("imageUrl"), str)
            ):
                continue
            results.append({
                "aspect": item["aspect"],
                "imageUrl": item["imageUrl"][:4096],
                "status": "success" if item.get("status") == "success" else "error",
                "message": str(item.get("message") or "")[:500],
            })
        return results

    def _pending_jobs(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        jobs: list[dict[str, str]] = []
        for item in value[:10]:
            if not isinstance(item, dict) or item.get("aspect") not in _COVER_ASPECTS:
                continue
            jobs.append({"aspect": item["aspect"], "jobId": str(item.get("jobId") or "")[:200]})
        return jobs

    return {
        "prompt": str(raw.get("prompt") or "")[:4000],
        "ratio": raw["ratio"] if raw.get("ratio") in _COVER_RATIOS else "both",
        "uploadedImages": _images(raw.get("uploadedImages")),
        "results": _results(raw.get("results")),
        "pendingJobs": _pending_jobs(raw.get("pendingJobs")),
        "generatedReference": "upload" if raw.get("generatedReference") == "upload" else "",
        "activeImageId": str(raw.get("activeImageId") or "")[:200],
    }


def _title_source(task: dict[str, Any]) -> dict[str, Any]:
    raw_title = str(task.get("title") or "").strip()
    topics = []
    for match in _TITLE_HASHTAG_RE.finditer(raw_title):
        topic = "#" + match.group(1)
        if len(topic) > 1 and topic not in topics:
            topics.append(topic)
    title = _TITLE_HASHTAG_RE.sub("", raw_title)
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"\s+([，。！？；：、,.!?])", r"\1", title).strip()
    return {"title": title, "topics": topics[:10]}


def _link_title_source(task_id: str) -> dict[str, Any] | None:
    task = task_store.get(task_id)
    if not task.directory:
        return None
    source = _title_source(task_store.workspace(task_id))
    return source if source["title"] and source["title"] != "未命名视频" else None


def _title_generation_input(script: dict[str, Any]) -> tuple[str, list[str]] | None:
    if script.get("source") == "link":
        source = _link_title_source(str(script.get("taskId") or ""))
        return (source["title"], source["topics"]) if source else None
    title = str(script.get("title") or "").strip()
    return (title, []) if title else None


def _has_writing_source(script: dict[str, Any]) -> bool:
    """编写 works from a reference transcript: a legacy link task or a 拆解记录."""
    return script.get("source") == "link" or bool(script.get("breakdownId"))


def _writing_transcript(script: dict[str, Any]) -> str:
    """Return the reference transcript that 编写 generation writes from.

    A script created from a 拆解视频 topic carries the record id instead of a task
    id, so the 编写 stage keeps working after the link-script flow was retired.
    """
    task_id = str(script.get("taskId") or "")
    if not task_id:
        breakdown_id = str(script.get("breakdownId") or "")
        if breakdown_id:
            try:
                breakdown = workspace_store.get_breakdown(breakdown_id)
            except (ValueError, KeyError):
                breakdown = None
            task_id = str((breakdown or {}).get("taskId") or "")
    if not task_id:
        return ""
    try:
        task = task_store.workspace(task_id)
    except KeyError:
        return ""
    for field in ("transcript", "sourceText"):
        text = str(task.get(field) or "").strip()
        if text:
            return text
    segments = task.get("transcriptSegments")
    if isinstance(segments, list):
        joined = "\n".join(
            str(segment.get("text") or "").strip()
            for segment in segments
            if isinstance(segment, dict) and str(segment.get("text") or "").strip()
        )
        if joined:
            return joined
    return ""


def _writing_structure_memory_text(structure: dict[str, Any]) -> str:
    topic = str(structure.get("topic") or "").strip()
    lines = [f"选题：{topic}"] if topic else []
    for section in structure.get("sections") if isinstance(structure.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        name = str(section.get("name") or "").strip()
        purpose = str(section.get("purpose") or "").strip()
        key_point = str(section.get("keyPoint") or "").strip()
        lines.append(f"- {name}｜作用：{purpose}｜关键句：{key_point}")
    return "\n".join(lines).strip()


def _cover_title_source(script: dict[str, Any]) -> str | None:
    platforms = script.get("titleState", {}).get("platforms", {}) if isinstance(script.get("titleState"), dict) else {}
    for platform, field in (("douyin", "title"), ("channels", "shortTitle")):
        draft = platforms.get(platform, {}).get("publishDraft", {}) if isinstance(platforms.get(platform), dict) else {}
        title = str(draft.get(field) or "").strip() if isinstance(draft, dict) else ""
        if title:
            return title
    return None


def _decode_cover_image(data: str) -> tuple[bytes, str]:
    match = _COVER_IMAGE_DATA_URL_RE.match(data)
    if not match:
        raise HTTPException(
            status_code=400,
            detail={"code": "cover_image_invalid", "message": "参考图格式无效，仅支持 PNG/JPEG/WebP 图片。"},
        )
    image_type = match.group(1)
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "cover_image_invalid", "message": "参考图数据损坏，请重新上传。"},
        ) from exc
    if not raw or len(raw) > _COVER_IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail={"code": "cover_image_too_large", "message": "单张参考图不能超过 8MB。"},
        )
    content_type = "image/jpeg" if image_type == "jpg" else f"image/{image_type}"
    return raw, content_type


def task_has_split_content(task: dict) -> bool:
    if any(str(task.get(field) or "").strip() for field in ("transcript", "sourceText", "rewrite")):
        return True
    segments = task.get("transcriptSegments")
    return isinstance(segments, list) and any(
        isinstance(segment, dict) and str(segment.get("text") or "").strip()
        for segment in segments
    )


def result_to_api(result) -> dict:
    return {
        "taskId": Path(result.download_path).parent.name,
        "videoId": result.video_id,
        "title": result.title,
        "author": result.author,
        "durationSeconds": result.duration_seconds,
        "coverUrl": result.cover_url,
        "stats": result.stats,
        "createTime": result.create_time,
        "music": result.music,
        "fileName": result.file_name,
        "fileSizeBytes": result.file_size_bytes,
        "downloadPath": result.download_path,
        "metadataPath": result.metadata_path,
        "fileUrl": result.file_url,
    }


def list_history_items() -> list[dict[str, str]]:
    if not DOWNLOAD_DIR.is_dir():
        return []

    records: list[tuple[str, float, dict[str, str]]] = []
    for metadata_path in DOWNLOAD_DIR.glob("*/video.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("history_metadata_unreadable path=%s", metadata_path.name)
            continue

        if not isinstance(metadata, dict):
            logger.warning("history_metadata_invalid path=%s", metadata_path.name)
            continue

        raw_response = metadata.get("mediaMetadata")
        post = raw_response if isinstance(raw_response, dict) else {}
        post_text = str(post.get("text") or "").strip()
        metadata_title = str(metadata.get("title") or "").strip()
        metadata_description = str(metadata.get("desc") or "").strip()
        title = metadata_title or (
            metadata_description if metadata_description and metadata_description != "douyin_video" else post_text
        ) or "未命名视频"
        source_text = post_text or metadata_description or title
        author_data: Any = metadata.get("author")
        author = author_data if isinstance(author_data, dict) else {}
        author_name = str(author.get("nickname") or author.get("name") or author.get("display_name") or "未知作者").strip()
        submitted_at = str(metadata.get("fetch_time") or metadata.get("create_time") or "未知").strip()
        history_task_id = metadata_path.parent.name
        try:
            task_metadata = json.loads((metadata_path.parent / "task.json").read_text(encoding="utf-8"))
            persisted_task_id = str(task_metadata.get("taskId") or "").strip() if isinstance(task_metadata, dict) else ""
            if persisted_task_id:
                history_task_id = persisted_task_id
        except (OSError, json.JSONDecodeError):
            pass

        records.append(
            (
                submitted_at,
                metadata_path.stat().st_mtime,
                {
                    "taskId": history_task_id,
                    "videoId": str(metadata.get("video_id") or "").strip(),
                    "title": title or "未命名视频",
                    "author": author_name or "未知作者",
                    "submittedAt": submitted_at or "未知",
                    "sourceText": source_text or title or "未找到帖子文案",
                },
            )
        )

    records.sort(key=lambda record: (record[0] != "未知", record[0], record[1]), reverse=True)
    return [item for _, _, item in records[:100]]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health() -> dict:
    # plugins.ok=false 会让更新验证把“插件加载失败”判为更新失败，而不是静默成功。
    return {
        **health_status(),
        **health_info(),
        "runningVersion": update_manager.current,
        "instanceId": restart_manager.instance_id,
        "plugins": plugin_registry.health_snapshot(),
    }


@app.get("/api/history")
async def get_history() -> dict:
    return {"items": list_history_items()}


@app.get("/api/title-settings")
async def get_title_settings() -> dict:
    return {"systemPrompt": load_settings().title_rewrite_system_prompt}


@app.put("/api/title-settings")
async def save_title_settings(payload: TitleSettingsRequest) -> dict:
    save_settings(SettingsUpdate(titleRewriteSystemPrompt=payload.systemPrompt))
    return {"systemPrompt": payload.systemPrompt.strip()}




@app.get("/api/project-settings")
async def get_project_settings() -> dict[str, Any]:
    """项目设置只读视图：返回工作台平台地址与通路。"""
    return project_settings_view(load_settings())


# ----------------------------------------------------------- 订阅与积分（工作台侧）

# 合约见 工作台订阅积分接口契约。
# 工作台只做展示与转发：积分是否足够、应该扣多少，一律由创作服务 API 平台判定。


class SubscriptionPhoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = ""


class SubscriptionLoginRequest(SubscriptionPhoneRequest):
    code: str = ""


class SubscriptionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planId: str = ""
    # 支付方式由确认版弹框选择；模拟通路记录到订单，真实通路以渠道回调为准。
    method: str = ""


class SubscriptionSpendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specId: str = ""
    units: float = 1.0
    refId: str = ""


def _subscription_service() -> SubscriptionService:
    """每次请求读取一次配置，改 .env 后无需重启即可切换通路。"""
    return SubscriptionService(subscription_store, load_settings())


def _subscription_failure_http(exc: SubscriptionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code or 502, detail=exc.public_payload())


@app.get("/api/subscription/session")
async def get_subscription_session() -> dict[str, Any]:
    """本地登录态：供页面判断是否已登录，不返回任何凭证原文。"""
    return _subscription_service().session_view()


@app.post("/api/subscription/sms-code")
async def send_subscription_code(payload: SubscriptionPhoneRequest) -> dict[str, Any]:
    try:
        return await _subscription_service().send_code(payload.phone)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.post("/api/subscription/login")
async def subscription_login(payload: SubscriptionLoginRequest) -> dict[str, Any]:
    try:
        result = await _subscription_service().login(payload.phone, payload.code)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None
    # 登录成功后清掉登录前写入的阻断记录，界面不再残留「请先登录」的错误。
    await _release_login_blocks("login")
    return result


@app.post("/api/subscription/logout")
async def subscription_logout() -> dict[str, Any]:
    try:
        return await _subscription_service().logout()
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.get("/api/subscription/overview")
async def get_subscription_overview() -> dict[str, Any]:
    """账户与订阅首屏：套餐、当前订阅、可用与冻结积分一次取回。"""
    service = _subscription_service()
    session = service.session_view()
    if not session["loggedIn"]:
        return {"loggedIn": False, "mode": service.mode, "phone": "", "plans": (await service.plans(refresh=True))}
    try:
        # 先取一次 /points，订阅与余额共用：同一屏不再重复调用平台。
        owner = service.payment_owner()
        points = await service.balance()
        subscription = await service.subscription(points_view=points)
        await _monitor_subscription_recovery.check(
            monitor_store, service, balance=points, subscription=subscription, owner=owner)
        return {
            "loggedIn": True,
            "mode": service.mode,
            "phone": session["phone"],
            "paymentOwner": session["paymentOwner"],
            "subscription": subscription,
            "points": points,
            "plans": await service.plans(refresh=True),
        }
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.get("/api/subscription/trial-gift")
async def get_subscription_trial_gift(request: Request) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    try:
        result = await _subscription_service().trial_gift(owner=request.headers.get("X-Payment-Owner", ""))
        return JSONResponse(result, headers=headers)
    except SubscriptionError as exc:
        return JSONResponse({"detail": exc.public_payload()}, status_code=exc.status_code, headers=headers)


@app.get("/api/subscription/trial-gift/qrcode")
async def get_subscription_trial_gift_qrcode(request: Request) -> Response:
    headers = {"Cache-Control": "no-store"}
    try:
        service = _subscription_service()
        # An img src carries owner in its query. Neither version nor URL inputs select the target.
        service._trial_owner(request.headers.get("X-Payment-Owner", ""))
        content, media_type = await service.trial_gift_qrcode(owner=request.query_params.get("owner", ""))
        return Response(content, media_type=media_type, headers=headers)
    except SubscriptionError as exc:
        return JSONResponse({"detail": exc.public_payload()}, status_code=exc.status_code, headers=headers)


@app.get("/api/subscription/ledger")
async def get_subscription_ledger(page: int = 1, pageSize: int = 10, period: str = "current",
                                  type: str = "all", refresh: bool = False) -> dict[str, Any]:
    try:
        result = await _subscription_service().ledger(page=page, page_size=pageSize, period=period, entry_type=type, refresh=refresh)
        from .ledger_display import enrich_monitor_labels
        return await run_io(enrich_monitor_labels, result, monitor_store.blogger_by_sec_user)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.get("/api/subscription/orders")
async def get_subscription_orders(page: int = 1, pageSize: int = 10, status: str = "all",
                                  period: str = "3m") -> dict[str, Any]:
    try:
        return await _subscription_service().orders(page=page, page_size=pageSize, status=status, period=period)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


def _payment_service(request: Request):
    service = _subscription_service()
    owner = request.headers.get("X-Payment-Owner")
    if owner and owner != service.payment_owner():
        raise SubscriptionError("unauthorized", status_code=401)
    return service


@app.get("/api/subscription/orders/{order_id}")
async def get_subscription_order(order_id: str, request: Request) -> JSONResponse:
    try:
        result = await _payment_service(request).order(order_id)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.post("/api/subscription/orders/{order_id}/query")
async def query_subscription_order(order_id: str, request: Request) -> JSONResponse:
    try:
        result = await _payment_service(request).query_order(order_id)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.post("/api/subscription/orders/{order_id}/close")
async def close_subscription_order(order_id: str, request: Request) -> JSONResponse:
    try:
        result = await _payment_service(request).close_order(order_id)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


@app.post("/api/subscription/purchase")
async def purchase_subscription(payload: SubscriptionPlanRequest, request: Request) -> JSONResponse:
    try:
        result = await _payment_service(request).purchase(payload.planId, method=payload.method,
            idempotency_key=request.headers.get("Idempotency-Key", ""))
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None


async def _redemption_response(request: Request, *, preview: bool) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    try:
        # Manual validation deliberately excludes request input from error responses.
        try:
            body = await request.json()
        except Exception:
            body = None
        allowed = {"code", "planCode"} if preview else {"code", "planCode", "planVersion"}
        if (not isinstance(body, dict) or set(body) != allowed
                or not isinstance(body.get("code"), str) or not 1 <= len(body["code"]) <= 256
                or not body["code"].strip()
                or not isinstance(body.get("planCode"), str) or not 1 <= len(body["planCode"]) <= 80):
            raise SubscriptionError("validation_error", status_code=422)
        service = _subscription_service()
        if preview:
            result = await service.redemption_preview(body["code"], body["planCode"])
        else:
            key = request.headers.get("Idempotency-Key", "")
            if not 1 <= len(key) <= 80 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise SubscriptionError("idempotency_key_required", status_code=422)
            if type(body.get("planVersion")) is not int or body["planVersion"] < 1:
                raise SubscriptionError("validation_error", status_code=422)
            result = await service.redeem(body["code"], body["planCode"], body["planVersion"], key)
        return JSONResponse(result, headers=headers)
    except SubscriptionError as exc:
        retry = exc.details.get("retryAfterSeconds")
        if retry is not None:
            headers["Retry-After"] = str(retry)
        return JSONResponse({"detail": exc.public_payload()}, status_code=exc.status_code, headers=headers)


@app.post("/api/subscription/redemptions/preview")
async def preview_redemption(request: Request) -> JSONResponse:
    return await _redemption_response(request, preview=True)


@app.post("/api/subscription/redemptions")
async def redeem_subscription(request: Request) -> JSONResponse:
    return await _redemption_response(request, preview=False)


@app.post("/api/subscription/spend")
async def subscription_spend(payload: SubscriptionSpendRequest) -> dict[str, Any]:
    """模拟通路下的计费业务；真实通路由平台业务接口在服务端完成扣点。"""
    try:
        return await _subscription_service().spend(payload.specId, payload.units, ref_id=payload.refId)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None








@app.get("/api/project-settings/creation/status")
async def get_project_settings_creation_status() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail={"code": "creation_key_retired", "message": "旧版 Key 接口已停用，请登录工作台使用创作服务。"},
    )


@app.put("/api/project-settings")
async def save_project_settings(payload: ProjectSettingsRequest) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail={"code": "creation_key_retired", "message": "旧版 Key 接口已停用，请登录工作台使用创作服务。"},
    )


@app.post("/api/project-settings/creation/test")
async def test_project_settings_creation(payload: CreationConnectionTestRequest) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail={"code": "creation_key_retired", "message": "旧版 Key 接口已停用，请登录工作台使用创作服务。"},
    )




async def _transcription_estimate(media_id: str = "") -> dict[str, Any]:
    """预估本次拆解的两笔费用：视频解析（按次）与音频转写（按分钟）。

    只调免费报价，不产生任何付费调用。链接来源时长未知，按约定上限估算转写分钟；
    本地素材能探到真实时长，按它估算，且不产生解析费。未登录或模拟通路时返回空积分，
    界面只提示需要登录，不阻断素材选择。
    """
    staged = resolve_staged(media_id) if media_id else None
    if media_id and staged is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "media_unavailable", "message": "本地素材已不可用，请重新选择文件。"},
        )
    source = "upload" if staged else "link"
    seconds = float(staged.get("durationSeconds") or 0) if staged else 0.0
    if seconds <= 0:
        seconds = DEFAULT_LINK_MAX_SECONDS
    minutes = math.ceil(max(seconds, 0.0)) / 60.0
    quantity = "%0.4f" % minutes
    estimated_points = ""
    parse_points = ""
    try:
        client = _workbench_service().business_client()
        quoted = await workbench.quote(client, workbench.SPEC_AUDIO_TRANSCRIPTION, quantity)
        estimated_points = str(quoted.get("pointsAmount") or "")
        if source == "link":
            parse_quote = await workbench.quote(client, workbench.SPEC_VIDEO_PARSE, "1")
            parse_points = str(parse_quote.get("pointsAmount") or "")
    except SubscriptionError:
        estimated_points = ""
        parse_points = ""
    return {
        "source": source,
        "mediaId": staged["mediaId"] if staged else "",
        "mediaName": staged["name"] if staged else "",
        "durationSeconds": round(seconds, 2),
        "estimateMinutes": quantity,
        "estimatedPoints": estimated_points,
        "parseEstimatedPoints": parse_points,
    }


@app.post("/api/creation/media")
async def upload_creation_media(file: UploadFile = File(...)) -> dict[str, Any]:
    """暂存本地音视频素材并探测时长，供后续转写与费用上限估算使用。"""
    try:
        staged = await run_io(stage_upload, file.file, file.filename or "")
    except MediaStagingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    estimate = await _transcription_estimate(staged["mediaId"])
    return {**staged, "estimatedPoints": estimate["estimatedPoints"],
            "estimateMinutes": estimate["estimateMinutes"]}


@app.get("/api/creation/transcription-quote")
async def get_transcription_quote(mediaId: str = "") -> dict[str, Any]:
    """本次转写的费用上限预览：免费读取平台单价，不产生付费调用。"""
    return await _transcription_estimate(mediaId)






@app.get("/api/project-settings/creation/key")
async def get_project_settings_creation_key(request: Request) -> JSONResponse:
    raise HTTPException(
        status_code=410,
        detail={"code": "creation_key_retired", "message": "旧版 Key 接口已停用，请登录工作台使用创作服务。"},
    )


@app.get("/api/accounts")
async def get_accounts() -> dict:
    try:
        return {"items": await run_io(workspace_store.list_accounts)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


def _account_positioning_view(profile: Mapping[str, Any]) -> dict[str, Any]:
    """定位视图：原文照返，另外用 hasPositioning/hasAudience 标出哪些还是占位内容。"""
    return {
        "profile": {
            "businessPositioning": str(profile.get("businessPositioning") or ""),
            "targetAudience": str(profile.get("targetAudience") or ""),
        },
        "hasPositioning": _monitor_profile_ready(profile.get("businessPositioning")),
        "hasAudience": _monitor_profile_ready(profile.get("targetAudience")),
        "maxLength": ACCOUNT_PROFILE_FIELD_LIMIT,
    }


@app.get("/api/accounts/{account_id}/positioning")
async def get_account_positioning(account_id: str) -> dict[str, Any]:
    """读取当前账号的商业定位与面向人群，供项目设置页编辑。"""
    try:
        profile = await run_io(workspace_store.read_account_positioning, account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    return _account_positioning_view(profile)


@app.put("/api/accounts/{account_id}/positioning")
async def save_account_positioning(account_id: str, payload: AccountPositioningRequest) -> dict[str, Any]:
    """保存定位只作用于当前账号；留空按未完善处理，这不会触发任何模型调用。"""
    try:
        profile = await run_io(
            workspace_store.save_account_positioning,
            account_id,
            payload.businessPositioning,
            payload.targetAudience,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    return _account_positioning_view(profile)


_positioning_enhancing: set[str] = set()


@app.post("/api/accounts/{account_id}/positioning/enhance")
async def enhance_account_positioning(account_id: str, payload: AccountPositioningRequest) -> dict[str, str]:
    """只生成草稿；用户点击保存后才写入账号档案。"""
    try:
        values = positioning_input(payload.businessPositioning, payload.targetAudience)
        await run_io(workspace_store.read_account_positioning, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "workspace_validation_failed", "message": str(exc),
        }) from exc
    _require_workbench()
    if account_id in _positioning_enhancing:
        raise HTTPException(status_code=409, detail={
            "code": "positioning_generation_busy", "message": "该账号正在完善定位，请稍候。",
        })
    _positioning_enhancing.add(account_id)
    try:
        context = await _business_context("settings", account_id=account_id)
        context["action"] = "enhance_positioning"
        result = await workbench.generate_text_result(
            _workbench_service(), scene="title_copy", business_context=context,
            messages=[{"role": "system", "content": POSITIONING_PROMPT},
                      {"role": "user", "content": json.dumps(values, ensure_ascii=False)}],
            response_format={"type": "json_object"}, max_tokens=4096,
        )
        return positioning_result(result)
    except SubscriptionError as exc:
        raise _subscription_failure_http(exc) from None
    finally:
        _positioning_enhancing.discard(account_id)


def _memory_store_error(exc: MemoryStoreError) -> HTTPException:
    """记忆存储错误：只有「找不到这条记忆」是 404，其余都是可修正的输入问题。"""
    status_code = 404 if exc.code == "memory_not_found" else 400
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


def _account_or_value_error(exc: Exception) -> HTTPException:
    """账号/校验错误的统一映射：找不到资源是 404，输入不合法是 400。"""
    if isinstance(exc, MemoryStoreError):
        return _memory_store_error(exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"message": exc.args[0] if exc.args else "资源不存在。"})
    return HTTPException(status_code=400, detail={"message": str(exc)})


@app.get("/api/memory-settings")
async def get_memory_settings(accountId: str = "") -> dict[str, Any]:
    """根目录统一配置，专属目录按工作台返回。"""
    try:
        return await run_io(workspace_store.memory_settings_view, accountId)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except ValueError:
        raise HTTPException(status_code=404, detail={"message": "工作台不存在。"}) from None


@app.put("/api/memory-settings")
async def save_memory_settings(payload: MemoryDirectoryRequest) -> dict[str, Any]:
    """切换记忆目录；已有记忆会先复制到新目录，校验通过后才写入配置。"""
    try:
        return await run_io(workspace_store.save_memory_settings, payload.directory, payload.accountId)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except ValueError:
        raise HTTPException(status_code=404, detail={"message": "工作台不存在。"}) from None
    except OSError:
        logger.warning("记忆目录写入失败：%s", OSError.__name__)
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_directory_write_failed", "message": "目录写入失败，请检查路径与权限后重试。"},
        ) from None


@app.post("/api/memory-settings/choose")
async def choose_memory_directory(request: Request) -> dict[str, Any]:
    """调用本机文件夹选择器；用户取消或系统不支持时给出可理解的提示。"""
    _require_local_origin(request)
    if sys.platform != "darwin":
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_choose_unsupported", "message": "当前系统不支持文件夹选择器，请直接粘贴路径。"},
        )
    script = 'POSIX path of (choose folder with prompt "选择记忆文件夹")'
    try:
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=True, timeout=180, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_choose_cancelled", "message": "已取消选择，也可以直接粘贴文件夹路径。"},
        ) from None
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_choose_failed", "message": "未能打开系统文件夹选择器，请直接粘贴路径。"},
        ) from None
    directory = str(completed.stdout or "").strip()
    if not directory:
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_choose_cancelled", "message": "已取消选择，也可以直接粘贴文件夹路径。"},
        )
    return {"directory": directory}


@app.post("/api/memory-settings/open")
async def open_memory_directory(payload: MemoryDirectoryOpenRequest, request: Request) -> dict[str, Any]:
    """在本机打开记忆目录；Obsidian 需要用户已经安装并至少打开过一次仓库。"""
    _require_local_origin(request)
    try:
        view = await run_io(workspace_store.memory_settings_view, payload.accountId)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except ValueError:
        raise HTTPException(status_code=404, detail={"message": "工作台不存在。"}) from None
    directory = str(view.get("accountDirectory") or "")
    if not directory or not Path(directory).is_dir():
        raise HTTPException(
            status_code=400,
            detail={"code": "memory_directory_unavailable", "message": "记忆目录当前不可用，请重新选择后再打开。"},
        )
    if payload.target == "obsidian":
        vault = next((path for path in (Path(directory), *Path(directory).parents)
                      if (path / ".obsidian").is_dir()), None)
        if vault is None:
            raise HTTPException(status_code=400, detail={"code": "memory_obsidian_vault_missing", "message": "未找到所属 Obsidian 仓库，请先将记忆根目录加入仓库。"})
        directory = str(vault)
    command = ["/usr/bin/open", "-a", "Obsidian", directory] if payload.target == "obsidian" else ["/usr/bin/open", directory]
    try:
        subprocess.run(command, check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        message = "未能打开 Obsidian，请确认已安装并打开过这个仓库。" if payload.target == "obsidian" else "未能打开文件夹，请手动在访达中查看。"
        raise HTTPException(
            status_code=400, detail={"code": "memory_open_failed", "message": message}
        ) from None
    return {"ok": True}


@app.get("/api/accounts/{account_id}/memories")
async def list_account_memories(account_id: str) -> dict[str, Any]:
    """列出当前账号的记忆；目录不可用或存在无效文件时如实回报，不静默为空。"""
    try:
        return await run_io(workspace_store.list_memories, account_id)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "账号不存在。"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@app.post("/api/accounts/{account_id}/memories")
async def create_account_memory(account_id: str, payload: MemoryCreateRequest) -> dict[str, Any]:
    try:
        return await run_io(
            workspace_store.create_memory, account_id,
            {
                "title": payload.title,
                "category": payload.category,
                "scope": payload.scope,
                "content": payload.content,
                "evidence": payload.evidence,
                "enabled": payload.enabled,
            },
        )
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.put("/api/accounts/{account_id}/memories/{memory_id}")
async def update_account_memory(account_id: str, memory_id: str, payload: MemoryUpdateRequest) -> dict[str, Any]:
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"message": "没有需要修改的内容。"})
    try:
        return await run_io(workspace_store.update_memory, account_id, memory_id, fields)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.patch("/api/accounts/{account_id}/memories/{memory_id}")
async def patch_account_memory(account_id: str, memory_id: str, payload: MemoryEnabledRequest) -> dict[str, Any]:
    """启停记忆：停用后不再进入提示词，文件与内容都保留。"""
    try:
        return await run_io(workspace_store.set_memory_enabled, account_id, memory_id, payload.enabled)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.delete("/api/accounts/{account_id}/memories/{memory_id}")
async def delete_account_memory(account_id: str, memory_id: str) -> dict:
    try:
        return await run_io(workspace_store.delete_memory, account_id, memory_id)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


async def _breakdown_author_identity(account_id: str, breakdown_id: str) -> dict:
    await _require_account(account_id)
    try:
        record = await run_io(workspace_store.get_breakdown, breakdown_id)
        if record["accountId"] != account_id:
            raise KeyError("拆解记录不属于当前账号。")
        view = await run_io(task_store.workspace, record["taskId"])
        return view.get("authorIdentity") or {}
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.get("/api/accounts/{account_id}/breakdowns/{breakdown_id}/author")
async def get_breakdown_author(account_id: str, breakdown_id: str) -> dict:
    identity = await _breakdown_author_identity(account_id, breakdown_id)
    return await run_io(monitor_store.author_status, account_id, identity)


@app.post("/api/accounts/{account_id}/breakdowns/{breakdown_id}/author/monitor")
async def follow_breakdown_author(account_id: str, breakdown_id: str) -> dict:
    identity = await _breakdown_author_identity(account_id, breakdown_id)
    try:
        return await run_io(monitor_store.follow_local_author, account_id, identity)
    except ValueError as exc:
        raise _account_or_value_error(exc) from None


@app.post("/api/accounts/{account_id}/breakdowns/{breakdown_id}/reference-copy")
async def collect_breakdown_reference_copy(account_id: str, breakdown_id: str) -> dict:
    try:
        record = await run_io(workspace_store.get_breakdown, breakdown_id)
        if record["accountId"] != account_id:
            raise KeyError("拆解记录不属于当前账号。")
        # Resolve from managed source data; the caller cannot submit arbitrary transcript text.
        task = await run_io(task_store.workspace, record["taskId"])
        transcript = str(task.get("transcript") or "").strip()
        if task.get("phase") != "complete" or not transcript:
            raise HTTPException(status_code=409, detail={"message": "视频文案尚未转写完成，暂时不能收藏。"})
        return await run_io(workspace_store.collect_reference_copy, account_id, breakdown_id, transcript, str(task.get("title") or ""))
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.post("/api/accounts")
async def create_account(payload: AccountCreateRequest) -> dict:
    try:
        return workspace_store.create_account(payload.name, payload.platform, payload.onboardingStage)
    except MemoryStoreError as exc:
        raise _memory_store_error(exc) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, payload: AccountRequest) -> dict:
    try:
        return workspace_store.update_account_platform(account_id, payload.platform)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/accounts/{account_id}/name")
async def rename_account(account_id: str, payload: AccountNameRequest) -> dict:
    try:
        return workspace_store.rename_account(account_id, payload.name)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/accounts/{account_id}/rewrite-prompt")
async def get_account_rewrite_prompt(account_id: str) -> dict:
    try:
        return workspace_store.get_account_rewrite_prompt_config(account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.put("/api/accounts/{account_id}/rewrite-prompt")
async def save_account_rewrite_prompt(account_id: str, payload: AccountRewritePromptRequest) -> dict:
    try:
        return workspace_store.save_account_rewrite_prompt_config(account_id, payload.systemPrompt, payload.templateId)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.get("/api/accounts/{account_id}/deletion-summary")
async def get_account_deletion_summary(account_id: str) -> dict:
    try:
        return workspace_store.get_account_deletion_summary(account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str) -> dict[str, Any]:
    reserved = False
    try:
        _reserve_account_deletion(account_id)
        reserved = True
        scripts = workspace_store.list_scripts(account_id)
        # Validate every script before any account-owned file is removed, so an
        # active publisher task leaves the account untouched.
        for script in scripts:
            publisher_service.prepare_script_deletion(str(script["id"]))
        for script in scripts:
            if script.get("source") != "link":
                continue
            task_id = str(script.get("taskId") or "")
            await _cancel_link_script_jobs(task_id)
            try:
                task_store.delete(task_id)
            except KeyError:
                pass
            workspace_store.delete_link_task_materials(task_id)
        await _cancel_review_jobs(account_id)
        await home_advice_runtime.cancel(account_id)
        home_advice_store.delete(account_id)
        review_store.delete_account(account_id)
        monitor_store.delete_account(account_id)
        radar_store.delete_account(account_id)
        result = workspace_store.delete_account(account_id)
        publisher_service.delete_account_identity(account_id)
        return result
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc
    finally:
        if reserved:
            _release_account_deletion(account_id)


@app.get("/api/accounts/{account_id}/cover-templates")
async def get_account_cover_templates(account_id: str) -> dict:
    try:
        return {"items": workspace_store.list_cover_templates(account_id)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.post("/api/accounts/{account_id}/cover-templates")
async def create_account_cover_template(account_id: str, payload: CoverTemplateRequest) -> dict:
    try:
        return workspace_store.create_cover_template(account_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.put("/api/accounts/{account_id}/cover-templates/{template_id}")
async def update_account_cover_template(account_id: str, template_id: str, payload: CoverTemplateRequest) -> dict:
    try:
        return workspace_store.update_cover_template(account_id, template_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=404 if "不存在" in str(exc) else 400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.delete("/api/accounts/{account_id}/cover-templates/{template_id}", status_code=204)
async def delete_account_cover_template(account_id: str, template_id: str) -> Response:
    try:
        workspace_store.delete_cover_template(account_id, template_id)
        return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(
            status_code=404 if "不存在" in str(exc) else 400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.get("/api/accounts/{account_id}/scripts")
async def get_account_scripts(account_id: str) -> dict:
    try:
        return {"items": await run_io(workspace_store.list_scripts, account_id)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


class ScriptImportRequest(BaseModel):
    workbenchId: str = Field(min_length=1, max_length=100)
    accountId: str = Field(min_length=1, max_length=100)
    submissionId: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=100000)
    forceNew: bool = False


@app.get("/api/script-import/info")
async def script_import_info(request: Request) -> dict:
    from .script_import import ScriptImporter
    _require_local_origin(request)
    _require_loopback_client(request)
    return {"workbenchId": await run_io(ScriptImporter(workspace_store).identity),
            "kind": "desktop" if DESKTOP else "source", "importVersion": 1, "capabilities": ["update-script-v1"],
            "accounts": await run_io(workspace_store.list_accounts)}


@app.get("/api/script-import/notifications")
async def script_import_notifications(request: Request) -> dict:
    from .script_import import ScriptImporter
    _require_local_origin(request)
    _require_loopback_client(request)
    return await run_io(ScriptImporter(workspace_store).notifications)


@app.get("/api/script-import/events")
async def script_import_events(request: Request):
    _require_local_origin(request)
    _require_loopback_client(request)
    return StreamingResponse(script_import_event_hub.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


class ScriptImportUpdateRequest(BaseModel):
    workbenchId: str = Field(min_length=1, max_length=100)
    accountId: str = Field(min_length=1, max_length=100)
    submissionId: str = Field(min_length=1, max_length=200)
    scriptId: str = Field(pattern=r"^[a-zA-Z0-9-]{1,100}$")
    expectedRevision: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(min_length=1, max_length=100000)


@app.post("/api/script-import/update")
async def update_imported_script(payload: ScriptImportUpdateRequest, request: Request) -> dict:
    from .script_import import ScriptImporter, ImportFailure
    _require_local_origin(request)
    _require_loopback_client(request)
    try:
        result = await run_io(ScriptImporter(workspace_store).update, payload.model_dump())
        script_import_event_hub.publish()
        return result
    except ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc


@app.post("/api/script-import")
async def import_external_script(payload: ScriptImportRequest, request: Request) -> dict:
    from .script_import import ScriptImporter, ImportFailure
    _require_local_origin(request)
    _require_loopback_client(request)
    try:
        result = await run_io(ScriptImporter(workspace_store).save, payload.model_dump())
        script_import_event_hub.publish()
        return result
    except ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "account_missing", "message": "目标账号不存在，请重新选择。"}) from exc


@app.post("/api/accounts/{account_id}/scripts")
async def create_blank_script(account_id: str, payload: BlankScriptRequest) -> dict:
    try:
        return workspace_store.create_blank_script(account_id, payload.title)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


def _script_workspace_payload(script: dict[str, Any]) -> dict[str, Any]:
    """Build the script/task view shared by the workspace and panel endpoints."""
    missing_task_record = False
    task = None
    if script.get("source") == "link":
        task_id = str(script.get("taskId") or "")
        try:
            task = task_store.workspace(task_id)
        except KeyError:
            missing_task_record = True
            task = {
                "taskId": task_id,
                "phase": "failed",
                "message": "关联任务记录已丢失，无法继续处理。请删除这条失效脚本后重新创建。",
                "errorCode": "task_record_missing",
                "rewriteStatus": "failed",
                "warningCode": "",
                "warningMessage": "",
                "createdAt": "",
                "updatedAt": "",
            }
    if script.get("source") == "link" and script.get("stage") == "split" and not missing_task_record:
        _schedule_safari_compatibility(str(script.get("taskId") or ""))
        _schedule_preview_poster(str(script.get("taskId") or ""))
    return {"script": script, "task": task}


async def _script_title_state_payload(script: dict[str, Any]) -> dict[str, Any]:
    """Build the title panel payload so switch and title reads stay identical."""
    source = None
    source_ready = script.get("source") != "link"
    if script.get("source") == "link":
        source = await run_io(_link_title_source, str(script.get("taskId") or ""))
        source_ready = source is not None
    title_status = await run_io(workspace_store.get_title_status, str(script.get("id") or ""))
    return {
        "state": title_status["state"],
        "source": source,
        "sourceReady": source_ready,
        "generation": title_status["generation"],
    }


@app.get("/api/scripts/{script_id}/workspace")
async def get_script_workspace(script_id: str) -> dict:
    try:
        script = await run_io(workspace_store.get_script, script_id)
        return _script_workspace_payload(script)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/scripts/{script_id}/panel-state")
async def get_script_panel_state(script_id: str) -> dict:
    """Serve the whole switch surface in one round trip: workspace, cover and title."""
    try:
        script = await run_io(workspace_store.get_script, script_id)
        payload = _script_workspace_payload(script)
        payload["coverState"] = await run_io(workspace_store.get_cover_status, script_id)
        payload["titleState"] = await _script_title_state_payload(script)
        return payload
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/rewrite-model")
async def save_script_rewrite_model(script_id: str, payload: RewriteModelRequest) -> dict:
    try:
        return workspace_store.save_selected_rewrite_model(script_id, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)}) from exc


@app.put("/api/scripts/{script_id}/content")
async def save_script_content(script_id: str, payload: ScriptContentRequest) -> dict:
    try:
        return workspace_store.save_blank_content(script_id, payload.content)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.delete("/api/scripts/{script_id}")
async def delete_script(script_id: str) -> dict[str, str]:
    try:
        script = workspace_store.get_script(script_id)
        publisher_service.prepare_script_deletion(script_id)
        if script.get("source") == "link":
            task_id = str(script.get("taskId") or "")
            await _cancel_link_script_jobs(task_id)
            try:
                task_store.delete(task_id)
            except KeyError:
                pass
            workspace_store.delete_link_task_materials(task_id)
        workspace_store.delete_script(script_id)
        review_store.unlink_script(script_id)
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc
    return {"deletedScriptId": script_id}


# ----------------------------------------------------------------------
# 拆解视频 (video breakdown): the standalone entry that used to be 链接仿写.
# ----------------------------------------------------------------------


def _breakdown_task_view(breakdown: dict[str, Any]) -> dict[str, Any]:
    """Merge one record with its live task media so the result page can render it."""
    task_id = str(breakdown.get("taskId") or "")
    task: Optional[dict[str, Any]] = None
    media_missing = False
    if task_id:
        try:
            task = task_store.workspace(task_id)
        except KeyError:
            media_missing = True
    if task is None:
        task = {
            "taskId": task_id,
            "phase": "failed",
            "message": "拆解素材已不可用，请删除这条记录后重新拆解。" if media_missing else "拆解任务尚未开始。",
            "errorCode": "task_record_missing" if media_missing else "",
            "transcript": "",
            "transcriptSegments": [],
            "waveformPeaks": [],
            "videoFile": "",
            "posterFile": "",
            "title": "",
            "author": "",
            "publishedAt": "",
            "duration": 0,
        }
    elif task.get("phase") == "complete":
        # A completed task already has the video title/author/duration metadata that
        # the record itself does not need to duplicate.
        pass
    if task.get("phase") == "failed" and task.get("source") == "upload" and task_id:
        original = task_store.get(task_id)
        staged = resolve_staged(Path(original.media_path).stem) if original.media_path else None
        if staged:
            task["retryMedia"] = {"mediaId": staged["mediaId"], "name": original.media_name or staged["name"], "durationSeconds": staged["durationSeconds"]}
    memories = workspace_store.list_memories(breakdown["accountId"]) if breakdown.get("accountId") else {"items": []}
    reference_id = next((item["id"] for item in memories["items"] if item["category"] == "reference_copy" and item.get("sourceBreakdownId") == breakdown["id"]), "")
    assets = workspace_store.list_writing_assets(breakdown["accountId"]) if breakdown.get("accountId") else {}
    saved = {item["kind"]: item["id"] for items in assets.values() for item in items if item.get("sourceBreakdownId") == breakdown["id"]}
    return {**breakdown, "writingAssetIds": saved, "referenceCopyId": reference_id, "task": task, "title": breakdown.get("title") or (task.get("title") if task.get("title") != "未命名视频" else "") or "视频标题待获取"}


@app.get("/api/accounts/{account_id}/breakdowns")
async def get_account_breakdowns(account_id: str) -> dict:
    try:
        return await run_io(workspace_store.list_breakdowns, account_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/accounts/{account_id}/breakdowns")
async def create_account_breakdown(account_id: str, payload: BreakdownCreateRequest) -> dict:
    """Create the record first, then transcribe into it through the 创作服务.

    链接来源交给平台解析；本地音视频来源引用已暂存的素材号，跳过链接解析。
    """
    share_text = (payload.shareText or "").strip()
    media_id = (payload.mediaId or "").strip()
    if bool(share_text) == bool(media_id):
        raise HTTPException(
            status_code=400,
            detail={"code": "breakdown_source_required", "message": "请粘贴视频分享链接或选择本地音视频文件。"},
        )
    staged = resolve_staged(media_id) if media_id else None
    if media_id and staged is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "media_unavailable", "message": "本地素材已不可用，请重新选择文件。"},
        )
    try:
        await run_io(workspace_store.list_breakdowns, account_id)
        business_context = await _business_context("breakdown", account_id=account_id)
        business_context["action"] = "transcribe_video"
        if staged is not None:
            task = task_store.create(
                staged["name"], source="upload", media_path=staged["path"], media_name=staged["name"],
                business_context=business_context,
            )
        else:
            task = task_store.create(share_text, source="link", business_context=business_context)
        breakdown = await run_io(
            workspace_store.create_breakdown, account_id, task.task_id,
            staged["name"] if staged is not None else share_text,
        )
    except ValueError as exc:
        message = str(exc)
        code = "configuration_required" if "配置未完成" in message else "workspace_validation_failed"
        raise HTTPException(status_code=400, detail={"code": code, "message": message}) from exc
    except KeyError as exc:
        raise _home_error(exc) from exc
    if payload.title.strip():
        breakdown = await run_io(workspace_store.rename_breakdown, breakdown["id"], payload.title.strip())
    breakdown = await run_io(workspace_store.set_breakdown_analysis_status, breakdown["id"], "pending")
    try:
        _schedule_breakdown_task(task.task_id, breakdown["id"])
    except HTTPException:
        task_store._fail(task, "task_scheduling_failed", "拆解任务启动失败，请重新拆解。")
        await run_io(workspace_store.set_breakdown_analysis_status, breakdown["id"], "idle")
        raise
    return {**breakdown, "taskId": task.task_id}


@app.get("/api/breakdowns/{breakdown_id}")
async def get_breakdown(breakdown_id: str) -> dict:
    try:
        breakdown = await run_io(workspace_store.get_breakdown, breakdown_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc
    return _breakdown_task_view(breakdown)


@app.delete("/api/breakdowns/{breakdown_id}")
async def delete_breakdown(breakdown_id: str) -> dict:
    """Delete the record only; its topic, script, and downloaded media are kept."""
    try:
        return await run_io(workspace_store.delete_breakdown, breakdown_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


_breakdown_analysis_jobs: set[str] = set()


async def _run_breakdown_analysis(breakdown_id: str) -> dict:
    # Check and claim synchronously, before the first await, on the server loop.
    if breakdown_id in _breakdown_analysis_jobs:
        raise HTTPException(status_code=409, detail={"code": "analysis_running", "message": "分析正在进行，请稍候。"})
    _breakdown_analysis_jobs.add(breakdown_id)
    started = False
    breakdown = None
    try:
        breakdown = await run_io(workspace_store.get_breakdown, breakdown_id)
        task = await run_io(task_store.workspace, str(breakdown.get("taskId") or ""))
        transcript = str(task.get("transcript") or "").strip()
        if task.get("phase") != "complete" or not transcript:
            raise ValueError("视频文案还没准备好，请等待转写完成后再分析。")
        await run_io(workspace_store.set_breakdown_analysis_status, breakdown_id, "running")
        started = True
        profile = await run_io(workspace_store.read_account_profile, str(breakdown.get("accountId") or ""))
        client = _text_service_client()
        client.business_context = await _business_context("breakdown", account_id=str(breakdown.get("accountId") or ""))
        client.business_context["action"] = "analyze_structure"
        analysis = await client.analyze_breakdown(transcript, account_profile=profile)
        return await run_io(workspace_store.save_breakdown_analysis, breakdown_id, analysis)
    except Exception as exc:
        if started or (breakdown is not None and breakdown.get("analysisStatus") == "pending"):
            message = ("尚未配置模型 API Key，请检查当前服务的本地配置后重试。"
                       if isinstance(exc, TextServiceError) and exc.code == "model_api_key_required"
                       else str(exc) if isinstance(exc, ValueError) else "拆解分析失败，请重试分析。")
            try:
                await run_io(workspace_store.set_breakdown_analysis_status, breakdown_id, "failed", error=message)
            except KeyError:
                pass  # The user may have removed this record while the model ran.
        raise
    finally:
        _breakdown_analysis_jobs.discard(breakdown_id)


@app.post("/api/breakdowns/{breakdown_id}/retry")
async def retry_breakdown(breakdown_id: str) -> dict:
    """Retry a failed 拆解 in place, reusing the saved parse result and local media.

    就地重跑同一条任务：解析已成功时不重新解析（解析费不退也不重复收）；音频素材
    只能用于一次转写，重跑会用本地已有的 MP3 重新上传后再提交。链接直链过期属于
    已清掉解析结果的情况，这时重新解析是新的按次计费。
    """
    try:
        breakdown = await run_io(workspace_store.get_breakdown, breakdown_id)
        task_id = str(breakdown.get("taskId") or "")
        if not task_id:
            raise ValueError("这条拆解没有可重试的任务，请重新拆解。")
        await run_io(task_store.reset_for_retry, task_id)
        breakdown = await run_io(workspace_store.set_breakdown_analysis_status, breakdown_id, "pending")
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc
    try:
        _schedule_breakdown_task(task_id, breakdown_id)
    except HTTPException:
        task_store._fail(task_store.get(task_id), "task_scheduling_failed", "拆解任务启动失败，请重新拆解。")
        await run_io(workspace_store.set_breakdown_analysis_status, breakdown_id, "idle")
        raise
    return _breakdown_task_view({**breakdown, "taskId": task_id})


@app.post("/api/breakdowns/{breakdown_id}/analyze")
async def analyze_breakdown(breakdown_id: str) -> dict:
    try:
        updated = await _run_breakdown_analysis(breakdown_id)
    except TextServiceError as exc:
        message = ("尚未配置模型 API Key，请检查当前服务的本地配置后重试。"
                   if exc.code == "model_api_key_required" else "拆解分析失败，请稍后重试。")
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": message}) from exc
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc
    return _breakdown_task_view(updated)


@app.post("/api/accounts/{account_id}/breakdowns/{breakdown_id}/writing-assets/{kind}")
async def collect_breakdown_writing_asset(account_id: str, breakdown_id: str, kind: str, payload: Optional[BreakdownAssetRequest] = None) -> dict:
    try:
        return await run_io(workspace_store.collect_breakdown_asset, account_id, breakdown_id, kind, payload.model_dump() if payload is not None else None)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/breakdowns/{breakdown_id}/topic")
async def create_breakdown_topic(breakdown_id: str, payload: BreakdownTopicRequest) -> dict:
    """Write the analysis into 选题库 once the operator picked a week and category."""
    try:
        breakdown = await run_io(workspace_store.get_breakdown, breakdown_id)
        analysis = breakdown.get("analysis") if isinstance(breakdown.get("analysis"), dict) else None
        if not analysis:
            raise ValueError("请先分析这条视频，再把结果加入选题。")
        account_id = str(breakdown.get("accountId") or "")
        fields = _breakdown_topic_fields(breakdown, payload)
        topic = await run_io(workspace_store.create_topic, account_id, fields)
        await run_io(workspace_store.link_breakdown_topic, breakdown_id, str(topic["id"]))
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc
    return {"topic": topic, "breakdown": await run_io(workspace_store.get_breakdown, breakdown_id)}


def _breakdown_topic_fields(
    breakdown: dict[str, Any], payload: "BreakdownTopicRequest",
) -> dict[str, Any]:
    """Map one analysis onto the existing 选题 fields without inventing new ones.

    标题与大纲以弹窗里改过的值为准；没改就回落到 `breakdown_topic_draft` 的推荐初稿，
    也就是弹窗预填的那一份。分享链接只用来取视频，不当成「准备素材」带过来：
    素材字段留空，之后由操作者自己填。
    """
    draft = workspace_store.breakdown_topic_draft(breakdown)
    return {
        "title": (payload.title.strip() or draft["title"])[:160],
        "outline": (payload.outline.strip() or draft["outline"])[:2000],
        "category": payload.category,
        "format": payload.format,
        "publishDate": payload.publishDate,
        "weekStart": payload.weekStart,
    }


async def run_task_for_breakdown(task_id: str, breakdown_id: str) -> None:
    await task_store.run(task_id, auto_rewrite=False)
    task = task_store.get(task_id)
    if task.phase != "complete":
        await run_io(workspace_store.set_breakdown_analysis_status, breakdown_id, "idle")
        return
    title = str(task_store.workspace(task_id).get("title") or "").strip()
    if title and title != "未命名视频":
        await run_io(workspace_store.rename_breakdown, breakdown_id, title)
    try:
        await _run_breakdown_analysis(breakdown_id)
    except Exception:
        logger.exception("breakdown_automatic_analysis_failed breakdown_id=%s", breakdown_id)


def _schedule_breakdown_task(task_id: str, breakdown_id: str) -> None:
    runner = run_task_for_breakdown(task_id, breakdown_id)
    try:
        job = asyncio.create_task(runner)
        _link_task_jobs[task_id] = job
        job.add_done_callback(lambda completed: _forget_link_task_job(task_id, completed))
    except Exception:
        runner.close()
        logger.exception("breakdown_task_scheduling_failed task_id=%s", task_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "task_scheduling_failed", "message": "任务处理启动失败。"},
        )
@app.put("/api/scripts/{script_id}/account")
async def move_script(script_id: str, payload: ScriptAccountMoveRequest) -> dict:
    from .script_move import ScriptMoveError
    from .plugins.registry import PluginError

    def move_with_locks():
        # Acquire and release thread-owned locks in the worker, never across await.
        with _script_transition_lock(script_id):
            script = workspace_store.get_script(script_id)
            source_account_id = str(script.get("accountId") or "")
            with _account_deletion_lock:
                _ensure_accounts_available_for_move(source_account_id, payload.targetAccountId)
                publisher_service.prepare_script_move(script_id)
                return _get_script_move_service().move(script_id, payload.targetAccountId)

    try:
        return await asyncio.to_thread(move_with_locks)
    except ScriptMoveError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except PluginError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/title")
async def save_script_title(script_id: str, payload: ScriptTitleRequest) -> dict:
    try:
        return workspace_store.rename_blank_script(script_id, payload.title)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/scripts/{script_id}/cover-state")
async def get_script_cover_state(script_id: str) -> dict:
    try:
        status = await run_io(workspace_store.get_cover_status, script_id)
        for item in (status.get("generation") or {}).get("aspects", []):
            if item.get("status") == "submitted" and item.get("imageTaskId"):
                _start_cover_generation_recovery(script_id, item["jobId"])
        return status
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/cover-state")
async def save_script_cover_state(script_id: str, payload: CoverStateRequest) -> dict:
    try:
        state = _sanitize_cover_state(payload.state)
        return {"state": await run_io(workspace_store.save_cover_state, script_id, state)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.get("/api/scripts/{script_id}/publish-assets")
def get_script_publish_assets(script_id: str) -> dict:
    try:
        return workspace_store.get_publish_assets(script_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.api_route("/api/scripts/{script_id}/publish-assets/preview/{kind}", methods=["GET", "HEAD"])
def get_publish_asset_preview(script_id: str, kind: str, request: Request, playback: bool = False) -> Response:
    if kind not in {"video", "portrait", "landscape"}:
        raise HTTPException(status_code=404, detail="预览素材不存在")
    try:
        assets = workspace_store.get_publish_assets(script_id)
        aspect = "3:4" if kind == "portrait" else "4:3"
        asset = assets.get("video") if kind == "video" else assets.get("covers", {}).get(aspect)
        if asset:
            directory = publish_assets_store._safe_asset_dir(script_id, create=False).resolve()
            source = directory / Path(asset["path"]).name
            if source.is_symlink() or source.resolve().parent != directory:
                raise ValueError("素材路径无效")
        elif kind != "video":
            source = publish_assets_store._generated_cover_path(aspect, workspace_store.get_cover_state(script_id))
            # Generated previews must also stay within the managed download root.
            root = publish_assets_store._public_files_dir.resolve()
            if source is not None and (source.is_symlink() or not source.resolve().is_relative_to(root)):
                raise ValueError("素材路径无效")
        else:
            source = None
        if source is None or not source.is_file():
            raise ValueError("素材不存在")
        if kind == "video":
            if playback:
                media_type = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(source.suffix.lower())
                if media_type is None:
                    raise ValueError("视频格式无效")
                response = _video_file_response(source, request, media_type)
                response.headers["Cache-Control"] = "no-store"
                return response
            source = ensure_publish_preview_poster(source)
        elif source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("素材格式无效")
        return FileResponse(source, headers={"Cache-Control": "no-store"})
    except (ValueError, OSError, PublisherError) as exc:
        raise HTTPException(status_code=404, detail="预览不可用") from exc
    except subprocess.SubprocessError as exc:
        raise HTTPException(status_code=503, detail="预览不可用") from exc


@app.post("/api/scripts/{script_id}/publish-assets/reconcile-generated-covers")
def reconcile_script_publish_assets(script_id: str) -> dict:
    try:
        return _reconcile_generated_publish_covers(script_id)
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/publish-assets")
async def save_script_publish_assets(
    script_id: str,
    video: Optional[UploadFile] = File(default=None),
    portrait: Optional[UploadFile] = File(default=None),
    landscape: Optional[UploadFile] = File(default=None),
    videoPath: Optional[str] = Form(default=None),
    videoName: Optional[str] = Form(default=None),
    portraitPath: Optional[str] = Form(default=None),
    portraitName: Optional[str] = Form(default=None),
    landscapePath: Optional[str] = Form(default=None),
    landscapeName: Optional[str] = Form(default=None),
) -> dict:
    staging_directory: Path | None = None
    try:
        await run_io(workspace_store.get_script, script_id)
        current_assets = await run_io(workspace_store.get_publish_assets, script_id)
        if video is None and videoPath is None and current_assets.get("video"):
            videoPath = current_assets["video"]["path"]
            videoName = current_assets["video"]["name"]
        cover_state = await run_io(workspace_store.get_cover_state, script_id)
        generated_urls = _successful_generated_cover_urls(cover_state)
        # Preserve manual uploads when no generated default exists. Explicit
        # paths from the editor retain manual choices even with generated covers.
        current_covers = current_assets.get("covers", {})
        current_sources = current_assets.get("coverSources", {})
        if portrait is None and portraitPath is None and "3:4" not in generated_urls and current_sources.get("3:4", {}).get("type") == "manual":
            portraitPath = current_covers["3:4"]["path"]
            portraitName = current_covers["3:4"]["name"]
        if landscape is None and landscapePath is None and "4:3" not in generated_urls and current_sources.get("4:3", {}).get("type") == "manual":
            landscapePath = current_covers["4:3"]["path"]
            landscapeName = current_covers["4:3"]["name"]
        cover_sources = _cover_sources_for_publish_save(
            current_assets,
            cover_state,
            portrait_uploaded=portrait is not None,
            portrait_path=portraitPath,
            landscape_uploaded=landscape is not None,
            landscape_path=landscapePath,
        )
        asset_directory = await run_io(
            publish_assets_store._safe_asset_dir, script_id, create=True
        )
        staging_directory = asset_directory / f".incoming-{uuid.uuid4()}"
        staging_directory.mkdir()
        video_source = (
            await _stage_publish_upload(
                video, videoPath, videoName, staging_directory, "video", script_id
            )
            if video is not None or videoPath is not None
            else None
        )
        portrait_source = (
            await _stage_publish_upload(
                portrait,
                portraitPath,
                portraitName,
                staging_directory,
                "portrait",
                script_id,
            )
            if portrait is not None or portraitPath is not None
            else None
        )
        landscape_source = (
            await _stage_publish_upload(
                landscape,
                landscapePath,
                landscapeName,
                staging_directory,
                "landscape",
                script_id,
            )
            if landscape is not None or landscapePath is not None
            else None
        )
        save_task = asyncio.create_task(
            run_generation(
                _save_staged_publish_assets,
                script_id,
                video_source,
                portrait_source,
                landscape_source,
                cover_sources,
                staging_directory,
            )
        )
        staging_directory = None
        try:
            return await asyncio.shield(save_task)
        except asyncio.CancelledError:
            try:
                await save_task
            except Exception:
                pass
            raise
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_publish_asset_upload", "message": str(exc)},
        ) from exc
    finally:
        if staging_directory is not None and staging_directory.is_dir():
            shutil.rmtree(staging_directory)


# 插件受控媒体根目录；宿主“采用为发布素材”只接受此目录下的相对引用。
_PLUGIN_MEDIA_ROOT = DATA_ROOT / "workspace" / "plugins"


class PublishAdoptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media: str = Field(min_length=1, max_length=1024)
    replace: bool = False


def _resolve_plugin_media_reference(media: str) -> Path:
    """把插件登记的本地媒体相对路径解析成受控目录内的真实文件。

    只允许位于 workspace/plugins 之下、非符号链接、且为受支持的视频格式与体积。
    """
    relative = Path(media)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise HTTPException(400, detail={"code": "invalid_media_reference", "message": "发布素材引用无效。"})
    plugins_root = _PLUGIN_MEDIA_ROOT.resolve()
    candidate = plugins_root / relative
    try:
        resolved = candidate.resolve()
        resolved.relative_to(plugins_root)
    except ValueError:
        raise HTTPException(400, detail={"code": "invalid_media_reference", "message": "发布素材引用无效。"}) from None
    if candidate.is_symlink() or not resolved.is_file():
        raise HTTPException(404, detail={"code": "media_missing", "message": "本地视频不存在，请先生成并保存。"})
    if resolved.suffix.lower() not in _PUBLISH_VIDEO_EXTENSIONS:
        raise HTTPException(400, detail={"code": "media_type_unsupported", "message": "仅支持视频格式的发布素材。"})
    size = resolved.stat().st_size
    if size <= 0 or size > _PUBLISH_VIDEO_MAX_BYTES:
        raise HTTPException(400, detail={"code": "media_too_large", "message": "视频超出发布素材大小限制。"})
    return resolved


@app.post("/api/scripts/{script_id}/publish-assets/adopt")
async def adopt_publish_media(script_id: str, payload: PublishAdoptRequest,
                              account_id: str = Depends(plugin_registry.account_dependency)) -> dict:
    """通用宿主能力：把插件登记的本地媒体采用为该脚本的发布视频。

    宿主不感知任何供应商；插件只提交受控目录下的相对引用。已有发布视频时必须
    由调用方显式确认替换，避免静默覆盖。
    """
    try:
        script = await run_io(workspace_store.get_script, script_id)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc
    source = _resolve_plugin_media_reference(payload.media)
    if script.get("accountId") != account_id or not plugin_registry.owns_media(payload.media):
        raise HTTPException(404, detail={"code": "media_not_found", "message": "素材不存在或不属于当前工作台。"})
    current = await run_io(workspace_store.get_publish_assets, script_id)
    if isinstance(current.get("video"), Mapping) and current["video"].get("path") and not payload.replace:
        raise HTTPException(
            409,
            detail={"code": "publish_video_exists", "message": "该脚本已有发布视频，请确认是否替换。"},
        )

    def _adopt() -> dict:
        with _publish_assets_save_lock:
            # 只替换视频：封面文件原地保留，避免把已存在的封面再复制到自己身上。
            assets = dict(workspace_store.get_publish_assets(script_id))
            asset_dir = publish_assets_store._safe_asset_dir(script_id, create=True)
            destination = asset_dir / f"video{source.suffix.lower()}"
            if destination.is_symlink():
                raise PublisherError("unsafe_asset_path", "发布素材路径不安全。")
            shutil.copy2(source, destination)
            assets["video"] = {
                "name": source.name,
                "path": (Path("scripts") / script_id / "publish-assets" / destination.name).as_posix(),
            }
            return workspace_store.save_publish_assets(script_id, assets)

    try:
        return await run_io(_adopt)
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc


# Generic plugin services are shared by owned registries, including already-loaded ones.
async def _plugin_adopt_video(account_id, script_id, media):
    with plugin_registry.account_scope(account_id):
        return await adopt_publish_media(script_id, PublishAdoptRequest(media=media, replace=True), account_id)

from app.plugin_assistant import PluginAssistantService
plugin_registry.services.update({
    "assistant": lambda: PluginAssistantService(AssistantManager(workspace_store._workspace_dir)),
    "adopt_video": _plugin_adopt_video,
})


class PublishIdentityRefreshRequest(BaseModel):
    reason: Literal["initial", "manual"] = "manual"


@app.post("/api/accounts/{account_id}/publish-identity")
def refresh_account_publish_identity(account_id: str, payload: PublishIdentityRefreshRequest) -> dict:
    try:
        with _account_deletion_lock:
            if account_id in _accounts_being_deleted:
                raise ValueError("账号正在删除，请稍后再试。")
            workspace_store.validate_publish_platform(account_id, "douyin")
        return publisher_service.refresh_account_identity(account_id, "douyin", initial=payload.reason == "initial")
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc


@app.get("/api/accounts/{account_id}/publish-identity")
def get_account_publish_identity(account_id: str) -> dict:
    try:
        workspace_store.validate_publish_platform(account_id, "douyin")
        return publisher_service.account_identity(account_id, "douyin")
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc


@app.get("/api/accounts/{account_id}/publish-status")
def get_account_publish_status(account_id: str, platform: str) -> dict:
    try:
        workspace_store.validate_publish_platform(account_id, platform)
        return _normalize_login_response(publisher_service.check_login(account_id, platform), platform)
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.post("/api/accounts/{account_id}/publish-login")
def open_account_publish_login(account_id: str, payload: PublishPlatformRequest) -> dict:
    try:
        workspace_store.validate_publish_platform(account_id, payload.platform)
        return _normalize_login_response(
            publisher_service.open_login(account_id, payload.platform),
            payload.platform,
        )
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.post("/api/scripts/{script_id}/publish-fill")
def start_script_publish_fill(script_id: str, payload: PublishPlatformRequest) -> dict:
    try:
        with _script_transition_lock(script_id):
            script = workspace_store.get_script(script_id)
            account_id = str(script.get("accountId") or "")
            workspace_store.validate_publish_platform(account_id, payload.platform)
            try:
                assets = workspace_store.get_publish_assets(script_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={
                    "code": "publish_assets_required", "message": f"发布素材关联无效，请重新选择素材：{exc}",
                }) from exc
            covers = assets.get("covers") or {}
            missing_assets = []
            for label, asset in (("视频", assets.get("video")), ("3:4 封面", covers.get("3:4")), ("4:3 封面", covers.get("4:3"))):
                try:
                    if not isinstance(asset, dict) or not asset.get("path"):
                        raise ValueError("未关联")
                    workspace_store.resolve_publish_asset_path(script_id, asset["path"])
                except (ValueError, OSError):
                    missing_assets.append(label)
            if missing_assets:
                raise HTTPException(status_code=400, detail={
                    "code": "publish_assets_required",
                    "message": f"请补充或重新关联{'、'.join(missing_assets)}。",
                })
            try:
                draft = workspace_store.get_publish_draft(script_id, payload.platform)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "publish_draft_required", "message": str(exc)},
                ) from exc
            login = publisher_service.check_login(account_id, payload.platform)
            if not isinstance(login, dict) or login.get("status") != "logged_in":
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "publish_login_required",
                        "message": "请先完成平台登录并确认登录状态。",
                    },
                )
            return _normalize_publish_task(
                publisher_service.start_fill(
                    account_id,
                    script_id,
                    payload.platform,
                    draft,
                    assets,
                )
            )
    except PublisherError as exc:
        _raise_publisher_error(exc)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.get("/api/publish-tasks/{task_id}")
def get_publish_task(task_id: str) -> dict:
    try:
        return _normalize_publish_task(publisher_service.get_task(task_id))
    except PublisherError as exc:
        _raise_publisher_error(exc)


@app.get("/api/accounts/{account_id}/review")
async def get_account_review(account_id: str) -> dict[str, Any]:
    """复盘页首屏：作品列表、汇总口径、采集设置和可选项。"""
    try:
        platform = _review_platform_for_account(account_id)
        overview = await run_io(review_store.overview, account_id)
        scripts = await run_io(workspace_store.list_scripts, account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc
    overview["platform"] = platform
    overview["identity"] = await run_io(publisher_service.account_identity, account_id, platform)
    overview["options"] = review_options()
    overview["trend"] = await run_io(
        review_store.trend,
        account_id,
        days=REVIEW_TREND_DEFAULT_DAYS,
        scope=REVIEW_TREND_DEFAULT_SCOPE,
    )
    origins = await run_io(_review_origin_map, account_id, overview.get("works") or [])
    overview["factors"] = await run_io(
        review_store.factor_overview,
        account_id,
        dimension=REVIEW_FACTOR_DEFAULT_DIMENSION,
        metric=REVIEW_FACTOR_DEFAULT_METRIC,
        days=REVIEW_FACTOR_DEFAULT_RANGE_DAYS,
        origins=origins,
    )
    overview["factorCatalog"] = await run_io(_review_factor_catalog, account_id)
    overview["pendingFactorWorks"] = await run_io(review_store.pending_factor_works, account_id)
    overview["daily"] = await run_io(review_store.daily_view, account_id)
    # 排队任务可能尚未写入 running，不能让前端误判结束而停止轮询。
    with _review_jobs_lock:
        job = _review_jobs.get(account_id)
        if job is not None and not job.done():
            overview["config"]["running"] = True
    overview["linkOptions"] = {
        "scripts": [
            {"id": str(script.get("id") or ""), "title": str(script.get("title") or "")}
            for script in scripts
        ]
    }
    return overview


@app.put("/api/accounts/{account_id}/review/config")
async def save_account_review_config(account_id: str, payload: ReviewConfigRequest) -> dict[str, Any]:
    try:
        _review_platform_for_account(account_id, payload.platform)
        return await run_io(
            review_store.save_config,
            account_id,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.post("/api/accounts/{account_id}/review/collect")
async def start_account_review_collection(account_id: str, scope: Optional[Literal["recent30"]] = None) -> dict[str, Any]:
    """手动同步：不等定时设置，立即用该账号的专用浏览器采集一次。"""
    try:
        platform = _review_platform_for_account(account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    outcome = (_start_review_collection(account_id, trigger="manual", scope_override=scope)
               if scope else _start_review_collection(account_id, trigger="manual"))
    if outcome == "running":
        raise HTTPException(
            status_code=409,
            detail={"code": "review_collection_running", "message": "该账号正在采集，请稍候。"},
        )
    if outcome != "started":
        raise HTTPException(
            status_code=503,
            detail={"code": "review_collection_unavailable", "message": "采集暂时无法启动。"},
        )
    return {"accountId": account_id, "platform": platform, "status": "queued", "message": "已开始采集。"}


@app.get("/api/review/works/{work_id}")
async def get_review_work(work_id: str) -> dict[str, Any]:
    return await run_io(_review_work_or_404, work_id)


@app.put("/api/review/works/{work_id}/note")
async def save_review_work_note(work_id: str, payload: ReviewNoteRequest) -> dict[str, Any]:
    try:
        result = await run_io(
            review_store.save_note,
            work_id,
            note=payload.note,
            reviewed=payload.reviewed,
        )
        await run_io(_remember_review_onboarding, result["accountId"])
        return result
    except ValueError as exc:
        status_code = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail={"code": "review_note_failed", "message": str(exc)}) from exc


@app.put("/api/review/works/{work_id}/script")
async def link_review_work_script(work_id: str, payload: ReviewScriptLinkRequest) -> dict[str, Any]:
    """关联作品与原脚本；只允许关联同一账号下的脚本。"""
    work = await run_io(_review_work_or_404, work_id)
    account_id = str(work.get("accountId") or "")
    script_id = payload.scriptId.strip()
    if script_id:
        try:
            script = await run_io(workspace_store.get_script, script_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "review_script_not_found", "message": "脚本不存在。"},
            ) from exc
        if str(script.get("accountId") or "") != account_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "review_script_account_mismatch", "message": "只能关联当前账号下的脚本。"},
            )
    return await run_io(review_store.link_script, work_id, script_id)


@app.post("/api/review/works/{work_id}/topic-draft")
async def build_review_topic_draft(work_id: str, payload: ReviewTopicRequest) -> dict[str, Any]:
    """返回选题表单的预填内容；真正的保存仍由运营在选题页确认。"""
    work = await run_io(_review_work_or_404, work_id)
    return {"workId": work_id, "fields": build_manual_topic_fields(work, week_start=payload.weekStart)}


@app.post("/api/review/works/{work_id}/experience")
async def queue_review_experience(work_id: str) -> dict[str, Any]:
    """把复盘笔记存成待确认经验；确认之前不参与后续写作。"""
    work = await run_io(_review_work_or_404, work_id)
    note = str(work.get("note") or "").strip()
    if not note:
        raise HTTPException(
            status_code=400,
            detail={"code": "review_note_required", "message": "先写下复盘笔记，再沉淀为候选经验。"},
        )
    evidence = (
        f"来源作品：{work.get('title')}（{work.get('publishedText')}，"
        f"采集于 {work.get('collectedAt')}）"
    )[:600]
    result = await run_io(
        workspace_store.queue_pending_experience,
        str(work.get("accountId") or ""),
        node="content",
        text=note,
        evidence=evidence,
    )
    return {
        "workId": work_id,
        **result,
        "message": "已存为待确认经验，确认后才会用于后续写作。",
    }


@app.post("/api/review/works/{work_id}/suggest")
async def suggest_review_work(work_id: str) -> dict[str, Any]:
    """AI 辅助复盘：只用真实指标与已关联脚本，且不自动覆盖人工笔记。"""
    work = await run_io(_review_work_or_404, work_id)
    script: Optional[dict[str, Any]] = None
    script_id = str(work.get("scriptId") or "")
    if script_id:
        try:
            script = await run_io(workspace_store.get_script, script_id)
        except (ValueError, KeyError):
            script = None
    profile = await run_io(workspace_store.read_account_profile, str(work.get("accountId") or ""))
    metrics = work.get("metrics") if isinstance(work.get("metrics"), dict) else {}
    context: dict[str, Any] = {
        "work": {
            "title": work.get("title"),
            "publishedAt": work.get("publishedText"),
            "kind": work.get("kind"),
            "durationSeconds": work.get("durationSeconds"),
            "collectedAt": work.get("collectedAt"),
        },
        "metrics": {key: value for key, value in metrics.items() if value is not None},
        "missingMetrics": [key for key, value in metrics.items() if value is None],
        "snapshots": [
            {
                "collectedAt": item.get("collectedAt"),
                "metrics": {
                    key: value for key, value in (item.get("metrics") or {}).items() if value is not None
                },
            }
            for item in (work.get("snapshots") or [])[-10:]
        ],
        "manualNote": str(work.get("note") or ""),
        "accountProfile": {key: value for key, value in (profile or {}).items() if value},
    }
    if script is not None:
        context["script"] = {
            "title": str(script.get("title") or "")[:200],
            "content": str(script.get("content") or "")[:4000],
        }
    try:
        client = _text_service_client()
        client.business_context = await _business_context("review", account_id=str(work.get("accountId") or ""))
        client.business_context["action"] = "review_video"
        suggestions = await client.review_work(context)
    except TextServiceError as exc:
        status_code = 400 if exc.code == "model_api_key_required" else 503
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from exc
    return {
        "workId": work_id,
        "suggestions": suggestions,
        "scriptLinked": script is not None,
        "collectedAt": work.get("collectedAt"),
    }


@app.get("/api/accounts/{account_id}/review/trend")
async def get_account_review_trend(account_id: str, days: int = 30, scope: str = "account") -> dict[str, Any]:
    """每日播放与吸粉趋势：口径是抖音后台自己的逐日报表。"""
    try:
        _review_platform_for_account(account_id)
        return await run_io(review_store.trend, account_id, days=days, scope=scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)}) from exc


@app.get("/api/accounts/{account_id}/review/trend/day")
async def get_account_review_trend_day(account_id: str, date: str = "") -> dict[str, Any]:
    """某一天的账号总量与已采集作品明细。"""
    try:
        _review_platform_for_account(account_id)
        return await run_io(review_store.day_contributions, account_id, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "review_day_invalid", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)}) from exc

@app.get("/api/accounts/{account_id}/review/factors")
async def get_account_review_factors(
    account_id: str,
    dimension: str = "hook",
    metric: str = "median",
    days: int = 30,
) -> dict[str, Any]:
    """内容因子分组比较：统一用发布日起 7 个自然日的官方日数据。"""
    try:
        _review_platform_for_account(account_id)
        works = await run_io(review_store.list_works, account_id)
        origins = await run_io(_review_origin_map, account_id, works)
        return await run_io(
            review_store.factor_overview,
            account_id,
            dimension=dimension,
            metric=metric,
            days=days,
            origins=origins,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)}) from exc


@app.get("/api/review/works/{work_id}/factors")
async def get_review_work_factors(work_id: str) -> dict[str, Any]:
    """单条作品的因子编辑数据：现有快照、关联脚本候选和可选项。"""
    work = await run_io(_review_work_or_404, work_id)
    account_id = str(work.get("accountId") or "")
    stored = await run_io(review_store.work_factors, work_id)
    scripts, topics = await _review_script_and_topic_lookups(account_id)
    candidates = _review_script_candidates(account_id, work, scripts=scripts, topics=topics)
    return {
        **stored,
        "catalog": await run_io(_review_factor_catalog, account_id),
        "candidates": {key: value for key, value in candidates.items() if key != "scriptContent"},
        "hasScriptContent": bool(candidates.get("scriptContent")),
        "work": {
            "id": work["id"],
            "title": work.get("title"),
            "publishedText": work.get("publishedText"),
            "kind": work.get("kind"),
            "platform": work.get("platform"),
            "scriptId": work.get("scriptId"),
        },
    }


@app.put("/api/review/works/{work_id}/factors")
async def save_review_work_factors(work_id: str, payload: ReviewFactorRequest) -> dict[str, Any]:
    """保存人工核对后的因子快照；不反向修改脚本或分类库。"""
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"code": "review_factor_empty", "message": "没有需要保存的因子。"})
    try:
        return await run_io(review_store.save_work_factors, work_id, fields, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "review_factor_invalid", "message": str(exc)}) from exc


@app.post("/api/review/works/{work_id}/factors/suggest")
async def suggest_review_work_factors(work_id: str, payload: ReviewFactorSuggestRequest) -> dict[str, Any]:
    """按需生成因子建议：默认用关联脚本的创作选择，AI 模式按最终稿匹配现有分类。"""
    work = await run_io(_review_work_or_404, work_id)
    account_id = str(work.get("accountId") or "")
    scripts, topics = await _review_script_and_topic_lookups(account_id)
    candidates = _review_script_candidates(account_id, work, scripts=scripts, topics=topics)
    if payload.mode == "script":
        return {
            "workId": work_id,
            "mode": "script",
            "suggestions": {key: candidates[key] for key in ("topic", "hook", "structure") if candidates.get(key)},
            "origin": candidates["origin"],
            "candidateSource": candidates["source"],
            "scriptTitle": candidates["scriptTitle"],
        }
    catalog = await run_io(_review_factor_catalog, account_id)
    catalog_names = {
        "topic": [item["name"] for item in catalog["topic"]],
        "hook": [item["name"] for item in catalog["hook"]],
        "structure": [item["name"] for item in catalog["structure"]],
    }
    content = str(candidates.get("scriptContent") or "").strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "review_factor_draft_required",
                "message": "这条作品还没有最终稿，先关联写好的脚本，或手动补标分类。",
            },
        )
    context = {
        "work": {
            "title": work.get("title"),
            "publishedAt": work.get("publishedText"),
            "kind": work.get("kind"),
        },
        "finalDraft": content[:6000],
        "candidateSource": candidates["source"],
    }
    try:
        client = _text_service_client()
        client.business_context = await _business_context("review", account_id=account_id)
        client.business_context["action"] = "suggest_factors"
        suggestions = await client.suggest_factors(context, catalog=catalog_names)
    except TextServiceError as exc:
        status_code = 400 if exc.code == "model_api_key_required" else 503
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from exc
    return {
        "workId": work_id,
        "mode": "ai",
        "suggestions": suggestions,
        "origin": candidates["origin"],
        "candidateSource": candidates["source"],
        "scriptTitle": candidates["scriptTitle"],
    }


@app.post("/api/accounts/{account_id}/review/factors/suggest")
async def suggest_account_review_factors(account_id: str, payload: ReviewFactorSuggestRequest) -> dict[str, Any]:
    """批量列出待确认作品及其脚本候选，供「补全作品因子」逐条核对。"""
    try:
        _review_platform_for_account(account_id)
        pending = await run_io(review_store.pending_factor_works, account_id)
        scripts, topics = await _review_script_and_topic_lookups(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)}) from exc
    items = []
    for work in pending:
        candidates = _review_script_candidates(account_id, work, scripts=scripts, topics=topics)
        items.append({
            **work,
            "suggestions": {key: candidates[key] for key in ("topic", "hook", "structure") if candidates.get(key)},
            "origin": candidates["origin"],
            "candidateSource": candidates["source"],
            "scriptTitle": candidates["scriptTitle"],
            "hasScriptContent": bool(str(candidates.get("scriptContent") or "").strip()),
        })
    return {
        "accountId": account_id,
        "mode": payload.mode,
        "pending": items,
        "catalog": await run_io(_review_factor_catalog, account_id),
    }


@app.get("/api/review/covers/{account_id}/{name}")
async def get_review_cover(account_id: str, name: str) -> FileResponse:
    path = review_store.cover_file(account_id, name)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "review_cover_not_found", "message": "封面不存在。"},
        )
    return FileResponse(path)


@app.delete("/api/publish-tasks/{task_id}")
def dismiss_publish_task(task_id: str) -> dict[str, str]:
    try:
        publisher_service.dismiss_task(task_id)
        return {"taskId": str(task_id)[:200], "status": "dismissed"}
    except PublisherError as exc:
        _raise_publisher_error(exc)


@app.get("/api/scripts/{script_id}/title-state")
async def get_script_title_state(script_id: str) -> dict:
    try:
        script = await run_io(workspace_store.get_script, script_id)
        return await _script_title_state_payload(script)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


async def run_title_generation_job(
    script_id: str,
    job_id: str,
    *,
    title: str,
    topics: list[str],
    system_prompt: str,
    business_context: Optional[dict[str, str]] = None,
) -> None:
    try:
        client = _text_service_client()
        client.business_context = dict(business_context or {})
        candidates_by_platform = await client.generate_titles(
            title=title,
            topics=topics,
            system_prompt=system_prompt,
        )
        await run_io(workspace_store.complete_title_generation, script_id, job_id, candidates_by_platform)
    except TextServiceError as exc:
        logger.exception("title_generation_failed script_id=%s job_id=%s code=%s", script_id, job_id, exc.code)
        await run_io(
            workspace_store.fail_title_generation,
            script_id,
            job_id,
            code="title_generation_failed",
            message=_model_failure_message(exc, "标题生成失败，已保留现有结果。"),
        )
    except Exception:
        logger.exception("title_generation_unexpected_error script_id=%s job_id=%s", script_id, job_id)
        await run_io(
            workspace_store.fail_title_generation,
            script_id,
            job_id,
            code="title_generation_failed",
            message=_model_failure_message(exc, "标题生成失败，已保留现有结果。"),
        )
    finally:
        _title_generation_jobs.pop(job_id, None)


@app.post("/api/scripts/{script_id}/title-generate")
async def generate_script_titles(script_id: str) -> dict:
    try:
        script = await run_io(workspace_store.get_script, script_id)
        title_input = _title_generation_input(script)
        if title_input is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "title_source_pending", "message": "标题和话题尚未准备好，请稍候。"},
            )
        title, topics = title_input
        settings = load_settings()
        job_id = uuid.uuid4().hex
        generation = await run_io(workspace_store.start_title_generation, script_id, job_id)
        _title_generation_jobs[job_id] = asyncio.create_task(
            run_title_generation_job(
                script_id,
                job_id,
                title=title,
                topics=topics,
                system_prompt=settings.title_rewrite_system_prompt,

                business_context=await _script_business_context(script, "generate_title"),
            )
        )
        return Response(
            content=json.dumps({"generation": generation}, ensure_ascii=False),
            status_code=202,
            media_type="application/json",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        if "正在生成" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "title_generation_conflict", "message": str(exc)},
            ) from exc
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/scripts/{script_id}/title-selection")
async def select_script_title(script_id: str, payload: TitleSelectionRequest) -> dict:
    try:
        return {"state": workspace_store.select_title_candidate(script_id, payload.platform, payload.candidateId)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/publish-draft")
async def save_script_publish_draft(script_id: str, payload: PublishDraftRequest) -> dict:
    try:
        return {"state": workspace_store.save_publish_draft(
            script_id,
            payload.platform,
            title=payload.title,
            short_title=payload.shortTitle,
            description=payload.description,
            topics=payload.topics,
        )}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.post("/api/scripts/{script_id}/publish-draft/restore-selected-title")
async def restore_selected_title_to_publish_draft(script_id: str, payload: RestoreSelectedTitleRequest) -> dict:
    try:
        return {"state": workspace_store.restore_selected_title_to_publish_draft(script_id, payload.platform)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/scripts/{script_id}/writing-state")
async def get_script_writing_state(script_id: str) -> dict:
    try:
        script = await run_io(workspace_store.get_script, script_id)
        account_id = str(script.get("accountId") or "")
        memory = await run_io(workspace_store.read_account_memory, account_id)
        status = await run_io(workspace_store.get_writing_status, script_id)
        return {
            "state": status["state"],
            "generation": status["generation"],
            "source": {"ready": bool(_writing_transcript(script))},
            "prompts": {
                "structure": memory["structure"]["prompt"],
                "content": memory["content"]["prompt"],
            },
            "profile": await run_io(workspace_store.read_account_profile, account_id),
            "memory": memory,
            "selections": await run_io(workspace_store.get_memory_selections, script_id),
            "experiences": await run_io(workspace_store.list_memory_experiences, account_id),
            "referenceCopies": [item for item in (await run_io(workspace_store.list_memories, account_id))["items"] if item["category"] == "reference_copy"],
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/scripts/{script_id}/memory-selections")
async def get_script_memory_selections(script_id: str) -> dict:
    try:
        return await run_io(workspace_store.get_memory_selections, script_id)
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


@app.put("/api/scripts/{script_id}/memory-selections")
async def save_script_memory_selections(script_id: str, payload: MemorySelectionRequest) -> dict:
    """按篇保存选中的个人经历；只影响这一条脚本的后续生成。"""
    try:
        return await run_io(workspace_store.save_memory_selections, script_id,
            payload.experienceIds if "experienceIds" in payload.model_fields_set else None,
            payload.referenceCopyIds if "referenceCopyIds" in payload.model_fields_set else None)
    except (KeyError, ValueError) as exc:
        raise _account_or_value_error(exc) from None


async def run_writing_generation_job(
    script_id: str,
    job_id: str,
    *,
    node: str,
    system_prompt: str,
    account_profile: dict[str, str],
    memory_preferences: list[str],
    anti_similarity: bool = True,
    transcript: str = "",
    topic: str = "",
    sections: list[dict[str, str]] | None = None,
) -> None:
    try:
        client = _text_service_client()
        if node == "structure":
            structure = await client.analyze_structure(
                transcript,
                system_prompt=system_prompt,
                account_profile=account_profile,
                memory_preferences=memory_preferences,
            )
            await run_io(
                workspace_store.complete_writing_generation,
                script_id, job_id, node="structure", structure=structure,
            )
        else:
            content = await client.write_content(
                topic=topic,
                sections=sections or [],
                system_prompt=system_prompt,
                anti_similarity=anti_similarity,
                account_profile=account_profile,
                memory_preferences=memory_preferences,
            )
            await run_io(
                workspace_store.complete_writing_generation,
                script_id, job_id, node="content", content=content,
            )
    except TextServiceError as exc:
        logger.exception("writing_generation_failed script_id=%s job_id=%s code=%s", script_id, job_id, exc.code)
        await run_io(
            workspace_store.fail_writing_generation,
            script_id,
            job_id,
            code=exc.code,
            message=_model_failure_message(exc, "脚本生成失败，已保留现有结果。"),
        )
    except Exception:
        logger.exception("writing_generation_unexpected_error script_id=%s job_id=%s", script_id, job_id)
        await run_io(
            workspace_store.fail_writing_generation,
            script_id,
            job_id,
            code="writing_generation_failed",
            message="脚本生成失败，已保留现有结果。",
        )
    finally:
        _writing_generation_jobs.pop(job_id, None)


@app.post("/api/scripts/{script_id}/writing-generate")
async def generate_script_writing(script_id: str, payload: WritingGenerateRequest) -> Response:
    try:
        script = await run_io(workspace_store.get_script, script_id)
        if not _has_writing_source(script):
            raise ValueError("这条脚本还没有可用的原视频文案，先从「拆解视频」加入选题。")
        account_id = str(script.get("accountId") or "")
        node = payload.node
        account_profile = await run_io(workspace_store.read_account_profile, account_id)
        memory = await run_io(workspace_store.read_account_memory, account_id)
        unavailable = _memory_unavailable_message(memory)
        if unavailable:
            raise HTTPException(
                status_code=409, detail={"code": "memory_unavailable", "message": unavailable}
            )
        memory_preferences = [
            item["text"] for item in memory[node]["preferences"]
        ]
        task_kwargs: dict[str, Any] = {}
        if node == "structure":
            transcript = _writing_transcript(script)
            if not transcript:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "writing_transcript_pending", "message": "原视频文案尚未准备好，请稍候。"},
                )
            task_kwargs["transcript"] = transcript
        else:
            structure = (await run_io(workspace_store.get_writing_state, script_id))["structure"]
            if not structure or not structure.get("topic") or not structure.get("sections"):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "writing_structure_pending", "message": "请先生成脚本结构，再编写脚本内容。"},
                )
            task_kwargs["topic"] = structure["topic"]
            task_kwargs["sections"] = structure["sections"]
            # 个人经历只用于内容写作，按篇选择后追加到本次内容提示词。
            selections = await run_io(workspace_store.get_memory_selections, script_id)
            experiences = await _applied_experiences(account_id, selections["experienceIds"])
            reference_copies = await _applied_reference_copies(account_id, selections["referenceCopyIds"])
            memory_preferences = memory_preferences + [
                f"（个人经历）{item['text']}" for item in experiences["items"]
            ]
            reference_block = reference_copy_section(reference_copies)
            if reference_block:
                memory_preferences.append(reference_block)
        settings = load_settings()
        prompt = await run_io(
            workspace_store.record_writing_prompt, account_id, node, payload.prompt, payload.antiSimilarity
        )
        job_id = uuid.uuid4().hex
        generation = await run_io(workspace_store.start_writing_generation, script_id, job_id, node)
        _writing_generation_jobs[job_id] = asyncio.create_task(
            run_writing_generation_job(
                script_id,
                job_id,
                node=node,
                system_prompt=prompt,
                account_profile=account_profile,
                memory_preferences=memory_preferences,
                anti_similarity=payload.antiSimilarity,

                **task_kwargs,
            )
        )
        return Response(
            content=json.dumps({"generation": generation}, ensure_ascii=False),
            status_code=202,
            media_type="application/json",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        if "正在生成" in str(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "writing_generation_conflict", "message": str(exc)},
            ) from exc
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


def _assistant_manager() -> AssistantManager:
    return AssistantManager(workspace_store._workspace_dir)


class AssistantConfigurationRequest(BaseModel):
    selectDefault: bool = True
    agent: Literal["codex", "workbuddy"]
    path: str = Field(default="", max_length=2000)


@app.get("/api/writing-assistants")
async def writing_assistant_status(request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    try:
        return await run_io(_assistant_manager().status)
    except AssistantError as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/writing-assistants/choose")
async def choose_writing_assistant(payload: AssistantConfigurationRequest, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    try:
        return await run_io(_assistant_manager().choose_app, payload.agent)
    except AssistantError as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/writing-assistants/configure")
async def configure_writing_assistant(payload: AssistantConfigurationRequest, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    try:
        async with _writing_agent_lock:
            return await run_io(_assistant_manager().configure, payload.agent, payload.path, select_default=payload.selectDefault)
    except AssistantError as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/writing-assistants/test")
async def test_writing_assistant(request: Request, agent: Optional[Literal["codex", "workbuddy"]] = None) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    async with _writing_agent_lock:
        try:
            endpoint = _writing_agent_endpoint(request, "")
            return await run_io(_assistant_manager().create_probe, endpoint, agent=agent)
        except AssistantError as exc:
            raise _writing_agent_error(exc) from None


async def _launch_writing_task(script_id: str, task_id: str, context: str, request: Request, *, agent: str | None = None) -> dict:
    manager = _assistant_manager()
    descriptor = workspace_store.writing_agent_descriptor_path(task_id)
    try:
        await run_io(workspace_store.create_writing_agent_task, script_id, task_id=task_id,
                     endpoint=_writing_agent_endpoint(request, task_id), token=secrets.token_urlsafe(32),
                     context=context, assistant_id=manager.ready(agent)["id"])
        script_import_event_hub.publish()
        prepared = await run_io(manager.prepare, descriptor, context, agent=agent)
        await run_io(manager.launch, prepared, agent=agent)
    except (AssistantError, OSError) as exc:
        # A draft may already exist even when persisting the task failed. Always preserve it.
        task = await run_io(workspace_store.get_writing_agent_task, script_id)
        retryable = bool(task and task.get("taskId") == task_id and descriptor.exists())
        return {"opened": False, "scriptId": script_id, "taskId": task_id if retryable else None,
                "retryable": retryable,
                "message": str(exc) if isinstance(exc, AssistantError) else "脚本已保留，但无法写入启动文件。请检查目录权限后重试。"}
    return {"opened": True, "scriptId": script_id, "taskId": task_id,
            "message": f"已请求打开 {prepared['assistantName']}，请检查预填内容并手动发送；定稿后再回传工作台。"}


@app.post("/api/scripts/{script_id}/writing-agent/{task_id}/retry")
async def retry_writing_assistant(script_id: str, task_id: str, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    async with _writing_agent_lock:
        try:
            script = await run_io(workspace_store.get_script, script_id)
            if (script.get("writingAgentTask") or {}).get("taskId") != task_id:
                raise ValueError("此任务已失效，请重新生成。")
            descriptor = workspace_store.writing_agent_descriptor_path(task_id)
            data = await run_io(read_assistant_json, descriptor)
            manager = _assistant_manager()
            if data.get("assistantId") != manager.ready()["id"]:
                raise AssistantError("请切回此任务的原助手后重试，或重新生成。")
            prepared = await run_io(manager.prepare, descriptor, data["context"])
            await run_io(manager.launch, prepared)
            return {"opened": True, "scriptId": script_id, "taskId": task_id,
                    "message": "已重新请求打开助手，请检查预填内容并手动发送。"}
        except (AssistantError, PermissionError, KeyError, ValueError) as exc:
            raise _writing_agent_error(exc) from None


@app.post("/api/scripts/{script_id}/writing-agent")
async def open_script_writing_agent(script_id: str, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    if _writing_agent_lock.locked():
        raise HTTPException(status_code=409, detail={"message": "正在打开助手，请勿重复点击。"})
    async with _writing_agent_lock:
        try:
            await run_io(_assistant_manager().ready)
            script = await run_io(workspace_store.get_script, script_id)
            account_id = script["accountId"]
            profile = await run_io(workspace_store.read_account_profile, account_id)
            memory = await run_io(workspace_store.read_account_memory, account_id)
            unavailable = _memory_unavailable_message(memory)
            if unavailable:
                raise HTTPException(
                    status_code=409, detail={"code": "memory_unavailable", "message": unavailable}
                )
            selections = await run_io(workspace_store.get_memory_selections, script_id)
            experiences = await _applied_experiences(account_id, selections["experienceIds"])
            reference_copies = await _applied_reference_copies(account_id, selections["referenceCopyIds"])
            if _has_writing_source(script):
                status = await run_io(workspace_store.get_writing_status, script_id)
                state = status["state"]
                structure = state.get("structure")
                if not structure or not structure.get("topic") or not structure.get("sections"):
                    raise HTTPException(status_code=409, detail={"message": "请先生成并保存脚本结构。"})
                if (status.get("generation") or {}).get("status") == "running":
                    raise HTTPException(status_code=409, detail={"message": "脚本正在生成，请完成后再打开助手。"})
                transcript = await run_io(_writing_transcript, script)
                if not transcript:
                    raise HTTPException(status_code=409, detail={"message": "原视频文案尚未准备好，请稍候。"})
                base_prompt = build_writing_agent_prompt(
                    state=state, profile=profile, memory=memory, transcript=transcript,
                    experiences=experiences["items"], reference_copies=reference_copies,
                )
            else:
                creation = script.get("creation") if isinstance(script.get("creation"), dict) else {}
                base_prompt = build_draft_agent_prompt(
                    creation=creation,
                    profile=profile,
                    memory=memory,
                    descriptor_path="",
                    script_title=str(script.get("title") or ""),
                    existing_content=str(script.get("content") or ""),
                    experiences=experiences["items"], reference_copies=reference_copies,
                )
            task_id = str(uuid.uuid4())
            return await _launch_writing_task(script_id, task_id, base_prompt, request)
        except AssistantError as exc:
            raise _writing_agent_error(exc) from None
        except CodexAgentError as exc:
            raise HTTPException(status_code=503, detail={"code": "writing_agent_open_failed", "message": str(exc)}) from None
        except KeyError:
            raise HTTPException(status_code=404, detail={"message": "脚本或账号不存在。"}) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from None


@app.put("/api/scripts/{script_id}/writing-structure")
async def save_script_writing_structure(script_id: str, payload: SaveWritingStructureRequest) -> dict:
    try:
        return {"state": workspace_store.save_writing_structure(script_id, payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=409 if "正在生成" in str(exc) else 400,
                            detail={"code": "writing_structure_save_failed", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404,
                            detail={"code": "workspace_not_found", "message": str(exc)}) from exc


@app.put("/api/scripts/{script_id}/writing-content")
async def save_script_writing_content(script_id: str, payload: SaveWritingContentRequest) -> dict:
    try:
        return {"state": workspace_store.save_writing_content(script_id, payload.content)}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/scripts/{script_id}/writing-prompt")
async def save_script_writing_prompt(script_id: str, payload: WritingPromptRequest) -> dict:
    """Persist one node's prompt for the script's account without starting a generation."""
    try:
        script = workspace_store.get_script(script_id)
        # The prompt is stored per account + node, and the script is only the entry point
        # that resolves the account. The 编辑 stage configures it for scripts that have no
        # 编写 stage at all, and the same value feeds their Agent组装内容.
        account_id = str(script.get("accountId") or "")
        prompt = workspace_store.record_writing_prompt(
            account_id, payload.node, payload.prompt, payload.antiSimilarity
        )
        return {"node": payload.node, "prompt": prompt, "antiSimilarity": payload.antiSimilarity}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.post("/api/scripts/{script_id}/writing-memory")
async def save_script_writing_memory(script_id: str, payload: WritingMemoryRequest) -> dict:
    try:
        script = workspace_store.get_script(script_id)
        account_id = str(script.get("accountId") or "")
        node = payload.node
        state = workspace_store.get_writing_state(script_id)
        if node == "structure":
            structure = state.get("structure")
            if not structure or not structure.get("sections"):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "writing_memory_empty", "message": "当前环节还没有可沉淀的结构内容。"},
                )
            text = _writing_structure_memory_text(structure)
        else:
            text = str(state.get("content") or "").strip()
            if not text:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "writing_memory_empty", "message": "当前环节还没有可沉淀的脚本内容。"},
                )
        rule = payload.rule.strip()
        if not rule or rule == text.strip():
            raise ValueError("请填写可复用的写作规则，不要直接保存整篇结构或正文。")
        preferences = workspace_store.append_writing_memory(account_id, node, rule)
        return {"node": node, "preferences": preferences}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/scripts/{script_id}/stage")
async def update_script_stage(script_id: str, payload: ScriptStageRequest) -> dict:
    try:
        if payload.stage == "split":
            raise ValueError("拆片已经移到「拆解视频」模块。")
        if payload.stage == "write":
            # 编写 needs the reference transcript, which a 拆解视频 topic carries.
            script = workspace_store.get_script(script_id)
            if not await run_io(_writing_transcript, script):
                raise ValueError("这条脚本还没有可用的原视频文案，先从「拆解视频」加入选题。")
        return workspace_store.update_stage(script_id, payload.stage)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/scripts/{script_id}/workflow-status")
async def update_script_workflow_status(script_id: str, payload: ScriptWorkflowStatusRequest) -> dict:
    try:
        return workspace_store.update_workflow_status(script_id, payload.workflowStatus)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.get("/api/accounts/{account_id}/topics")
async def get_account_topics(account_id: str) -> dict:
    try:
        return await run_io(workspace_store.list_topics, account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc


@app.post("/api/accounts/{account_id}/topics")
async def create_account_topic(account_id: str, payload: TopicCreateRequest) -> dict:
    try:
        return workspace_store.create_topic(account_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.patch("/api/topics/{topic_id}")
async def update_topic(topic_id: str, payload: TopicUpdateRequest) -> dict:
    try:
        return workspace_store.update_topic(topic_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.delete("/api/topics/{topic_id}", status_code=204)
async def delete_topic(topic_id: str):
    try:
        workspace_store.delete_topic(topic_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.put("/api/accounts/{account_id}/topic-plans/{week_start}")
async def save_account_topic_plan(account_id: str, week_start: str, payload: TopicPlanRequest) -> dict:
    try:
        return workspace_store.save_topic_plan(account_id, week_start, payload.targets.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.post("/api/accounts/{account_id}/topic-plans/{week_start}/confirm")
async def confirm_account_topic_plan(account_id: str, week_start: str) -> dict:
    try:
        return workspace_store.confirm_topic_plan(account_id, week_start)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


@app.post("/api/topics/{topic_id}/script")
async def create_topic_script(topic_id: str) -> dict:
    try:
        return workspace_store.create_script_from_topic(topic_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc


def _home_error(exc: Exception) -> HTTPException:
    """Map the 首页 store errors onto the workspace error contract."""
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": str(exc)})
    return HTTPException(status_code=400, detail={"code": "workspace_validation_failed", "message": str(exc)})


def _remember_review_onboarding(account_id: str) -> None:
    # Optional guidance must not turn a successful collection/note save into a failure.
    try:
        workspace_store.onboarding_view(account_id, review_store.list_works(account_id))
    except ValueError:
        logger.info("onboarding_review_account_unavailable account=%s", account_id)
    except Exception:
        logger.exception("onboarding_review_refresh_failed account=%s", account_id)


def _account_onboarding_view(account_id: str) -> dict:
    works = review_store.list_works(account_id)
    sources = {"keywordIds": radar_store.account_keyword_ids(account_id),
               "bloggerIds": monitor_store.account_blogger_ids(account_id)}
    result = workspace_store.onboarding_view(account_id, works, content_sources=sources)
    result["collection"] = review_store.get_config(account_id)
    return result


@app.get("/api/accounts/{account_id}/onboarding")
async def get_account_onboarding(account_id: str) -> dict:
    try:
        return await run_io(_account_onboarding_view, account_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.put("/api/accounts/{account_id}/onboarding")
async def save_account_onboarding(account_id: str, payload: OnboardingRequest) -> dict:
    try:
        await run_io(workspace_store.save_onboarding, account_id, payload.model_dump(exclude_none=True))
        return await run_io(_account_onboarding_view, account_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.get("/api/accounts/{account_id}/home")
async def get_account_home(account_id: str, today: str = "", weekStart: str = "") -> dict:
    try:
        return await run_io(
            workspace_store.home_overview,
            account_id,
            today=today or None,
            week_start=weekStart or None,
        )
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.get("/api/accounts/{account_id}/home/tasks")
async def get_account_home_tasks(
    account_id: str,
    scope: str = "pending",
    page: int = 1,
    pageSize: int = 8,
    today: str = "",
) -> dict:
    try:
        return await run_io(
            workspace_store.list_home_tasks,
            account_id,
            scope=scope,
            page=page,
            page_size=pageSize,
            today=today or None,
        )
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/accounts/{account_id}/manual-tasks")
async def create_account_manual_task(account_id: str, payload: ManualTaskCreateRequest) -> dict:
    try:
        return await run_io(workspace_store.create_manual_task, account_id, payload.model_dump())
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.patch("/api/manual-tasks/{task_id}")
async def update_manual_task(task_id: str, payload: ManualTaskUpdateRequest) -> dict:
    try:
        return await run_io(workspace_store.update_manual_task, task_id, payload.model_dump(exclude_unset=True))
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.delete("/api/manual-tasks/{task_id}", status_code=204)
async def delete_manual_task(task_id: str):
    try:
        await run_io(workspace_store.delete_manual_task, task_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.get("/api/accounts/{account_id}/inspirations")
async def get_account_inspirations(account_id: str) -> dict:
    try:
        return await run_io(workspace_store.list_inspirations, account_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/accounts/{account_id}/inspirations")
async def create_account_inspiration(account_id: str, payload: InspirationCreateRequest) -> dict:
    try:
        return await run_io(workspace_store.create_inspiration, account_id, payload.model_dump())
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.patch("/api/inspirations/{inspiration_id}")
async def update_inspiration(inspiration_id: str, payload: InspirationUpdateRequest) -> dict:
    try:
        return await run_io(workspace_store.update_inspiration, inspiration_id, payload.model_dump(exclude_unset=True))
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.delete("/api/inspirations/{inspiration_id}", status_code=204)
async def delete_inspiration(inspiration_id: str):
    try:
        await run_io(workspace_store.delete_inspiration, inspiration_id)
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/inspirations/{inspiration_id}/topic")
async def convert_inspiration_to_topic(inspiration_id: str, payload: InspirationConvertRequest) -> dict:
    try:
        return await run_io(workspace_store.convert_inspiration, inspiration_id, payload.model_dump())
    except (ValueError, KeyError) as exc:
        raise _home_error(exc) from exc


@app.post("/api/tasks")
async def create_task(payload: TaskRequest) -> dict:
    """Start one download/transcription task without attaching it to any record.

    The 拆解视频 flow creates its own record first and then calls task_store through
    the breakdown endpoint, so this route never writes a script any more.
    """
    try:
        task = task_store.create(payload.shareText)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "configuration_required", "message": str(exc)}) from exc
    asyncio.create_task(task_store.run(task.task_id))
    return task.public_view()


@app.post("/api/scripts/{script_id}/retry")
async def retry_script_task(script_id: str) -> dict:
    try:
        existing_script = workspace_store.get_script(script_id)
        if existing_script.get("source") != "link":
            raise ValueError("只有链接脚本可以重试。")
        if existing_script.get("processingStatus") != "failed":
            raise ValueError("仅可重试处理失败的链接脚本。")
        share_text = str(existing_script.get("shareText") or "").strip()
        if not share_text:
            raise ValueError("该历史链接脚本未保存原分享链接，无法重试。")
        task = task_store.create(share_text)
        task.rewrite_system_prompt = workspace_store.get_account_rewrite_prompt(str(existing_script.get("accountId") or ""))
        script = workspace_store.retry_link_script(script_id, task.task_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc

    _schedule_link_task(task.task_id, script["id"])
    return {**task.public_view(), "scriptId": script["id"], "script": script}


@app.delete("/api/scripts/{script_id}/task")
async def delete_failed_script_task(script_id: str) -> dict:
    try:
        script = workspace_store.get_script(script_id)
        if script.get("source") != "link":
            raise ValueError("只有链接脚本可以删除任务。")
        task_id = str(script.get("taskId") or "")
        task_failed = False
        try:
            task_failed = task_store.get(task_id).phase == "failed"
        except KeyError:
            # A persisted failed script can outlive its task record after a restart.
            pass
        if script.get("processingStatus") != "failed" and not task_failed:
            raise ValueError("仅可删除处理失败的链接脚本。")
        if task_failed and script.get("processingStatus") != "failed":
            workspace_store.mark_link_script(script_id, "failed")
        await _cancel_link_script_jobs(task_id)
        try:
            task_store.delete_failed(task_id)
        except KeyError:
            # A failed task can exist without a task directory after a server restart.
            pass
        workspace_store.delete_failed_link_script(script_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "workspace_validation_failed", "message": str(exc)},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc
    return {"deletedScriptId": script_id}


def _schedule_link_task(task_id: str, script_id: str) -> None:
    runner = run_task_for_script(task_id, script_id)
    try:
        job = asyncio.create_task(runner)
        _link_task_jobs[task_id] = job
        job.add_done_callback(lambda completed: _forget_link_task_job(task_id, completed))
    except Exception as exc:
        runner.close()
        workspace_store.mark_link_script(script_id, "failed")
        logger.exception("linked_task_scheduling_failed task_id=%s", task_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "task_scheduling_failed", "message": "任务处理启动失败。"},
        ) from exc


def _forget_link_task_job(task_id: str, completed: asyncio.Task) -> None:
    if _link_task_jobs.get(task_id) is completed:
        _link_task_jobs.pop(task_id, None)


async def _cancel_link_script_jobs(task_id: str) -> None:
    jobs = [
        _link_task_jobs.pop(task_id, None),
        _safari_compatibility_jobs.pop(task_id, None),
        _preview_poster_jobs.pop(task_id, None),
    ]
    active_jobs = [job for job in jobs if job is not None and not job.done()]
    for job in active_jobs:
        job.cancel()
    if active_jobs:
        await asyncio.gather(*active_jobs, return_exceptions=True)


def _schedule_local_media_recovery(task_id: str) -> None:
    """Resume local-only media work only when the completed task media still exists."""
    try:
        task = task_store.get(task_id)
    except KeyError:
        return
    if task.phase != "complete" or task.directory is None or not task.directory.is_dir():
        return
    source_path = task.directory / "video.mp4"
    if not source_path.is_file():
        source_path = next(
            (path for path in sorted(task.directory.glob("*.mp4")) if not path.name.endswith(".safari.mp4")),
            None,
        )
    if source_path is None or not source_path.is_file():
        return
    _schedule_safari_compatibility(task_id)
    _schedule_preview_poster(task_id)


def _resume_pending_creation_tasks() -> None:
    """继续查询已提交给创作服务的转写任务。

    工作台关闭期间平台仍在推进任务，重启后按已保存的平台任务号继续查询，
    既不新建任务、也不会产生第二笔消费。
    """
    resumed = 0
    for task_id in task_store.resumable_platform_tasks():
        if task_id in _link_task_jobs:
            continue
        try:
            job = asyncio.create_task(task_store.run(task_id, auto_rewrite=False))
        except Exception:
            logger.exception("creation_task_resume_failed task_id=%s", task_id)
            continue
        _link_task_jobs[task_id] = job
        job.add_done_callback(lambda completed, tid=task_id: _forget_link_task_job(tid, completed))
        resumed += 1
    if resumed:
        logger.info("creation_tasks_resumed_on_startup count=%s", resumed)


def _schedule_safari_compatibility(task_id: str) -> None:
    existing = _safari_compatibility_jobs.get(task_id)
    if existing and not existing.done():
        return

    async def convert() -> None:
        try:
            task = await run_io(task_store.get, task_id)
            source_path = task.directory / "video.mp4" if task.directory else None
            if source_path and not source_path.is_file():
                source_path = next(
                    (path for path in sorted(task.directory.glob("*.mp4")) if not path.name.endswith(".safari.mp4")),
                    None,
                )
            if source_path and source_path.is_file():
                result = await run_generation(ensure_safari_compatible, source_path)
                if result.status == "failed":
                    logger.warning("safari_compatibility_failed task_id=%s reason=%s", task_id, result.reason)
        except Exception:
            logger.exception("safari_compatibility_unexpected_error task_id=%s", task_id)
        finally:
            _safari_compatibility_jobs.pop(task_id, None)

    _safari_compatibility_jobs[task_id] = asyncio.create_task(convert())


def _schedule_preview_poster(task_id: str) -> None:
    existing = _preview_poster_jobs.get(task_id)
    if existing and not existing.done():
        return

    async def extract() -> None:
        try:
            task = await run_io(task_store.get, task_id)
            source_path = task.directory / "video.mp4" if task.directory else None
            if source_path and not source_path.is_file():
                source_path = next(
                    (path for path in sorted(task.directory.glob("*.mp4")) if not path.name.endswith(".safari.mp4")),
                    None,
                )
            if source_path and source_path.is_file():
                result = await run_generation(ensure_preview_poster, source_path)
                if result.status == "failed":
                    logger.warning("preview_poster_failed task_id=%s reason=%s", task_id, result.reason)
        except Exception:
            logger.exception("preview_poster_unexpected_error task_id=%s", task_id)
        finally:
            _preview_poster_jobs.pop(task_id, None)

    _preview_poster_jobs[task_id] = asyncio.create_task(extract())


async def _start_automatic_script_structure(script_id: str) -> None:
    """Start once after extraction, independently of the browser and legacy rewrites."""
    job_id = uuid.uuid4().hex
    reserved = False
    try:
        script = await run_io(workspace_store.get_script, script_id)
        transcript = await run_io(_writing_transcript, script)
        if not transcript:
            return
        account_id = script["accountId"]
        memory = await run_io(workspace_store.read_account_memory, account_id)
        profile = await run_io(workspace_store.read_account_profile, account_id)
        settings = load_settings()
        generation = await run_io(
            workspace_store.start_writing_generation, script_id, job_id, "structure", only_if_empty=True,
        )
        if generation is None:
            return
        reserved = True
        _writing_generation_jobs[job_id] = asyncio.create_task(run_writing_generation_job(
            script_id, job_id, node="structure", transcript=transcript,
            system_prompt=memory["structure"]["prompt"], account_profile=profile,
            memory_preferences=[item["text"] for item in memory["structure"]["preferences"]],

        ))
    except Exception:
        # A structure failure must never turn successful transcription into a failed download.
        logger.exception("automatic_structure_start_failed script_id=%s", script_id)
        if reserved:
            await run_io(workspace_store.fail_writing_generation, script_id, job_id,
                         code="writing_generation_failed", message="自动生成结构启动失败，请点击生成重试。")


async def run_task_for_script(task_id: str, script_id: str) -> None:
    await task_store.run(task_id)
    task = task_store.get(task_id)
    if task.phase == "complete":
        title = str(task_store.workspace(task_id).get("title") or "未命名视频")
        await _start_automatic_script_structure(script_id)
        workspace_store.mark_link_script(script_id, "ready", title)
    else:
        workspace_store.mark_link_script(script_id, "failed")


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    try:
        task = await run_io(task_store.get, task_id)
        return task.public_view()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "未找到该任务。"}) from exc


@app.get("/api/tasks/{task_id}/workspace")
async def get_task_workspace(task_id: str) -> dict:
    try:
        return await run_io(task_store.workspace, task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "未找到该任务。"}) from exc


@app.post("/api/tasks/{task_id}/rewrite")
async def regenerate_task_rewrite(task_id: str, payload: RewriteRequest) -> dict:
    try:
        return await task_store.rewrite(task_id, payload.systemPrompt, payload.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "未找到该任务。"}) from exc
    except ValueError as exc:
        status = 409 if "正在生成" in str(exc) else 400
        raise HTTPException(status_code=status, detail={"code": "rewrite_conflict" if status == 409 else "transcript_required", "message": str(exc)}) from exc
    except Exception:
        logger.exception("rewrite_request_failed task_id=%s", task_id)
        raise HTTPException(status_code=502, detail={"code": "rewrite_failed", "message": "仿写生成失败，已保留原稿。"})


@app.put("/api/tasks/{task_id}/rewrite")
async def save_task_rewrite(task_id: str, payload: SaveRewriteRequest) -> dict:
    try:
        return task_store.save_rewrite(task_id, payload.content, payload.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "未找到该任务。"}) from exc
    except ValueError as exc:
        status = 409 if "正在生成" in str(exc) else 400
        raise HTTPException(status_code=status, detail={"code": "rewrite_conflict" if status == 409 else "rewrite_save_failed", "message": str(exc)}) from exc


_COVER_RATIO_ASPECTS = {"portrait": ["3:4"], "landscape": ["4:3"], "both": ["3:4", "4:3"]}


def _cover_image_extension(url: str) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"


@app.post("/api/scripts/{script_id}/cover-title-generate")
async def generate_cover_title(script_id: str) -> Response:
    try:
        script = await run_io(workspace_store.get_script, script_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "workspace_not_found", "message": str(exc)},
        ) from exc
    title = _cover_title_source(script)
    if title is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "cover_title_source_required", "message": "请先在标题阶段生成并确认发布标题。"},
        )
    active_job_id = cover_title_jobs_by_script.get(script_id)
    if active_job_id and cover_title_jobs.get(active_job_id, None) and cover_title_jobs[active_job_id].status == "running":
        raise HTTPException(
            status_code=409,
            detail={"code": "cover_title_generation_conflict", "message": "封面标题正在生成，请稍候。"},
        )
    job_id = uuid.uuid4().hex
    await run_io(workspace_store.start_cover_title_generation, script_id, job_id)
    job = CoverTitleJobRecord(job_id=job_id, script_id=script_id)
    _register_cover_title_job(job)
    _cover_title_job_tasks[job_id] = asyncio.create_task(
        run_cover_title_job(job_id, title,
                            business_context=await _script_business_context(script, "generate_cover_title"))
    )
    return Response(
        content=json.dumps({"jobId": job_id, "status": "running"}, ensure_ascii=False),
        status_code=202,
        media_type="application/json",
    )


@app.get("/api/cover-title-jobs/{job_id}")
async def get_cover_title_job(job_id: str) -> dict:
    job = cover_title_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "cover_title_job_not_found", "message": "未找到该生成任务。"})
    return {"jobId": job.job_id, "status": job.status, "result": job.result, "error": job.error}


@app.post("/api/cover/references")
async def upload_cover_references(payload: CoverReferenceUpload) -> dict:
    if not payload.images:
        raise HTTPException(
            status_code=400,
            detail={"code": "cover_image_required", "message": "请选择要上传的参考图。"},
        )
    upload_id = uuid.uuid4().hex[:12]
    refs_dir = DOWNLOAD_DIR / "covers-refs" / upload_id
    try:
        refs_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for index, upload in enumerate(payload.images):
            raw, content_type = _decode_cover_image(upload.data)
            extension = ".jpg" if content_type == "image/jpeg" else f".{content_type.rsplit('/', 1)[-1]}"
            name = f"{index}{extension}"
            (refs_dir / name).write_bytes(raw)
            items.append({"name": upload.name, "url": f"/api/files/covers-refs/{upload_id}/{name}"})
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "cover_reference_save_failed", "message": "参考图保存失败。"},
        ) from exc
    return {"items": items}


@dataclass
class CoverTitleJobRecord:
    job_id: str
    script_id: str
    status: str = "running"
    result: dict | None = None
    error: dict = field(default_factory=dict)


cover_title_jobs: dict[str, CoverTitleJobRecord] = {}
cover_title_jobs_by_script: dict[str, str] = {}
_COVER_TITLE_JOB_LIMIT = 100


def _register_cover_title_job(job: CoverTitleJobRecord) -> None:
    cover_title_jobs[job.job_id] = job
    cover_title_jobs_by_script[job.script_id] = job.job_id
    while len(cover_title_jobs) > _COVER_TITLE_JOB_LIMIT:
        stale_job_id, stale_job = next(iter(cover_title_jobs.items()))
        cover_title_jobs.pop(stale_job_id, None)
        if cover_title_jobs_by_script.get(stale_job.script_id) == stale_job_id:
            cover_title_jobs_by_script.pop(stale_job.script_id, None)


async def run_cover_title_job(job_id: str, title: str, *,
                              business_context: Optional[dict[str, str]] = None) -> None:
    job = cover_title_jobs[job_id]
    try:
        client = _text_service_client()
        client.business_context = dict(business_context or {})
        job.result = await client.generate_cover_titles(title=title)
        job.status = "success"
        await run_io(
            workspace_store.complete_cover_title_generation, job.script_id, job_id, job.result
        )
    except TextServiceError as exc:
        logger.exception("cover_title_generation_failed job_id=%s code=%s", job_id, exc.code)
        job.status = "failed"
        job.error = {"code": "cover_title_generation_failed", "message": "封面标题生成失败，请稍后重试。"}
        await run_io(
            workspace_store.fail_cover_title_generation,
            job.script_id, job_id, code=job.error["code"], message=job.error["message"]
        )
    except Exception:
        logger.exception("cover_title_generation_unexpected_error job_id=%s", job_id)
        job.status = "failed"
        job.error = {"code": "cover_title_generation_failed", "message": "封面标题生成失败，请稍后重试。"}
        await run_io(
            workspace_store.fail_cover_title_generation,
            job.script_id, job_id, code=job.error["code"], message=job.error["message"]
        )
    finally:
        if cover_title_jobs_by_script.get(job.script_id) == job_id:
            cover_title_jobs_by_script.pop(job.script_id, None)
        _cover_title_job_tasks.pop(job_id, None)


def _cover_output_path(script_id: str, job_id: str, aspect_ratio: str, remote_url: str) -> Path:
    short = "3x4" if aspect_ratio == "3:4" else "4x3"
    return DOWNLOAD_DIR / "covers" / script_id / job_id / f"{short}{_cover_image_extension(remote_url)}"


def _cover_output_url(script_id: str, job_id: str, aspect_ratio: str, remote_url: str) -> str:
    return f"/api/files/{_cover_output_path(script_id, job_id, aspect_ratio, remote_url).relative_to(DOWNLOAD_DIR).as_posix()}"


def _cover_output_exists(image_url: str) -> bool:
    prefix = "/api/files/"
    if not image_url.startswith(prefix):
        return False
    candidate = (DOWNLOAD_DIR / unquote(image_url[len(prefix):])).resolve()
    covers_root = (DOWNLOAD_DIR / "covers").resolve()
    return covers_root in candidate.parents and candidate.is_file()


async def _save_cover_image(
    client: CreationImageClient,
    task_id: str,
    index: int,
    aspect_ratio: str,
    *,
    script_id: str | None = None,
    job_id: str | None = None,
) -> str:
    """按任务号下载受控成果并落到现有封面目录；失败张数只影响该比例。"""
    if script_id and job_id:
        target = _cover_output_path(script_id, job_id, aspect_ratio, "")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            await client.download(task_id, index, target)
        except CreationImageError as exc:
            raise ImageError(exc.code, exc.message) from None
        except OSError as exc:
            raise ImageError("image_save_failed", "生成图片保存到本地失败。") from exc
        return f"/api/files/{target.relative_to(DOWNLOAD_DIR).as_posix()}"

    covers_dir = DOWNLOAD_DIR / "covers"
    # 非脚本级调用沿用「时间戳-比例」命名，保持既有文件命名约定。
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    short = "3x4" if aspect_ratio == "3:4" else "4x3"
    target = covers_dir / f"{stamp}-{short}{_cover_image_extension('')}"
    try:
        covers_dir.mkdir(parents=True, exist_ok=True)
        await client.download(task_id, index, target)
    except CreationImageError as exc:
        raise ImageError(exc.code, exc.message) from None
    except OSError as exc:
        raise ImageError("image_save_failed", "生成图片保存到本地失败。") from exc
    return f"/api/files/{target.relative_to(DOWNLOAD_DIR).as_posix()}"


async def _upload_cover_references(
    reference_paths: list[Path],
    client: CreationImageClient,
) -> list[str]:
    """把参考图交到创作服务换成素材号，供 image-to-image 使用，不再自行直连对象存储。"""
    upload_ids: list[str] = []
    for path in reference_paths:
        try:
            upload_ids.append(await client.upload_reference(path))
        except CreationImageError as exc:
            raise ImageError(exc.code, exc.message) from None
    return upload_ids


async def resume_cover_generation(script_id: str, job_id: str) -> None:
    generation = await run_io(workspace_store.interrupt_unsubmitted_cover_aspects, script_id, job_id)
    if not generation or generation["status"] != "running":
        return
    try:
        client = _creation_image_client()
    except ImageError:
        # Missing/expired session is not proof that the paid task failed.
        return
    await _settle_platform_cover_task(script_id, job_id, generation, client)


def _creation_image_client(settings: "AppSettings | None" = None) -> CreationImageClient:
    """封面生成统一走创作服务平台的 /workbench/v1，用当前登录用户的会话凭证。"""
    settings = settings if settings is not None else load_settings()
    return CreationImageClient.from_settings(settings, store=subscription_store)


async def _settle_platform_cover_task(
    script_id: str,
    job_id: str,
    generation: Mapping[str, Any],
    client: CreationImageClient,
) -> None:
    """结算一次封面生成：每个比例各自一个平台任务，失败张数只影响该比例。

    只结算成功张数；某个比例没有成功图片时按该张自己的错误码标记失败，
    不影响另一个比例已经生成的成品。
    """
    aspects = [
        aspect for aspect in generation.get("aspects", [])
        if aspect.get("status") == "submitted"
    ]
    succeeded: list[str] = []
    for aspect in aspects:
        ratio = str(aspect["aspect"])
        task_id = str(aspect.get("imageTaskId") or "")
        if not task_id:
            continue
        try:
            outcome = await client.await_task(task_id, ratio)
        except CreationImageError as exc:
            if not exc.terminal:
                # Keep the original task recoverable; never offer a paid resubmission.
                continue
            await run_io(
                workspace_store.fail_cover_aspect,
                script_id, job_id, ratio, code=exc.code, message=exc.message,
            )
            continue

        # 平台的成功张数只带受控地址 url（assetId 只在成果详情接口里），据此判断该比例是否出图。
        entry = next(
            (item for item in outcome.get("images", [])
             if item.get("ok") is not False and (item.get("url") or item.get("assetId"))),
            None,
        )
        if entry is None:
            failure = next((item for item in outcome.get("images", []) if item.get("ok") is False), {})
            await run_io(
                workspace_store.fail_cover_aspect,
                script_id, job_id, ratio,
                code=str(failure.get("errorCode") or "image_generation_failed"),
                message="这一张封面未生成成功，可单独重试。",
            )
            continue
        local_url = _cover_output_url(script_id, job_id, ratio, "")
        await run_io(workspace_store.reserve_cover_output, script_id, job_id, ratio, local_url)
        try:
            saved_url = await _save_cover_image(
                client, task_id, int(entry.get("index") or 0), ratio, script_id=script_id, job_id=job_id,
            )
        except ImageError as exc:
            logger.info("cover_download_pending script_id=%s job_id=%s code=%s", script_id, job_id, exc.code)
            continue
        completed = await run_io(workspace_store.complete_cover_aspect, script_id, job_id, ratio, saved_url)
        if completed is not None:
            succeeded.append(ratio)
    logger.info("cover_platform_settled script_id=%s job_id=%s succeeded=%s", script_id, job_id, succeeded)
    for ratio in succeeded:
        await run_generation(_refresh_publish_assets_after_cover_completion, script_id, ratio)


def _start_cover_generation_recovery(script_id: str, job_id: str) -> None:
    if job_id in _cover_generation_tasks and not _cover_generation_tasks[job_id].done():
        return
    task = asyncio.create_task(resume_cover_generation(script_id, job_id))
    _cover_generation_tasks[job_id] = task
    task.add_done_callback(lambda _task: _cover_generation_tasks.pop(job_id, None))


async def run_persisted_cover_generation(
    script_id: str,
    job_id: str,
    prompt: str,
    reference_paths: list[Path],
    settings,
    business_context: Optional[dict[str, str]] = None,
) -> None:
    try:
        client = _creation_image_client(settings)
        client.business_context = dict(business_context or {})
        reference_upload_ids: list[str] = []
        if reference_paths:
            reference_upload_ids = await _upload_cover_references(reference_paths, client)
        generation = await run_io(workspace_store.get_cover_generation, script_id, job_id)
        if not generation or generation["status"] != "running":
            return
        pending = [aspect["aspect"] for aspect in generation["aspects"] if aspect["status"] == "pending"]
        if not pending:
            return
        # Persist each accepted ratio before submitting another or polling results.
        for ratio in pending:
            try:
                task_ids = await client.submit(prompt, [ratio], reference_upload_ids=reference_upload_ids or None)
            except CreationImageError as exc:
                await run_io(workspace_store.fail_cover_aspect,
                             script_id, job_id, ratio, code=exc.code, message=exc.message)
                continue
            if task_ids.get(ratio):
                await run_io(workspace_store.record_cover_task, script_id, job_id, ratio, task_ids[ratio])
        refreshed = await run_io(workspace_store.get_cover_generation, script_id, job_id)
        if refreshed and refreshed["status"] == "running":
            await _settle_platform_cover_task(script_id, job_id, refreshed, client)
    except ImageError as exc:
        generation = await run_io(workspace_store.get_cover_generation, script_id, job_id)
        if generation and generation["status"] == "running":
            for aspect in generation["aspects"]:
                if aspect["status"] == "pending":
                    await run_io(
                        workspace_store.fail_cover_aspect,
                        script_id, job_id, aspect["aspect"], code=exc.code, message=exc.message,
                    )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("cover_generation_submission_failed script_id=%s job_id=%s", script_id, job_id)
        generation = await run_io(workspace_store.get_cover_generation, script_id, job_id)
        if generation and generation["status"] == "running":
            for aspect in generation["aspects"]:
                if aspect["status"] == "pending":
                    await run_io(
                        workspace_store.fail_cover_aspect,
                        script_id,
                        job_id,
                        aspect["aspect"],
                        code="cover_generation_unexpected_error",
                        message="封面生成意外中断，请重新生成。",
                    )


def _cover_reference_paths(image_urls: list[str]) -> list[Path]:
    reference_paths: list[Path] = []
    if not image_urls:
        return reference_paths
    refs_root = (DOWNLOAD_DIR / "covers-refs").resolve()
    for url in image_urls:
        path_text = unquote(url)
        prefix = "/api/files/covers-refs/"
        if not path_text.startswith(prefix):
            raise HTTPException(
                status_code=400,
                detail={"code": "cover_image_invalid", "message": "参考图地址无效。"},
            )
        resolved = (refs_root / path_text[len(prefix):]).resolve()
        if refs_root not in resolved.parents or not resolved.is_file():
            raise HTTPException(
                status_code=400,
                detail={"code": "cover_image_missing", "message": "参考图不存在，请重新上传。"},
            )
        reference_paths.append(resolved)
    return reference_paths


@app.post("/api/scripts/{script_id}/cover-generate")
async def generate_script_cover(script_id: str, payload: CoverImageRequest) -> Response:
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail={"code": "cover_prompt_required", "message": "请先填写封面提示词。"},
        )
    settings = load_settings()
    try:
        _creation_image_client()
        script = await run_io(workspace_store.get_script, script_id)
        reference_paths = await run_io(_cover_reference_paths, payload.imageUrls)
        job_id = uuid.uuid4().hex
        generation = await run_io(
            workspace_store.start_cover_generation, script_id, job_id, _COVER_RATIO_ASPECTS[payload.ratio]
        )
    except ImageError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc
    except ValueError as exc:
        status_code = 409 if "正在生成" in str(exc) else 404
        raise HTTPException(
            status_code=status_code,
            detail={"code": "cover_generation_conflict" if status_code == 409 else "workspace_not_found", "message": str(exc)},
        ) from exc

    task = asyncio.create_task(
        run_persisted_cover_generation(script_id, job_id, prompt, reference_paths, settings,
                                       business_context=await _script_business_context(script, "generate_cover"))
    )
    _cover_generation_tasks[job_id] = task
    task.add_done_callback(lambda _task: _cover_generation_tasks.pop(job_id, None))
    return Response(
        content=json.dumps({"generation": generation}, ensure_ascii=False),
        status_code=202,
        media_type="application/json",
    )


@app.delete("/api/scripts/{script_id}/cover-generation")
async def cancel_script_cover_generation(script_id: str) -> dict:
    raise HTTPException(
        status_code=409,
        detail={"code": "cover_generation_not_cancellable",
                "message": "封面提交后无法取消，请等待生成完成；可离开页面，稍后查看结果。"},
    )


@app.post("/api/cover/generate")
async def generate_cover() -> None:
    raise HTTPException(
        status_code=410,
        detail={"code": "cover_generation_endpoint_retired", "message": "请使用脚本级封面生成接口。"},
    )


@app.post("/api/downloads")
async def create_download(payload: DownloadRequest) -> dict:
    raise HTTPException(
        status_code=410,
        detail={"code": "legacy_download_retired", "message": "旧直连下载接口已停用，请使用工作台视频转文案入口。"},
    )


@app.api_route("/api/files/{file_path:path}", methods=["GET", "HEAD"])
async def get_file(file_path: str, request: Request) -> Response:
    requested_path = Path(unquote(file_path))
    download_root = DOWNLOAD_DIR.resolve()
    resolved_path = (download_root / requested_path).resolve()

    media_types = {
        ".mp4": "video/mp4",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(resolved_path.suffix.lower())
    if (
        requested_path.is_absolute()
        or ".." in requested_path.parts
        or download_root not in resolved_path.parents
        or media_type is None
        or not resolved_path.is_file()
    ):
        raise HTTPException(status_code=404, detail="文件不存在")

    file_size = resolved_path.stat().st_size
    if resolved_path.suffix.lower() != ".mp4":
        if request.method == "HEAD":
            return Response(status_code=200, media_type=media_type, headers={"Content-Length": str(file_size)})
        return FileResponse(resolved_path, media_type=media_type, filename=resolved_path.name)
    return _video_file_response(resolved_path, request, media_type)


def _video_file_response(resolved_path: Path, request: Request, media_type: str) -> Response:
    """Shared bounded byte-range streaming for public and script-owned videos."""
    file_size = resolved_path.stat().st_size
    range_header = request.headers.get("range", "").strip()
    base_headers = {"Accept-Ranges": "bytes"}
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if not match or not file_size:
            return Response(status_code=416, headers={**base_headers, "Content-Range": f"bytes */{file_size}"})

        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        elif end_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return Response(status_code=416, headers={**base_headers, "Content-Range": f"bytes */{file_size}"})
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            return Response(status_code=416, headers={**base_headers, "Content-Range": f"bytes */{file_size}"})

        if start >= file_size or start > end:
            return Response(status_code=416, headers={**base_headers, "Content-Range": f"bytes */{file_size}"})

        end = min(end, file_size - 1)
        content_length = end - start + 1

        if request.method == "HEAD":
            return Response(
                status_code=206,
                media_type=media_type,
                headers={
                    **base_headers,
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(content_length),
                },
            )

        def stream_range():
            with resolved_path.open("rb") as handle:
                handle.seek(start)
                remaining = content_length
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            stream_range(),
            status_code=206,
            media_type=media_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
            },
        )

    if request.method == "HEAD":
        return Response(
            status_code=200,
            media_type=media_type,
            headers={**base_headers, "Content-Length": str(file_size)},
        )

    return FileResponse(
        resolved_path,
        media_type=media_type,
        filename=resolved_path.name,
        headers=base_headers,
    )


# ----------------------------------------------------------------------
# 新建脚本: creation assets, 直接创建 and Agent generation tasks
# ----------------------------------------------------------------------


@app.get("/api/accounts/{account_id}/writing-assets")
async def get_writing_assets(account_id: str) -> dict:
    try:
        return await run_io(workspace_store.list_writing_assets, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "账号不存在。"}) from exc


@app.post("/api/accounts/{account_id}/writing-assets")
async def create_writing_asset(account_id: str, payload: WritingAssetRequest) -> dict:
    try:
        return await run_io(
            workspace_store.create_writing_asset, account_id, payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "账号不存在。"}) from exc


@app.patch("/api/accounts/{account_id}/writing-assets/{asset_id}")
async def update_account_writing_asset(account_id: str, asset_id: str, payload: WritingAssetUpdateRequest) -> dict:
    try:
        return await run_io(workspace_store.update_account_writing_asset, account_id, asset_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "素材或工作台不存在。"}) from exc


@app.delete("/api/accounts/{account_id}/writing-assets/{asset_id}", status_code=204)
async def delete_account_writing_asset(account_id: str, asset_id: str):
    try:
        await run_io(workspace_store.delete_account_writing_asset, account_id, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "素材或工作台不存在。"}) from exc


@app.patch("/api/writing-assets/{asset_id}")
async def update_writing_asset(asset_id: str, payload: WritingAssetUpdateRequest) -> dict:
    try:
        return await run_io(
            workspace_store.update_writing_asset, asset_id, payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "素材不存在。"}) from exc


@app.delete("/api/writing-assets/{asset_id}", status_code=204)
async def delete_writing_asset(asset_id: str):
    try:
        await run_io(workspace_store.delete_writing_asset, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "素材不存在。"}) from exc


@app.post("/api/accounts/{account_id}/scripts/draft")
async def create_script_draft(account_id: str, payload: ScriptCreationRequest) -> dict:
    try:
        return await run_io(workspace_store.create_script_draft, account_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "账号不存在。"}) from exc


@app.put("/api/scripts/{script_id}/creation")
async def save_script_creation(script_id: str, payload: ScriptCreationRequest) -> dict:
    try:
        return await run_io(workspace_store.save_script_creation, script_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "脚本不存在。"}) from exc


def _memory_unavailable_message(memory: dict[str, Any]) -> str:
    """记忆目录不可用时给出原因，而不是悄悄用空记忆继续生成。"""
    for node in ("structure", "content"):
        node_memory = memory.get(node) if isinstance(memory.get(node), dict) else {}
        message = str(node_memory.get("memoryError") or "").strip()
        if message:
            return f"记忆文件夹当前不可用：{message}"
    return ""


def _selection_warnings(selection: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    missing = [item for item in selection.get("missing") or [] if item]
    disabled = [item for item in selection.get("disabled") or [] if item]
    if missing:
        warnings.append(f"有 {len(missing)} 条已选的个人经历已被删除，请重新选择。")
    if disabled:
        warnings.append(f"有 {len(disabled)} 条已选的个人经历已被停用，本次没有使用。")
    return warnings


async def _applied_experiences(account_id: str, ids: list[str]) -> dict[str, Any]:
    selection = await run_io(workspace_store.read_memory_experiences, account_id, list(ids or []))
    return {"items": selection.get("items") or [], "warnings": _selection_warnings(selection)}


async def _applied_reference_copies(account_id: str, ids: list[str]) -> list[dict[str, Any]]:
    try:
        selection = await run_io(workspace_store.read_reference_copies, account_id, ids)
    except MemoryStoreError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from None
    if selection["missing"] or selection["disabled"]:
        raise HTTPException(status_code=409, detail={
            "code": "reference_copy_unavailable",
            "message": "已选爆款文案中有条目已停用、删除、不属于当前账号或无法读取，请重新选择后再生成。",
            "missing": selection["missing"], "disabled": selection["disabled"],
        })
    return selection["items"]


async def _assemble_draft_prompt(account_id: str, payload: WritingAgentDraftRequest) -> dict[str, Any]:
    """组装直接创建场景的提示词，并回报本次真正带入的记忆与个人经历。"""
    profile = await run_io(workspace_store.read_account_profile, account_id)
    memory = await run_io(workspace_store.read_account_memory, account_id)
    unavailable = _memory_unavailable_message(memory)
    if unavailable:
        raise HTTPException(
            status_code=409, detail={"code": "memory_unavailable", "message": unavailable}
        )
    experiences = await _applied_experiences(account_id, payload.experienceIds)
    reference_copies = await _applied_reference_copies(account_id, payload.referenceCopyIds)
    prompt = build_draft_agent_prompt(
        creation=payload.model_dump(),
        profile=profile,
        memory=memory,
        descriptor_path="",
        script_title=payload.title,
        experiences=experiences["items"], reference_copies=reference_copies,
    )
    return {
        "prompt": prompt,
        "applied": {
            "preferences": memory["content"]["preferences"],
            "experiences": experiences["items"],
            "referenceCopies": reference_copies,
        },
        "warnings": experiences["warnings"],
    }


@app.post("/api/accounts/{account_id}/writing-agent/preview")
async def preview_writing_agent_prompt(account_id: str, payload: WritingAgentDraftRequest, request: Request) -> dict:
    """Show the assembled prompt without creating a script or opening Codex."""
    _require_local_origin(request)
    try:
        assembled = await _assemble_draft_prompt(account_id, payload)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": "账号不存在。"}) from exc
    return assembled


@app.post("/api/accounts/{account_id}/writing-agent")
async def open_draft_writing_agent(
    account_id: str, payload: WritingAgentDraftRequest, request: Request,
) -> dict:
    """直接创建的 Agent生成: create/reuse the script, freeze settings, open Codex."""
    _require_loopback_client(request)
    _require_local_origin(request)
    if _writing_agent_lock.locked():
        raise HTTPException(status_code=409, detail={"message": "正在打开助手，请勿重复点击。"})
    async with _writing_agent_lock:
        try:
            await run_io(_assistant_manager().ready)
            assembled = await _assemble_draft_prompt(account_id, payload)
            script_id = str(payload.scriptId or "")
            if script_id:
                script = await run_io(workspace_store.get_script, script_id)
                if str(script.get("accountId") or "") != account_id:
                    raise ValueError("脚本不属于当前账号，请重新创建。")
                await run_io(workspace_store.save_script_creation, script_id, payload.model_dump(exclude_unset=True))
            else:
                script = await run_io(
                    workspace_store.create_script_draft, account_id, payload.model_dump(),
                )
                script_id = str(script["id"])
            base_prompt = assembled["prompt"]
            # 直接创建也要记住本篇选了哪些个人经历，回传与再次打开时保持一致。
            await run_io(workspace_store.save_memory_selections, script_id, payload.experienceIds, payload.referenceCopyIds)
            task_id = str(uuid.uuid4())
            return await _launch_writing_task(script_id, task_id, base_prompt, request)
        except (CodexAgentError, PermissionError, KeyError, ValueError) as exc:
            raise _writing_agent_error(exc) from None


async def _breakdown_rewrite_context(account_id: str, breakdown_id: str, requirements: str) -> dict:
    record = await run_io(workspace_store.get_breakdown, breakdown_id)
    if record["accountId"] != account_id:
        raise KeyError("拆解记录不属于当前账号。")
    analysis = record.get("analysis") or {}
    if record.get("analysisStatus") != "complete" or not analysis.get("sections"):
        raise HTTPException(status_code=409, detail={"message": "请等待拆解结构分析完成后再仿写。"})
    task = await run_io(task_store.workspace, record["taskId"])
    transcript = str(task.get("transcript") or "").strip()
    if task.get("phase") != "complete" or not transcript:
        raise HTTPException(status_code=409, detail={"message": "原视频文案尚未准备好，请稍后重试。"})
    title = str(record.get("title") or task.get("title") or analysis.get("topic") or "仿写脚本")
    profile = await run_io(workspace_store.read_account_positioning, account_id)
    prompt = build_breakdown_rewrite_prompt(breakdown_id=breakdown_id, title=title,
        analysis=analysis, transcript=transcript, requirements=requirements, profile=profile)
    return {"prompt": prompt, "title": title, "analysis": analysis}


@app.post("/api/accounts/{account_id}/breakdowns/{breakdown_id}/rewrite/preview")
async def preview_breakdown_rewrite(account_id: str, breakdown_id: str, payload: BreakdownRewriteRequest, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    try:
        context = await _breakdown_rewrite_context(account_id, breakdown_id, payload.requirements)
        return {"prompt": context["prompt"]}
    except (KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/accounts/{account_id}/breakdowns/{breakdown_id}/rewrite")
async def open_breakdown_rewrite(account_id: str, breakdown_id: str, payload: BreakdownRewriteRequest, request: Request) -> dict:
    _require_loopback_client(request)
    _require_local_origin(request)
    if _writing_agent_lock.locked():
        raise HTTPException(status_code=409, detail={"message": "正在打开助手，请勿重复点击。"})
    async with _writing_agent_lock:
        try:
            manager = _assistant_manager()
            await run_io(manager.ready)
            agent = (await run_io(manager.ready, payload.agentId))["id"]
            context = await _breakdown_rewrite_context(account_id, breakdown_id, payload.requirements)
            task_id = str(payload.requestId)
            descriptor = workspace_store.writing_agent_descriptor_path(task_id)
            if descriptor.exists():
                # Retrying a lost response must never create another script. A request
                # ID is tied to the exact source snapshot, requirements and assistant.
                saved = await run_io(read_assistant_json, descriptor)
                if saved.get("accountId") != account_id or saved.get("context") != context["prompt"] or saved.get("assistantId") != agent:
                    raise HTTPException(status_code=409, detail={"message": "仿写内容或助手已变化，请关闭弹窗后重新发起。"})
                script_id = saved["scriptId"]
                script = await run_io(workspace_store.get_script, script_id)
                if script.get("accountId") != account_id or (script.get("writingAgentTask") or {}).get("taskId") != task_id:
                    raise HTTPException(status_code=409, detail={"message": "此仿写任务已失效，请重新发起。"})
                prepared = await run_io(manager.prepare, descriptor, saved["context"], agent=agent)
                await run_io(manager.launch, prepared, agent=agent)
                return {"opened": True, "scriptId": script_id, "taskId": task_id,
                        "message": f"已重新请求打开 {prepared['assistantName']}，请检查预填内容并手动发送。"}
            analysis = context["analysis"]
            script = await run_io(workspace_store.create_script_draft, account_id, {
                "title": ("仿写 · " + context["title"])[:120],
                "topic": str(analysis.get("topic") or context["title"])[:200],
                "contentFormat": "video", "advanced": payload.requirements,
                "structure": (analysis.get("templates") or {}).get("structure"),
            })
            return await _launch_writing_task(script["id"], task_id, context["prompt"], request, agent=agent)
        except (AssistantError, CodexAgentError, PermissionError, KeyError, ValueError) as exc:
            raise _writing_agent_error(exc) from None


@app.get("/api/writing-return-notifications")
async def writing_return_notifications() -> dict:
    return {"items": await run_io(workspace_store.writing_return_notifications)}


@app.post("/api/writing-agent-tasks/{task_id}")
async def submit_writing_agent_return(task_id: str, payload: WritingAgentReturnRequest, request: Request) -> dict:
    """Public 定稿回传 endpoint used by the writing-workbench-return skill."""
    _require_loopback_client(request)
    token = request.headers.get("x-writing-agent-token") or ""
    try:
        if task_id.startswith("probe-"):
            return await run_io(_assistant_manager().submit_probe, task_id, token, payload.content)
        await run_io(workspace_store.verify_writing_agent_token, task_id, token)
        result = await run_io(
            workspace_store.submit_writing_agent_return, task_id, payload.model_dump(),
        )
        script_import_event_hub.publish()
        try:
            descriptor = await run_io(read_assistant_json, workspace_store.writing_agent_descriptor_path(task_id))
            agent = descriptor.get("assistantId")
            if agent in ("codex", "workbuddy"):
                await run_io(_assistant_manager().record_return, agent)
        except Exception:
            # Verification bookkeeping must never turn a completed return into a failure.
            logger.warning("writing_return_verification_failed task=%s", task_id, exc_info=False)
        return result
    except (PermissionError, KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/scripts/{script_id}/writing-return/adopt")
async def adopt_writing_return(script_id: str) -> dict:
    try:
        result = await run_io(workspace_store.adopt_writing_return, script_id)
        script_import_event_hub.publish()
        return result
    except (KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/scripts/{script_id}/writing-return/discard")
async def discard_writing_return(script_id: str) -> dict:
    try:
        return await run_io(workspace_store.discard_writing_return, script_id)
    except (KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


@app.get("/api/accounts/{account_id}/writing-pending")
async def get_writing_pending(account_id: str) -> dict:
    try:
        return await run_io(workspace_store.list_pending_experiences, account_id)
    except (KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


@app.post("/api/accounts/{account_id}/writing-pending/resolve")
async def resolve_writing_pending(account_id: str, payload: PendingExperienceResolveRequest) -> dict:
    try:
        return await run_io(
            workspace_store.resolve_pending_experiences,
            account_id, payload.ids, adopt=payload.adopt,
        )
    except (KeyError, ValueError) as exc:
        raise _writing_agent_error(exc) from None


# ----------------------------------------------------------------------
# 监控（/api/monitor）
# ----------------------------------------------------------------------


class MonitorAddBloggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareText: str = Field(min_length=1, max_length=5000)
    note: str = Field(default="", max_length=60)
    priority: bool = False
    intervalMinutes: Optional[int] = None


class MonitorFollowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=60)
    priority: Optional[bool] = None
    intervalMinutes: Optional[int] = None
    enabled: Optional[bool] = None


class MonitorSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectEnabled: Optional[bool] = None
    intervalMinutes: Optional[int] = None
    aiEnabled: Optional[bool] = None
    aiDailyTime: Optional[str] = None


class MonitorSavedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=100)
    saved: bool


class MonitorTopicRequest(BaseModel):
    """把一条 AI 建议转成正式选题；字段沿用现有选题模块的分类与周计划。"""

    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1)
    outline: str = Field(default="", max_length=2000)
    category: str = "highlight"
    format: str = "video"
    weekPlan: Literal["current", "next"] = "current"


def _monitor_http_status(exc: DataServiceError) -> int:
    if exc.status == 402 or exc.code == "data_insufficient_balance":
        return 402
    if exc.status == 429 or exc.code == "data_rate_limited":
        return 429
    if exc.code.startswith("monitor_") or exc.code in ("data_api_key_required", "data_auth_failed", "data_endpoint_missing"):
        return 400
    if exc.code == "http_client_unavailable":
        return 500
    return 502


def _raise_monitor_error(exc: DataServiceError) -> None:
    code, message = public_error(exc.code, exc.message, status=exc.status)
    raise HTTPException(status_code=_monitor_http_status(exc), detail={"code": code, "message": message}) from exc


def _monitor_week_start(plan: str) -> str:
    today = datetime.now(timezone.utc).astimezone().date()
    monday = today - timedelta(days=today.weekday())
    if str(plan) == "next":
        monday = monday + timedelta(days=7)
    return monday.isoformat()


async def _require_account(account_id: str) -> str:
    accounts = await run_io(workspace_store.list_accounts)
    if not any(str(item.get("id")) == str(account_id) for item in accounts):
        raise HTTPException(status_code=404, detail={"code": "account_not_found", "message": "账号不存在。"})
    return str(account_id)


@app.get("/api/monitor/overview")
async def monitor_overview(accountId: str) -> dict:
    await _require_account(accountId)
    view = await run_io(monitor_store.overview, accountId)
    await _attach_original_topic_states(accountId, view["recommendation"])
    return view


@app.get("/api/monitor/bloggers")
async def list_monitor_bloggers(
    accountId: str,
    keyword: str = "",
    priority: bool = False,
    date: str = "today",
    page: int = 1,
    pageSize: int = 0,
) -> dict:
    """关注的博主列表。pageSize 由调用方指定，前端每批加载 20 条，缺省时用服务端默认每页条数；
    date 跟作品动态的日期筛选同步，用于统计每位博主在该范围内的作品条数。"""
    await _require_account(accountId)
    day = date if date in MONITOR_WORK_DATE_OPTIONS else "today"
    result = await run_io(
        monitor_store.list_follows,
        accountId,
        keyword=keyword.strip()[:60],
        only_priority=priority,
        page=page,
        page_size=max(0, min(int(pageSize or 0), MONITOR_BLOGGER_PAGE_SIZE_MAX)),
        day=day,
    )


    # 提交接口先注册内存任务，落盘 running 在后台执行；这段间隙不能返回上一轮失败。
    for item in result.get("items", []):
        job = _monitor_jobs.get(item["id"])
        if job is not None and not job.done():
            item.update(status="running", lastError="", lastErrorCode="")
    return result


@app.post("/api/monitor/bloggers")
async def add_monitor_blogger(accountId: str, payload: MonitorAddBloggerRequest) -> dict:
    """解析博主身份并建立当前账号的关注；作品在后台采集，不阻塞本次请求。"""
    await _require_account(accountId)
    _require_workbench()
    try:
        # 主页链接解析只在本地完成，不需要数据接口密钥。
        sec_user_id = await resolve_creator_sec_user_id(payload.shareText)
    except DataServiceError as exc:
        _raise_monitor_error(exc)
    return await _add_monitor_blogger_serialized(accountId, payload, sec_user_id)


_monitor_author_locks = weakref.WeakValueDictionary()


async def _add_monitor_blogger_serialized(account_id, payload, sec_user_id, *, skip_existing=False):
    # Serialize all entry points for the shared author, including different accounts.
    key = (asyncio.get_running_loop(), sec_user_id)
    lock = _monitor_author_locks.setdefault(key, asyncio.Lock())
    async with lock:
        return await _add_monitor_blogger_resolved(account_id, payload, sec_user_id, skip_existing=skip_existing)


async def _add_monitor_blogger_resolved(accountId, payload, sec_user_id, *, skip_existing=False):
    existing = await run_io(monitor_store.blogger_by_sec_user, sec_user_id)
    if skip_existing and existing is not None and accountId in (existing.get("follows") or {}):
        return {"blogger": {"id": existing["id"]}, "reused": True, "alreadyFollowing": True}
    if existing is None:
        try:
            async with _monitor_sem():
                data = _data_client()
                data.business_context = await _business_context("monitor", account_id=accountId, blogger={"secUserId": sec_user_id})
                profile_result = await data.query(CAPABILITY_PROFILE, {"sec_user_id": sec_user_id})
        except PlatformDataError as exc:
            raise HTTPException(status_code=_creation_failure_status(exc), detail={"code": exc.code, "message": exc.message}) from exc
        if profile_result.get("charged"):
            await run_io(monitor_store.record_charge, "%0.2f" % float(profile_result["charged"]), 1)
        await run_io(monitor_store.record_requests, "profile", 1, account_ids=(accountId,))
        profile = normalize_douyin_user(profile_to_user((profile_result.get("page") or {}).get("profile")))
        if skip_existing and not profile.get("secUserId"):
            raise HTTPException(status_code=422, detail={"code": "monitor_author_unavailable", "message": "未能获取博主资料，请稍后重试。"})
        if profile.get("secUserId") and profile["secUserId"] != sec_user_id:
            raise HTTPException(status_code=502, detail={"code": "monitor_author_mismatch", "message": "博主身份校验失败，请稍后重试。"})
        if not profile.get("secUserId"):
            profile["secUserId"] = sec_user_id
        try:
            blogger = await run_io(monitor_store.upsert_blogger, profile, source_url=payload.shareText[:500])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "monitor_blogger_invalid", "message": str(exc)}) from exc
    else:
        blogger = existing
    blogger_id = str(blogger.get("id"))
    already = accountId in (blogger.get("follows") or {})
    try:
        blogger = await run_io(
            monitor_store.follow,
            accountId,
            blogger_id,
            note=payload.note,
            priority=payload.priority,
            interval_minutes=payload.intervalMinutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "monitor_follow_failed", "message": str(exc)}) from exc
    _start_monitor_collection(blogger_id, trigger="manual", account_id=accountId)
    view = await run_io(monitor_store.list_follows, accountId, keyword="", only_priority=False, page=1, page_size=500)
    entry = next((item for item in view["items"] if item["id"] == blogger_id), None)
    return {"blogger": entry, "reused": existing is not None, "alreadyFollowing": already}


@app.patch("/api/monitor/bloggers/{blogger_id}")
async def update_monitor_blogger(blogger_id: str, accountId: str, payload: MonitorFollowUpdateRequest) -> dict:
    await _require_account(accountId)
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"code": "monitor_nothing_to_update", "message": "没有需要更新的内容。"})
    try:
        await run_io(monitor_store.update_follow, accountId, blogger_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_follow_not_found", "message": str(exc)}) from exc
    view = await run_io(monitor_store.list_follows, accountId, keyword="", only_priority=False, page=1, page_size=500)
    return {"blogger": next((item for item in view["items"] if item["id"] == blogger_id), None)}


@app.delete("/api/monitor/bloggers/{blogger_id}")
async def remove_monitor_blogger(blogger_id: str, accountId: str) -> dict:
    await _require_account(accountId)
    try:
        await run_io(monitor_store.unfollow, accountId, blogger_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_blogger_not_found", "message": str(exc)}) from exc
    return {"removed": True}


@app.post("/api/monitor/collect")
async def collect_monitor(accountId: str, bloggerId: str = "") -> dict:
    """立即同步：手动触发不等定时，但同一博主仍然只跑一个任务。"""
    await _require_account(accountId)
    _require_workbench()
    if bloggerId:
        blogger = await run_io(monitor_store.get_blogger, bloggerId)
        if accountId not in (blogger.get("follows") or {}):
            raise HTTPException(status_code=403, detail={"code": "monitor_not_following", "message": "当前账号没有关注这位博主。"})
        outcome = _start_monitor_collection(bloggerId, trigger="manual", account_id=accountId)
        return {"started": 1 if outcome == "started" else 0, "running": 1 if outcome == "running" else 0}
    return await _start_monitor_collections_for_account(accountId, trigger="manual")


@app.get("/api/monitor/works")
async def list_monitor_works(
    accountId: str,
    bloggerId: str = "",
    filter: str = "all",
    date: str = "today",
    page: int = 1,
) -> dict:
    await _require_account(accountId)
    work_filter = filter if filter in ("all", "new", "saved") else "all"
    day = date if date in MONITOR_WORK_DATE_OPTIONS else "today"
    return await run_io(
        monitor_store.list_works,
        accountId,
        blogger_id=bloggerId,
        work_filter=work_filter,
        day=day,
        page=page,
    )


@app.get("/api/monitor/works/{work_id}")
async def get_monitor_work(work_id: str, accountId: str) -> dict:
    await _require_account(accountId)
    try:
        return await run_io(monitor_store.work_detail, work_id, accountId)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_work_not_found", "message": str(exc)}) from exc


@app.post("/api/monitor/works/{work_id}/saved")
async def save_monitor_work(work_id: str, payload: MonitorSavedRequest) -> dict:
    await _require_account(payload.accountId)
    try:
        saved = await run_io(monitor_store.set_saved, payload.accountId, work_id, payload.saved)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_work_not_found", "message": str(exc)}) from exc
    return {"id": str(work_id), "saved": saved}


@app.get("/api/monitor/recommendations")
async def get_monitor_recommendations(accountId: str) -> dict:
    await _require_account(accountId)
    return await _attach_original_topic_states(accountId, await run_io(monitor_store.get_recommendation, accountId))


@app.post("/api/monitor/recommendations/generate")
async def generate_monitor_recommendations(accountId: str) -> dict:
    """手动更新建议：后台生成，立即返回当前状态，界面按状态轮询。"""
    topic_recommendation_availability.require_available()
    await _require_account(accountId)
    _require_workbench()
    await topic_recommendation_runtime.start(accountId, "manual")
    return await run_io(topic_recommendation_runtime.overview, accountId)


@app.post("/api/monitor/recommendations/{key}/dismiss")
async def dismiss_monitor_recommendation(key: str, accountId: str) -> dict:
    await _require_account(accountId)
    try:
        return await run_io(monitor_store.dismiss_recommendation, accountId, key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_recommendation_not_found", "message": str(exc)}) from exc


@app.post("/api/monitor/recommendations/{key}/restore")
async def restore_monitor_recommendation(key: str, accountId: str) -> dict:
    await _require_account(accountId)
    return await run_io(monitor_store.restore_recommendation, accountId, key)


def _original_topic_fields(item, payload):
    source = item.get("sourceWork") or {}
    parts = [payload.outline.strip()]
    for label, value in (("我的切入角度", item.get("angle")), ("推荐理由", item.get("reason"))):
        text = str(value or "").strip()
        if text and not any(text == part or part.endswith("：" + text) for part in parts):
            parts.append(f"{label}：{text}")
    return {"weekStart": _monitor_week_start(payload.weekPlan), "title": payload.title,
            "outline": "\n".join(part for part in parts if part)[:2000],
            "category": payload.category, "format": payload.format, "materials": "",
            "sourceRecommendationId": str(item.get("key") or ""),
            "sourceWork": dict(source),
            "sourceWorkIds": [str(item["sourceWorkId"])] if item.get("sourceWorkId") else []}


@app.post("/api/monitor/recommendations/{key}/topic")
async def create_monitor_topic(key: str, payload: MonitorTopicRequest) -> dict:
    """把一条建议转成正式选题；标题和安排以用户提交的为准。"""
    await _require_account(payload.accountId)
    try:
        item = await run_io(monitor_store.recommendation_item, payload.accountId, key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "monitor_recommendation_not_found", "message": str(exc)}) from exc
    if item.get("topicId"):
        raise HTTPException(status_code=409, detail={"code": "monitor_topic_exists", "message": "这条建议已经加入选题了。"})
    fields = _original_topic_fields(item, payload)
    try:
        topic = await run_io(workspace_store.create_topic, payload.accountId, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "monitor_topic_invalid", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "account_not_found", "message": str(exc)}) from exc
    view = await run_io(monitor_store.mark_recommendation_topic, payload.accountId, key, str(topic.get("id") or ""))
    return {"topic": topic, "recommendation": view}


@app.get("/api/monitor/settings")
async def get_monitor_settings() -> dict:
    settings = await run_io(monitor_store.get_settings)
    return {
        "settings": settings,
        "intervalOptions": list(MONITOR_INTERVAL_OPTIONS),
        "usage": await run_io(monitor_store.usage_view),
        "creationConfigured": _workbench_ready(),
    }


@app.put("/api/monitor/settings")
async def update_monitor_settings(payload: MonitorSettingsRequest) -> dict:
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"code": "monitor_nothing_to_update", "message": "没有需要更新的设置。"})
    try:
        settings = await run_io(monitor_store.save_settings, fields)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "monitor_settings_invalid", "message": str(exc)}) from exc
    return {"settings": settings, "intervalOptions": list(MONITOR_INTERVAL_OPTIONS), "usage": await run_io(monitor_store.usage_view)}


# ----------------------------------------------------------------------
# 雷达（/api/radar）
#
# 采集规则（需求文档 V1）：首次订阅查最近七天、最多三页并标记历史导入；
# 日常每词每天一个时刻查最近一天、固定一页；停机超过 24 小时恢复时查最近七天、一页。
# 所有窗口都先由接口筛选，返回后再按发布时间本地复核一次。
# ----------------------------------------------------------------------


def _radar_sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _radar_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(2)
        if len(_radar_semaphores) > 8:
            _radar_semaphores.clear()
        _radar_semaphores[loop] = semaphore
    return semaphore


async def _radar_search_works(keyword: str, *, window: str, pages: int, data: Optional[PlatformDataClient] = None, on_page=None) -> dict[str, Any]:
    """Latest-first, bounded search. Persist each completed page before advancing."""
    from .creation_data import CAPABILITY_SEARCH
    data = data or _data_client()
    cursor = ""
    works = []
    usage = RoundUsage()
    used_pages = 0
    seen_pages = set()
    seen_cursors = set()
    stop_reason = "exhausted"
    error = ""
    # data_service V2 day filter returned 400 in live acceptance; latest/week works.
    # Keep the requested rolling day/week window at local ingestion.
    params = {"keyword": keyword, "sort_type": "2", "publish_time": "7", "content_type": "0"}
    for index in range(max(1, min(int(pages or 1), 3))):
        try:
            result = await data.query(CAPABILITY_SEARCH, params, cursor=cursor or None)
        except PlatformDataError as exc:
            if used_pages == 0:
                raise
            stop_reason, error = "request_failed", exc.message
            break
        usage.add(result.get("chargedPoints"), frozen=result.get("frozenPoints"))
        used_pages += 1
        page = result.get("page") or {}
        rows = [row for item in page_items(page) if (row := normalize_search_work(posts_item_to_aweme(item))) is not None]
        fingerprint = tuple(sorted(row["id"] for row in rows))
        repeated = bool(fingerprint) and fingerprint in seen_pages
        if fingerprint:
            seen_pages.add(fingerprint)
        if on_page is not None:
            await on_page(rows, result)
        if not repeated:
            works.extend(rows)
        if repeated:
            stop_reason = "repeated_page"
            break
        next_value = next_cursor(page)
        if not next_value:
            stop_reason = "invalid_cursor" if page.get("hasMore") else "exhausted"
            break
        if next_value == cursor or next_value in seen_cursors:
            stop_reason = "repeated_cursor"
            break
        seen_cursors.add(next_value)
        cursor = next_value
        stop_reason = "page_limit"
    return {"works": works, "requests": usage.requests, "chargedPoints": usage.chargedPoints,
            "pages": used_pages, "truncated": stop_reason != "exhausted", "stopReason": stop_reason, "error": error}


async def _run_radar_keyword(keyword_id: str, *, trigger: str = "manual", data_client=None, include_trends: bool = True) -> dict[str, Any]:
    """一个关键词的一轮采集：V2 近期视频 + V3 低粉爆款 + 热度飙升榜。"""
    if trigger == "schedule" and not _workbench_ready():
        # 未登录时不启动平台任务、也不写失败记录：登录后由调度自动补齐。
        return {"status": "skipped", "reason": "waiting_login"}
    try:
        keyword = await run_io(radar_store.get_keyword, keyword_id)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    settings = await run_io(radar_store.get_settings)
    if not settings.get("collectEnabled", True) and trigger == "schedule":
        return {"status": "skipped", "reason": "内容采集已暂停"}
    text = str(keyword.get("text") or "")
    if not text:
        await run_io(radar_store.record_collection, keyword_id, status="failed", error="关键词为空，已跳过。")
        return {"status": "failed", "error": "关键词为空"}
    plan = plan_collection(keyword)
    await run_io(radar_store.mark_collect_started, keyword_id)
    added = 0
    updated = 0
    low_fans_added = 0
    imported = 0
    skipped = 0
    requests = 0
    trend_requests = 0
    charged_total = 0.0
    pages = 0
    truncated = False
    trend_error = ""
    search_error = ""
    summaries = {}
    collection_moment = datetime.now(timezone.utc)
    collected_at = collection_moment.isoformat()
    persisted_pages = 0
    search_summary = {"received": 0, "added": 0, "updated": 0, "linked": 0, "skipped": 0, "invalidTag": 0, "taskIds": []}

    async def persist_search(rows, result):
        nonlocal added, updated, skipped, imported, persisted_pages
        outcome = await run_io(radar_store.upsert_works, keyword_id, rows, source="search",
            collected_at=collected_at, baseline=bool(plan["baseline"]), skip_out_of_window=plan["window"],
            now=collection_moment, task_id=str(result.get("taskId") or ""), batch_id=collected_at)
        persisted_pages += 1
        added += outcome["added"]
        updated += outcome["updated"]
        skipped += outcome["skipped"]
        if plan["baseline"]:
            imported += outcome["added"]
        for key in ("received", "added", "updated", "linked", "skipped", "invalidTag"):
            search_summary[key] += outcome.get(key, 0)
        if result.get("taskId"):
            search_summary["taskIds"].append(result["taskId"])
    low_fans_error = ""
    low_fans_requests = 0
    try:
        data = data_client or _data_client()
        data.business_context = await _business_context("radar", account_id=str(keyword.get("accountId") or ""), trigger=trigger, keyword=text)
        async with _radar_sem():
            search = await _radar_search_works(text, window=plan["window"], pages=plan["pages"], data=data, on_page=persist_search)
            requests += search["requests"]
            charged_total = round(charged_total + float(search.get("chargedPoints") or 0), 6)
            pages += search["pages"]
            truncated = search["truncated"]
            if not persisted_pages:  # also supports injected/offline search implementations
                await persist_search(search["works"], {})
            search_summary.update(pages=pages, stopReason=search.get("stopReason", "page_limit" if truncated else "exhausted"))
            summaries["search"] = search_summary
            search_error = search.get("error") or ("搜索未完整获取" if search.get("stopReason") in ("repeated_page", "repeated_cursor", "invalid_cursor") else "")
            # 低粉爆款：接口本身固定「最近七天 + 平台低粉爆款标签」，不受日常窗口影响。
            try:
                low_fans_result = await data.query(CAPABILITY_LOW_FANS, {"keyword": text})
                requests += 1
                low_fans_requests += 1
                charged_total = round(charged_total + float(low_fans_result.get("chargedPoints") or 0), 6)
                low_fans_page = low_fans_result.get("page") or {}
                rows = [
                    item
                    for item in (
                        normalize_low_fans_work(low_fans_item_to_row(raw)) for raw in page_items(low_fans_page)
                    )
                    if item
                ]
                outcome = await run_io(
                    radar_store.upsert_works,
                    keyword_id,
                    rows,
                    source="lowfans",
                    collected_at=collected_at,
                    baseline=bool(plan["baseline"]),
                    now=collection_moment, task_id=str(low_fans_result.get("taskId") or ""), batch_id=collected_at,
                )
                added += outcome["added"]
                updated += outcome["updated"]
                low_fans_added += outcome["lowFansAdded"]
                if plan["baseline"]:
                    imported += outcome["added"]
                summaries["lowfans"] = {**outcome, "taskIds": [low_fans_result.get("taskId")], "stopReason": "batch_complete"}
                if outcome["skipped"] or outcome.get("invalidTag"):
                    low_fans_error = "低粉结果未通过校验"
                    summaries["lowfans"]["stopReason"] = "filtered_invalid_results"
            except PlatformDataError as exc:
                low_fans_error = exc.message
                logger.info("radar_low_fans_failed keyword=%s code=%s", keyword_id, exc.code)
            if include_trends:
                trend_result = await collect_trend(radar_store, data, text, scheduled=trigger == "schedule")
                trend_requests = trend_result["requests"]
                requests += trend_requests
                charged_total = round(charged_total + float(trend_result.get("chargedPoints") or 0), 6)
                trend_error = trend_result["error"]
                summaries["trends"] = {"count": len((radar_store.get_keyword(keyword_id).get("trend") or {}).get("items") or [])}


    except PlatformDataError as exc:
        status = _data_error_status(exc)
        message = exc.message
        await run_io(
            radar_store.record_collection,
            keyword_id,
            status=status,
            error=message,
            error_code=_relogin_code(exc.code),
            window=plan["window"],
            pages=pages,
            requests=requests,
        )
        if requests:
            await run_io(radar_store.record_requests, "search", requests)
        if charged_total:
            await run_io(radar_store.record_charge, "%0.2f" % charged_total, requests)
        logger.info("radar_collection_failed keyword=%s code=%s trigger=%s", keyword_id, exc.code, trigger)
        return {"status": status, "error": message}
    except Exception:  # pragma: no cover - 兜底，避免后台任务静默死掉
        await run_io(radar_store.record_collection, keyword_id, status="failed", error="采集发生未预期错误。")
        logger.exception("radar_collection_crashed keyword=%s trigger=%s", keyword_id, trigger)
        return {"status": "failed", "error": "采集发生未预期错误。"}

    if requests:
        # 用量按请求类别拆开，费用估算才分得清「便宜十倍」的榜单和搜索接口。
        try:
            await run_io(radar_store.record_requests, "search", max(0, requests - low_fans_requests - trend_requests))
            if low_fans_requests:
                await run_io(radar_store.record_requests, "lowfans", low_fans_requests)
        except Exception:  # pragma: no cover - 记账失败只影响用量展示，不改变本轮采集结论
            logger.exception("radar_usage_record_failed keyword=%s trigger=%s", keyword_id, trigger)
    # 真实扣费按本轮合计入账：界面展示总请求数与总费用，不写成一个固定价格。
    if charged_total:
        try:
            await run_io(radar_store.record_charge, "%0.2f" % charged_total, requests)
        except Exception:  # pragma: no cover - 记账失败只影响用量展示，不改变本轮采集结论
            logger.exception("radar_charge_record_failed keyword=%s trigger=%s", keyword_id, trigger)
    error = ""
    if search_error or low_fans_error or trend_error:
        # 只记「哪个数据源没拿到」这一件事：卡片上不再常驻长句，失败细节在任务记录里看。
        # 搜索本身是主数据源，它失败会走上面的整体失败分支，这里只会是次要数据源。
        error = "、".join(
            f"{label}未获取"
            for label, failure in (("搜索", search_error), ("低粉爆款", low_fans_error), ("热度飙升榜", trend_error))
            if failure
        )
    status = "partial" if error else "success"
    try:
        await run_io(
            radar_store.record_collection,
            keyword_id,
            status=status,
            error=error,
            window=plan["window"],
            pages=pages,
            requests=requests,
            imported=imported,
            added=added,
            low_fans_added=low_fans_added,
            gap_note=str(plan.get("gapNote") or ""),
            truncated=truncated,
            summaries=summaries,
        )
    except Exception:  # pragma: no cover - 兜底：终态必须落盘，否则关键词会永久停在「同步中」
        logger.exception("radar_collection_finalize_failed keyword=%s trigger=%s", keyword_id, trigger)
        try:
            await run_io(
                radar_store.record_collection,
                keyword_id,
                status="failed",
                error="采集已返回，但状态回写失败，请重试。",
            )
        except Exception:
            logger.exception("radar_collection_finalize_retry_failed keyword=%s", keyword_id)
        return {"status": "failed", "error": "采集已返回，但状态回写失败，请重试。"}
    logger.info(
        "radar_collection_done keyword=%s trigger=%s mode=%s added=%s updated=%s pages=%s skipped_out_of_window=%s",
        keyword_id,
        trigger,
        plan["mode"],
        added,
        updated,
        pages,
        skipped,
    )
    return {
        "status": status,
        "added": added,
        "updated": updated,
        "lowFansAdded": low_fans_added,
        "imported": imported,
        "pages": pages,
        "requests": requests,
        "window": plan["window"],
        "mode": plan["mode"],
        "skippedOutOfWindow": skipped,
        "truncated": truncated,
        "error": error,
    }


def _start_radar_collection(keyword_id: str, *, trigger: str) -> str:
    existing = _radar_jobs.get(keyword_id)
    if existing is not None and not existing.done():
        return "running"
    loop = asyncio.get_running_loop()
    task = loop.create_task(_run_radar_keyword(keyword_id, trigger=trigger))
    _radar_jobs[keyword_id] = task

    def _cleanup(_task: asyncio.Task, key: str = keyword_id) -> None:
        if _radar_jobs.get(key) is _task:
            _radar_jobs.pop(key, None)
        # 主动取一次异常：否则后台任务失败只会留下「never retrieved」提示，静默丢掉原因。
        if not _task.cancelled() and _task.exception() is not None:
            logger.error("radar_collection_task_unhandled keyword=%s", key, exc_info=_task.exception())

    task.add_done_callback(_cleanup)
    return "started"


async def _start_radar_collections_for_account(account_id: str, *, trigger: str) -> dict[str, int]:
    settings = await run_io(radar_store.get_settings)
    if not settings.get("collectEnabled", True) and trigger == "schedule":
        return {"started": 0, "running": 0}
    keyword_ids = await run_io(radar_store.account_keyword_ids, account_id)
    started = 0
    running = 0
    for keyword_id in keyword_ids:
        keyword = await run_io(radar_store.get_keyword, keyword_id)
        if not keyword.get("enabled", True):
            continue
        outcome = _start_radar_collection(keyword_id, trigger=trigger)
        if outcome == "running":
            running += 1
        else:
            started += 1
    return {"started": started, "running": running}


async def _radar_recommendation_context(account_id: str) -> dict[str, Any]:
    """准备一次雷达 AI 生成所需的输入；返回 ``skip`` 表示这次不调用模型。"""
    keyword_ids = await run_io(radar_store.account_keyword_ids, account_id)
    if not keyword_ids:
        return {"skip": True, "reason": "当前账号还没有订阅关键词，先在内容采集里添加关键词。"}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RADAR_ANALYSIS_WINDOW_DAYS)).isoformat()
    works = await run_io(radar_store.recommendation_works, account_id, since=cutoff, limit=200)
    note = f"最近 {RADAR_ANALYSIS_WINDOW_DAYS} 天内容采集收集到的作品"
    if len(works) < 3:
        # 首次接入时近七天可能只有刚导入的历史作品：候选太少就纳入它们，
        # 但必须在窗口说明里写清楚，不能让历史导入冒充最近动态。
        works = await run_io(
            radar_store.recommendation_works,
            account_id,
            since=cutoff,
            limit=200,
            include_baseline=True,
        )
        note = f"最近 {RADAR_ANALYSIS_WINDOW_DAYS} 天的新作品不足 3 条，本次把刚导入的历史作品也纳入参考"
    if not works:
        return {"skip": True, "reason": "最近七天没有可用的内容采集作品，跳过本次生成，已有建议保留。"}
    try:
        account_inputs = await run_io(build_account_inputs, account_id, workspace_store, review_store)
    except (ValueError, OSError, KeyError) as exc:
        raise TextServiceError("radar_inputs_unavailable", "账号复盘数据读取失败，已有建议保留。") from exc
    profile = await run_io(workspace_store.read_account_profile, account_id)
    accounts = await run_io(workspace_store.list_accounts)
    account_name = next((str(item.get("name") or "") for item in accounts if str(item.get("id")) == account_id), "")
    trends = await run_io(radar_store.trend_rows, account_id)
    topics = await run_io(workspace_store.list_topics, account_id)
    dismissed = await run_io(radar_store.dismissed_recommendations, account_id)
    trend_flat: list[dict[str, Any]] = []
    for row in trends:
        for item in row.get("items") or []:
            trend_flat.append({"keyword": item.get("keyword"), "score": item.get("score"), "from": row.get("keyword")})
    # 一次最多送 200 条作品，正文里 publishedText 能从 publishedAt 推出、discoveredAt 只描述采集
    # 时刻（窗口说明已交代），带上只会挤占推理与正文预算；这里只把模型真正需要的字段交给它。
    model_works = [
        dict(work)
        for work in works
    ]
    window = {"from": cutoff, "to": now_iso(), "note": note, "days": RADAR_ANALYSIS_WINDOW_DAYS}
    context = {
        **account_inputs,
        "accountName": account_name,
        "businessPositioning": str(profile.get("businessPositioning") or ""),
        "targetAudience": str(profile.get("targetAudience") or ""),
        "window": window,
        "radarWorks": model_works,
        "trending": trend_flat[:40],
        "existingTopics": list((topics or {}).get("items") or []),
        "dismissed": dismissed,
    }
    inputs = {
        "radarWorkCount": len(works),
        "keywordCount": len(keyword_ids),
        "lowFansCount": len([work for work in works if work.get("lowFans")]),
        "hasPositioning": _monitor_profile_ready(profile.get("businessPositioning")),
        "hasAudience": _monitor_profile_ready(profile.get("targetAudience")),
    }
    analysis = {"schemaVersion": 2, "review": account_inputs["review"],
                "gaps": account_inputs["review"]["gaps"], "radarWorkCount": len(works)}
    return {"schemaVersion": 2, "context": context, "window": window, "inputs": inputs, "works": works, "analysis": analysis}


def _radar_finalize_items(items: list[Mapping[str, Any]], works: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _original_finalize_items(items, works, source="radar", limit=RADAR_RECOMMENDATION_MAX)


async def _run_radar_recommendation(account_id: str, *, trigger: str = "manual") -> dict[str, Any]:
    await run_io(radar_store.set_recommendation_job, account_id, "running")
    try:
        prepared = await _radar_recommendation_context(account_id)
        if prepared.get("skip"):
            reason = str(prepared.get("reason") or "没有可用的内容采集数据")
            logger.info("radar_recommendation_skipped account=%s reason=%s", account_id, reason)
            return await run_io(radar_store.set_recommendation_job, account_id, "skipped", error=reason)
        works = prepared["works"]
        allowed = {str(work.get("id")) for work in works}
        client = _text_service_client()
        client.business_context = await _business_context("radar", account_id=account_id, trigger=trigger)
        items = await client.suggest_radar_topics(prepared["context"], allowed_references=allowed)
        finalized = _radar_finalize_items(items, works)
        await _attach_original_topic_states(account_id, {"items": finalized})
        message = str(prepared["window"].get("note") or "")
        view = await run_io(
            radar_store.save_recommendation,
            account_id,
            finalized,
            schema_version=2,
            message=message,
            scope=message,
            analysis=prepared["analysis"],
        )
        logger.info("radar_recommendation_done account=%s trigger=%s items=%s", account_id, trigger, len(finalized))
        return view
    except TextServiceError as exc:
        logger.info("radar_recommendation_failed account=%s code=%s", account_id, exc.code)
        return await run_io(radar_store.set_recommendation_job, account_id, "failed", error=exc.message,
                            error_code=_relogin_code(exc.code))
    except Exception:  # pragma: no cover - 兜底
        logger.exception("radar_recommendation_crashed account=%s trigger=%s", account_id, trigger)
        return await run_io(radar_store.set_recommendation_job, account_id, "failed", error="生成选题建议时发生未预期错误。")


def _start_radar_recommendation(account_id: str, *, trigger: str) -> str:
    existing = _radar_ai_jobs.get(account_id)
    if existing is not None and not existing.done():
        return "running"
    loop = asyncio.get_running_loop()
    task = loop.create_task(_run_radar_recommendation(account_id, trigger=trigger))
    _radar_ai_jobs[account_id] = task

    def _cleanup(_task: asyncio.Task, key: str = account_id) -> None:
        if _radar_ai_jobs.get(key) is _task:
            _radar_ai_jobs.pop(key, None)

    task.add_done_callback(_cleanup)
    return "started"


async def _retry_radar_trend(text: str) -> None:
    try:
        async with _radar_sem():
            # A normal collection may have updated this key while this job was queued.
            if text not in await run_io(radar_store.trend_retry_keywords):
                return
            cached = await run_io(radar_store.shared_trend, text)
            context = dict(cached.get("businessContext") or {})
            if context.get("source") != "radar" or not context.get("accountId"):
                return  # Legacy shared requests have no trustworthy owner.
            accounts = await run_io(workspace_store.list_accounts)
            if not any(str(item.get("id")) == context["accountId"] for item in accounts):
                return
            data = _data_client()
            data.business_context = {**context, "trigger": "schedule"}
            await collect_trend(radar_store, data, text, scheduled=True)
    except Exception:
        logger.exception("radar_trend_retry_failed")


async def _check_radar_schedule() -> None:
    """到点关键词采集 + 每天一次的 AI 建议；两边合成一次读盘。"""
    if not _workbench_ready():
        # 未登录（或处于模拟通路）时不启动任何采集，也不落失败记录。
        return
    snapshot = await run_io(radar_store.schedule_snapshot)
    for text in await run_io(radar_store.trend_retry_keywords):
        running = _radar_trend_retry_jobs.get(text)
        if running is None or running.done():
            task = asyncio.create_task(_retry_radar_trend(text))
            _radar_trend_retry_jobs[text] = task
            task.add_done_callback(lambda done, key=text: _radar_trend_retry_jobs.pop(key, None)
                                   if _radar_trend_retry_jobs.get(key) is done else None)
    for keyword_id in snapshot["dueKeywords"]:
        _start_radar_collection(keyword_id, trigger="schedule")


async def _radar_scheduler_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_RADAR_SCHEDULER_TICK_SECONDS)
            await _check_radar_schedule()
        except asyncio.CancelledError:  # pragma: no cover - 关闭时正常退出
            raise
        except Exception:  # pragma: no cover - 单次失败不能让循环退出
            logger.exception("radar_scheduler_tick_failed")


async def _stop_radar_scheduler() -> None:
    global _radar_scheduler_task
    task = _radar_scheduler_task
    _radar_scheduler_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


app.add_event_handler("shutdown", _stop_radar_scheduler)


class RadarKeywordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=40)
    kind: Literal["normal", "key"] = "normal"
    group: str = Field(default="", max_length=20)
    dailyTime: Optional[str] = None


class RadarKeywordUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Optional[Literal["normal", "key"]] = None
    group: Optional[str] = Field(default=None, max_length=20)
    enabled: Optional[bool] = None
    dailyTime: Optional[str] = None


class RadarAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=64)


class RadarWorkSavedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=64)
    saved: bool


class RadarTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    outline: str = Field(default="", max_length=2000)
    category: Literal["highlight", "daily", "series", "test"] = "daily"
    format: Literal["video", "article"] = "video"
    weekPlan: Literal["current", "next"] = "current"


class RadarRecommendationTopicRequest(RadarTopicRequest):
    title: str = Field(min_length=1)


class RadarSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collectEnabled: Optional[bool] = None
    collectDailyTime: str = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    aiEnabled: Optional[bool] = None
    aiDailyTime: Optional[str] = None


async def _ensure_radar_cover(work_id: str) -> Path | None:
    """返回可显示的雷达作品封面；本地已有缓存就直接用，否则下载并在需要时转换。"""
    cached = await run_io(radar_store.cover_file, work_id)
    if cached is not None:
        return cached
    try:
        work = await run_io(radar_store.get_work, work_id)
    except ValueError:
        return None
    url = str(work.get("coverUrl") or "")
    if not url:
        return None
    return await _cache_monitor_image(url, directory=radar_store.covers_dir, name=str(work.get("id") or ""))


@app.get("/api/radar/covers/{work_id}")
async def get_radar_cover(work_id: str) -> FileResponse:
    path = await _ensure_radar_cover(work_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "radar_cover_not_found", "message": "封面暂时不可用。"})
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


async def _radar_account_overview(account_id: str) -> dict:
    overview = await run_io(radar_store.overview, account_id)
    overview["usage"].update(radar_billing.view(_subscription_service(), account_id))
    await _attach_original_topic_states(account_id, overview["recommendation"])
    return overview


@app.get("/api/radar/overview")
async def radar_overview(accountId: str) -> dict:
    await _require_account(accountId)
    return await _radar_account_overview(accountId)


@app.get("/api/radar/settings")
async def get_radar_settings() -> dict:
    return {
        "settings": await run_io(radar_store.get_settings),
        "tabs": [{"key": key, "label": label} for key, label in (("latest", "最新视频"), ("lowfans", "低粉爆款"))],
        "filters": [{"key": key, "label": label} for key, label in (("all", "全部状态"), ("unread", "未读"), ("saved", "已收藏"))],
        "days": [{"key": key, "label": label} for key, label in (("today", "今天"), ("yesterday", "昨天"), ("7d", "近 7 天"), ("30d", "近 30 天"), ("all", "全部日期"))],
        "kinds": [{"key": key, "label": label} for key, label in (("normal", "普通"), ("key", "重点"))],
        "suggestLimit": RADAR_SUGGEST_LIMIT,
        "creationConfigured": _workbench_ready(),
        "usage": await run_io(radar_store.usage),
    }


@app.put("/api/radar/settings")
async def update_radar_settings(payload: RadarSettingsRequest) -> dict:
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"code": "radar_nothing_to_update", "message": "没有需要更新的设置。"})
    try:
        settings = await run_io(radar_store.save_settings, fields)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "radar_settings_invalid", "message": str(exc)}) from exc
    return {"settings": settings, "usage": await run_io(radar_store.usage)}


@app.get("/api/radar/keywords")
async def list_radar_keywords(accountId: str) -> dict:
    await _require_account(accountId)
    overview = await _radar_account_overview(accountId)
    return {"items": overview["keywords"], "groups": overview["groups"], "creationConfigured": _workbench_ready()}


@app.post("/api/radar/keywords")
async def add_radar_keyword(payload: RadarKeywordRequest) -> dict:
    account_id = await _require_account(payload.accountId)
    _require_workbench()
    try:
        keyword = await run_io(
            radar_store.add_keyword,
            account_id,
            payload.text,
            kind=payload.kind,
            group=payload.group,
            daily_time=payload.dailyTime or "09:00",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "radar_keyword_invalid", "message": str(exc)}) from exc
    # 新订阅立刻做一次初始建库（最近七天、最多三页、标记历史导入）。
    started = _start_radar_collection(keyword["id"], trigger="manual")
    overview = await _radar_account_overview(account_id)
    return {"keyword": keyword, "started": started, "overview": overview}


@app.patch("/api/radar/keywords/{keyword_id}")
async def update_radar_keyword(keyword_id: str, payload: RadarKeywordUpdateRequest) -> dict:
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail={"code": "radar_nothing_to_update", "message": "没有需要更新的内容。"})
    try:
        keyword = await run_io(radar_store.update_keyword, keyword_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_keyword_not_found", "message": str(exc)}) from exc
    return {"keyword": keyword, "overview": await _radar_account_overview(keyword["accountId"])}


@app.delete("/api/radar/keywords/{keyword_id}")
async def delete_radar_keyword(keyword_id: str) -> dict:
    try:
        keyword = await run_io(radar_store.remove_keyword, keyword_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_keyword_not_found", "message": str(exc)}) from exc
    return {"removed": keyword["id"], "overview": await _radar_account_overview(keyword["accountId"])}


@app.post("/api/radar/keywords/{keyword_id}/collect")
async def collect_radar_keyword(keyword_id: str) -> dict:
    try:
        keyword = await run_io(radar_store.get_keyword, keyword_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_keyword_not_found", "message": str(exc)}) from exc
    _require_workbench()
    started = _start_radar_collection(keyword_id, trigger="manual")
    return {"started": started, "keyword": keyword["id"]}


@app.post("/api/radar/keywords/{keyword_id}/suggest")
async def suggest_radar_keyword(keyword_id: str) -> dict:
    """关键词联想：按需触发一次，不后台定时采集，也不自动添加订阅。"""
    try:
        keyword = await run_io(radar_store.get_keyword, keyword_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_keyword_not_found", "message": str(exc)}) from exc
    try:
        data = _data_client()
        data.business_context = await _business_context("radar", account_id=str(keyword.get("accountId") or ""), keyword=str(keyword.get("text") or ""))
        async with _radar_sem():
            suggest_result = await data.query(CAPABILITY_SUGGESTIONS, {"keyword": str(keyword.get("text") or "")})
    except PlatformDataError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc
    await run_io(radar_store.record_requests, "suggest", 1)
    if str(suggest_result.get("chargedPoints") or "").strip() not in ("", "0.000"):
        await run_io(radar_store.record_charge, str(suggest_result["chargedPoints"]), 1)
    words = await run_io(radar_store.save_suggestions, keyword_id, suggestion_words(suggest_result.get("page")))
    return {"words": words, "usage": await run_io(radar_store.usage)}


@app.post("/api/radar/collect")
async def collect_radar_account(payload: RadarAccountRequest) -> dict:
    account_id = await _require_account(payload.accountId)
    _require_workbench()
    outcome = await _start_radar_collections_for_account(account_id, trigger="manual")
    return {"accountId": account_id, **outcome}


@app.get("/api/radar/works")
async def list_radar_works(
    accountId: str,
    tab: str = "latest",
    day: str = RADAR_DEFAULT_DAY,
    filter: str = "all",
    keywordId: str = "",
    minLikes: int = 0,
    page: int = 1,
    pageSize: int = 10,
    maxLikes: Optional[int] = None,
    keywordIds: str = "",
    offset: Optional[int] = None,
) -> dict:
    await _require_account(accountId)
    if tab not in RADAR_TABS:
        raise HTTPException(status_code=400, detail={"code": "radar_tab_invalid", "message": "列表类型只能是全部、最新视频或低粉爆款。"})
    if filter not in RADAR_FILTERS:
        raise HTTPException(status_code=400, detail={"code": "radar_filter_invalid", "message": "状态筛选不正确。"})
    if day not in RADAR_DATE_OPTIONS:
        raise HTTPException(status_code=400, detail={"code": "radar_day_invalid", "message": "日期筛选不正确。"})
    if minLikes < 0:
        raise HTTPException(status_code=400, detail={"code": "radar_min_likes_invalid", "message": "最低点赞数必须是非负整数。"})
    if maxLikes is not None and (maxLikes < 0 or maxLikes < minLikes):
        raise HTTPException(status_code=400, detail={"code": "radar_max_likes_invalid", "message": "最高点赞数必须是非负整数，且不能小于最低点赞数。"})
    if offset is not None and offset < 0:
        raise HTTPException(status_code=400, detail={"code": "radar_offset_invalid", "message": "加载起点必须是非负整数。"})
    return await run_io(
        radar_store.list_works,
        accountId,
        tab=tab,
        day=day,
        work_filter=filter,
        keyword_id=keywordId,
        keyword_ids=[value.strip() for value in keywordIds.split(",") if value.strip()],
        min_likes=minLikes,
        max_likes=maxLikes,
        page=page,
        page_size=pageSize,
        offset=offset,
    )


@app.get("/api/radar/works/{work_id}")
async def get_radar_work(work_id: str, accountId: str = "") -> dict:
    if accountId:
        await _require_account(accountId)
    try:
        view = await run_io(radar_store.work_detail, work_id, accountId)
        view.update(await _radar_author_status(view.get("authorId"), accountId))
        return view
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_work_not_found", "message": str(exc)}) from exc


def _radar_sec_uid(value):
    value = str(value or "").strip()
    return value if re.fullmatch(r"MS4w[\w-]+", value, flags=re.ASCII) else ""


async def _radar_author_status(author_id, account_id):
    sec_uid = _radar_sec_uid(author_id)
    blogger = await run_io(monitor_store.blogger_by_sec_user, sec_uid) if sec_uid else None
    return {
        "authorProfileUrl": "https://www.douyin.com/user/" + sec_uid if sec_uid else "",
        "authorFollowing": bool(blogger and account_id in (blogger.get("follows") or {})),
    }


_radar_author_queries = {}


async def _resolve_radar_author(work_id, account_id):
    # Re-read after scheduling: a previous query may already have persisted the identity.
    work = await run_io(radar_store.get_work, work_id)
    sec_uid = _radar_sec_uid(work.get("authorId"))
    if sec_uid:
        return sec_uid
    data = _data_client()
    data.business_context = await _business_context("radar", account_id=account_id)
    data.business_context.update(action="resolve_author", targetId=work_id, targetName=str(work.get("title") or "")[:200])
    try:
        async with _radar_sem():
            result = await data.query("video", {"aweme_id": work_id})
    except PlatformDataError as exc:
        raise HTTPException(status_code=_creation_failure_status(exc), detail={"code": exc.code, "message": exc.message}) from exc
    video = (result.get("page") or {}).get("video")
    video = video if isinstance(video, Mapping) else {}
    author = video.get("author")
    author = author if isinstance(author, Mapping) else {}
    sec_uid = _radar_sec_uid(author.get("secUid"))
    if str(video.get("id") or "") != work_id or not sec_uid:
        raise HTTPException(status_code=422, detail={"code": "radar_author_unavailable", "message": "未能获取有效博主身份，作品可能已不可用，请稍后重试。"})
    await run_io(radar_store.save_author_identity, work_id, sec_uid)
    return sec_uid


@app.post("/api/radar/works/{work_id}/monitor")
async def monitor_radar_author(work_id: str, accountId: str) -> dict:
    await _require_account(accountId)
    _require_workbench()
    try:
        work = await run_io(radar_store.get_work, work_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_work_not_found", "message": str(exc)}) from exc
    sec_uid = _radar_sec_uid(work.get("authorId"))
    if not sec_uid:
        key = (asyncio.get_running_loop(), work_id)
        task = _radar_author_queries.get(key)
        if task is None:
            task = asyncio.create_task(_resolve_radar_author(work_id, accountId))
            _radar_author_queries[key] = task
            def finished(done):
                if _radar_author_queries.get(key) is done:
                    _radar_author_queries.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Retrieve failures even if the initiating HTTP request was cancelled.
            task.add_done_callback(finished)
        sec_uid = await asyncio.shield(task)
    result = await _add_monitor_blogger_serialized(
        accountId, MonitorAddBloggerRequest(shareText="https://www.douyin.com/user/" + sec_uid),
        sec_uid, skip_existing=True,
    )
    return {**result, "authorId": sec_uid, **(await _radar_author_status(sec_uid, accountId))}


@app.post("/api/radar/works/{work_id}/saved")
async def save_radar_work(work_id: str, payload: RadarWorkSavedRequest) -> dict:
    await _require_account(payload.accountId)
    try:
        saved = await run_io(radar_store.set_saved, payload.accountId, work_id, payload.saved)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_work_not_found", "message": str(exc)}) from exc
    return {"id": work_id, "saved": saved}


@app.post("/api/radar/works/{work_id}/read")
async def read_radar_work(work_id: str, payload: RadarAccountRequest) -> dict:
    await _require_account(payload.accountId)
    changed = await run_io(radar_store.mark_read, payload.accountId, [work_id])
    return {"id": work_id, "changed": changed}


@app.post("/api/radar/works/{work_id}/topic")
async def create_radar_work_topic(work_id: str, payload: RadarTopicRequest) -> dict:
    """从雷达作品创建选题；仅保存用户提交的大纲，不附加作品来源信息。"""
    account_id = await _require_account(payload.accountId)
    try:
        work = await run_io(radar_store.work_detail, work_id, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "radar_work_not_found", "message": str(exc)}) from exc
    if work.get("topicId"):
        raise HTTPException(status_code=409, detail={"code": "radar_topic_exists", "message": "这条作品已经加入选题了。"})
    fields = {
        "weekStart": _monitor_week_start(payload.weekPlan),
        "title": payload.title,
        "outline": payload.outline.strip(),
        "category": payload.category,
        "format": payload.format,
    }
    try:
        topic = await run_io(workspace_store.create_topic, account_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "radar_topic_invalid", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "account_not_found", "message": str(exc)}) from exc
    await run_io(radar_store.attach_topic, account_id, work_id, str(topic.get("id") or ""))
    return {"topic": topic}


@app.post("/api/radar/recommendation")
async def refresh_radar_recommendation(payload: RadarAccountRequest) -> dict:
    topic_recommendation_availability.require_available()
    account_id = await _require_account(payload.accountId)
    _require_workbench()
    started = await topic_recommendation_runtime.start(account_id, "manual")
    return {"started": started, "accountId": account_id}


@app.post("/api/radar/recommendation/{key}/dismiss")
async def dismiss_radar_recommendation(key: str, payload: RadarAccountRequest) -> dict:
    account_id = await _require_account(payload.accountId)
    return await run_io(radar_store.dismiss_recommendation, account_id, key)


@app.post("/api/radar/recommendation/{key}/restore")
async def restore_radar_recommendation(key: str, payload: RadarAccountRequest) -> dict:
    account_id = await _require_account(payload.accountId)
    return await run_io(radar_store.restore_recommendation, account_id, key)


@app.post("/api/radar/recommendation/{key}/topic")
async def create_radar_recommendation_topic(key: str, payload: RadarRecommendationTopicRequest) -> dict:
    """把一条 AI 建议转成正式选题；标题和安排以用户提交的为准。"""
    account_id = await _require_account(payload.accountId)
    view = await run_io(radar_store.get_recommendation, account_id)
    item = next((entry for entry in view["items"] if str(entry.get("key")) == str(key)), None)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "radar_recommendation_not_found", "message": "这条建议不存在或已被移除。"})
    if item.get("topicId"):
        raise HTTPException(status_code=409, detail={"code": "radar_topic_exists", "message": "这条建议已经加入选题了。"})
    fields = _original_topic_fields(item, payload)
    try:
        topic = await run_io(workspace_store.create_topic, account_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "radar_topic_invalid", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "account_not_found", "message": str(exc)}) from exc
    recommendation = await run_io(radar_store.attach_recommendation_topic, account_id, key, str(topic.get("id") or ""))
    return {"topic": topic, "recommendation": recommendation}


# Count both requests and scheduler dispatches so update draining has no await gap.
def _update_safe_schedule(function):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        if update_manager.maintenance:
            return
        update_manager.schedulers += 1
        try:
            return await function(*args, **kwargs)
        finally:
            update_manager.schedulers -= 1
    return wrapped


_check_review_schedule = _update_safe_schedule(_check_review_schedule)
_check_monitor_schedule = _update_safe_schedule(_check_monitor_schedule)
_check_monitor_ai_schedule = _update_safe_schedule(_check_monitor_ai_schedule)
_check_radar_schedule = _update_safe_schedule(_check_radar_schedule)


def _active_update_tasks():
    registries = (_review_jobs, _monitor_jobs, _monitor_ai_jobs, _radar_jobs,
                  _radar_ai_jobs, _radar_trend_retry_jobs, _link_task_jobs,
                  _safari_compatibility_jobs, _preview_poster_jobs,
                  _title_generation_jobs, _writing_generation_jobs,
                  _cover_title_job_tasks, _cover_generation_tasks,
                  home_advice_runtime.jobs, topic_recommendation_runtime.jobs, task_store._rewrite_jobs)
    pending = {id(task) for registry in registries for task in list(registry.values())
               if not task.done()}
    count = len(pending)
    count += sum(record.phase not in {"complete", "failed"} or record.rewrite_status == "running"
                 for record in list(task_store._records.values()))
    with publisher_service._lock:
        count += sum(not future.done() for future in publisher_service._task_futures)
        count += sum(task.status in {"queued", "running", "waiting_for_review"}
                     for task in publisher_service._tasks.values())
    return count


update_manager.active_count = _active_update_tasks
