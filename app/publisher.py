from __future__ import annotations

import logging
import os
import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PLATFORMS = {"douyin", "channels"}
ACTIVE_TASK_STATUSES = {"queued", "running"}
MOVE_BLOCKING_TASK_STATUSES = ACTIVE_TASK_STATUSES | {"waiting_for_review"}
DEFAULT_TASK_RETENTION_SECONDS = 30 * 60

logger = logging.getLogger(__name__)


def _sanitized_exception_detail(exc: Exception) -> str:
    detail = str(exc).replace("\r", " ").replace("\n", " ")[:1000]
    if re.search(
        r"(?i)\b(cookie|authorization|password|token|secret|session|api[_ -]?key|access[_ -]?key)\b",
        detail,
    ):
        return "[REDACTED sensitive exception detail]"
    return detail


class PublisherError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PublishAssetsStore:
    """Copies publish inputs into script-owned storage.

    Returned paths are always relative to the workspace. Source paths never
    become part of persisted or API-facing metadata.
    """

    def __init__(self, workspace_dir: Path, public_files_dir: Path | None = None) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._public_files_dir = Path(public_files_dir) if public_files_dir is not None else self._workspace_dir

    def save(
        self,
        script_id: str,
        video_source: str | Path | None,
        portrait_source: str | Path | None,
        landscape_source: str | Path | None,
        cover_state: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        self._validate_identifier(script_id, "脚本")
        video = self._validate_source(video_source, VIDEO_EXTENSIONS, "视频") if video_source is not None else None
        portrait = self._cover_source("3:4", portrait_source, cover_state)
        landscape = self._cover_source("4:3", landscape_source, cover_state)

        asset_dir = self._safe_asset_dir(script_id, create=True)
        result: dict[str, Any] = {
            "video": self._copy_asset(video, asset_dir, "video") if video is not None else None,
            "covers": {},
        }
        if portrait is not None:
            result["covers"]["3:4"] = self._copy_asset(portrait, asset_dir, "cover-3x4")
        if landscape is not None:
            result["covers"]["4:3"] = self._copy_asset(landscape, asset_dir, "cover-4x3")
        return result

    def _cover_source(
        self,
        aspect: str,
        explicit_source: str | Path | None,
        cover_state: Mapping[str, Any] | None,
    ) -> Path | None:
        if explicit_source is not None:
            return self._validate_source(explicit_source, IMAGE_EXTENSIONS, "图片")
        generated = self._generated_cover_path(aspect, cover_state)
        if generated is None:
            return None
        return self._validate_source(generated, IMAGE_EXTENSIONS, "图片")

    def _generated_cover_path(self, aspect: str, cover_state: Mapping[str, Any] | None) -> Path | None:
        results = cover_state.get("results") if isinstance(cover_state, Mapping) else None
        if not isinstance(results, list):
            return None
        for item in results:
            if not isinstance(item, Mapping) or item.get("aspect") != aspect or item.get("status") != "success":
                continue
            local_path = item.get("localPath")
            if isinstance(local_path, str) and local_path.strip():
                return Path(local_path)
            image_url = item.get("imageUrl")
            if not isinstance(image_url, str):
                continue
            parsed = urlsplit(image_url)
            prefix = "/api/files/"
            if parsed.scheme or parsed.netloc or not parsed.path.startswith(prefix):
                continue
            relative = Path(parsed.path[len(prefix):])
            candidate = (self._public_files_dir / relative).resolve()
            root = self._public_files_dir.resolve()
            if not self._is_relative_to(candidate, root):
                raise PublisherError("unsafe_asset_path", "生成封面路径不安全。")
            return candidate
        return None

    def _copy_asset(self, source: Path, asset_dir: Path, stem: str) -> dict[str, str]:
        destination = asset_dir / f"{stem}{source.suffix.lower()}"
        if destination.is_symlink():
            raise PublisherError("unsafe_asset_path", "发布素材路径不安全。")
        shutil.copy2(source, destination)
        relative = destination.relative_to(self._workspace_dir)
        return {"name": source.name, "path": relative.as_posix()}

    def _safe_asset_dir(self, script_id: str, *, create: bool) -> Path:
        workspace = self._workspace_dir.resolve()
        scripts_dir = self._workspace_dir / "scripts"
        script_dir = scripts_dir / script_id
        asset_dir = script_dir / "publish-assets"
        for component in (scripts_dir, script_dir, asset_dir):
            if component.is_symlink():
                raise PublisherError("unsafe_asset_path", "发布素材路径不安全。")
        resolved = asset_dir.resolve()
        if not self._is_relative_to(resolved, workspace):
            raise PublisherError("unsafe_asset_path", "发布素材路径不安全。")
        if create:
            asset_dir.mkdir(parents=True, exist_ok=True)
        if asset_dir.resolve() != resolved:
            raise PublisherError("unsafe_asset_path", "发布素材路径不安全。")
        return asset_dir

    @staticmethod
    def _validate_source(source: str | Path, extensions: set[str], label: str) -> Path:
        path = Path(source).expanduser()
        if not path.is_file():
            raise PublisherError("asset_missing", f"{label}文件不存在。")
        if path.suffix.lower() not in extensions:
            raise PublisherError("asset_type_unsupported", f"{label}格式不支持。")
        return path.resolve()

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not isinstance(value, str) or not value or value in {".", ".."} or Path(value).name != value:
            raise PublisherError("invalid_identifier", f"{label}标识无效。")

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


class _LoginAwarePublisher:
    login_timeout_seconds = 5.0
    login_poll_seconds = 0.1
    login_url_grace_seconds = 0.3
    login_selector = ""
    # 登录状态检测导航的页面：登录后访问它会停留在已登录界面，
    # 未登录访问它会被平台重定向回登录页。绝不能直接拿登录页本身做检测，
    # 否则已登录用户也会被判定为"需要登录"（登录页不会自动跳走）。
    check_url = ""

    def __init__(
        self,
        *,
        login_timeout_seconds: float | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if login_timeout_seconds is not None:
            if login_timeout_seconds <= 0:
                raise ValueError("login_timeout_seconds must be positive")
            self.login_timeout_seconds = float(login_timeout_seconds)
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep

    def login_state(self, page: Any) -> str:
        started_at = self._monotonic()
        deadline = started_at + self.login_timeout_seconds
        login_evidence_since: float | None = None
        previous_login_evidence: tuple[bool, bool] | None = None
        while True:
            if self._selector_is_visible(page, self.logged_in_selector):
                return "logged_in"

            now = self._monotonic()
            login_evidence = (
                self._is_login_page(str(page.url)),
                bool(self.login_selector and self._selector_is_visible(page, self.login_selector)),
            )
            if any(login_evidence):
                if login_evidence != previous_login_evidence:
                    login_evidence_since = now
                previous_login_evidence = login_evidence
                if now - login_evidence_since >= min(
                    self.login_url_grace_seconds,
                    self.login_timeout_seconds,
                ):
                    return "login_required"
            else:
                login_evidence_since = None
                previous_login_evidence = None
                if self._is_logged_in_page(page):
                    return "logged_in"
            if now >= deadline:
                return "login_required" if any(login_evidence) else "unknown"
            self._sleep(min(self.login_poll_seconds, deadline - now))

    @staticmethod
    def _selector_is_visible(page: Any, selector: str) -> bool:
        locator = page.locator(selector)
        first = getattr(locator, "first", locator)
        is_visible = getattr(first, "is_visible", None)
        return bool(is_visible()) if callable(is_visible) else locator.count() > 0

    def _is_logged_in_page(self, page: Any) -> bool:
        """Subclasses may report authenticated pages via stable URL structure."""
        return False


class DouyinPublisher(_LoginAwarePublisher):
    platform = "douyin"
    login_url = "https://creator.douyin.com/"
    check_url = "https://creator.douyin.com/"
    publish_url = "https://creator.douyin.com/creator-micro/content/upload"
    logged_in_selector = '[data-e2e="creator-header-avatar"]'
    login_selector = 'input[type="tel"], input[type="password"], [class*="qrcode"]'
    video_selector = 'input[type="file"][accept*="video"]'
    cover_upload_selector = 'div[class*="selectArea"] input.semi-upload-hidden-input'
    active_cover_upload_selector = 'div[class*="selectArea"]:visible input.semi-upload-hidden-input'
    title_selector = 'input[placeholder*="填写作品标题"]'
    description_selector = '[contenteditable="true"][data-placeholder*="添加作品简介"]'
    # 抖音上传 4:3 封面后会先同步竖封面底图和素材（提示条 + 处理中），
    # 该处理完成前"完成"按钮无效，必须等处理结束再确认。
    cover_sync_banner_text = "已优先同步竖封面底图和素材"

    def fill(self, page: Any, draft: Mapping[str, Any], assets: Mapping[str, Any]) -> None:
        page.locator(self.video_selector).set_input_files(str(assets["video"]["path"]))
        # 等待视频上传完成、编辑表单就绪（标题输入框出现），
        # 否则封面弹窗会在过渡状态打开，视频上传完成后弹窗重渲染会把标签页藏起来。
        page.locator(self.title_selector).wait_for(state="visible", timeout=180000)
        # 标题输入框在上传刚开始时就出现，视频仍在后台上传；
        # 必须等视频预览渲染（上传完成）后再操作封面，否则视频传完会重置弹窗状态。
        page.wait_for_selector("video", timeout=180000)
        DouyinPublisher._dismiss_prompts(page)
        covers = assets.get("covers") if isinstance(assets.get("covers"), Mapping) else {}
        self._upload_covers(page, covers)
        page.locator(self.title_selector).fill(str(draft.get("title") or ""))
        page.locator(self.description_selector).fill(self._description(draft))
        DouyinPublisher._dismiss_prompts(page)

    def _is_login_page(self, url: str) -> bool:
        return url.startswith(self.login_url) and "/creator-micro/" not in url

    def _is_logged_in_page(self, page: Any) -> bool:
        return (
            "/creator-micro/" in str(page.url)
            and not self._selector_is_visible(page, self.login_selector)
        )

    @staticmethod
    def _upload_covers(page: Any, covers: Mapping[str, Any]) -> None:
        portrait = covers.get("3:4") if isinstance(covers, Mapping) else None
        landscape = covers.get("4:3") if isinstance(covers, Mapping) else None
        has_portrait = isinstance(portrait, Mapping) and portrait.get("path")
        has_landscape = isinstance(landscape, Mapping) and landscape.get("path")
        if not (has_portrait or has_landscape):
            return
        # 打开一次"选择封面"弹窗；每种比例都显式切换并确认，避免依赖默认标签页。
        logger.info("publisher_cover_start portrait=%s landscape=%s", has_portrait, has_landscape)
        DouyinPublisher._dismiss_prompts(page)
        if not DouyinPublisher._wait_click_text(page, "选择封面", timeout_seconds=60):
            raise PublisherError("cover_dialog_unavailable", "无法打开封面设置，请手动完成封面上传。")
        DouyinPublisher._dismiss_prompts(page)
        if not DouyinPublisher._wait_for_unblocked_cover_ui(page, timeout_seconds=30):
            raise PublisherError("cover_dialog_blocked", "封面设置被提示遮挡，请手动处理后重试。")
        for aspect, asset in (("3:4", portrait), ("4:3", landscape)):
            if not isinstance(asset, Mapping) or not asset.get("path"):
                continue
            logger.info("publisher_cover_aspect_start aspect=%s", aspect)
            if not DouyinPublisher._activate_cover_tab(page, aspect, timeout_seconds=30):
                raise PublisherError("cover_tab_unavailable", f"无法确认{aspect}封面设置，请手动完成封面上传。")
            DouyinPublisher._dismiss_prompts(page)
            DouyinPublisher._upload_cover_file(page, str(asset["path"]))
            DouyinPublisher._dismiss_prompts(page)
            logger.info("publisher_cover_aspect_done aspect=%s", aspect)
        # 4:3 封面上传后抖音可能同步竖封面素材并处理（"已优先同步竖封面底图和素材"提示条），
        # 处理完成前"完成"无效；确认循环会自适应等待并关闭提示条。
        if not DouyinPublisher._confirm_cover_dialog(page):
            raise PublisherError("cover_dialog_unconfirmed", "封面设置未完成，请手动确认封面。")
        logger.info("publisher_cover_dialog_confirmed")

    @staticmethod
    def _upload_cover_file(page: Any, path: str) -> None:
        logger.info("publisher_cover_upload_start path=%s", path)
        if not DouyinPublisher._wait_for_unblocked_cover_ui(page, timeout_seconds=30):
            raise PublisherError("cover_upload_blocked", "封面上传被提示遮挡，请手动处理后重试。")
        before_srcs = page.evaluate(
            "() => Array.from(document.querySelectorAll('img'))"
            ".filter(i => (i.src || '').startsWith('data:')).map(i => i.src)"
        )
        upload_input = page.locator(DouyinPublisher.active_cover_upload_selector)
        if upload_input.count() != 1:
            raise PublisherError("cover_upload_unavailable", "无法确认当前封面上传区域，请手动完成封面上传。")
        upload_input.set_input_files(path, timeout=60000)
        # 等待封面上传并渲染预览：弹窗里本来就有 data:image 推荐图（横封面会替换预览而非新增），
        # 必须等待出现新的 data:image 源（真正出现新图）才算上传成功。
        if DouyinPublisher._wait_for_cover_preview(page, before_srcs, timeout_seconds=30):
            logger.info("publisher_cover_upload_preview_ok")
            return
        raise PublisherError("cover_preview_timeout", "封面预览未更新，请手动确认封面上传结果。")

    @staticmethod
    def _wait_for_cover_preview(page: Any, before_srcs: Any, timeout_seconds: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            DouyinPublisher._dismiss_prompts(page)
            if DouyinPublisher._has_unexpected_prompt(page):
                page.wait_for_timeout(500)
                continue
            try:
                page.wait_for_function(
                    """(before) => Array.from(document.querySelectorAll('img'))
                        .filter(i => (i.src || '').startsWith('data:'))
                        .some(i => !before.includes(i.src))""",
                    arg=before_srcs,
                    timeout=3000,
                )
                return True
            except Exception:
                page.wait_for_timeout(300)
        return False

    @staticmethod
    def _cover_sync_banner_visible(page: Any) -> bool:
        """4:3 封面上传后"已优先同步竖封面底图和素材"提示条是否可见。"""
        return bool(
            page.evaluate(
                """(text) => {
                    const isVisible = (el) => el.getClientRects().length > 0
                        && getComputedStyle(el).visibility !== 'hidden'
                        && getComputedStyle(el).display !== 'none';
                    return Array.from(document.querySelectorAll('*')).some((el) =>
                        isVisible(el) && (el.textContent || '').includes(text)
                    );
                }""",
                DouyinPublisher.cover_sync_banner_text,
            )
        )

    @staticmethod
    def _dismiss_cover_sync_banner(page: Any) -> bool:
        """关闭同步提示条（点其 X）；绝不点击"一键清空素材"。"""
        return bool(
            page.evaluate(
                """(text) => {
                    const isVisible = (el) => el.getClientRects().length > 0
                        && getComputedStyle(el).visibility !== 'hidden'
                        && getComputedStyle(el).display !== 'none';
                    const banner = Array.from(document.querySelectorAll('*')).find((el) => {
                        if (!isVisible(el)) return false;
                        const value = (el.textContent || '').trim();
                        return value.includes(text) && value.length < 200;
                    });
                    if (!banner) return false;
                    let node = banner;
                    while (node && node !== document.documentElement) {
                        const close = Array.from(node.querySelectorAll('*')).find((el) => {
                            if (!isVisible(el)) return false;
                            if ((el.textContent || '').trim().includes('一键清空素材')) return false;
                            const cls = String(el.className || '');
                            const aria = String(
                                el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || '')
                            );
                            if (/close|Close|关闭/.test(cls + ' ' + aria)) return true;
                            const tag = el.tagName.toLowerCase();
                            if (tag === 'svg' || tag === 'path' || tag === 'i' || tag === 'span') {
                                const parent = el.parentElement;
                                if (parent && /button|icon|close/i.test(String(parent.className || ''))) return true;
                            }
                            return false;
                        });
                        if (close) {
                            close.click();
                            return true;
                        }
                        node = node.parentElement;
                    }
                    return false;
                }""",
                DouyinPublisher.cover_sync_banner_text,
            )
        )

    @staticmethod
    def _wait_for_unblocked_cover_ui(page: Any, timeout_seconds: float = 30.0) -> bool:
        """已知提示自动关闭；未知弹框只能等待用户处理，绝不向其后方的控件上传。"""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            DouyinPublisher._dismiss_prompts(page)
            if not DouyinPublisher._has_unexpected_prompt(page):
                return True
            page.wait_for_timeout(500)
        return False

    @staticmethod
    def _has_unexpected_prompt(page: Any) -> bool:
        return bool(
            page.evaluate(
                """() => {
                    const isVisible = (element) => (
                        element.getClientRects().length > 0
                        && getComputedStyle(element).visibility !== 'hidden'
                        && getComputedStyle(element).display !== 'none'
                    );
                    return Array.from(document.querySelectorAll(
                        "[role='dialog'], [aria-modal='true'], [class*='modal-content'], [class*='modalContent'], [class*='dialog-content'], [class*='dialogContent']"
                    )).some((element) => {
                        if (!isVisible(element)) return false;
                        const labels = Array.from(element.querySelectorAll('*'))
                            .map((child) => (child.textContent || '').trim());
                        const isCoverEditor = labels.includes('设置竖封面')
                            && labels.includes('设置横封面')
                            && Boolean(element.querySelector(
                                "div[class*='selectArea'] input.semi-upload-hidden-input"
                            ));
                        return !isCoverEditor;
                    });
                }"""
            )
        )

    @staticmethod
    def _activate_cover_tab(page: Any, aspect: str, timeout_seconds: float = 30.0) -> bool:
        """激活并确认指定比例的封面标签，提示重现时继续重试。"""
        tab_text = {"3:4": "设置竖封面", "4:3": "设置横封面"}.get(aspect)
        if tab_text is None:
            raise PublisherError("invalid_cover_aspect", "封面比例无效。")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            DouyinPublisher._dismiss_prompts(page)
            if DouyinPublisher._has_unexpected_prompt(page):
                page.wait_for_timeout(500)
                continue
            if DouyinPublisher._click_text(page, tab_text):
                DouyinPublisher._dismiss_prompts(page)
                try:
                    page.wait_for_function(
                        """(tabText) => Array.from(document.querySelectorAll('*')).some(e =>
                            (e.textContent || '').trim() === tabText && /step-active/i.test(e.className || ''))""",
                        arg=tab_text,
                        timeout=3000,
                    )
                    return True
                except Exception:
                    pass
            page.wait_for_timeout(500)
        return False

    @staticmethod
    def _confirm_cover_dialog(page: Any, timeout_seconds: float = 300.0) -> bool:
        """点击"完成"并确认弹窗关闭；AI 封面同步/生成中"完成"可能暂时无效，需自适应重试。"""
        deadline = time.monotonic() + timeout_seconds
        blocked_by_prompt = False
        while time.monotonic() < deadline:
            DouyinPublisher._dismiss_prompts(page)
            DouyinPublisher._dismiss_cover_sync_banner(page)
            if DouyinPublisher._has_unexpected_prompt(page):
                blocked_by_prompt = True
                page.wait_for_timeout(500)
                continue
            if DouyinPublisher._click_text(page, "完成"):
                try:
                    page.wait_for_function(
                        "() => !Array.from(document.querySelectorAll('*')).some(e => "
                        "(e.textContent || '').trim() === '设置竖封面' && /step/i.test(e.className || ''))",
                        timeout=5000,
                    )
                    return True
                except Exception:
                    pass
            page.wait_for_timeout(500)
        if blocked_by_prompt:
            raise PublisherError("cover_dialog_blocked", "封面设置被提示遮挡，请手动处理后重试。")
        return False

    @staticmethod
    def _dismiss_prompts(page: Any, rounds: int = 3) -> None:
        """关闭 douyin 的推广/新手提示（"暂不设置"/"我知道了"），避免残留弹窗遮挡发布。"""
        for _ in range(rounds):
            changed = False
            for text in ("暂不设置", "我知道了"):
                if DouyinPublisher._click_text(page, text):
                    changed = True
            if not changed:
                return
            page.wait_for_timeout(400)

    @staticmethod
    def _wait_click_text(page: Any, text: str, timeout_seconds: float = 60.0) -> bool:
        """等待文本元素出现后点击；视频上传后界面元素是异步渲染的。"""
        deadline = time.monotonic() + timeout_seconds
        blocked_by_prompt = False
        while time.monotonic() < deadline:
            DouyinPublisher._dismiss_prompts(page)
            if DouyinPublisher._has_unexpected_prompt(page):
                blocked_by_prompt = True
                page.wait_for_timeout(500)
                continue
            if DouyinPublisher._click_text(page, text):
                return True
            page.wait_for_timeout(500)
        if blocked_by_prompt:
            raise PublisherError("cover_dialog_blocked", "封面设置被提示遮挡，请手动处理后重试。")
        return False

    @staticmethod
    def _click_text(page: Any, text: str) -> bool:
        """Click the first visible element whose text matches exactly (SPA 元素拦截时依然可靠)."""
        return bool(
            page.evaluate(
                """(text) => {
                    const els = Array.from(document.querySelectorAll('*'));
                    for (const el of els) {
                        if ((el.textContent || '').trim() !== text) continue;
                        if (el.offsetParent === null && el.getClientRects().length === 0) continue;
                        el.click();
                        return true;
                    }
                    return false;
                }""",
                text,
            )
        )

    @staticmethod
    def _description(draft: Mapping[str, Any]) -> str:
        description = str(draft.get("description") or "").strip()
        topics = draft.get("topics")
        hashtags = " ".join(
            f"#{str(topic).strip().lstrip('#')}"
            for topic in topics
            if str(topic).strip().lstrip("#")
        ) if isinstance(topics, list) else ""
        return " ".join(part for part in (description, hashtags) if part)


class ChannelsPublisher(_LoginAwarePublisher):
    platform = "channels"
    login_url = "https://channels.weixin.qq.com/login.html"
    check_url = "https://channels.weixin.qq.com/platform/home"
    # 填充时直接进首页再点"发表视频"：深链 /platform/post/create 会被 SPA
    # 重定向回首页，先访问它只会让标签页多一次"发布页→首页"的跳转。
    fill_url = "https://channels.weixin.qq.com/platform/home"
    publish_url = "https://channels.weixin.qq.com/platform/post/create"
    logged_in_selector = '.finder-nickname, [class*="account-avatar"]'
    login_selector = '[class*="qrcode"], [class*="login"] canvas'
    video_selector = 'input[type="file"][accept*="video"]'
    cover_selector = 'input[type="file"][accept*="image"]'
    cover_trigger_selector = ".vertical-cover-wrap"
    cover_dialog_selector = ".edit-cover-dialog .weui-desktop-dialog__wrp:visible"
    cover_dialog_selectors = (
        cover_dialog_selector,
        ".weui-desktop-dialog__wrp:visible",
        '[role="dialog"]:visible',
    )
    # 上传完成后平台会保留过渡页的隐藏输入框。必须限定可见字段并取第一个，
    # 否则 Playwright 的严格模式会因多个匹配项中断整条自动填充。
    title_selector = (
        'input[placeholder*="短标题"]:visible, '
        'textarea[placeholder*="短标题"]:visible, '
        '[contenteditable][data-placeholder*="短标题"]:visible'
    )
    description_selector = (
        '[contenteditable][data-placeholder*="描述"]:visible, '
        '[contenteditable][placeholder*="描述"]:visible, '
        'textarea[placeholder*="描述"]:visible'
    )
    cover_cards = (
        ("3:4", "个人主页卡片"),
        ("4:3", "分享卡片"),
    )
    cover_card_preview_selectors = {
        "3:4": (
            ".vertical-cover-wrap:visible",
            "img.cover-img-vertical:visible",
            ".cover-img-vertical:visible",
        ),
        "4:3": (
            ".horizontal-cover-wrap:visible",
            "img.cover-img-horizontal:visible",
            ".cover-img-horizontal:visible",
            ".cover-img-horizontal-center:visible",
        ),
    }

    def fill(self, page: Any, draft: Mapping[str, Any], assets: Mapping[str, Any]) -> list[str]:
        self._ensure_create_form(page)
        page.locator(self.video_selector).set_input_files(str(assets["video"]["path"]))
        logger.info("publisher_channels_video_uploaded")
        # 等视频上传完成（短标题输入框出现）后再填文案与封面，此时封面上传入口才挂载。
        # 先填文案，即使某个封面卡片需要人工处理，也不会丢失标题和描述。
        title_field = page.locator(self.title_selector).first
        title_field.wait_for(state="visible", timeout=180000)
        logger.info("publisher_channels_title_field_ready")
        title_field.fill(str(draft.get("shortTitle") or ""))
        logger.info("publisher_channels_title_filled")
        description_field = page.locator(self.description_selector).first
        description_field.wait_for(state="visible", timeout=30000)
        logger.info("publisher_channels_description_field_ready")
        description_field.fill(self._description(draft))
        logger.info("publisher_channels_description_filled")
        covers = assets.get("covers") if isinstance(assets.get("covers"), Mapping) else {}
        found_new_cards, warnings = self._upload_new_cover_cards(page, covers)
        if not found_new_cards:
            cover = covers.get("3:4") or covers.get("4:3")
            if isinstance(cover, Mapping) and cover.get("path"):
                if not self._upload_legacy_cover(page, str(cover["path"])):
                    warnings.append("封面未完成")
        DouyinPublisher._dismiss_prompts(page)
        return warnings

    @staticmethod
    def _ensure_create_form(page: Any) -> None:
        """确保发布表单已打开：等 SPA 外壳渲染后，若不在发布表单页
        就点首页的"发表视频"。"""
        if page.locator(ChannelsPublisher.video_selector).count() > 0:
            return
        if ChannelsPublisher._is_login_page(str(page.url)):
            raise PublisherError("publish_login_required", "视频号登录已失效，请重新登录。")
        # 等 SPA 外壳渲染完成（登录后侧边栏必有 .finder-nickname），
        # 此时才能判断当前视图是发布表单还是首页。
        try:
            page.wait_for_selector(ChannelsPublisher.logged_in_selector, timeout=45000)
        except Exception:
            if ChannelsPublisher._is_login_page(str(page.url)):
                raise PublisherError("publish_login_required", "视频号登录已失效，请重新登录。")
            raise
        if ChannelsPublisher._is_login_page(str(page.url)):
            raise PublisherError("publish_login_required", "视频号登录已失效，请重新登录。")
        # "发表视频"按钮不在主文档里（同源 iframe），必须用可穿透 iframe 的
        # 文本定位器点击，不能用 evaluate 式的主文档点击。
        for attempt in range(2):
            if page.locator(ChannelsPublisher.video_selector).count() == 0:
                try:
                    publish_button = page.locator('text="发表视频"').first
                    publish_button.wait_for(state="visible", timeout=30000)
                    publish_button.click(timeout=10000)
                except Exception:
                    if attempt == 0:
                        page.goto(ChannelsPublisher.check_url)
                        continue
                    break
            try:
                page.locator(ChannelsPublisher.video_selector).first.wait_for(
                    state="attached", timeout=30000
                )
                return
            except Exception:
                if attempt == 0:
                    page.goto(ChannelsPublisher.check_url)
                    continue
                break
        raise PublisherError("publish_form_open_failed", "无法打开视频号发布表单，请重试。")

    @staticmethod
    def _upload_new_cover_cards(page: Any, covers: Mapping[str, Any]) -> tuple[bool, list[str]]:
        """按新版卡片语义分别打开 3:4 / 4:3 的编辑入口。

        返回是否至少发现一个新版卡片；只有两个卡片都不存在时才允许旧版单封面兜底，
        以避免把横图错填进新版的个人主页卡片。
        """
        card_presence = {
            aspect: ChannelsPublisher._new_cover_card_present(page, card, aspect)
            for aspect, card in ChannelsPublisher.cover_cards
        }
        logger.info("publisher_channels_cover_cards_detected states=%s", card_presence)
        if any(present is None for present in card_presence.values()):
            logger.info("publisher_channels_cover_card_detection_failed")
            return True, ["封面卡片检测失败"]
        ChannelsPublisher._wait_for_new_cover_editors(
            page,
            card_presence,
            covers,
        )
        # 视频处理期间卡片会分批挂载，等待预览后必须重新检测，不能把
        # 首次短暂缺失的 3:4 固定为“不存在”并跳过整张封面。
        card_presence = {
            aspect: ChannelsPublisher._new_cover_card_present(page, card, aspect)
            for aspect, card in ChannelsPublisher.cover_cards
        }
        if any(present is None for present in card_presence.values()):
            return True, ["封面卡片检测失败"]
        found_new_card = any(card_presence.values())
        portrait_only_layout = card_presence["3:4"] and not card_presence["4:3"]
        warnings: list[str] = []
        for aspect, card in ChannelsPublisher.cover_cards:
            asset = covers.get(aspect) if isinstance(covers, Mapping) else None
            if not isinstance(asset, Mapping) or not asset.get("path"):
                if card_presence[aspect] and not (portrait_only_layout and aspect == "4:3"):
                    warnings.append(f"{card}封面待补齐")
                continue
            if not card_presence[aspect]:
                if found_new_card and not (portrait_only_layout and aspect == "4:3"):
                    warnings.append(f"{card}封面未找到")
                continue
            # 确认前一张封面后，视频号会重建整个封面组件。不能复用流程开始时
            # 保存的 Locator，必须在每张卡片点击前重新定位。
            editor = (
                None
                if aspect == "4:3"
                else ChannelsPublisher._wait_for_cover_editor(
                    page,
                    aspect,
                    card_presence,
                )
            )
            dialog = ChannelsPublisher._open_new_cover_card(
                page,
                card,
                aspect,
                editor,
            )
            if dialog is None or not ChannelsPublisher._upload_cover_dialog(
                page,
                dialog,
                str(asset["path"]),
                aspect=aspect,
            ):
                logger.info("publisher_channels_cover_card_upload_failed aspect=%s", aspect)
                warnings.append(f"{card}封面未完成")
        return found_new_card, warnings

    @staticmethod
    def _wait_for_new_cover_editors(
        page: Any,
        card_presence: Mapping[str, bool],
        covers: Mapping[str, Any],
    ) -> dict[str, Any]:
        """等视频处理后卡片编辑入口稳定，避免在封面组件重渲染时误点或漏传。"""
        required_aspects = [
            aspect
            for aspect, _card in ChannelsPublisher.cover_cards
            if card_presence.get(aspect)
            and isinstance(covers.get(aspect), Mapping)
            and covers[aspect].get("path")
        ]
        if not required_aspects:
            return {}

        latest: dict[str, Any] = {}
        # “编辑”可能由组件绘制，文本定位器始终看不到。竖屏已验证可通过封面
        # 预览打开编辑弹窗；横屏复用同一路径，并用横版预览定位分享卡片。
        for poll in range(240):
            preview_editors = ChannelsPublisher._cover_preview_editors_by_aspect(
                page,
                card_presence,
            )
            if all(aspect in preview_editors for aspect in required_aspects):
                logger.info(
                    "publisher_channels_cover_previews_ready aspects=%s polls=%s",
                    required_aspects,
                    poll + 1,
                )
                return preview_editors
            try:
                current = ChannelsPublisher._cover_editors_by_aspect(page, card_presence)
            except Exception as exc:
                logger.info(
                    "publisher_channels_cover_editor_mapping_failed error_type=%s",
                    type(exc).__name__,
                )
                current = {}
            latest = current
            if all(aspect in current for aspect in required_aspects):
                logger.info(
                    "publisher_channels_cover_editors_ready aspects=%s polls=%s",
                    required_aspects,
                    poll + 1,
                )
                return current
            page.wait_for_timeout(750)

        logger.info(
            "publisher_channels_cover_editors_wait_timeout required=%s available=%s",
            required_aspects,
            sorted(latest),
        )
        return latest

    @staticmethod
    def _cover_preview_editors_by_aspect(
        page: Any,
        card_presence: Mapping[str, bool],
    ) -> dict[str, Any]:
        """复用竖屏成功路径，通过封面预览元素打开对应卡片编辑弹窗。"""
        result: dict[str, Any] = {}
        for aspect, _card in ChannelsPublisher.cover_cards:
            if not card_presence.get(aspect):
                continue
            for selector in ChannelsPublisher.cover_card_preview_selectors[aspect]:
                try:
                    candidates = [
                        candidate
                        for candidate in page.locator(selector).all()
                        if candidate.is_visible()
                    ]
                except Exception:
                    continue
                if not candidates:
                    continue
                positioned = [
                    (candidate, center)
                    for candidate in candidates
                    if (center := ChannelsPublisher._control_center(candidate)) is not None
                ]
                # 发布页左侧还有视频预览；封面卡片位于右侧，选择最右的同类预览。
                result[aspect] = (
                    max(positioned, key=lambda item: item[1]["x"])[0]
                    if positioned
                    else candidates[-1]
                )
                logger.info(
                    "publisher_channels_cover_preview_found aspect=%s selector=%s candidates=%s",
                    aspect,
                    selector,
                    len(candidates),
                )
                break
        return result

    @staticmethod
    def _wait_for_cover_editor(
        page: Any,
        aspect: str,
        card_presence: Mapping[str, bool],
    ) -> Any | None:
        """在当前 DOM 中重新获取单张卡片入口，兼容上一张确认后的组件重建。"""
        for poll in range(80):
            preview_editor = ChannelsPublisher._cover_preview_editors_by_aspect(
                page,
                {item_aspect: item_aspect == aspect for item_aspect, _card in ChannelsPublisher.cover_cards},
            ).get(aspect)
            if preview_editor is not None:
                logger.info(
                    "publisher_channels_cover_editor_reacquired aspect=%s source=preview polls=%s",
                    aspect,
                    poll + 1,
                )
                return preview_editor
            try:
                text_editor = ChannelsPublisher._cover_editors_by_aspect(
                    page,
                    card_presence,
                ).get(aspect)
            except Exception:
                text_editor = None
            if text_editor is not None:
                logger.info(
                    "publisher_channels_cover_editor_reacquired aspect=%s source=text polls=%s",
                    aspect,
                    poll + 1,
                )
                return text_editor
            page.wait_for_timeout(750)
        logger.info("publisher_channels_cover_editor_reacquire_timeout aspect=%s", aspect)
        return None

    @staticmethod
    def _new_cover_card_present(page: Any, card: str, aspect: str) -> bool | None:
        """检测新版卡片是否存在，兼容组件的开放 Shadow DOM。"""
        try:
            return ChannelsPublisher._cover_card_label(page, card, aspect) is not None
        except Exception:
            return None

    @staticmethod
    def _open_new_cover_card(page: Any, card: str, aspect: str, editor: Any | None) -> Any | None:
        """通过卡片的可见名称和比例打开编辑弹窗，并确认该弹窗已经出现。"""
        try:
            coordinate: dict[str, float] | None = None
            if aspect == "4:3":
                # 图片的 cover-img-horizontal* 类描述的是裁切样式，并不代表分享卡片。
                # 3:4 更新后也会使用这些类。用“分享卡片”语义标签的 x 坐标，并点击
                # 其正上方的右侧卡片区域，才能保证第二张图进入 4:3 槽位。
                label = ChannelsPublisher._cover_card_label(page, card, aspect)
                coordinate = ChannelsPublisher._control_center(label) if label is not None else None
                if coordinate is None:
                    logger.info("publisher_channels_cover_card_label_position_missing aspect=%s", aspect)
                    return None
                try:
                    page.mouse.click(coordinate["x"], coordinate["y"] - 80.0)
                except Exception:
                    # 被“使用此素材”遮罩拦截时，鼠标动作可能直接失败；下方统一恢复。
                    logger.info("publisher_channels_cover_card_coordinate_intercepted aspect=%s", aspect)
                logger.info(
                    "publisher_channels_cover_card_coordinate_clicked aspect=%s",
                    aspect,
                )
            else:
                if editor is None:
                    logger.info("publisher_channels_cover_card_edit_missing aspect=%s", aspect)
                    return None
                # 与已稳定工作的竖屏单封面流程一致：封面预览上方常有组件覆盖层，
                # 普通 click 会返回成功却不触发弹窗，必须绕过可操作性拦截。
                editor.click(timeout=10000, force=True)
            logger.info(
                "publisher_channels_cover_card_edit_clicked aspect=%s",
                aspect,
            )
            page.wait_for_timeout(1500)
            if not ChannelsPublisher._cover_dialog_is_visible(page):
                if coordinate is not None:
                    ChannelsPublisher._click_cover_material_prompt_coordinate(page)
                    refreshed_label = ChannelsPublisher._cover_card_label(page, card, aspect)
                    refreshed = (
                        ChannelsPublisher._control_center(refreshed_label)
                        if refreshed_label is not None
                        else coordinate
                    )
                    page.mouse.click(refreshed["x"], refreshed["y"] - 80.0)
                    page.wait_for_timeout(1500)
                    logger.info(
                        "publisher_channels_cover_card_coordinate_retried aspect=%s",
                        aspect,
                    )
                    if not ChannelsPublisher._cover_dialog_is_visible(page):
                        page.mouse.click(refreshed["x"], refreshed["y"] - 120.0)
                        logger.info(
                            "publisher_channels_cover_card_coordinate_fallback aspect=%s",
                            aspect,
                        )
                else:
                    editor.evaluate(
                        """element => {
                            const target = element.matches('img, [class*="cover-img"]')
                                ? element
                                : element.querySelector('img, [class*="cover-img"]') || element;
                            for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                                target.dispatchEvent(new MouseEvent(type, {
                                    bubbles: true, cancelable: true, view: window, button: 0, detail: 1,
                                }));
                            }
                        }"""
                    )
                    logger.info(
                        "publisher_channels_cover_card_pointer_fallback aspect=%s",
                        aspect,
                    )
                page.wait_for_timeout(1500)
            # 缩略图出现不代表平台已生成可编辑的封面。首张卡片常在视频
            # 处理阶段被拒绝，持续重试到弹窗真正打开才上传。
            # 生成提示可能由组件绘制，文本定位不可见；以编辑弹窗出现为就绪条件。
            if not ChannelsPublisher._cover_dialog_is_visible(page):
                logger.info("publisher_channels_cover_generation_wait aspect=%s", aspect)
                for _ in range(120):
                    page.wait_for_timeout(1500)
                    if coordinate is not None:
                        label = ChannelsPublisher._cover_card_label(page, card, aspect)
                        center = ChannelsPublisher._control_center(label) if label is not None else None
                        if center is None:
                            continue
                        page.mouse.click(center["x"], center["y"] - 80.0)
                    else:
                        refreshed = ChannelsPublisher._cover_preview_editors_by_aspect(
                            page, {aspect: True},
                        ).get(aspect)
                        (refreshed if refreshed is not None else editor).click(timeout=10000, force=True)
                    page.wait_for_timeout(500)
                    if ChannelsPublisher._cover_dialog_is_visible(page):
                        logger.info("publisher_channels_cover_generation_ready aspect=%s", aspect)
                        break
                else:
                    logger.info("publisher_channels_cover_generation_timeout aspect=%s", aspect)
                    return None
            dialog = ChannelsPublisher._wait_for_cover_dialog(page, prefer_newest=True)
            if dialog is not None:
                logger.info("publisher_channels_cover_card_dialog_opened aspect=%s", aspect)
            else:
                logger.info("publisher_channels_cover_card_panel_unrecognized aspect=%s", aspect)
            return dialog
        except Exception as exc:
            logger.info(
                "publisher_channels_cover_card_edit_error aspect=%s error_type=%s",
                aspect,
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _cover_card_label(page: Any, card: str, aspect: str) -> Any | None:
        return next(
            (
                label
                for label in page.get_by_text(card, exact=True).all()
                if ChannelsPublisher._cover_control_matches_card(label, card, aspect)
            ),
            None,
        )

    @staticmethod
    def _cover_editors_by_aspect(page: Any, card_presence: Mapping[str, bool]) -> dict[str, Any]:
        """为新版封面卡片配对可见编辑入口；数量不一致时拒绝猜测。"""
        labels: dict[str, tuple[str, Any]] = {}
        for aspect, card in ChannelsPublisher.cover_cards:
            if not card_presence.get(aspect):
                continue
            label = ChannelsPublisher._cover_card_label(page, card, aspect)
            if label is not None:
                labels[aspect] = (card, label)
        try:
            editors = [
                editor
                for editor in page.get_by_text("编辑", exact=True).all()
                if ChannelsPublisher._control_center(editor) is not None
            ]
        except Exception:
            return {}

        if len(editors) != len(labels):
            logger.info(
                "publisher_channels_cover_editor_cardinality_mismatch cards=%s editors=%s",
                len(labels),
                len(editors),
            )
            return {}

        assignments: dict[str, Any] = {}
        used_editor_ids: set[int] = set()
        for aspect, (card, _label) in labels.items():
            editor = next(
                (
                    candidate
                    for candidate in editors
                    if id(candidate) not in used_editor_ids
                    and ChannelsPublisher._cover_control_matches_card(candidate, card, aspect)
                ),
                None,
            )
            if editor is not None:
                assignments[aspect] = editor
                used_editor_ids.add(id(editor))

        unresolved = [
            (aspect, label)
            for aspect, (_card, label) in labels.items()
            if aspect not in assignments
        ]
        if not unresolved:
            return assignments
        positioned_labels = [
            (aspect, center)
            for aspect, label in unresolved
            if (center := ChannelsPublisher._control_center(label)) is not None
        ]
        positioned_editors = [
            (editor, center)
            for editor in editors
            if id(editor) not in used_editor_ids
            if (center := ChannelsPublisher._control_center(editor)) is not None
        ]
        if len(positioned_labels) != len(unresolved) or len(positioned_editors) != len(unresolved):
            return {}

        # 新版横屏页的两张卡片和它们的“编辑”按钮均从左到右排列。按钮已可见即为
        # 平台允许编辑的信号，不应再用标签的垂直距离猜测视频处理状态。
        for (aspect, _label_center), (editor, _editor_center) in zip(
            sorted(positioned_labels, key=lambda item: item[1]["x"]),
            sorted(positioned_editors, key=lambda item: item[1]["x"]),
        ):
            assignments[aspect] = editor
        return assignments

    @staticmethod
    def _control_center(control: Any) -> dict[str, float] | None:
        try:
            if not control.is_visible():
                return None
        except Exception:
            return None
        center = control.evaluate(
            """element => {
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                const visible = element.offsetParent !== null || element.getClientRects().length > 0;
                if (!visible || style.visibility === 'hidden' || style.display === 'none' ||
                    style.pointerEvents === 'none' || Number(style.opacity) === 0 ||
                    rect.width <= 0 || rect.height <= 0) return null;
                return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
            }"""
        )
        if not isinstance(center, Mapping):
            return None
        x, y = center.get("x"), center.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return {"x": float(x), "y": float(y)}

    @staticmethod
    def _cover_control_matches_card(control: Any, card: str, aspect: str) -> bool:
        """从可见控件向上遍历元素与 ShadowRoot host，判断其所属封面卡片。"""
        return bool(control.evaluate(
            """(start, {card, aspect, cardLabels}) => {
                const visible = (element) => element &&
                    (element.offsetParent !== null || element.getClientRects().length > 0);
                const nextContainer = (element) => {
                    if (element.parentElement) return element.parentElement;
                    const root = element.getRootNode && element.getRootNode();
                    return root && root.host instanceof Element ? root.host : null;
                };
                const hasExactLabel = (container, name) =>
                    (container.textContent || '').trim() === name ||
                    Array.from(container.querySelectorAll('*')).some((element) =>
                        (element.textContent || '').trim() === name
                    );
                for (let depth = 0, container = start; depth < 10 && container;
                    depth += 1, container = nextContainer(container)) {
                    if (!visible(container)) continue;
                    const text = container.textContent || '';
                    if (!text.includes(card) || !text.includes(aspect)) continue;
                    if (cardLabels.some((name) => name !== card && hasExactLabel(container, name))) continue;
                    return true;
                }
                return false;
            }""",
            {"card": card, "aspect": aspect, "cardLabels": [item[1] for item in ChannelsPublisher.cover_cards]},
        ))

    @staticmethod
    def _upload_legacy_cover(page: Any, path: str) -> bool:
        """旧版只有一个封面入口时，打开弹窗并上传优先选择的单张封面。"""
        try:
            # 等封面缩略图稳定（视频处理完成、封面区不再重渲染），否则点击会落空。
            thumb = page.locator("img.cover-img-vertical").first
            thumb.wait_for(state="attached", timeout=60000)
            previous_src: Any = None
            stable_since = time.monotonic()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                src = thumb.get_attribute("src")
                if src is None:
                    break  # 拿不到 src（如测试替身），不再等待
                if src != previous_src:
                    previous_src = src
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 3:
                    break
                page.wait_for_timeout(500)
        except Exception:
            logger.info("publisher_channels_cover_thumbnail_missing")
            return False
        opened = False
        triggers = page.locator(ChannelsPublisher.cover_trigger_selector)
        for _attempt in range(4):
            for index in range(triggers.count()):
                try:
                    triggers.nth(index).click(force=True, timeout=3000)
                except Exception:
                    continue
                page.wait_for_timeout(1500)
                if ChannelsPublisher._cover_dialog_is_visible(page):
                    opened = True
                    break
            if opened:
                break
        if not opened:
            # 兜底：直接 JS 派发点击缩略图
            try:
                page.locator("img.cover-img-vertical").first.evaluate(
                    """img => {
                        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                            img.dispatchEvent(new MouseEvent(type, {
                                bubbles: true, cancelable: true, view: window, button: 0, detail: 1,
                            }));
                        }
                    }"""
                )
                page.wait_for_timeout(2000)
                opened = ChannelsPublisher._cover_dialog_is_visible(page)
            except Exception:
                pass
        if not opened:
            logger.info("publisher_channels_cover_dialog_open_failed")
            return False
        dialog = ChannelsPublisher._wait_for_cover_dialog(page, prefer_newest=True)
        return bool(dialog) and ChannelsPublisher._upload_cover_dialog(page, dialog, path)

    @staticmethod
    def _wait_for_cover_dialog(page: Any, *, prefer_newest: bool = False) -> Any | None:
        for selector in ChannelsPublisher.cover_dialog_selectors:
            locator = page.locator(selector)
            dialog = locator.last if prefer_newest else locator.first
            try:
                dialog.wait_for(state="visible", timeout=15000)
                return dialog
            except Exception as exc:
                logger.info(
                    "publisher_channels_cover_panel_wait_failed selector=%s error_type=%s",
                    selector,
                    type(exc).__name__,
                )
                continue
        logger.info("publisher_channels_cover_dialog_missing")
        return None

    @staticmethod
    def _cover_dialog_is_visible(page: Any) -> bool:
        for selector in ChannelsPublisher.cover_dialog_selectors:
            try:
                if page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _upload_cover_dialog(
        page: Any,
        dialog: Any,
        path: str,
        *,
        aspect: str | None = None,
    ) -> bool:
        """向已打开的编辑封面弹窗上传图片并确认应用。"""
        cover_input = dialog.locator(ChannelsPublisher.cover_selector).first
        try:
            cover_input.wait_for(state="attached", timeout=30000)
            cover_input.set_input_files(path, timeout=60000)
            logger.info("publisher_channels_cover_file_uploaded")
        except Exception as exc:
            logger.info("publisher_channels_cover_file_upload_failed error_type=%s", type(exc).__name__)
            return False
        # 上传的图片需要几秒处理；等它在弹窗里以 blob/data 预览出现后再点"确认"，
        # 否则弹窗会直接应用旧的视频帧封面。
        upload_preview = dialog.locator('img[src^="blob:"], img[src^="data:"]').first
        try:
            upload_preview.wait_for(state="attached", timeout=25000)
            logger.info("publisher_channels_cover_preview_ready")
        except Exception:
            page.wait_for_timeout(6000)
            logger.info("publisher_channels_cover_preview_timeout")
        confirmed = False
        for text in ("确认", "确定", "完成"):
            try:
                dialog.get_by_text(text, exact=True).first.click(timeout=4000)
                logger.info("publisher_channels_cover_confirm_clicked text=%s", text)
                confirmed = True
                break
            except Exception:
                continue
        if not confirmed:
            logger.info("publisher_channels_cover_confirm_missing")
            return False
        try:
            dialog.wait_for(state="hidden", timeout=15000)
        except Exception:
            logger.info("publisher_channels_cover_dialog_close_timeout")
            return False
        return ChannelsPublisher._confirm_cover_material_prompt(page, aspect=aspect)

    @staticmethod
    def _confirm_cover_material_prompt(page: Any, *, aspect: str | None = None) -> bool:
        """确认上传后的“使用此素材”提示，避免其遮罩拦截下一张卡片。"""
        use_material = page.get_by_text("使用素材", exact=True).last
        try:
            use_material.wait_for(state="visible", timeout=5000)
        except Exception:
            return True
        try:
            use_material.click(timeout=5000)
            logger.info("publisher_channels_cover_material_confirm_clicked")
            use_material.wait_for(state="hidden", timeout=10000)
            logger.info("publisher_channels_cover_material_prompt_closed")
            return True
        except Exception as exc:
            logger.info(
                "publisher_channels_cover_material_prompt_failed error_type=%s",
                type(exc).__name__,
            )
            return False

    @staticmethod
    def _click_cover_material_prompt_coordinate(page: Any) -> bool:
        """4:3 被遮罩拦截后，按个人主页卡片位置点击提示框中的“使用素材”。"""
        label = ChannelsPublisher._cover_card_label(page, "个人主页卡片", "3:4")
        center = ChannelsPublisher._control_center(label) if label is not None else None
        if center is None:
            logger.info("publisher_channels_cover_material_coordinate_missing")
            return False
        try:
            logger.info(
                "publisher_channels_cover_material_coordinate_target x=%.1f y=%.1f",
                center["x"] - 35.0,
                center["y"] + 6.0,
            )
            page.mouse.click(center["x"] - 35.0, center["y"] + 6.0)
            page.wait_for_timeout(1500)
            logger.info("publisher_channels_cover_material_coordinate_clicked")
            return True
        except Exception as exc:
            logger.info(
                "publisher_channels_cover_material_coordinate_failed error_type=%s",
                type(exc).__name__,
            )
            return False

    @staticmethod
    def _is_login_page(url: str) -> bool:
        return url.startswith(ChannelsPublisher.login_url)

    @staticmethod
    def _description(draft: Mapping[str, Any]) -> str:
        return DouyinPublisher._description(draft)


@dataclass
class PublishTask:
    task_id: str
    account_id: str
    script_id: str
    platform: str
    status: str = "queued"
    message: str = "发布填充任务已创建。"
    manual_review_url: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    terminal_at: float | None = field(default=None, repr=False)

    def public_view(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "accountId": self.account_id,
            "scriptId": self.script_id,
            "platform": self.platform,
            "status": self.status,
            "message": self.message,
            "manualReviewUrl": self.manual_review_url,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class PublisherService:
    def __init__(
        self,
        workspace_dir: Path,
        *,
        browser_factory: Callable[..., Any] | None = None,
        adapters: Mapping[str, Any] | None = None,
        executor: Executor | None = None,
        monotonic: Callable[[], float] | None = None,
        task_retention_seconds: float = DEFAULT_TASK_RETENTION_SECONDS,
    ) -> None:
        if task_retention_seconds <= 0:
            raise ValueError("task_retention_seconds must be positive")
        self._workspace_dir = Path(workspace_dir)
        self._tasks_dir = self._workspace_dir / "publisher-tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._profiles_dir = self._workspace_dir / "publisher-profiles"
        from .publisher_identity import IdentityCache
        self.identity_cache = IdentityCache(self._workspace_dir)
        self._browser_factory = browser_factory or _default_browser_factory
        self._adapters: dict[str, Any] = {
            "douyin": DouyinPublisher(),
            "channels": ChannelsPublisher(),
        }
        if adapters is not None:
            self._adapters.update(adapters)
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="publisher")
        self._tasks: dict[str, PublishTask] = {}
        self._active_task_ids: dict[tuple[str, str, str], str] = {}
        self._account_sessions: dict[str, Any] = {}
        self._account_platforms: dict[str, str] = {}
        self._account_workers: dict[str, ThreadPoolExecutor] = {}
        self._review_pages: dict[str, tuple[str, Any]] = {}
        self._snapshot_task_ids: set[str] = set()
        self._task_futures: list[Any] = []
        self._lock = threading.Lock()
        self._monotonic = monotonic or time.monotonic
        self._task_retention_seconds = float(task_retention_seconds)
        self._closed = False
        self._restore_interrupted_tasks()

    def _task_path(self, task_id: str) -> Path:
        return self._tasks_dir / f"{task_id}.json"

    def _persist_task_locked(self, task: PublishTask) -> None:
        path = self._task_path(task.task_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(task.public_view(), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _restore_interrupted_tasks(self) -> None:
        for path in self._tasks_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                task = PublishTask(
                    task_id=str(payload["taskId"]), account_id=str(payload["accountId"]), script_id=str(payload["scriptId"]),
                    platform=str(payload["platform"]), status="failed", message="服务重启，发布填充已中断，请重新发起。",
                    created_at=str(payload.get("createdAt") or self._now()), updated_at=self._now(), terminal_at=self._monotonic(),
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            self._tasks[task.task_id] = task
            self._persist_task_locked(task)

    def account_identity(self, account_id: str, platform: str) -> dict[str, Any]:
        """Local-only lookup, safe on every overview load and after a restart."""
        self._validate_identifier(account_id, "账号")
        self._adapter(platform)
        return self.identity_cache.get(account_id, platform)

    def refresh_account_identity(self, account_id: str, platform: str, *, initial: bool = False) -> dict[str, Any]:
        self._validate_identifier(account_id, "账号")
        self._adapter(platform)
        return self._account_worker(account_id).submit(
            self._refresh_identity_on_worker, account_id, platform, initial
        ).result()

    def _refresh_identity_on_worker(self, account_id: str, platform: str, initial: bool) -> dict[str, Any]:
        from .publisher_identity import read_identity
        cached = self.identity_cache.get(account_id, platform)
        if account_id in self.identity_cache.deleted or (initial and not cached["needsInitialRead"]):
            return cached
        # Claim the first attempt before opening a browser, including crash/failure paths.
        self.identity_cache.record(account_id, platform, {"status": "unknown"})
        profile = self._profile_path(account_id)
        if not any(profile.iterdir()):
            return self.identity_cache.record(account_id, platform, {"status": "unbound"})
        try:
            outcome = self._check_login_on_worker(account_id, platform, self._adapter(platform), profile, read_identity)
        except Exception:
            outcome = {"status": "unknown"}
        return self.identity_cache.record(account_id, platform, outcome)

    def capture_account_identity(self, account_id: str, platform: str, page: Any, *, status: str = "logged_in") -> None:
        """Called on the account worker using a page already opened by login/collection."""
        if platform != "douyin":
            return
        from .publisher_identity import read_identity
        try:
            outcome = read_identity(page, self._adapter(platform), known_status=status)
            self.identity_cache.record(account_id, platform, outcome)
        except Exception:
            logger.info("publisher_identity_cache_update_failed account=%s", account_id)

    def _login_state_and_cache(self, account_id: str, platform: str, page: Any, adapter: Any) -> str:
        status = adapter.login_state(page)
        self.capture_account_identity(account_id, platform, page, status=status)
        return status

    def delete_account_identity(self, account_id: str) -> None:
        # The cache lock/tombstone also rejects an in-flight worker's late write.
        self.identity_cache.delete(account_id)

    def check_login(self, account_id: str, platform: str) -> dict[str, Any]:
        self._reap_expired_tasks()
        adapter = self._adapter(platform)
        profile = self._profile_path(account_id)
        worker = self._account_worker(account_id)
        try:
            status = worker.submit(self._check_login_on_worker, account_id, platform, adapter, profile).result()
        except PublisherError:
            raise
        except Exception as exc:
            raise PublisherError("browser_unavailable", "无法检查平台登录状态。") from exc
        messages = {
            "logged_in": "已登录。",
            "login_required": "需要登录。",
            "unknown": "暂时无法确认登录状态。",
        }
        safe_status = status if status in messages else "unknown"
        return {
            "platform": platform,
            "status": safe_status,
            "message": messages[safe_status],
            "loginUrl": adapter.login_url,
        }

    def open_login(self, account_id: str, platform: str) -> dict[str, Any]:
        self._reap_expired_tasks()
        adapter = self._adapter(platform)
        profile = self._profile_path(account_id)
        worker = self._account_worker(account_id)
        try:
            worker.submit(self._open_login_on_worker, account_id, platform, adapter, profile).result()
        except PublisherError:
            raise
        except Exception as exc:
            raise PublisherError("browser_unavailable", "无法打开平台登录页。") from exc
        return {
            "platform": platform,
            "status": "login_opened",
            "message": "已打开登录页，请在浏览器中完成登录。",
            "loginUrl": adapter.login_url,
        }

    def run_on_account_page(
        self,
        account_id: str,
        platform: str,
        callback: Callable[[Any], Any],
    ) -> Any:
        """在账号专用浏览器里执行一次短任务（复盘采集走这里）。

        复用「脚本 → 发布」的资料目录与登录状态：同一账号的发布和采集共用该账号的
        单线程 worker，不会同时操作浏览器；回调只拿到一个新标签页，调用结束就关掉，
        不触碰用户正在看或正在填充的页面。回调自身抛出的异常原样向上传递。
        """
        self._reap_expired_tasks()
        self._adapter(platform)
        profile = self._profile_path(account_id)
        self._ensure_open()
        worker = self._account_worker(account_id)
        try:
            future = worker.submit(
                self._run_on_account_page_on_worker, account_id, platform, profile, callback
            )
        except Exception as exc:
            raise PublisherError("browser_unavailable", "无法在账号专用浏览器中执行任务。") from exc
        return future.result()

    def run_on_account_background_page(
        self,
        account_id: str,
        platform: str,
        callback: Callable[[Any], Any],
    ) -> Any:
        """在独立无头会话采集，保留账号已有的登录/发布页面。"""
        self._reap_expired_tasks()
        self._adapter(platform)
        profile = self._profile_path(account_id)
        self._ensure_open()
        worker = self._account_worker(account_id)
        return worker.submit(
            self._run_on_account_background_page_on_worker, account_id, profile, callback
        ).result()

    def _run_on_account_background_page_on_worker(
        self, account_id: str, profile: Path, callback: Callable[[Any], Any]
    ) -> Any:
        with self._lock:
            existing = self._account_sessions.get(account_id)
        try:
            session = (existing.new_headless_session() if existing is not None
                       else self._browser_factory(profile, headless=True))
        except PublisherError:
            raise
        except Exception as exc:
            raise PublisherError("browser_unavailable", "无法启动账号后台采集浏览器，请检查账号登录状态后重试。") from exc
        try:
            return callback(self._session_page(session))
        finally:
            try:
                self._close_session(session)
            except Exception:
                logger.info("publisher_background_close_failed account=%s", account_id)

    def close_account_browser(self, account_id: str) -> bool:
        """采集结束后在所属线程关闭会话，保留仍需人工确认的发布窗口。"""
        with self._lock:
            worker = self._account_workers.get(account_id)
        if worker is None:
            return False
        return worker.submit(self._close_idle_account_browser_on_worker, account_id).result()

    def _close_idle_account_browser_on_worker(self, account_id: str) -> bool:
        with self._lock:
            if any(task.account_id == account_id and task.status in MOVE_BLOCKING_TASK_STATUSES
                   for task in self._tasks.values()):
                return False
        self._discard_account_session_on_worker(account_id)
        return True

    def _run_on_account_page_on_worker(
        self,
        account_id: str,
        platform: str,
        profile: Path,
        callback: Callable[[Any], Any],
    ) -> Any:
        page, owned = self._open_temporary_page_on_worker(account_id, platform, profile)
        try:
            return callback(page)
        finally:
            if owned:
                close_page = getattr(page, "close", None)
                if callable(close_page):
                    try:
                        close_page()
                    except Exception:
                        logger.info("publisher_temp_page_close_failed account=%s", account_id)

    def _open_temporary_page_on_worker(
        self,
        account_id: str,
        platform: str,
        profile: Path,
    ) -> tuple[Any, bool]:
        """取该账号会话里的新标签页；会话不存在时就地启动，失效时重建一次。"""
        last_error: Exception | None = None
        for _attempt in range(2):
            with self._lock:
                session = self._account_sessions.get(account_id)
            if session is None:
                try:
                    session = self._browser_factory(profile, headless=False)
                except PublisherError:
                    raise
                except Exception as exc:
                    raise PublisherError("browser_unavailable", "无法启动账号专用浏览器。") from exc
                with self._lock:
                    self._account_sessions[account_id] = session
                    self._account_platforms[account_id] = platform
            try:
                return self._new_session_page(session)
            except Exception as exc:
                last_error = exc
                self._discard_account_session_on_worker(account_id)
        raise PublisherError("browser_unavailable", "账号专用浏览器页面不可用。") from last_error

    def start_fill(
        self,
        account_id: str,
        script_id: str,
        platform: str,
        draft: Mapping[str, Any],
        assets: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._reap_expired_tasks()
        self._adapter(platform)
        self._validate_identifier(script_id, "脚本")
        self._profile_path(account_id)
        self._ensure_open()
        if not isinstance(draft, Mapping):
            raise PublisherError("invalid_draft", "发布文案无效。")
        resolved_assets = self._resolve_assets(script_id, assets)
        task_key = (account_id, script_id, platform)
        with self._lock:
            active_task_id = self._active_task_ids.get(task_key)
            active_task = self._tasks.get(active_task_id) if active_task_id is not None else None
            if active_task is not None and active_task.status in ACTIVE_TASK_STATUSES:
                return active_task.public_view()
            task = PublishTask(
                task_id=str(uuid.uuid4()),
                account_id=account_id,
                script_id=script_id,
                platform=platform,
            )
            self._tasks[task.task_id] = task
            self._active_task_ids[task_key] = task.task_id
            self._persist_task_locked(task)
        try:
            task_assets = self._snapshot_assets(task.task_id, resolved_assets)
        except Exception:
            self._remove_task_record(task.task_id)
            raise
        try:
            future = self._executor.submit(self._run_fill, task.task_id, dict(draft), task_assets)
        except Exception as exc:
            self._remove_task_record(task.task_id)
            self._cleanup_task_assets(task.task_id)
            raise PublisherError("publish_task_start_failed", "无法启动发布填充任务。") from exc
        with self._lock:
            self._task_futures.append(future)
            view = task.public_view()
        add_done_callback = getattr(future, "add_done_callback", None)
        if callable(add_done_callback):
            add_done_callback(self._forget_future)
        return view

    def get_task(self, task_id: str) -> dict[str, Any]:
        self._reap_expired_tasks()
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise PublisherError("publish_task_not_found", "发布填充任务不存在。")
            return task.public_view()

    def dismiss_task(self, task_id: str) -> dict[str, str]:
        self._reap_expired_tasks()
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise PublisherError("publish_task_not_found", "发布填充任务不存在。")
            if task.terminal_at is None:
                raise PublisherError("publish_task_active", "发布填充任务仍在进行中。")
        self._discard_terminal_task(task_id)
        return {"taskId": task_id, "status": "dismissed"}

    def prepare_script_deletion(self, script_id: str) -> None:
        """Block active fills and discard terminal review snapshots for one script."""
        self._validate_identifier(script_id, "脚本")
        self._reap_expired_tasks()
        with self._lock:
            matching_tasks = [task for task in self._tasks.values() if task.script_id == script_id]
            if any(task.status in ACTIVE_TASK_STATUSES for task in matching_tasks):
                raise PublisherError("publish_task_active", "发布填充任务仍在进行中，请完成后再删除脚本。")
            terminal_task_ids = [task.task_id for task in matching_tasks if task.terminal_at is not None]
        for task_id in terminal_task_ids:
            self._discard_terminal_task(task_id)

    def prepare_script_move(self, script_id: str) -> None:
        """Reject moves while a script can still operate in its original account session."""
        self._validate_identifier(script_id, "脚本")
        self._reap_expired_tasks()
        with self._lock:
            has_blocking_task = any(
                task.script_id == script_id and task.status in MOVE_BLOCKING_TASK_STATUSES
                for task in self._tasks.values()
            )
        if has_blocking_task:
            raise PublisherError("publish_task_active", "发布流程仍在进行或等待人工审核，请完成或取消后再移动脚本。")

    def _reap_expired_tasks(self) -> None:
        now = self._monotonic()
        with self._lock:
            expired_task_ids = [
                task.task_id
                for task in self._tasks.values()
                if task.terminal_at is not None
                and now - task.terminal_at >= self._task_retention_seconds
            ]
        for task_id in expired_task_ids:
            try:
                self._discard_terminal_task(task_id)
            except Exception as exc:
                logger.error(
                    "publisher_task_cleanup_failed task_id=%s error_type=%s detail=%s",
                    task_id,
                    type(exc).__name__,
                    _sanitized_exception_detail(exc),
                )

    def _discard_terminal_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.terminal_at is None:
                return
            self._tasks.pop(task_id, None)
            self._clear_active_task_locked(task)
            review = self._review_pages.get(task_id)
            self._task_path(task_id).unlink(missing_ok=True)
        cleanup_error = None
        if review is not None:
            account_id, _page = review
            worker = self._account_worker(account_id)
            try:
                worker.submit(self._close_review_page_on_worker, task_id).result()
            except Exception as exc:
                cleanup_error = exc
        try:
            self._cleanup_task_assets(task_id)
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            raise cleanup_error

    def _close_review_page_on_worker(self, task_id: str) -> None:
        with self._lock:
            review = self._review_pages.pop(task_id, None)
        if review is None:
            return
        _account_id, page = review
        close_page = getattr(page, "close", None)
        if callable(close_page):
            close_page()

    def _remove_task_record(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if task is not None:
                self._clear_active_task_locked(task)
                self._task_path(task_id).unlink(missing_ok=True)

    def _clear_active_task_locked(self, task: PublishTask) -> None:
        task_key = (task.account_id, task.script_id, task.platform)
        if self._active_task_ids.get(task_key) == task.task_id:
            self._active_task_ids.pop(task_key, None)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = list(self._task_futures)
        for future in futures:
            try:
                future.result()
            except Exception:
                pass
        if self._owns_executor:
            shutdown = getattr(self._executor, "shutdown", None)
            if callable(shutdown):
                shutdown(wait=True)
        with self._lock:
            workers = list(self._account_workers.items())
        cleanup_error = None
        for account_id, worker in workers:
            try:
                worker.submit(self._close_account_on_worker, account_id).result()
            except Exception as exc:
                cleanup_error = cleanup_error or exc
            finally:
                worker.shutdown(wait=True)
        with self._lock:
            self._account_workers.clear()
            snapshot_task_ids = list(self._snapshot_task_ids)
        for task_id in snapshot_task_ids:
            try:
                self._cleanup_task_assets(task_id)
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        with self._lock:
            self._review_pages.clear()
            self._tasks.clear()
            self._active_task_ids.clear()
        if cleanup_error is not None:
            raise cleanup_error

    def _run_fill(self, task_id: str, draft: dict[str, Any], assets: dict[str, Any]) -> None:
        with self._lock:
            task = self._tasks[task_id]
            adapter = self._adapters[task.platform]
            task.status = "running"
            task.message = "正在打开平台并填充素材。"
            task.updated_at = self._now()
            self._persist_task_locked(task)
        retain_snapshot = False
        try:
            profile = self._profile_path(task.account_id)
            worker = self._account_worker(task.account_id)
            fill_result = worker.submit(
                self._fill_on_worker,
                task.task_id,
                task.account_id,
                task.platform,
                adapter,
                profile,
                draft,
                assets,
            ).result()
            with self._lock:
                task.status = "waiting_for_review"
                task.message = self._manual_review_message(fill_result)
                task.manual_review_url = adapter.publish_url
                task.updated_at = self._now()
                task.terminal_at = self._monotonic()
                self._clear_active_task_locked(task)
                self._persist_task_locked(task)
                retain_snapshot = True
        except Exception as exc:
            logger.error(
                "publisher_fill_failed task_id=%s platform=%s error_type=%s detail=%s",
                task.task_id,
                task.platform,
                type(exc).__name__,
                _sanitized_exception_detail(exc),
            )
            with self._lock:
                task.status = "failed"
                task.message = "自动填充失败，请重试。"
                task.updated_at = self._now()
                task.terminal_at = self._monotonic()
                self._clear_active_task_locked(task)
                self._persist_task_locked(task)
        finally:
            if not retain_snapshot:
                try:
                    self._cleanup_task_assets(task_id)
                except Exception as exc:
                    logger.error(
                        "publisher_snapshot_cleanup_failed task_id=%s platform=%s error_type=%s detail=%s",
                        task.task_id,
                        task.platform,
                        type(exc).__name__,
                        _sanitized_exception_detail(exc),
                    )

    def _check_login_on_worker(
        self,
        account_id: str,
        platform: str,
        adapter: Any,
        profile: Path,
        identity_reader: Callable[..., Any] | None = None,
    ) -> Any:
        with self._lock:
            session = self._account_sessions.get(account_id)
        if session is not None:
            check_page = None
            owned_page = False
            try:
                # 用独立标签页检测，避免把用户正在看的标签页拽回登录页。
                check_page, owned_page = self._new_session_page(session)
                check_page.goto(self._login_check_url(adapter))
                with self._lock:
                    self._account_platforms[account_id] = platform
                return identity_reader(check_page, adapter) if identity_reader else self._login_state_and_cache(account_id, platform, check_page, adapter)
            except Exception:
                self._discard_account_session_on_worker(account_id)
            finally:
                if check_page is not None and owned_page:
                    close_page = getattr(check_page, "close", None)
                    if callable(close_page):
                        close_page()
        temporary_session = None
        try:
            temporary_session = self._browser_factory(profile, headless=True)
            page = self._session_page(temporary_session)
            page.goto(self._login_check_url(adapter))
            return identity_reader(page, adapter) if identity_reader else self._login_state_and_cache(account_id, platform, page, adapter)
        finally:
            if temporary_session is not None:
                self._close_session(temporary_session)

    def _open_login_on_worker(
        self,
        account_id: str,
        platform: str,
        adapter: Any,
        profile: Path,
    ) -> None:
        with self._lock:
            session = self._account_sessions.get(account_id)
        if session is not None:
            page = None
            try:
                page, _owned = self._new_session_page(session)
                page.goto(adapter.login_url)
                with self._lock:
                    self._account_platforms[account_id] = platform
                return
            except Exception:
                close_page = getattr(page, "close", None) if page is not None else None
                if callable(close_page):
                    close_page()
                self._discard_account_session_on_worker(account_id)
        session = None
        try:
            session = self._browser_factory(profile, headless=False)
            self._session_page(session).goto(adapter.login_url)
        except Exception:
            if session is not None:
                self._close_session(session)
            raise
        with self._lock:
            self._account_sessions[account_id] = session
            self._account_platforms[account_id] = platform

    def _fill_on_worker(
        self,
        task_id: str,
        account_id: str,
        platform: str,
        adapter: Any,
        profile: Path,
        draft: dict[str, Any],
        assets: dict[str, Any],
    ) -> None:
        page = None
        for attempt in range(2):
            with self._lock:
                session = self._account_sessions.get(account_id)
            if session is None:
                session = self._browser_factory(profile, headless=False)
                with self._lock:
                    self._account_sessions[account_id] = session
                    self._account_platforms[account_id] = platform
            try:
                new_page = getattr(session, "new_page", None)
                page = new_page() if callable(new_page) else self._session_page(session)
                break
            except Exception:
                self._discard_account_session_on_worker(account_id)
                if attempt == 1:
                    raise
        try:
            page.goto(self._fill_url(adapter))
            fill_result = adapter.fill(page, draft, assets)
        except Exception:
            close_page = getattr(page, "close", None)
            if callable(close_page):
                close_page()
            raise
        with self._lock:
            self._review_pages[task_id] = (account_id, page)
            self._account_platforms[account_id] = platform
        return fill_result

    @staticmethod
    def _manual_review_message(fill_result: Any) -> str:
        base = "素材与文案已填充"
        warnings = fill_result if isinstance(fill_result, (list, tuple)) else []
        safe_warnings = [str(item).strip() for item in warnings if str(item).strip()]
        if safe_warnings:
            return f"{base}；但{'、'.join(safe_warnings)}，请在浏览器中检查并手动发布。"
        return f"{base}，请在浏览器中检查并手动发布。"

    def _resolve_assets(self, script_id: str, assets: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(assets, Mapping):
            raise PublisherError("invalid_assets", "发布素材无效。")
        root = PublishAssetsStore(self._workspace_dir)._safe_asset_dir(script_id, create=False).resolve()
        video = self._resolve_asset(assets.get("video"), root, VIDEO_EXTENSIONS, "视频")
        covers_value = assets.get("covers")
        if covers_value is None:
            covers_value = {}
        if not isinstance(covers_value, Mapping):
            raise PublisherError("invalid_assets", "封面素材无效。")
        covers: dict[str, Any] = {}
        for aspect in ("3:4", "4:3"):
            if covers_value.get(aspect) is not None:
                covers[aspect] = self._resolve_asset(covers_value[aspect], root, IMAGE_EXTENSIONS, "图片")
        return {"video": video, "covers": covers}

    def _snapshot_assets(self, task_id: str, assets: Mapping[str, Any]) -> dict[str, Any]:
        snapshot_dir = self._task_asset_dir(task_id, create=True)
        try:
            video = self._copy_snapshot_asset(assets["video"], snapshot_dir, "video")
            covers: dict[str, Any] = {}
            for aspect, stem in (("3:4", "cover-3x4"), ("4:3", "cover-4x3")):
                asset = assets.get("covers", {}).get(aspect)
                if asset is not None:
                    covers[aspect] = self._copy_snapshot_asset(asset, snapshot_dir, stem)
            with self._lock:
                self._snapshot_task_ids.add(task_id)
            return {"video": video, "covers": covers}
        except Exception:
            self._cleanup_task_assets(task_id)
            raise

    @staticmethod
    def _copy_snapshot_asset(asset: Mapping[str, Any], snapshot_dir: Path, stem: str) -> dict[str, str]:
        source = Path(str(asset["path"]))
        destination = snapshot_dir / f"{stem}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        return {"name": str(asset.get("name") or source.name), "path": str(destination.resolve())}

    def _task_asset_dir(self, task_id: str, *, create: bool) -> Path:
        self._validate_identifier(task_id, "任务")
        workspace = self._workspace_dir.resolve()
        root = self._workspace_dir / "publisher-task-assets"
        task_dir = root / task_id
        for component in (root, task_dir):
            if component.is_symlink():
                raise PublisherError("unsafe_asset_path", "任务素材路径不安全。")
        resolved = task_dir.resolve()
        if not PublishAssetsStore._is_relative_to(resolved, workspace):
            raise PublisherError("unsafe_asset_path", "任务素材路径不安全。")
        if create:
            task_dir.mkdir(parents=True, exist_ok=False)
        return task_dir

    def _cleanup_task_assets(self, task_id: str) -> None:
        task_dir = self._task_asset_dir(task_id, create=False)
        if task_dir.is_dir():
            shutil.rmtree(task_dir)
        with self._lock:
            self._snapshot_task_ids.discard(task_id)

    def _resolve_asset(
        self,
        metadata: Any,
        root: Path,
        extensions: set[str],
        label: str,
    ) -> dict[str, Any]:
        if not isinstance(metadata, Mapping) or not isinstance(metadata.get("path"), str):
            raise PublisherError("invalid_assets", f"{label}素材无效。")
        candidate = (self._workspace_dir / metadata["path"]).resolve()
        if not PublishAssetsStore._is_relative_to(candidate, root):
            raise PublisherError("unsafe_asset_path", f"{label}素材路径不安全。")
        source = PublishAssetsStore._validate_source(candidate, extensions, label)
        return {"name": str(metadata.get("name") or source.name), "path": str(source)}

    def _profile_path(self, account_id: str) -> Path:
        self._validate_identifier(account_id, "账号")
        workspace = self._workspace_dir.resolve()
        if self._profiles_dir.is_symlink():
            raise PublisherError("unsafe_profile_path", "账号资料路径不安全。")
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        profiles = self._profiles_dir.resolve()
        if not PublishAssetsStore._is_relative_to(profiles, workspace):
            raise PublisherError("unsafe_profile_path", "账号资料路径不安全。")
        path = self._profiles_dir / account_id
        if path.is_symlink():
            raise PublisherError("unsafe_profile_path", "账号资料路径不安全。")
        path.mkdir(parents=True, exist_ok=True)
        if not PublishAssetsStore._is_relative_to(path.resolve(), profiles):
            raise PublisherError("unsafe_profile_path", "账号资料路径不安全。")
        return path

    def _account_worker(self, account_id: str) -> ThreadPoolExecutor:
        with self._lock:
            if self._closed:
                raise PublisherError("publisher_closed", "发布服务已关闭。")
            worker = self._account_workers.get(account_id)
            if worker is None:
                worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"publisher-{account_id}")
                self._account_workers[account_id] = worker
            return worker

    def _discard_account_session_on_worker(self, account_id: str) -> None:
        with self._lock:
            session = self._account_sessions.pop(account_id, None)
            self._account_platforms.pop(account_id, None)
            review_task_ids = [
                task_id
                for task_id, (review_account_id, _page) in self._review_pages.items()
                if review_account_id == account_id
            ]
            for task_id in review_task_ids:
                self._review_pages.pop(task_id, None)
        if session is not None:
            self._close_session(session)

    def _close_account_on_worker(self, account_id: str) -> None:
        self._discard_account_session_on_worker(account_id)

    def _ensure_open(self) -> None:
        with self._lock:
            if self._closed:
                raise PublisherError("publisher_closed", "发布服务已关闭。")

    def _forget_future(self, future: Any) -> None:
        with self._lock:
            try:
                self._task_futures.remove(future)
            except ValueError:
                pass

    def _adapter(self, platform: str) -> Any:
        if platform not in PLATFORMS or platform not in self._adapters:
            raise PublisherError("invalid_platform", "发布平台无效。")
        return self._adapters[platform]

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        PublishAssetsStore._validate_identifier(value, label)

    @staticmethod
    def _session_page(session: Any) -> Any:
        page = getattr(session, "page", None)
        if page is None:
            raise PublisherError("browser_unavailable", "浏览器页面不可用。")
        return page

    @staticmethod
    def _new_session_page(session: Any) -> tuple[Any, bool]:
        """在既有会话里开一个新标签页；返回 (page, 是否由本次创建)。
        检测登录/打开登录页都不要动用户当前正在看的标签页。"""
        new_page = getattr(session, "new_page", None)
        if callable(new_page):
            return new_page(), True
        return PublisherService._session_page(session), False

    @staticmethod
    def _login_check_url(adapter: Any) -> str:
        return str(getattr(adapter, "check_url", "") or adapter.login_url)

    @staticmethod
    def _fill_url(adapter: Any) -> str:
        return str(getattr(adapter, "fill_url", "") or adapter.publish_url)

    @staticmethod
    def _close_session(session: Any) -> None:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


class _PlaywrightSession:
    def __init__(self, playwright: Any, context: Any, *, browser: Any = None) -> None:
        self._playwright = playwright
        self._context = context
        # 独立后台 browser 借用原会话 runtime，不能在结束时 stop 原 runtime。
        self._browser = browser
        self.page = context.pages[0] if context.pages else context.new_page()

    def new_page(self) -> Any:
        return self._context.new_page()

    def new_headless_session(self) -> "_PlaywrightSession":
        state = self._context.storage_state()
        browser = self._playwright.chromium.launch(
            channel="chrome", headless=True, args=["--no-proxy-server"],
        )
        try:
            context = browser.new_context(storage_state=state)
            return _PlaywrightSession(self._playwright, context, browser=browser)
        except BaseException:
            browser.close()
            raise

    def close(self) -> None:
        try:
            self._context.close()
        finally:
            if self._browser is not None:
                self._browser.close()
            else:
                self._playwright.stop()


# Chrome 被强杀后会在资料目录留下单实例锁；带着残留锁启动会再被强杀一次，
# macOS 每次都会弹「Google Chrome 意外退出」。启动前清理属于已退出进程的锁文件。
_PROFILE_LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def clear_stale_profile_locks(profile_path: Path) -> list[str]:
    """清掉没有人持有的 Chrome 单实例锁，只在确认进程已退出时删除。"""
    cleared: list[str] = []
    for name in _PROFILE_LOCK_NAMES:
        lock = Path(profile_path) / name
        if not lock.exists() and not lock.is_symlink():
            continue
        if _profile_lock_is_live(lock):
            continue
        try:
            lock.unlink()
            cleared.append(name)
        except OSError:
            continue
    return cleared


def _profile_lock_is_live(lock: Path) -> bool:
    """SingletonLock 是指向 <host>-<pid> 的符号链接；进程还在就说明浏览器仍在运行。"""
    try:
        target = os.readlink(lock) if lock.is_symlink() else ""
    except OSError:
        target = ""
    pid_text = target.rsplit("-", 1)[-1] if target else ""
    if not pid_text.isdigit() or len(pid_text) > 9:
        # SingletonCookie 那类文件名是一串随机数字，明显超出 pid 范围，直接当作非进程锁。
        return False
    try:
        os.kill(int(pid_text), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _default_browser_factory(profile_path: Path, *, headless: bool) -> _PlaywrightSession:

    from .runtime import DESKTOP
    if DESKTOP and not Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        raise PublisherError('browser_unavailable', '此功能需要 Chrome，请安装 Google Chrome 到“应用程序”后重试。其他功能可以继续使用。')
    # Playwright remains optional until a real browser operation is requested.
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    # 带着残留单实例锁启动会被 Chrome 直接拒绝并强杀，所以先清理已退出进程留下的锁。
    cleared = clear_stale_profile_locks(profile_path)
    if cleared:
        logger.info("publisher_profile_locks_cleared profile=%s names=%s", Path(profile_path).name, ",".join(cleared))
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            channel="chrome",
            headless=headless,
            args=[
                # 发布/复盘使用独立账号浏览器直连，避免继承系统代理；
                # 不改变 Codex 或用户日常浏览器的代理设置。
                "--no-proxy-server",
                # profile 上次被强杀后，Chrome 会弹"恢复页面？"气泡（浏览器自身 UI，
                # 页面定位器够不到，还会挡住/干扰自动操作），这里直接关掉。
                "--hide-crash-restore-bubble",
                "--no-default-browser-check",
            ],
        )
    except Exception:
        playwright.stop()
        raise
    return _PlaywrightSession(playwright, context)
