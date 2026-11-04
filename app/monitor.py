"""监控（monitor）模块：关注抖音博主、保存公开作品数据、生成 AI 选题建议。

数据分两层保存：

* **共享层**：博主身份与作品记录。多创作账号关注同一个博主时只采集一份，不重复付费。
* **账号层**：关注关系、备注、重点关注、收藏、暂不考虑、AI 建议。按创作账号隔离。

采集走 ``app/data_service.py``；本模块只做规范化、去重、快照和调度所需的读写。
所有作品指标都按接口真实返回保存，缺失记为 ``None``，不补零、不推算播放量。
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .upstream_errors import public_code, sanitize_message
from .subscription import NEEDS_RELOGIN, RELOGIN_CODES, points

logger = logging.getLogger("douyin-downloader")

MONITOR_DATA_VERSION = 1
MONITOR_PLATFORM = "douyin"

# 频率沿用需求文档第 12 节确认的默认值。
MONITOR_DEFAULT_INTERVAL_MINUTES = 360
MONITOR_INTERVAL_OPTIONS = (60, 120, 360, 1440)
MONITOR_DEFAULT_AI_TIME = "10:30"

# 每轮只采最新第一页（20 条）：监控判断的是最新发布数据的增量，第二页往后已经过了时效。
MONITOR_MAX_PAGES_PER_ROUND = 1
# 快照按每一轮采集都记录，保留上限按「每轮一条」的量级放宽。
MONITOR_SNAPSHOT_LIMIT = 200
# 作品动态行内迷你曲线最多画这么多点；超出时等距采样并保留首尾。
MONITOR_TREND_POINTS_MAX = 40
MONITOR_WORK_LIMIT_PER_BLOGGER = 600
MONITOR_TITLE_LIMIT = 200
MONITOR_TEXT_LIMIT = 1000
MONITOR_USAGE_KEEP_DAYS = 60
MONITOR_RECOMMENDATION_LIMIT = 3
MONITOR_RECENT_WINDOW_DAYS = 30
MONITOR_WORK_PAGE_SIZE = 20
MONITOR_BLOGGER_PAGE_SIZE = 3
# 关注的博主列表按面板高度决定每页条数，这里只挡住异常大的请求值。
MONITOR_BLOGGER_PAGE_SIZE_MAX = 60
# 作品动态的日期筛选：今天 / 昨天 / 最近 N 天 / 全部。最近 N 天包含今天。
MONITOR_WORK_DATE_OPTIONS = ("today", "yesterday", "7d", "15d", "30d", "all")
MONITOR_WORK_DATE_RANGE_DAYS = {"7d": 7, "15d": 15, "30d": 30}

MONITOR_STATUSES = (
    "idle",
    "queued",
    "running",
    "success",
    "partial",
    "failed",
    "auth_required",
    "insufficient_balance",
)
MONITOR_ACTIVE_STATUSES = ("queued", "running")
# 这几类错误在人工处理前不再自动重试，避免无限消耗付费额度。
MONITOR_BLOCKING_STATUSES = ("auth_required", "insufficient_balance")
MONITOR_BLOCKING_ERROR_CODES = {
    "unauthorized", "session_revoked", "account_disabled", "permission_denied", "needs_relogin",
    "insufficient_points", "insufficient_balance", "subscription_required", "subscription_expired",
    "platform_mode_required",
}

MONITOR_RECOMMENDATION_PRIORITIES = ("primary", "worth", "backup")
MONITOR_PRIORITY_LABELS = {"primary": "优先推荐", "worth": "值得尝试", "backup": "备选方向"}
MONITOR_RECOMMENDATION_STATUSES = ("idle", "running", "pending", "unconfirmed", "success", "failed", "skipped")

MONITOR_KINDS = ("video", "image")
MONITOR_METRIC_FIELDS = ("likes", "comments", "shares", "collects")
MONITOR_METRIC_LABELS = {"likes": "点赞", "comments": "评论", "shares": "分享", "collects": "收藏"}

# data_service 抖音资料/主页作品接口的公开基础单价（美元/次，以官方当期价目为准）。
MONITOR_REQUEST_COST_USD = 0.001


# ----------------------------------------------------------------------
# 时间
# ----------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_day(value: Any = None) -> str:
    """北京时间自然日；「今天采集/新发现」都按这个口径统计。"""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        moment = parse_iso(value) or datetime.now(timezone.utc)
    else:
        moment = datetime.now(timezone.utc)
    return moment.astimezone().date().isoformat()


def in_work_date_range(published_at: Any, day: str, today: date) -> bool:
    """作品发布时间是否落在作品动态的日期筛选范围内。

    作品列表和博主列表共用这一套口径，左边每位博主的条数才能和右边列表对上：
    今天/昨天按北京时间自然日，最近 N 天包含今天，发布日期缺失的作品不猜日期。
    """
    if str(day) == "all":
        return True
    published_day = local_day(parse_iso(published_at)) if published_at else ""
    if str(day) == "today":
        return published_day == today.isoformat()
    if str(day) == "yesterday":
        return published_day == (today - timedelta(days=1)).isoformat()
    range_days = MONITOR_WORK_DATE_RANGE_DAYS.get(str(day))
    if range_days is None:
        return True
    if not published_day:
        return False
    earliest = (today - timedelta(days=range_days - 1)).isoformat()
    return earliest <= published_day <= today.isoformat()


def published_text(value: Any) -> str:
    moment = parse_iso(value)
    if moment is None:
        return ""
    local = moment.astimezone()
    today = datetime.now(timezone.utc).astimezone().date()
    if local.date() == today:
        return f"今天 {local.strftime('%H:%M')}"
    if local.date() == today - timedelta(days=1):
        return f"昨天 {local.strftime('%H:%M')}"
    return local.strftime("%m-%d %H:%M")


def _unix_to_iso(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


# ----------------------------------------------------------------------
# 规范化
# ----------------------------------------------------------------------


def _pick_int(*values: Any) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_url(node: Any) -> str:
    """抖音的图片/视频地址统一是 ``{"url_list": [...]}``，取第一个可用地址。"""
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, Mapping):
        return ""
    urls = node.get("url_list")
    if isinstance(urls, str):
        return urls.strip()
    if isinstance(urls, Iterable):
        for item in urls:
            text = str(item or "").strip()
            if text:
                return text
    return ""


def normalize_douyin_user(raw: Any) -> dict[str, Any]:
    """把资料接口返回的用户对象转成监控模块的博主字段。"""
    user = raw if isinstance(raw, Mapping) else {}
    avatar = user.get("avatar_thumb") or user.get("avatar_larger") or user.get("avatar_medium")
    return {
        "secUserId": str(user.get("sec_uid") or "").strip(),
        "uid": str(user.get("uid") or "").strip(),
        "uniqueId": str(user.get("unique_id") or "").strip(),
        "nickname": str(user.get("nickname") or "").strip()[:80],
        "signature": str(user.get("signature") or "").strip()[:300],
        "avatarUrl": _first_url(avatar),
        "followerCount": _pick_int(user.get("follower_count")),
        "followingCount": _pick_int(user.get("following_count")),
        "awemeCount": _pick_int(user.get("aweme_count")),
        "totalFavorited": _pick_int(user.get("total_favorited")),
    }


def media_urls_from_aweme(raw: Mapping[str, Any]) -> list[str]:
    """按 APP 优先、WEB 兜底的顺序收集视频直链。

    这些是抖音 CDN 的临时地址，只用于当场下载/拆解，不能当永久素材链接保存。
    """
    video = raw.get("video") if isinstance(raw.get("video"), Mapping) else {}
    urls: list[str] = []
    for key in ("play_addr_265", "play_addr_h264", "play_addr", "download_addr"):
        url = _first_url(video.get(key))
        if url and url not in urls:
            urls.append(url)
    bit_rates = video.get("bit_rate")
    if isinstance(bit_rates, Iterable):
        for item in bit_rates:
            url = _first_url((item or {}).get("play_addr") if isinstance(item, Mapping) else "")
            if url and url not in urls:
                urls.append(url)
    return urls


def normalize_douyin_aweme(raw: Any, *, blogger_id: str, discovered_at: str) -> dict[str, Any] | None:
    """把一条作品规范化成监控记录；缺少作品 ID 的条目直接丢弃。

    图集没有视频直链，按图文保存；他人作品的播放量接口不返回，一律记 ``None``。
    """
    item = raw if isinstance(raw, Mapping) else {}
    work_id = str(item.get("aweme_id") or item.get("awemeId") or "").strip()
    if not work_id:
        return None
    video = item.get("video") if isinstance(item.get("video"), Mapping) else {}
    statistics = item.get("statistics") if isinstance(item.get("statistics"), Mapping) else {}
    images = [entry for entry in (item.get("images") or []) if isinstance(entry, Mapping)]
    raw_type = _pick_int(item.get("aweme_type"))
    has_video = bool(media_urls_from_aweme(item))
    kind = "image" if (images and not has_video) else "video"
    if raw_type in (2, 68) and images:
        kind = "image"

    cover = _first_url(video.get("cover")) or _first_url(video.get("origin_cover")) or _first_url(video.get("dynamic_cover"))
    if not cover and images:
        cover = _first_url(images[0])
    share_url = str(item.get("share_url") or "").strip()
    if not share_url:
        prefix = "note" if kind == "image" else "video"
        share_url = f"https://www.douyin.com/{prefix}/{work_id}"
    duration_ms = _pick_int(video.get("duration"))

    return {
        "id": work_id,
        "bloggerId": str(blogger_id),
        "title": str(item.get("desc") or "").strip(),
        "kind": kind,
        "createTime": _pick_int(item.get("create_time")),
        "publishedAt": _unix_to_iso(item.get("create_time")),
        "pinned": bool(item.get("is_top")),
        "coverUrl": cover,
        "shareUrl": share_url,
        "durationSeconds": int(duration_ms / 1000) if duration_ms else None,
        "metrics": {
            "likes": _pick_int(statistics.get("digg_count")),
            "comments": _pick_int(statistics.get("comment_count")),
            "shares": _pick_int(statistics.get("share_count")),
            "collects": _pick_int(statistics.get("collect_count")),
        },
        "imageCount": len(images),
        "mediaUrls": media_urls_from_aweme(item),
        "discoveredAt": str(discovered_at),
    }


def like_trend_values(snapshots: Iterable[Any], *, max_points: int = MONITOR_TREND_POINTS_MAX) -> list[int]:
    """快照里的点赞序列（旧→新）；点太少不画曲线，点太多时等距采样并保留首尾。"""
    values: list[int] = []
    for item in snapshots:
        if not isinstance(item, Mapping):
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), Mapping) else {}
        value = metrics.get("likes")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(int(value))
    if len(values) < 2:
        return []
    if len(values) <= max_points:
        return values
    step = (len(values) - 1) / (max_points - 1)
    return [values[round(index * step)] for index in range(max_points)]


def _days_ago_key(days: int, *, now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return (moment.astimezone() - timedelta(days=days)).date().isoformat()


# ----------------------------------------------------------------------
# 存储
# ----------------------------------------------------------------------


def _locked(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapper(self: "MonitorStore", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def cached_image_file(directory: Path, name: str) -> Path | None:
    """在缓存目录里找一个已下载的图片文件。

    名字只允许字母、数字、下划线和连字符：博主/作品标识都来自平台，
    但仍然按不可信输入处理，避免 ../ 之类的名字读到工作区以外的文件。
    """
    target = str(name or "").strip()
    if not target or not target.replace("_", "").replace("-", "").isalnum():
        return None
    for suffix in (".jpg", ".png", ".webp"):
        candidate = directory / f"{target}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def default_settings() -> dict[str, Any]:
    return {
        "collectEnabled": True,
        "intervalMinutes": MONITOR_DEFAULT_INTERVAL_MINUTES,
        "aiEnabled": True,
        "aiDailyTime": MONITOR_DEFAULT_AI_TIME,
    }


class MonitorStore:
    """监控数据存储：共享博主/作品 + 按创作账号隔离的关注与 AI 建议。"""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._path = self._workspace_dir / "monitor-data.json"
        self._covers_dir = self._workspace_dir / "monitor-covers"
        self._avatars_dir = self._workspace_dir / "monitor-avatars"
        self._lock = threading.RLock()

    @property
    def covers_dir(self) -> Path:
        """封面缓存目录：抖音封面是签名临时地址，而且是 HEIC，浏览器不能直接显示。"""
        return self._covers_dir

    @property
    def avatars_dir(self) -> Path:
        """博主头像缓存目录：和封面同样是签名临时地址 + HEIC，需要本地转码后才能显示。"""
        return self._avatars_dir

    @_locked
    def cover_file(self, work_id: str) -> Path | None:
        """返回已缓存的封面文件；只接受工作区内部路径，避免被路径穿透读取其他文件。"""
        return cached_image_file(self._covers_dir, work_id)

    @_locked
    def avatar_file(self, blogger_id: str) -> Path | None:
        """返回已缓存的博主头像文件；同样拒绝不安全的文件名。"""
        return cached_image_file(self._avatars_dir, blogger_id)

    @_locked
    def complete_original_source_restore(self) -> None:
        data = self._read()
        data.setdefault("originalRecommendationMigration", {})["sourcesRestored"] = True
        self._write(data)

    @_locked
    def migrate_original_recommendations(self) -> dict[str, Any]:
        """Back up once before clearing legacy recommendation-only state across accounts."""
        data = self._read()
        previous = data.get("originalRecommendationMigration") or {}
        if previous.get("schemaVersion") == 2:
            return {**previous, "migrated": False}
        backup = ""
        if self._path.exists():
            target = self._path.with_name(f"{self._path.stem}.before-original-v2.{uuid.uuid4().hex}.json")
            target.write_bytes(self._path.read_bytes())
            backup = str(target)
        discarded = {}
        for account_id, bucket in data["accounts"].items():
            record = bucket.get("recommendation") or {}
            if record.get("schemaVersion") != 2:
                items = record.get("items") or []
                discarded[account_id] = items
                dismissed = bucket.setdefault("dismissed", {})
                for key in record.get("dismissed") or []:
                    if str(key) not in dismissed:
                        dismissed[str(key)] = next((dict(item) for item in items if str(item.get("key")) == str(key)), {"key": str(key)})
                bucket["recommendation"] = {"schemaVersion": 2, "items": [], "analysis": {},
                                            "message": "推荐方式已升级，请更新建议",
                                            "generatedAt": str(record.get("generatedAt") or "")}
            job = bucket.get("recommendationJob") or {}
            if (record.get("schemaVersion") != 2 or
                    (job.get("prepared") and job["prepared"].get("schemaVersion") != 2)):
                bucket["recommendationJob"] = {
                    **{key: job[key] for key in ("startedAt", "finishedAt", "lastRunAt", "lastRunDay") if key in job},
                    "status": "skipped", "lastRunDay": local_day(), "finishedAt": now_iso(),
                    "previousFinishedAt": str(job.get("finishedAt") or ""),
                    "previousLastRunDay": str(job.get("lastRunDay") or ""),
                }
        report = {"schemaVersion": 2, "backupPath": backup, "migratedAt": now_iso()}
        data["originalRecommendationMigration"] = report
        self._write(data)
        return {**report, "migrated": True, "discardedItems": discarded}

    # ---- 基础读写 -----------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        source = raw if isinstance(raw, dict) else {}
        settings = {**default_settings()}
        stored_settings = source.get("settings") if isinstance(source.get("settings"), dict) else {}
        for key in settings:
            if key in stored_settings and stored_settings[key] is not None:
                settings[key] = stored_settings[key]
        settings = normalize_settings(settings)
        return {
            "version": MONITOR_DATA_VERSION,
            "originalRecommendationMigration": source.get("originalRecommendationMigration") or {},
            "settings": settings,
            "bloggers": {str(k): v for k, v in (source.get("bloggers") or {}).items() if isinstance(v, dict)},
            "works": {str(k): v for k, v in (source.get("works") or {}).items() if isinstance(v, dict)},
            "accounts": {str(k): v for k, v in (source.get("accounts") or {}).items() if isinstance(v, dict)},
            "usage": source.get("usage") if isinstance(source.get("usage"), dict) else {},
        }

    def _write(self, data: Mapping[str, Any]) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _account(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(account_id)
        if not isinstance(bucket, dict):
            bucket = {"follows": {}, "saves": {}, "dismissed": {}, "recommendation": {}}
            data["accounts"][account_id] = bucket
        for key, fallback in (("follows", {}), ("saves", {}), ("dismissed", {}), ("recommendation", {})):
            if not isinstance(bucket.get(key), dict):
                bucket[key] = fallback
        return bucket

    # ---- 设置 ---------------------------------------------------------

    @_locked
    def get_settings(self) -> dict[str, Any]:
        return dict(self._read()["settings"])

    @_locked
    def save_settings(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        data = self._read()
        merged = {**data["settings"]}
        for key in ("collectEnabled", "intervalMinutes", "aiEnabled", "aiDailyTime"):
            if key in fields and fields.get(key) is not None:
                merged[key] = fields.get(key)
        data["settings"] = normalize_settings(merged)
        self._write(data)
        return dict(data["settings"])

    # ---- 共享博主 -----------------------------------------------------

    @_locked
    def blogger_by_sec_user(self, sec_user_id: str) -> dict[str, Any] | None:
        target = str(sec_user_id or "").strip()
        if not target:
            return None
        for blogger in self._read()["bloggers"].values():
            if str(blogger.get("secUserId") or "") == target:
                return dict(blogger)
        return None

    @_locked
    def author_status(self, account_id: str, identity: Mapping[str, Any]) -> dict[str, Any]:
        uid = str(identity.get("uid") or "").strip()
        handle = str(identity.get("uniqueId") or "").strip()
        result = {"bloggerId": "", "profileUrl": "", "following": False, "uniqueId": handle if identity.get("platform") == "douyin" else ""}
        if identity.get("platform") != "douyin":
            return result
        bloggers = list(self._read()["bloggers"].values())
        candidates = [b for b in bloggers if uid and str(b.get("uid") or "") == uid]
        if not candidates:
            candidates = [b for b in bloggers if handle and str(b.get("uniqueId") or "") == handle]
            if any(uid and b.get("uid") and str(b["uid"]) != uid for b in candidates):
                return result
        if len(candidates) != 1:
            return result
        blogger = candidates[0]
        sec_uid = str(blogger.get("secUserId") or "")
        if not re.fullmatch(r"MS4w[\w-]+", sec_uid):
            return result
        result.update(nickname=str(blogger.get("nickname") or ""), bloggerId=blogger["id"], profileUrl="https://www.douyin.com/user/" + sec_uid,
                      following=account_id in (blogger.get("follows") or {}))
        return result

    @_locked
    def follow_local_author(self, account_id: str, identity: Mapping[str, Any]) -> dict[str, Any]:
        status = self.author_status(account_id, identity)
        if not status["bloggerId"]:
            raise ValueError("未匹配到本地博主，请复制抖音号查找主页。")
        if not status["following"]:
            self.follow(account_id, status["bloggerId"])
        return self.author_status(account_id, identity)

    @_locked
    def get_blogger(self, blogger_id: str) -> dict[str, Any]:
        blogger = self._read()["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        return dict(blogger)

    @_locked
    def list_bloggers(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read()["bloggers"].values()]

    @_locked
    def upsert_blogger(self, profile: Mapping[str, Any], *, source_url: str = "") -> dict[str, Any]:
        """新增或更新一位共享博主；同一 ``secUserId`` 只保留一条记录。"""
        data = self._read()
        sec_user_id = str(profile.get("secUserId") or "").strip()
        if not sec_user_id:
            raise ValueError("博主身份不能为空。")
        stamp = now_iso()
        blogger = next((item for item in data["bloggers"].values() if str(item.get("secUserId") or "") == sec_user_id), None)
        if blogger is None:
            blogger = {
                "id": uuid.uuid4().hex,
                "secUserId": sec_user_id,
                "createdAt": stamp,
                "baselineAt": "",
                "collection": {"status": "idle", "lastAttemptAt": "", "lastSuccessAt": "", "lastError": "", "lastErrorCode": "", "nextCheckAt": "", "coverage": {}},
            }
            data["bloggers"][blogger["id"]] = blogger
        for field in ("uid", "uniqueId", "nickname", "signature", "avatarUrl", "followerCount", "followingCount", "awemeCount", "totalFavorited"):
            value = profile.get(field)
            if value is not None and value != "":
                blogger[field] = value
        if source_url and not blogger.get("sourceUrl"):
            blogger["sourceUrl"] = str(source_url)[:500]
        blogger["profileUpdatedAt"] = stamp
        self._write(data)
        return dict(blogger)

    @_locked
    def record_collection(
        self,
        blogger_id: str,
        *,
        status: str,
        error: str = "",
        error_code: str = "",
        coverage: Mapping[str, Any] | None = None,
        first_page_at: str = "",
        baseline_at: str = "",
    ) -> dict[str, Any]:
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        stamp = now_iso()
        collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
        # 数据客户端沿用平台状态名，监控使用自己的余额阻断状态。
        if status == "insufficient_points":
            status = "insufficient_balance"
        collection["status"] = status if status in MONITOR_STATUSES else "failed"
        collection["lastAttemptAt"] = stamp
        collection["lastError"] = sanitize_message(str(error or ""))[:300]
        collection["lastErrorCode"] = public_code(str(error_code or ""))[:60]
        blocked = collection["status"] in MONITOR_BLOCKING_STATUSES or error_code in MONITOR_BLOCKING_ERROR_CODES
        collection["nextCheckAt"] = "" if blocked else (
            datetime.fromisoformat(stamp) + timedelta(minutes=self._follow_interval(blogger))
        ).isoformat()
        if coverage is not None:
            collection["coverage"] = dict(coverage)
        # 只有本轮成功采到第一页时才更新；失败时保留上一轮的值，「数据监控」标签不会闪掉。
        if first_page_at:
            collection["firstPageAt"] = str(first_page_at)
        if status in ("success", "partial"):
            collection["lastSuccessAt"] = stamp
        blogger["collection"] = collection
        if baseline_at:
            blogger["baselineAt"] = baseline_at
        self._write(data)
        return dict(blogger)

    @_locked
    def recover_orphaned_collections(self, active_ids: Iterable[str]) -> list[str]:
        """无实际任务的 running 不再永久挡住调度；保留正常重试间隔。"""
        active = set(active_ids)
        orphaned = [key for key, blogger in self._read()["bloggers"].items()
                    if key not in active and (blogger.get("collection") or {}).get("status") in MONITOR_ACTIVE_STATUSES]
        for key in orphaned:
            self.record_collection(key, status="failed", error_code="collection_interrupted",
                                   error="上一轮采集已中断，将按设置的间隔再次检查。")
        return orphaned

    @_locked
    def reset_running(self) -> list[str]:
        """服务重启后把中断的采集状态复位，避免界面一直显示「采集中」。"""
        data = self._read()
        reset: list[str] = []
        changed = False
        for blogger_id, blogger in data["bloggers"].items():
            collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
            if str(collection.get("status")) in MONITOR_ACTIVE_STATUSES:
                collection["status"] = "idle"
                collection["lastError"] = "服务重启，上一轮采集已中断。"
                collection["lastErrorCode"] = ""
                blogger["collection"] = collection
                reset.append(blogger_id)
                changed = True
        for bucket in data["accounts"].values():
            job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else None
            if job is not None and (job.get("status") == "running" or
                                    (job.get("status") == "failed" and job.get("errorCode") == "status_pending")):
                if job.get("taskId") and (job.get("prepared") or {}).get("schemaVersion") == 2:
                    job["status"] = "pending"
                    job["error"] = "上次生成结果待确认，正在继续查询。"
                else:
                    job["status"] = "unconfirmed"
                    job["error"] = "上次生成结果未确认，旧建议已保留；可点击更新建议重新生成。"
                job["errorCode"] = "status_pending"
                changed = True
        if changed:
            self._write(data)
        return reset

    @_locked
    def release_login_blocks(self) -> dict[str, int]:
        """会话恢复后清理登录类阻断：只清提示、恢复为待采，不主动补采。

        登录前写入的 ``auth_required`` 会永久阻断自动采集：会话有效后把它改回 ``idle`` 并清空错误，
        交由原有间隔锚点决定何时采；同样清掉登录类的 AI 建议任务失败。
        ``insufficient_balance`` 不属于登录问题，保持阻断。
        """
        data = self._read()
        released = 0
        jobs = 0
        changed = False
        for blogger in data["bloggers"].values():
            collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
            if str(collection.get("status")) == "auth_required" and self._is_login_error(collection):
                collection["status"] = "idle"
                collection["lastError"] = ""
                collection["lastErrorCode"] = ""
                collection["nextCheckAt"] = ""
                blogger["collection"] = collection
                released += 1
                changed = True
        for bucket in data["accounts"].values():
            job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else None
            if job is not None and str(job.get("status")) == "failed" and self._is_login_error(job):
                job["status"] = "idle"
                job["error"] = ""
                job["errorCode"] = ""
                jobs += 1
                changed = True
        if changed:
            self._write(data)
        return {"released": released, "jobs": jobs}

    @staticmethod
    def _is_subscription_block(collection: Mapping[str, Any]) -> bool:
        code = str(collection.get("lastErrorCode") or "")
        if str(collection.get("status")) in MONITOR_ACTIVE_STATUSES:
            return False
        if code:
            return code in {"insufficient_points", "insufficient_balance", "subscription_required", "subscription_expired"}
        return collection.get("status") == "insufficient_balance"

    @_locked
    def has_subscription_blocks(self) -> bool:
        return any(self._is_subscription_block(blogger.get("collection") or {})
                   for blogger in self._read()["bloggers"].values())

    @_locked
    def release_subscription_blocks(self, available: str, *, now: datetime | None = None) -> int:
        """平台确认权益恢复后解除阻断；再次额度不足时每 15 分钟最多恢复一次。

        冷却落盘以跨重启生效；可用余额增加时允许提前恢复。共享博主仍只采集一次。
        """
        if points(available) <= 0:
            return 0
        data = self._read()
        moment = now or datetime.now(timezone.utc)
        released = 0
        for blogger in data["bloggers"].values():
            collection = blogger.get("collection") or {}
            if not self._is_subscription_block(collection):
                continue
            retry_at = parse_iso(collection.get("subscriptionRetryAt"))
            if retry_at and retry_at > moment and points(available) <= points(collection.get("subscriptionRecoveryBalance")):
                continue
            collection.update(status="idle", lastError="", lastErrorCode="", nextCheckAt=moment.isoformat(),
                              subscriptionRetryAt=(moment + timedelta(minutes=15)).isoformat(),
                              subscriptionRecoveryBalance=str(available))
            blogger["collection"] = collection
            released += 1
        if released:
            self._write(data)
        return released

    @staticmethod
    def _is_login_error(record: Mapping[str, Any]) -> bool:
        """判断记录是否属于登录/凭证类问题：新记录看精确码，旧记录回退到文案匹配。"""
        code = str(record.get("lastErrorCode") or record.get("errorCode") or "")
        if code == NEEDS_RELOGIN or code in RELOGIN_CODES:
            return True
        if code:
            return False
        # 升级前的旧记录没有码：只有空码且文案就是登录提示时才当作登录问题。
        message = str(record.get("lastError") or record.get("error") or "")
        return message == "请先登录后再使用该功能。"

    # ---- 关注关系 -----------------------------------------------------

    def _follow_interval(self, blogger: Mapping[str, Any]) -> int:
        """共享采集按所有启用关注里最短的间隔执行。"""
        follows = blogger.get("follows") if isinstance(blogger.get("follows"), dict) else {}
        values = [int(item.get("intervalMinutes") or 0) for item in follows.values() if isinstance(item, Mapping) and item.get("enabled", True)]
        values = [value for value in values if value > 0]
        return min(values) if values else MONITOR_DEFAULT_INTERVAL_MINUTES

    @_locked
    def follow(
        self,
        account_id: str,
        blogger_id: str,
        *,
        note: str = "",
        priority: bool = False,
        interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        follows = blogger.setdefault("follows", {})
        existing = follows.get(account_id) if isinstance(follows.get(account_id), dict) else None
        stamp = now_iso()
        follow = {
            "accountId": account_id,
            "note": str(note or (existing or {}).get("note") or "").strip()[:60],
            "priority": bool(priority) if priority else bool((existing or {}).get("priority")),
            "intervalMinutes": normalize_interval(interval_minutes if interval_minutes is not None else (existing or {}).get("intervalMinutes")),
            "enabled": True,
            "addedAt": str((existing or {}).get("addedAt") or stamp),
            "updatedAt": stamp,
        }
        follows[account_id] = follow
        collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
        if not collection.get("nextCheckAt") or str(collection.get("status")) in MONITOR_BLOCKING_STATUSES:
            collection["nextCheckAt"] = stamp
            if str(collection.get("status")) in MONITOR_BLOCKING_STATUSES:
                collection["status"] = "idle"
                collection["lastError"] = ""
                collection["lastErrorCode"] = ""
            else:
                collection["status"] = collection.get("status", "idle")
        blogger["collection"] = collection
        self._write(data)
        return dict(blogger)

    @_locked
    def update_follow(self, account_id: str, blogger_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        follows = blogger.get("follows") if isinstance(blogger.get("follows"), dict) else {}
        follow = follows.get(account_id)
        if not isinstance(follow, dict):
            raise ValueError("当前账号没有关注这位博主。")
        if "note" in fields and fields.get("note") is not None:
            follow["note"] = str(fields.get("note")).strip()[:60]
        if "priority" in fields and fields.get("priority") is not None:
            follow["priority"] = bool(fields.get("priority"))
        if "intervalMinutes" in fields and fields.get("intervalMinutes") is not None:
            follow["intervalMinutes"] = normalize_interval(fields.get("intervalMinutes"))
        if "enabled" in fields and fields.get("enabled") is not None:
            follow["enabled"] = bool(fields.get("enabled"))
        follow["updatedAt"] = now_iso()
        follows[account_id] = follow
        self._write(data)
        return dict(blogger)

    @_locked
    def unfollow(self, account_id: str, blogger_id: str) -> dict[str, Any]:
        """取消当前账号的关注；共享作品和已形成的选题关联都保留。"""
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        follows = blogger.get("follows") if isinstance(blogger.get("follows"), dict) else {}
        follows.pop(account_id, None)
        blogger["follows"] = follows
        if not any(isinstance(item, Mapping) and item.get("enabled", True) for item in follows.values()):
            collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
            collection["nextCheckAt"] = ""
            blogger["collection"] = collection
        self._write(data)
        return dict(blogger)

    @_locked
    def account_blogger_ids(self, account_id: str) -> list[str]:
        return [blogger_id for blogger_id, blogger in self._read()["bloggers"].items() if account_id in (blogger.get("follows") or {})]

    @_locked
    def due_bloggers(self, *, now: datetime | None = None) -> list[str]:
        data = self._read()
        if not data["settings"].get("collectEnabled", True):
            return []
        moment = now or datetime.now(timezone.utc)
        due: list[str] = []
        for blogger_id, blogger in data["bloggers"].items():
            follows = blogger.get("follows") if isinstance(blogger.get("follows"), dict) else {}
            if not any(isinstance(item, Mapping) and item.get("enabled", True) for item in follows.values()):
                continue
            collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
            status = str(collection.get("status") or "idle")
            if status in MONITOR_ACTIVE_STATUSES or status in MONITOR_BLOCKING_STATUSES or collection.get("lastErrorCode") in MONITOR_BLOCKING_ERROR_CODES:
                continue
            last_attempt = parse_iso(collection.get("lastAttemptAt"))
            next_check = parse_iso(collection.get("nextCheckAt"))
            # 旧失败记录把 nextCheckAt 写成本轮结束时间；至少等待完整周期。
            if status in ("failed", "partial") and last_attempt is not None:
                earliest = last_attempt + timedelta(minutes=self._follow_interval(blogger))
                next_check = max(next_check, earliest) if next_check is not None else earliest
            if next_check is None:
                interval = self._follow_interval(blogger)
                anchor = parse_iso(collection.get("lastSuccessAt")) or parse_iso(collection.get("lastAttemptAt"))
                if anchor is not None and (moment - anchor).total_seconds() < interval * 60:
                    continue
            elif next_check > moment:
                continue
            due.append(blogger_id)
        return due

    @_locked
    def mark_collect_started(self, blogger_id: str) -> None:
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            return
        collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
        collection["status"] = "running"
        collection["startedAt"] = now_iso()
        collection["lastError"] = ""
        collection["lastErrorCode"] = ""
        blogger["collection"] = collection
        self._write(data)

    @_locked
    def schedule_next_check(self, blogger_id: str, *, minutes: int | None = None) -> None:
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            return
        interval = normalize_interval(minutes) if minutes else self._follow_interval(blogger)
        collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
        collection["nextCheckAt"] = (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat()
        blogger["collection"] = collection
        self._write(data)

    # ---- 作品 ---------------------------------------------------------

    @_locked
    def upsert_works(
        self,
        blogger_id: str,
        works: Iterable[Mapping[str, Any]],
        *,
        collected_at: str,
        baseline: bool = False,
    ) -> dict[str, Any]:
        """写入一轮采集结果：按作品 ID 去重，本轮返回的作品每轮都追加快照。"""
        data = self._read()
        blogger = data["bloggers"].get(str(blogger_id))
        if not isinstance(blogger, dict):
            raise ValueError("博主不存在。")
        added = 0
        updated = 0
        snapshots = 0
        for work in works:
            work_id = str(work.get("id") or "").strip()
            if not work_id:
                continue
            metrics = {field: (work.get("metrics") or {}).get(field) for field in MONITOR_METRIC_FIELDS}
            existing = data["works"].get(work_id)
            if not isinstance(existing, dict):
                record = {
                    "id": work_id,
                    "bloggerId": str(blogger_id),
                    "title": str(work.get("title") or ""),
                    "kind": work.get("kind") if work.get("kind") in MONITOR_KINDS else "video",
                    "createTime": work.get("createTime"),
                    "publishedAt": str(work.get("publishedAt") or ""),
                    "pinned": bool(work.get("pinned")),
                    "coverUrl": str(work.get("coverUrl") or ""),
                    "shareUrl": str(work.get("shareUrl") or ""),
                    "durationSeconds": work.get("durationSeconds"),
                    "imageCount": int(work.get("imageCount") or 0),
                    "mediaUrls": [str(url) for url in (work.get("mediaUrls") or [])][:8],
                    "metrics": metrics,
                    "snapshots": [{"at": collected_at, "metrics": dict(metrics)}],
                    "firstSeenAt": collected_at,
                    "discoveredAt": collected_at,
                    "firstPageAt": collected_at,
                    "baseline": bool(baseline),
                    "statsUpdatedAt": collected_at,
                    "updatedAt": collected_at,
                }
                data["works"][work_id] = record
                added += 1
                continue

            for field in ("title", "kind", "coverUrl", "shareUrl", "durationSeconds", "createTime", "publishedAt", "imageCount", "pinned"):
                value = work.get(field)
                if value not in (None, ""):
                    existing[field] = value
            media = [str(url) for url in (work.get("mediaUrls") or [])][:8]
            if media:
                existing["mediaUrls"] = media
            existing["metrics"] = metrics
            history = existing.get("snapshots") if isinstance(existing.get("snapshots"), list) else []
            history.append({"at": collected_at, "metrics": dict(metrics)})
            existing["snapshots"] = history[-MONITOR_SNAPSHOT_LIMIT:]
            existing["statsUpdatedAt"] = collected_at
            existing["firstPageAt"] = collected_at
            snapshots += 1
            existing["updatedAt"] = collected_at
            updated += 1

        self._prune_works(data, str(blogger_id))
        self._write(data)
        return {"added": added, "updated": updated, "snapshots": snapshots}

    @staticmethod
    def _prune_works(data: dict[str, Any], blogger_id: str) -> None:
        """单博主作品超过上限时按发布时间裁掉最旧的；不删除仍被选题引用的记录由页面兜底。"""
        owned = [(work_id, work) for work_id, work in data["works"].items() if str(work.get("bloggerId")) == blogger_id]
        if len(owned) <= MONITOR_WORK_LIMIT_PER_BLOGGER:
            return
        owned.sort(key=lambda item: (str(item[1].get("publishedAt") or ""), str(item[1].get("id"))))
        for work_id, _ in owned[: len(owned) - MONITOR_WORK_LIMIT_PER_BLOGGER]:
            data["works"].pop(work_id, None)

    @_locked
    def get_work(self, work_id: str) -> dict[str, Any]:
        work = self._read()["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        return dict(work)

    @_locked
    def update_work_media(self, work_id: str, media_urls: list[str]) -> dict[str, Any]:
        data = self._read()
        work = data["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        work["mediaUrls"] = [str(url) for url in media_urls][:8]
        work["mediaUpdatedAt"] = now_iso()
        self._write(data)
        return dict(work)

    @_locked
    def list_works(
        self,
        account_id: str,
        *,
        blogger_id: str = "",
        work_filter: str = "all",
        day: str = "today",
        page: int = 1,
        page_size: int = MONITOR_WORK_PAGE_SIZE,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """列出当前账号关注范围内的作品；博主筛选、日期与收藏筛选在这里统一组合。"""
        data = self._read()
        blogger_ids = self.account_blogger_ids(account_id)
        bucket = self._account(data, account_id)
        saves = bucket.get("saves") or {}
        moment = now or datetime.now(timezone.utc)
        today = moment.astimezone().date()
        items: list[dict[str, Any]] = []
        for work in data["works"].values():
            blogger_owner = str(work.get("bloggerId") or "")
            if blogger_owner not in blogger_ids:
                continue
            if blogger_id and blogger_owner != str(blogger_id):
                continue
            saved = work["id"] in saves
            is_new = is_new_work(work, today)
            if work_filter == "new" and not is_new:
                continue
            if work_filter == "saved" and not saved:
                continue
            if not in_work_date_range(work.get("publishedAt"), str(day), today):
                continue
            item = self.work_view(data, work, account_id=account_id, saved=saved, is_new=is_new)
            item["likeTrend"] = like_trend_values(work.get("snapshots") or [])
            items.append(item)
        items.sort(key=lambda item: (item.get("publishedAt") or "", item.get("id") or ""), reverse=True)
        total = len(items)
        page_size = max(1, int(page_size or MONITOR_WORK_PAGE_SIZE))
        page_count = max(1, (total + page_size - 1) // page_size)
        current = max(1, min(int(page or 1), page_count))
        return {
            "items": items[(current - 1) * page_size : current * page_size],
            "total": total,
            "page": current,
            "pageCount": page_count,
            "pageSize": page_size,
        }

    def work_view(self, data: Mapping[str, Any], work: Mapping[str, Any], *, account_id: str = "", saved: bool = False, is_new: bool = False) -> dict[str, Any]:
        bloggers = data.get("bloggers") or {}
        blogger = bloggers.get(str(work.get("bloggerId") or "")) or {}
        metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
        snapshots = work.get("snapshots") if isinstance(work.get("snapshots"), list) else []
        collection = blogger.get("collection") if isinstance(blogger.get("collection"), Mapping) else {}
        # 作品仍在该博主最新一轮的第一页里，才算「正在被数据监控」；落出第一页后标签自动消失。
        first_page_at = str(work.get("firstPageAt") or "")
        monitored = bool(first_page_at) and first_page_at == str(collection.get("firstPageAt") or "")
        return {
            "id": str(work.get("id") or ""),
            "bloggerId": str(work.get("bloggerId") or ""),
            "bloggerName": str(blogger.get("nickname") or ""),
            "title": str(work.get("title") or ""),
            "kind": str(work.get("kind") or "video"),
            "coverUrl": str(work.get("coverUrl") or ""),
            "coverSrc": f"/api/monitor/covers/{work.get('id')}" if work.get("coverUrl") else "",
            "shareUrl": str(work.get("shareUrl") or ""),
            "publishedAt": str(work.get("publishedAt") or ""),
            "publishedText": published_text(work.get("publishedAt")),
            "discoveredAt": str(work.get("discoveredAt") or ""),
            "pinned": bool(work.get("pinned")),
            "durationSeconds": work.get("durationSeconds"),
            "imageCount": int(work.get("imageCount") or 0),
            "metrics": {field: metrics.get(field) for field in MONITOR_METRIC_FIELDS},
            "hasMetrics": any(metrics.get(field) is not None for field in MONITOR_METRIC_FIELDS),
            "snapshotCount": len(snapshots),
            "statsUpdatedAt": str(work.get("statsUpdatedAt") or ""),
            "monitored": monitored,
            "baseline": bool(work.get("baseline")),
            "isNew": bool(is_new),
            "saved": bool(saved),
            "hasMedia": bool(work.get("mediaUrls")),
        }

    @_locked
    def work_detail(self, work_id: str, account_id: str = "") -> dict[str, Any]:
        data = self._read()
        work = data["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        bucket = self._account(data, account_id) if account_id else {"saves": {}}
        today = datetime.now(timezone.utc).astimezone().date()
        view = self.work_view(
            data,
            work,
            account_id=account_id,
            saved=work["id"] in (bucket.get("saves") or {}),
            is_new=is_new_work(work, today),
        )
        snapshots = work.get("snapshots") if isinstance(work.get("snapshots"), list) else []
        view["snapshots"] = [
            {"at": str(item.get("at") or ""), "metrics": {field: (item.get("metrics") or {}).get(field) for field in MONITOR_METRIC_FIELDS}}
            for item in snapshots[-MONITOR_SNAPSHOT_LIMIT:]
            if isinstance(item, Mapping)
        ]
        return view

    @_locked
    def set_saved(self, account_id: str, work_id: str, saved: bool) -> bool:
        data = self._read()
        if str(work_id) not in data["works"]:
            raise ValueError("作品不存在。")
        bucket = self._account(data, account_id)
        if saved:
            bucket["saves"][str(work_id)] = {"savedAt": now_iso()}
        else:
            bucket["saves"].pop(str(work_id), None)
        self._write(data)
        return bool(saved)

    @_locked
    def is_saved(self, account_id: str, work_id: str) -> bool:
        return str(work_id) in (self._account(self._read(), account_id).get("saves") or {})

    # ---- 概览 ---------------------------------------------------------

    @_locked
    def overview(self, account_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        data = self._read()
        moment = now or datetime.now(timezone.utc)
        today = moment.astimezone().date().isoformat()
        blogger_ids = self.account_blogger_ids(account_id)
        bucket = self._account(data, account_id)
        followers = [data["bloggers"][blogger_id] for blogger_id in blogger_ids if blogger_id in data["bloggers"]]
        owned = [work for work in data["works"].values() if str(work.get("bloggerId")) in blogger_ids]
        collected_today = [work for work in owned if local_day(parse_iso(work.get("updatedAt"))) == today]
        new_today = [work for work in owned if is_new_work(work, moment.astimezone().date())]
        active = [blogger for blogger in followers if any(isinstance(item, Mapping) and item.get("enabled", True) for item in (blogger.get("follows") or {}).values())]
        statuses = [str((blogger.get("collection") or {}).get("status") or "idle") for blogger in active]
        if not data["settings"].get("collectEnabled", True):
            health = {"key": "paused", "label": "监控已暂停", "tone": "muted"}
        elif not active:
            health = {"key": "empty", "label": "还没有关注的博主", "tone": "muted"}
        elif any(status in ("queued", "running") for status in statuses):
            health = {"key": "syncing", "label": "正在同步", "tone": "active"}
        elif any(status == "auth_required" for status in statuses):
            health = {"key": "auth_required", "label": "需要检查数据接口配置", "tone": "warning"}
        elif any(status == "insufficient_balance" for status in statuses):
            health = {"key": "insufficient_balance", "label": "额度不足，已暂停", "tone": "warning"}
        elif any(status in ("failed", "partial") for status in statuses):
            health = {"key": "partial", "label": "部分采集未完成", "tone": "warning"}
        else:
            health = {"key": "ok", "label": "监控正常", "tone": "ok"}
        last_success = max((str((blogger.get("collection") or {}).get("lastSuccessAt") or "") for blogger in active), default="")
        follow_info = {blogger_id: ((data["bloggers"][blogger_id].get("follows") or {}).get(account_id) or {}) for blogger_id in blogger_ids if blogger_id in data["bloggers"]}
        return {
            "accountId": account_id,
            "bloggerCount": len(followers),
            "activeBloggerCount": len(active),
            "todayCollected": len(collected_today),
            "newToday": len(new_today),
            "savedCount": len(bucket.get("saves") or {}),
            "health": health,
            "lastSuccessAt": last_success,
            "lastSuccessText": published_text(last_success) if last_success else "",
            "settings": dict(data["settings"]),
            "usage": usage_view(bucket),
            "follows": follow_info,
            "recommendation": self._recommendation_view(data, account_id),
        }

    @_locked
    def list_follows(
        self,
        account_id: str,
        *,
        keyword: str = "",
        only_priority: bool = False,
        page: int = 1,
        page_size: int = MONITOR_BLOGGER_PAGE_SIZE,
        day: str = "today",
    ) -> dict[str, Any]:
        """关注的博主列表。

        day 跟着作品动态的日期筛选走：行内条数用同一套日期口径统计，
        切换「最近 N 天」时左边每位博主的数字和右边作品列表保持一致。
        """
        data = self._read()
        moment = datetime.now(timezone.utc)
        today_date = moment.astimezone().date()
        today = today_date.isoformat()
        window = str(day) if str(day) in MONITOR_WORK_DATE_OPTIONS else "today"
        entries: list[dict[str, Any]] = []
        for blogger_id, blogger in data["bloggers"].items():
            follow = (blogger.get("follows") or {}).get(account_id)
            if not isinstance(follow, Mapping):
                continue
            name = str(blogger.get("nickname") or "") or str(follow.get("note") or "")
            if keyword and keyword not in name and keyword not in str(follow.get("note") or ""):
                continue
            if only_priority and not follow.get("priority"):
                continue
            owned = [work for work in data["works"].values() if str(work.get("bloggerId")) == blogger_id]
            today_works = [work for work in owned if in_work_date_range(work.get("publishedAt"), "today", today_date)]
            range_works = [work for work in owned if in_work_date_range(work.get("publishedAt"), window, today_date)]
            collection = blogger.get("collection") if isinstance(blogger.get("collection"), dict) else {}
            entries.append({
                "id": blogger_id,
                "name": name,
                "nickname": str(blogger.get("nickname") or ""),
                "avatarUrl": str(blogger.get("avatarUrl") or ""),
                "avatarSrc": f"/api/monitor/avatars/{blogger_id}" if blogger.get("avatarUrl") else "",
                "signature": str(blogger.get("signature") or ""),
                "uniqueId": str(blogger.get("uniqueId") or ""),
                "followerCount": blogger.get("followerCount"),
                "awemeCount": blogger.get("awemeCount"),
                "note": str(follow.get("note") or ""),
                "priority": bool(follow.get("priority")),
                "enabled": bool(follow.get("enabled", True)),
                "intervalMinutes": normalize_interval(follow.get("intervalMinutes")),
                "todayWorkCount": len(today_works),
                "workCount": len(owned),
                "workWindow": window,
                "rangeWorkCount": len(range_works),
                "lastSuccessAt": str(collection.get("lastSuccessAt") or ""),
                "lastSuccessText": published_text(collection.get("lastSuccessAt")) if collection.get("lastSuccessAt") else "",
                "status": str(collection.get("status") or "idle"),
                "lastError": sanitize_message(str(collection.get("lastError") or "")),
                "lastErrorCode": public_code(str(collection.get("lastErrorCode") or "")),
                "baselineAt": str(blogger.get("baselineAt") or ""),
            })
        # 排序跟着行内显示的数字走，否则「最近 7 天」下会出现 5 条排在小数字后面。
        entries.sort(key=lambda item: (not item["priority"], -(item["rangeWorkCount"] or 0), item["name"]))
        total = len(entries)
        page_size = max(1, int(page_size or MONITOR_BLOGGER_PAGE_SIZE))
        page_count = max(1, (total + page_size - 1) // page_size)
        current = max(1, min(int(page or 1), page_count))
        return {
            "items": entries[(current - 1) * page_size : current * page_size],
            "total": total,
            "page": current,
            "pageCount": page_count,
            "workWindow": window,
            "priorityCount": sum(1 for item in entries if item["priority"]),
        }

    # ---- AI 建议 ------------------------------------------------------

    @_locked
    def get_recommendation(self, account_id: str) -> dict[str, Any]:
        return self._recommendation_view(self._read(), account_id)

    def _recommendation_view(self, data: Mapping[str, Any], account_id: str) -> dict[str, Any]:
        bucket = (data.get("accounts") or {}).get(account_id) or {}
        record = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), dict) else {}
        dismissed = bucket.get("dismissed") if isinstance(bucket.get("dismissed"), dict) else {}
        items = []
        for item in record.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            entry = dict(item)
            entry["dismissed"] = entry.get("key") in dismissed
            entry["topicId"] = str(entry.get("topicId") or "")
            items.append(entry)
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else {}
        return {
            "status": str(job.get("status") or "idle"),
            "error": sanitize_message(str(job.get("error") or "")),
            "errorCode": public_code(str(job.get("errorCode") or "")),
            "startedAt": str(job.get("startedAt") or ""),
            "finishedAt": str(job.get("finishedAt") or ""),
            "generatedAt": str(record.get("generatedAt") or ""),
            "generatedText": published_text(record.get("generatedAt")) if record.get("generatedAt") else "",
            "window": dict(record.get("window") or {}),
            "inputs": dict(record.get("inputs") or {}),
            "analysis": dict(record.get("analysis") or {}),
            "items": items,
            "dismissedItems": [
                {**dict(value), "key": key, "dismissed": True}
                for key, value in (bucket.get("dismissed") or {}).items()
                if isinstance(value, Mapping) and value.get("schemaVersion") == 2
                and key not in {str(item.get("key")) for item in items if isinstance(item, Mapping)}
            ],
            "dismissedCount": len(dismissed),
            "schemaVersion": record.get("schemaVersion", 1),
            "message": str(record.get("message") or ""),
        }

    @_locked
    def recommendation_recovery(self, account_id: str) -> dict[str, Any]:
        job = self._account(self._read(), account_id).get("recommendationJob") or {}
        if job.get("status") in ("pending", "running") and job.get("taskId") and (job.get("prepared") or {}).get("schemaVersion") == 2:
            return {"taskId": job["taskId"], "prepared": job["prepared"]}
        return {}

    @_locked
    def remember_recommendation_task(self, account_id: str, task_id: str, prepared: dict[str, Any]) -> None:
        if prepared.get("schemaVersion") != 2:
            raise ValueError("推荐方式已升级，请更新建议")
        data = self._read()
        job = self._account(data, account_id).setdefault("recommendationJob", {})
        job.update(taskId=task_id, prepared=prepared)
        self._write(data)

    @_locked
    def set_recommendation_job(self, account_id: str, status: str, *, error: str = "", error_code: str = "") -> dict[str, Any]:
        data = self._read()
        bucket = self._account(data, account_id)
        status = status if status in MONITOR_RECOMMENDATION_STATUSES else "failed"
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else {}
        job["status"] = status
        job["error"] = sanitize_message(str(error or ""))[:300]
        job["errorCode"] = public_code(str(error_code or ""))[:60]
        if status in ("success", "failed", "skipped", "unconfirmed"):
            job.pop("taskId", None)
            job.pop("prepared", None)
        if status == "running":
            job["startedAt"] = now_iso()
        else:
            job["finishedAt"] = now_iso()
        bucket["recommendationJob"] = job
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def save_recommendation(self, account_id: str, *, items: list[Mapping[str, Any]], window: Mapping[str, Any], inputs: Mapping[str, Any], analysis: Mapping[str, Any] | None = None, schema_version: int | None = None) -> dict[str, Any]:
        items = _original_items(items, schema_version)
        data = self._read()
        bucket = self._account(data, account_id)
        previous = {recommendation_key(item): item for item in (bucket.get("recommendation") or {}).get("items", [])}
        for item in items:
            old = previous.get(item["key"], {})
            if old.get("topicId"):
                item["topicId"] = old["topicId"]
                item["adoptedAt"] = old.get("adoptedAt", "")
        record = {
            "schemaVersion": 2,
            "generatedAt": now_iso(),
            "window": dict(window),
            "inputs": dict(inputs),
            "analysis": dict(analysis or {}),
            "items": [dict(item) for item in items][:MONITOR_RECOMMENDATION_LIMIT],
        }
        bucket["recommendation"] = record
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else {}
        job["status"] = "success"
        job.pop("taskId", None)
        job.pop("prepared", None)
        job["errorCode"] = ""
        job["error"] = ""
        job["finishedAt"] = now_iso()
        bucket["recommendationJob"] = job
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def patch_legacy_hooks(self, account_id: str, matches: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Merge only missing hooks; preserve the original generation and adoption metadata."""
        data = self._read()
        record = self._account(data, account_id).get("recommendation") or {}
        by_key = {item["key"]: item for item in matches}
        for item in record.get("items") or []:
            match = by_key.get(item.get("key"))
            if match and not item.get("hook") and item.get("title") == match.get("title"):
                item.update({"hook": dict(match["hook"]), "hookReason": str(match["hookReason"]),
                             "hookMatchSource": "legacy-title", "hookMatchedAt": now_iso()})
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def recommendation_item(self, account_id: str, key: str) -> dict[str, Any]:
        view = self._recommendation_view(self._read(), account_id)
        for item in view["items"]:
            if str(item.get("key")) == str(key):
                return item
        raise ValueError("这条建议已经不存在，请更新建议后重试。")

    @_locked
    def dismiss_recommendation(self, account_id: str, key: str) -> dict[str, Any]:
        item = self.recommendation_item(account_id, key)
        data = self._read()
        bucket = self._account(data, account_id)
        bucket["dismissed"][str(key)] = {
            **dict(item),
            "title": str(item.get("title") or ""),
            "dismissedAt": now_iso(),
        }
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def restore_recommendation(self, account_id: str, key: str) -> dict[str, Any]:
        data = self._read()
        bucket = self._account(data, account_id)
        bucket["dismissed"].pop(str(key), None)
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def mark_recommendation_topic(self, account_id: str, key: str, topic_id: str) -> dict[str, Any]:
        data = self._read()
        bucket = self._account(data, account_id)
        record = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), dict) else {}
        for item in record.get("items") or []:
            if isinstance(item, dict) and str(item.get("key")) == str(key):
                item["topicId"] = str(topic_id)
                item["adoptedAt"] = now_iso()
        self._write(data)
        return self._recommendation_view(data, account_id)

    @_locked
    def dismissed_recommendations(self, account_id: str) -> list[dict[str, Any]]:
        data = self._read()
        bucket = self._account(data, account_id)
        return [{"key": key, **value} for key, value in bucket["dismissed"].items() if isinstance(value, Mapping)]

    @_locked
    def recommendation_works(
        self,
        account_id: str,
        *,
        since: str = "",
        limit: int = 200,
        include_baseline: bool = False,
    ) -> list[dict[str, Any]]:
        """给 AI 分析用的候选作品：当前账号关注范围内、按发现时间过滤后的最近作品。

        默认排除首次导入的历史基线：那些作品不是今天出现的，把它们当成今日热点会误导选题。
        只有候选太少时，调用方才显式允许纳入，并需要在窗口说明里讲清楚。
        """
        data = self._read()
        blogger_ids = self.account_blogger_ids(account_id)
        bucket = self._account(data, account_id)
        cutoff = parse_iso(since) if since else None
        today = datetime.now(timezone.utc).astimezone().date()
        rows: list[dict[str, Any]] = []
        for work in data["works"].values():
            if str(work.get("bloggerId")) not in blogger_ids:
                continue
            discovered = parse_iso(work.get("discoveredAt"))
            if cutoff is not None:
                if discovered is None or discovered < cutoff:
                    continue
            if work.get("baseline") and not include_baseline:
                continue
            blogger = data["bloggers"].get(str(work.get("bloggerId"))) or {}
            metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
            rows.append({
                "id": str(work.get("id") or ""),
                "bloggerId": str(work.get("bloggerId") or ""),
                "statsUpdatedAt": str(work.get("statsUpdatedAt") or ""),
                "bloggerName": str(blogger.get("nickname") or ""),
                "title": str(work.get("title") or ""),
                "shareUrl": str(work.get("shareUrl") or ""),
                "coverUrl": str(work.get("coverUrl") or ""),
                "coverSrc": f"/api/monitor/covers/{work.get('id')}" if work.get("coverUrl") else "",
                "kind": str(work.get("kind") or "video"),
                "publishedAt": str(work.get("publishedAt") or ""),
                "publishedText": published_text(work.get("publishedAt")),
                "discoveredAt": str(work.get("discoveredAt") or ""),
                "isNew": is_new_work(work, today),
                "metrics": {field: metrics.get(field) for field in MONITOR_METRIC_FIELDS},
            })
        rows.sort(key=lambda item: (item.get("discoveredAt") or "", item.get("publishedAt") or ""), reverse=True)
        return rows[: max(1, int(limit))]

    # ---- 用量 ---------------------------------------------------------

    @_locked
    def record_requests(self, kind: str, count: int = 1, *, account_ids: Iterable[str] = ()) -> dict[str, Any]:
        """全局只计一次；账号按发起者或定时任务的关注快照分别累计。"""
        if count <= 0:
            return self.usage_view()
        data = self._read()
        day = local_day()
        requested_at = now_iso()
        targets = [data, *(self._account(data, account_id) for account_id in dict.fromkeys(account_ids) if account_id)]
        for target in targets:
            usage = target.get("usage") if isinstance(target.get("usage"), dict) else {}
            by_day = usage.get("byDay") if isinstance(usage.get("byDay"), dict) else {}
            bucket = by_day.get(day) if isinstance(by_day.get(day), dict) else {}
            bucket[kind] = int(bucket.get(kind) or 0) + int(count)
            by_day[day] = bucket
            usage["byDay"] = {key: value for key, value in sorted(by_day.items())[-MONITOR_USAGE_KEEP_DAYS:]}
            usage["requests"] = int(usage.get("requests") or 0) + int(count)
            usage["lastRequestAt"] = requested_at
            target["usage"] = usage
        self._write(data)
        return usage_view(data)

    @_locked
    def usage_view(self) -> dict[str, Any]:
        return usage_view(self._read())

    @_locked
    def record_charge(self, amount_points: str, requests: int = 0) -> dict[str, Any]:
        """记一次真实的创作服务扣费：界面按「总请求数 + 总费用」汇总，不伪装成固定价格。"""
        data = self._read()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        by_day = usage.get("chargedByDay") if isinstance(usage.get("chargedByDay"), dict) else {}
        day = local_day()
        by_day[day] = str(_add_points(by_day.get(day), amount_points))
        usage["chargedByDay"] = {key: value for key, value in sorted(by_day.items())[-MONITOR_USAGE_KEEP_DAYS:]}
        usage["chargedTotalPoints"] = str(_add_points(usage.get("chargedTotalPoints"), amount_points))
        usage["lastChargedRequests"] = int(requests or 0)
        data["usage"] = usage
        self._write(data)
        return usage_view(data)

    # ---- 账号生命周期 -------------------------------------------------

    @_locked
    def delete_account(self, account_id: str) -> int:
        """账号删除时清理它的关注关系和账号层数据；共享作品保留给其他账号。"""
        data = self._read()
        removed = 0
        for blogger in data["bloggers"].values():
            follows = blogger.get("follows") if isinstance(blogger.get("follows"), dict) else {}
            if account_id in follows:
                follows.pop(account_id, None)
                removed += 1
        data["accounts"].pop(account_id, None)
        self._write(data)
        return removed

    @_locked
    def orphan_bloggers(self) -> list[str]:
        """没有任何账号关注的共享博主；暂不自动删除，供后续清理使用。"""
        return [
            blogger_id
            for blogger_id, blogger in self._read()["bloggers"].items()
            if not (blogger.get("follows") or {})
        ]


def is_new_work(work: Mapping[str, Any], today: date) -> bool:
    """「新发现」＝今天被发现的非历史基线作品。"""
    if work.get("baseline"):
        return False
    discovered = parse_iso(work.get("discoveredAt"))
    if discovered is None:
        return False
    return discovered.astimezone().date() == today


def _original_items(items: Iterable[Mapping[str, Any]], schema_version: int | None) -> list[dict[str, Any]]:
    entries = [dict(item) for item in items]
    if schema_version not in (None, 2) or (not entries and schema_version != 2):
        raise ValueError("推荐方式已升级，请更新建议")
    for entry in entries:
        source = entry.get("sourceWork")
        if (entry.get("schemaVersion") != 2 or not str(entry.get("sourceWorkId") or "").strip()
                or not isinstance(source, Mapping) or not str(source.get("title") or "").strip()
                or entry.get("title") != source.get("title")
                or str(source.get("id") or "") != str(entry.get("sourceWorkId"))):
            raise ValueError("推荐必须使用原作品完整标题和来源快照")
        entry["key"] = recommendation_key(entry)
    return entries


def recommendation_key(item: Mapping[str, Any]) -> str:
    """建议的稳定标识：同一条建议重新生成后仍是同一个 key，暂不考虑状态不会丢。"""
    if item.get("schemaVersion") == 2 and str(item.get("sourceWorkId") or "").strip():
        return "monitor:" + str(item["sourceWorkId"]).strip()
    refs = item.get("references") if isinstance(item.get("references"), list) else []
    seed = f"{str(item.get('title') or '').strip()}|{str(refs[0]) if refs else ''}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def usage_view(data: Mapping[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    by_day = usage.get("byDay") if isinstance(usage.get("byDay"), dict) else {}
    charged_by_day = usage.get("chargedByDay") if isinstance(usage.get("chargedByDay"), dict) else {}
    today = local_day()
    today_counts = by_day.get(today) if isinstance(by_day.get(today), dict) else {}
    today_total = sum(int(value or 0) for value in today_counts.values())
    total_requests = int(usage.get("requests") or 0)
    total_charged = str(usage.get("chargedTotalPoints") or "0.00")
    today_charged = str(charged_by_day.get(today) or "0.00")
    return {
        "requests": total_requests,
        "todayRequests": today_total,
        "todayBreakdown": {key: int(value or 0) for key, value in today_counts.items()},
        # 创作服务的真实扣费：总请求数与总费用一起给，供界面汇总展示。
        "chargedTotalPoints": total_charged,
        "chargedTodayPoints": today_charged,
        "lastChargedRequests": int(usage.get("lastChargedRequests") or 0),
        # 兼容字段：仅用于旧记录的量级参考，界面以真实扣费为准。
        "estimatedCostUsd": round(total_requests * MONITOR_REQUEST_COST_USD, 3),
        "lastRequestAt": str(usage.get("lastRequestAt") or ""),
        "byDay": {key: dict(value) for key, value in by_day.items() if isinstance(value, Mapping)},
    }


def _add_points(current: Any, amount: Any) -> str:
    """把两笔积分数相加并保留两位小数；无法解析的一方按 0 处理。"""
    from decimal import Decimal

    def parse(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:  # noqa: BLE001
            return Decimal("0")

    return "%0.2f" % (parse(current) + parse(amount))


def normalize_interval(value: Any) -> int:
    """频率只接受确认过的固定档位，避免出现任意分钟数。"""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return MONITOR_DEFAULT_INTERVAL_MINUTES
    return minutes if minutes in MONITOR_INTERVAL_OPTIONS else MONITOR_DEFAULT_INTERVAL_MINUTES


def normalize_settings(values: Mapping[str, Any]) -> dict[str, Any]:
    source = values if isinstance(values, Mapping) else {}
    defaults = default_settings()
    ai_time = str(source.get("aiDailyTime") or defaults["aiDailyTime"]).strip()
    if not _valid_clock(ai_time):
        ai_time = defaults["aiDailyTime"]
    return {
        "collectEnabled": bool(source.get("collectEnabled", defaults["collectEnabled"])),
        "intervalMinutes": normalize_interval(source.get("intervalMinutes")),
        "aiEnabled": bool(source.get("aiEnabled", defaults["aiEnabled"])),
        "aiDailyTime": ai_time,
    }


def _valid_clock(value: str) -> bool:
    parts = str(value or "").split(":")
    if len(parts) != 2:
        return False
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def ai_due_at(settings: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """到点判断：当天已过设定时刻就允许生成一次，由调用方按「今天是否已生成」去重。"""
    if not settings.get("aiEnabled", True):
        return False
    text = str(settings.get("aiDailyTime") or MONITOR_DEFAULT_AI_TIME)
    if not _valid_clock(text):
        text = MONITOR_DEFAULT_AI_TIME
    hour, minute = (int(part) for part in text.split(":"))
    moment = (now or datetime.now(timezone.utc)).astimezone()
    return (moment.hour, moment.minute) >= (hour, minute)


# ----------------------------------------------------------------------
# AI 分析输入
# ----------------------------------------------------------------------


def build_recommendation_context(
    *,
    account_name: str,
    business_positioning: str,
    target_audience: str,
    monitor_works: list[Mapping[str, Any]],
    review_works: list[Mapping[str, Any]],
    existing_topics: list[Mapping[str, Any]],
    dismissed: list[Mapping[str, Any]],
    window: Mapping[str, Any],
    today: str,
    works_limit: int = 120,
    review_limit: int = 30,
) -> dict[str, Any]:
    """把所有输入整理成一次模型调用的上下文。

    只放模型判断真正需要的信息，并显式说明数据缺口，避免它把「没有这个字段」
    当成「数据是 0」，也避免它以为看过视频正文。
    """
    works = [dict(work) for work in monitor_works[: max(1, int(works_limit))]]
    review = [dict(work) for work in review_works[: max(1, int(review_limit))]]
    scored = [work for work in review if isinstance(work.get("metrics"), Mapping) and work["metrics"].get("likes") is not None]
    scored.sort(key=lambda work: int(work["metrics"].get("likes") or 0), reverse=True)
    notes = [
        {"title": str(work.get("title") or ""), "note": str(work.get("note") or "")[:200]}
        for work in review
        if str(work.get("note") or "").strip()
    ][:8]
    return {
        "account": {
            "name": str(account_name or ""),
            "businessPositioning": str(business_positioning or ""),
            "targetAudience": str(target_audience or ""),
        },
        "today": str(today),
        "window": dict(window),
        "monitorWorks": works,
        "monitorWorkCount": len(monitor_works),
        "monitorWorksTruncated": len(monitor_works) > len(works),
        "review": {
            "windowDays": MONITOR_RECENT_WINDOW_DAYS,
            "total": len(review_works),
            "withMetrics": len(scored),
            "betterPerforming": [
                {
                    "title": str(work.get("title") or ""),
                    "publishedAt": str(work.get("publishedAtIso") or ""),
                    "metrics": {
                        "views": (work.get("metrics") or {}).get("views"),
                        "likes": (work.get("metrics") or {}).get("likes"),
                        "saves": (work.get("metrics") or {}).get("saves"),
                        "completionRate": (work.get("metrics") or {}).get("completionRate"),
                    },
                }
                for work in scored[:5]
            ],
            "weakerPerforming": [
                {
                    "title": str(work.get("title") or ""),
                    "metrics": {"views": (work.get("metrics") or {}).get("views"), "likes": (work.get("metrics") or {}).get("likes")},
                }
                for work in scored[-3:]
            ],
            "notes": notes,
            "hasData": bool(scored),
        },
        "existingTopics": [
            {"title": str(topic.get("title") or ""), "weekStart": str(topic.get("weekStart") or ""), "category": str(topic.get("category") or "")}
            for topic in existing_topics[:40]
        ],
        "dismissed": [
            {"title": str(item.get("title") or ""), "sourceWorkId": str(item.get("sourceWorkId") or "")} for item in dismissed[:20]
        ],
    }
