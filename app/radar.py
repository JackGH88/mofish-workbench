"""雷达（radar）模块：按行业关键词持续发现近期视频、低粉爆款与趋势信息。

数据分两层保存：

* **共享层**：作品记录按抖音作品 ID 去重。不同关键词、不同创作账号命中的同一作品只存一份，
  各自保留来源关联，避免因为多账号订阅而重复付费采集。
* **账号层**：关键词订阅、收藏/未读状态、AI 建议按创作账号隔离；趋势快照按词共享。

采集走 ``app/data_service.py``；本模块只做规范化、去重、快照、调度判断和视图组装。
所有指标都按接口真实返回保存，缺失记为 ``None``，不补零，也不推算出接口没有给的数字：
V3（低粉爆款）只返回粉丝数和点赞数，因此那类作品的评论/分享保持缺失。
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import secrets
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Callable, Iterable, Mapping

from .monitor import now_iso, parse_iso, published_text
from .upstream_errors import public_code, sanitize_message
from .subscription import NEEDS_RELOGIN, RELOGIN_CODES

logger = logging.getLogger("douyin-downloader")

RADAR_DATA_VERSION = 2
RADAR_PLATFORM = "douyin"

RADAR_DEFAULT_DAILY_TIME = "09:00"
RADAR_DEFAULT_AI_TIME = "10:30"
RADAR_KEYWORD_KINDS = ("normal", "key")
RADAR_KEYWORD_KIND_LABELS = {"normal": "普通", "key": "重点"}
RADAR_UNGROUPED = "未分组"

# 采集窗口：日常是「最近一天」，首次建库和停机恢复是「最近七天」。
RADAR_WINDOW_DAY = "day"
RADAR_WINDOW_WEEK = "week"
RADAR_WINDOW_LABELS = {RADAR_WINDOW_DAY: "最近一天", RADAR_WINDOW_WEEK: "最近七天"}
RADAR_INITIAL_PAGES = 3
RADAR_PAGE_LIMIT = 3
RADAR_RECOVERY_HOURS = 24
RADAR_GAP_HOURS = 24 * 7

# 作品来源：search＝V2 近期视频，lowfans＝V3 低粉爆款。
RADAR_SOURCES = ("search", "lowfans")
RADAR_TABS = ("all", "latest", "lowfans")
RADAR_TAB_LABELS = {"all": "全部", "latest": "最新视频", "lowfans": "低粉爆款"}
RADAR_FILTERS = ("all", "unread", "saved")
RADAR_FILTER_LABELS = {"all": "全部状态", "unread": "未读", "saved": "已收藏"}
RADAR_DATE_OPTIONS = ("today", "yesterday", "7d", "30d", "all")
RADAR_DATE_LABELS = {"today": "今天", "yesterday": "昨天", "7d": "近 7 天", "30d": "近 30 天", "all": "全部日期"}
RADAR_DATE_RANGE_DAYS = {"7d": 7, "30d": 30}
RADAR_DEFAULT_DAY = "7d"

RADAR_METRIC_FIELDS = ("likes", "comments", "shares")
RADAR_METRIC_LABELS = {"likes": "点赞", "comments": "评论", "shares": "分享"}
RADAR_KINDS = ("video", "image")

RADAR_PAGE_SIZE = 10
RADAR_PAGE_SIZE_MAX = 50
RADAR_TITLE_LIMIT = 200
RADAR_SNAPSHOT_LIMIT = 60
RADAR_WORK_LIMIT = 5000
RADAR_USAGE_KEEP_DAYS = 60
RADAR_MIN_RETRY_SECONDS = 300
RADAR_KEYWORD_LIMIT = 60
RADAR_GROUP_LIMIT = 20
RADAR_SUGGEST_LIMIT = 8
RADAR_TREND_LIMIT = 10
RADAR_TREND_ITEM_LIMIT = 5

RADAR_RECOMMENDATION_LIMIT = 3
RADAR_RECOMMENDATION_MAX = 6
RADAR_ANALYSIS_WINDOW_DAYS = 7
RADAR_RECOMMENDATION_STATUSES = ("idle", "running", "success", "failed", "skipped")

RADAR_STATUSES = (
    "idle",
    "queued",
    "running",
    "success",
    "partial",
    "failed",
    "auth_required",
    "insufficient_balance",
)
RADAR_ACTIVE_STATUSES = ("queued", "running")
# 这两类错误在人工处理前不再自动重试，避免无限消耗付费额度。
RADAR_BLOCKING_STATUSES = ("auth_required", "insufficient_balance")

# 官方当期公开单价（美元/次）。免费额度与折扣是否命中不预扣，只在展示层注明估算依据。
RADAR_REQUEST_COSTS = {"search": 0.01, "lowfans": 0.01, "suggest": 0.01, "trend": 0.001}
RADAR_REQUEST_KINDS = tuple(RADAR_REQUEST_COSTS)


# ----------------------------------------------------------------------
# 时间与字段小工具
# ----------------------------------------------------------------------


def _unix_to_iso(value: Any) -> str:
    """抖音时间戳可能是秒、毫秒，或以字符串形式返回（V3 就是毫秒字符串）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if number > 10_000_000_000:  # 毫秒
        number = number // 1000
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _local_time_to_iso(value: Any) -> str:
    """V3 的 ``createTime`` 实测是北京时间字符串 ``2026-09-18 17:34:49``，不是时间戳。

    按北京时间（UTC+8）解释后转成 UTC ISO，和 V2 的作品时间口径一致；
    解析不出来就返回空串，交由窗口校验把这些作品挡在「最近一天」之外。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc).isoformat()
    return _unix_to_iso(text)


def _pick_time(value: Any) -> str:
    """时间字段既可能是 unix 时间戳，也可能是北京时间字符串，两种都支持。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "-" in text or ":" in text:
        return _local_time_to_iso(text)
    return _unix_to_iso(text)


def _pick_int(*values: Any) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return None


def _first_url(node: Any) -> str:
    """抖音的封面/播放地址统一是 ``{"url_list": [...]}``，取第一个可用地址。"""
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


def clock_parts(value: Any) -> tuple[int, int]:
    """把 ``HH:MM`` 解成小时和分钟；非法输入退回默认时刻。"""
    parts = str(value or "").split(":")
    if len(parts) == 2:
        try:
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
        except ValueError:
            pass
    return clock_parts(RADAR_DEFAULT_DAILY_TIME)


def trend_day(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def normalize_clock(value: Any, *, fallback: str = RADAR_DEFAULT_DAILY_TIME) -> str:
    parts = str(value or "").split(":")
    if len(parts) == 2:
        try:
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except ValueError:
            pass
    return fallback


def in_date_range(published_at: Any, day: str, today: date) -> bool:
    """作品发布时间是否落在列表日期筛选范围内；口径和监控模块保持一致。"""
    if str(day) == "all":
        return True
    published_day = local_day(parse_iso(published_at)) if published_at else ""
    if str(day) == "today":
        return published_day == today.isoformat()
    if str(day) == "yesterday":
        return published_day == (today - timedelta(days=1)).isoformat()
    range_days = RADAR_DATE_RANGE_DAYS.get(str(day))
    if range_days is None:
        return True
    if not published_day:
        return False
    earliest = (today - timedelta(days=range_days - 1)).isoformat()
    return earliest <= published_day <= today.isoformat()


def local_day(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def source_channels(source: Mapping[str, Any]) -> dict[str, Any]:
    channels = source.get("channels")
    if isinstance(channels, dict):
        return channels
    kind = str(source.get("source") or "search")
    return {kind: {k: v for k, v in source.items() if k != "channels"}}


def has_source(source: Mapping[str, Any], kind: str) -> bool:
    channels = source_channels(source)
    return kind in channels and (kind != "lowfans" or bool(channels[kind].get("lowFans")))


def work_lowfans(work: Mapping[str, Any], owned_ids=None) -> bool:
    return any(has_source(value, "lowfans") for key, value in work.get("sources", {}).items()
               if owned_ids is None or key in owned_ids)


def within_window(published_at: Any, window: str, *, now: datetime | None = None) -> bool:
    """请求返回后的本地二次校验：超出窗口或时间缺失的作品不进对应列表。

    接口文档写的是「最近一天/最近一周」，但实测只保证大致范围，所以这里再按发布时间核一遍。
    昨天发布但仍在过去 24 小时内属于正常情况，不算越界。
    """
    moment = now or datetime.now(timezone.utc)
    published = parse_iso(published_at)
    if published is None or published > moment:
        return False
    if str(window) == RADAR_WINDOW_WEEK:
        return published >= moment - timedelta(days=7)
    return published >= moment - timedelta(hours=24)


def _locked(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapper(self: "RadarStore", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


# ----------------------------------------------------------------------
# 接口返回 → 雷达作品
# ----------------------------------------------------------------------


def search_items(data: Any) -> list[Mapping[str, Any]]:
    """V2 响应里的视频列表；卡片被平台包了一层，这里统一解包。"""
    payload = data if isinstance(data, Mapping) else {}
    cards = payload.get("business_data")
    if not isinstance(cards, Iterable) or isinstance(cards, (str, bytes)):
        return []
    items: list[Mapping[str, Any]] = []
    for card in cards:
        node = card if isinstance(card, Mapping) else {}
        inner = node.get("data") if isinstance(node.get("data"), Mapping) else {}
        aweme = inner.get("aweme_info") or inner.get("aweme_list") or node.get("aweme_info")
        if isinstance(aweme, Mapping):
            items.append(aweme)
        elif isinstance(aweme, Iterable) and not isinstance(aweme, (str, bytes)):
            items.extend(entry for entry in aweme if isinstance(entry, Mapping))
    return items


def search_pagination(data: Any) -> dict[str, Any]:
    """V2 的翻页信息：``has_more``、下一页游标与搜索上下文。"""
    payload = data if isinstance(data, Mapping) else {}
    config = payload.get("business_config") if isinstance(payload.get("business_config"), Mapping) else {}
    next_page = config.get("next_page") if isinstance(config.get("next_page"), Mapping) else {}
    has_more = _pick_int(config.get("has_more")) or 0
    return {
        "hasMore": bool(has_more),
        "cursor": next_page.get("cursor", 0),
        "searchId": str(next_page.get("search_id") or ""),
        "backtrace": str(config.get("backtrace") or ""),
    }


def low_fans_items(data: Any) -> list[Mapping[str, Any]]:
    """V3 响应里的低粉爆款列表。

    ``data_serviceClient`` 已经剥掉最外层的 ``code/data`` 信封，实测（2026-09-21）剩下的结构是
    ``{"data": [ ...作品... ]}``；这里同时容忍多包一层的写法，避免接口再改层级时静默变空。
    """
    payload = data if isinstance(data, Mapping) else {}
    candidate = payload.get("data")
    if isinstance(candidate, Mapping):
        candidate = candidate.get("data")
    rows = candidate
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def hot_items(data: Any) -> list[dict[str, Any]]:
    """热度飙升榜；这个接口是嵌套信封 ``data.data.search_list``。"""
    payload = data if isinstance(data, Mapping) else {}
    inner = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    rows = inner.get("search_list")
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
        return []
    items: list[dict[str, Any]] = []
    for row in rows[:RADAR_TREND_LIMIT]:
        node = row if isinstance(row, Mapping) else {}
        word = str(node.get("key_word") or "").strip()
        if not word:
            continue
        trends = node.get("trends")
        labels = [str(entry.get("label" if isinstance(entry, Mapping) else "") or "").strip() for entry in trends] if isinstance(trends, Iterable) and not isinstance(trends, (str, bytes)) else []
        items.append({
            "keyword": word[:60],
            "score": _pick_int(node.get("search_score")),
            "trends": [label for label in labels if label][:RADAR_TREND_ITEM_LIMIT],
        })
    return items


def suggest_words(data: Any) -> list[str]:
    """搜索联想词。``fetch_search_suggest_v2`` 实测已下线，这里是 V1 的 ``sug_list``。"""
    payload = data if isinstance(data, Mapping) else {}
    rows = payload.get("sug_list")
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
        return []
    words: list[str] = []
    for row in rows:
        node = row if isinstance(row, Mapping) else {}
        text = str(node.get("content") or "").strip()
        if text and text not in words:
            words.append(text[:60])
        if len(words) >= RADAR_SUGGEST_LIMIT:
            break
    return words


def normalize_search_work(raw: Any) -> dict[str, Any] | None:
    """把 V2 的一条作品转成雷达记录；缺作品 ID 的直接丢弃。"""
    item = raw if isinstance(raw, Mapping) else {}
    work_id = str(item.get("aweme_id") or item.get("awemeId") or "").strip()
    if not work_id:
        return None
    author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
    video = item.get("video") if isinstance(item.get("video"), Mapping) else {}
    statistics = item.get("statistics") if isinstance(item.get("statistics"), Mapping) else {}
    images = [entry for entry in (item.get("images") or []) if isinstance(entry, Mapping)]
    duration_ms = _pick_int(video.get("duration"))
    kind = "image" if (images and not _first_url(video.get("play_addr"))) else "video"
    raw_type = _pick_int(item.get("aweme_type"))
    if raw_type in (2, 68) and images:
        kind = "image"
    cover = (
        _first_url(video.get("cover"))
        or _first_url(video.get("origin_cover"))
        or _first_url(video.get("dynamic_cover"))
        or (_first_url(images[0]) if images else "")
    )
    author_avatar = _first_url(author.get("avatar_thumb")) or _first_url(author.get("avatar_medium"))
    share_url = str(item.get("share_url") or "").strip()
    if not share_url:
        prefix = "note" if kind == "image" else "video"
        share_url = f"https://www.douyin.com/{prefix}/{work_id}"
    return {
        "id": work_id,
        "title": str(item.get("desc") or "").strip(),
        "kind": kind,
        "publishedAt": _pick_time(item.get("create_time")),
        "authorName": str(author.get("nickname") or "").strip()[:80],
        "authorId": str(author.get("sec_uid") or author.get("uid") or "").strip(),
        "authorFollowers": _pick_int(author.get("follower_count")),
        "authorAvatarUrl": author_avatar,
        "coverUrl": cover,
        "shareUrl": share_url,
        "durationSeconds": int(duration_ms / 1000) if duration_ms else None,
        "imageCount": len(images),
        "metrics": {
            "likes": _pick_int(statistics.get("digg_count")),
            "comments": _pick_int(statistics.get("comment_count")),
            "shares": _pick_int(statistics.get("share_count")),
        },
        "lowFans": False,
    }


def normalize_low_fans_work(raw: Any) -> dict[str, Any] | None:
    """把 V3 的一条低粉爆款转成雷达记录。

    V3 的字段是扁平的，而且只有点赞数、没有评论/分享，所以这两项保持 ``None``。
    是否「低粉爆款」以平台返回的 ``isLowFansButHot`` 为准，不自行用粉丝数推算。
    """
    item = raw if isinstance(raw, Mapping) else {}
    work_id = str(item.get("itemId") or item.get("aweme_id") or "").strip()
    if not work_id:
        return None
    share_url = str(item.get("url") or "").strip()
    if not share_url:
        share_url = f"https://www.douyin.com/video/{work_id}"
    # V3 的 duration 实测就是秒（V2 的 video.duration 才是毫秒），不做除法。
    duration_seconds = _pick_int(item.get("duration"))
    return {
        "id": work_id,
        "title": str(item.get("title") or "").strip(),
        "kind": "video",
        "publishedAt": _pick_time(item.get("createTime")),
        "authorName": str(item.get("nickname") or "").strip()[:80],
        "authorId": "",
        "authorFollowers": _pick_int(item.get("fans")),
        "authorAvatarUrl": str(item.get("avatarUrl") or "").strip(),
        "coverUrl": str(item.get("thumbnail") or "").strip(),
        "shareUrl": share_url,
        "durationSeconds": duration_seconds if duration_seconds else None,
        "imageCount": 0,
        "metrics": {
            "likes": _pick_int(item.get("likes")),
            "comments": None,
            "shares": None,
        },
        "lowFans": item.get("isLowFansButHot") is True or _pick_int(item.get("isLowFansButHot")) == 1,
    }


def _metrics_changed(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> bool:
    before = previous if isinstance(previous, Mapping) else {}
    return any(before.get(field) != current.get(field) for field in RADAR_METRIC_FIELDS)


def plan_collection(keyword: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """决定这一轮该查哪个窗口、最多几页、是否标记历史导入。

    * 从没成功过 → 最近七天、最多三页、标记历史导入（建立初始参考库）。
    * 停机超过 24 小时 → 最近七天、一页，覆盖停机缺口。
    * 其余 → 最近一天、一页。
    """
    moment = now or datetime.now(timezone.utc)
    collection = keyword.get("collection") if isinstance(keyword.get("collection"), Mapping) else {}
    last_success = parse_iso(collection.get("lastSuccessAt"))
    if last_success is None:
        return {
            "window": RADAR_WINDOW_WEEK,
            "pages": RADAR_INITIAL_PAGES,
            "baseline": not parse_iso(keyword.get("historyImportedAt")),
            "mode": "initial",
            "gapHours": None,
            "gapNote": "",
        }
    hours = (moment - last_success).total_seconds() / 3600.0
    if hours > RADAR_RECOVERY_HOURS:
        gap = hours > RADAR_GAP_HOURS
        return {
            "window": RADAR_WINDOW_WEEK,
            "pages": RADAR_PAGE_LIMIT,
            "baseline": False,
            "mode": "recovery",
            "gapHours": round(hours, 1),
            "gapNote": "停机超过七天，超过七天的部分无法补齐。" if gap else "停机超过一天，本轮按最近七天补查一页。",
        }
    return {
        "window": RADAR_WINDOW_DAY,
        "pages": RADAR_PAGE_LIMIT,
        "baseline": False,
        "mode": "daily",
        "gapHours": None,
        "gapNote": "",
    }


def default_settings() -> dict[str, Any]:
    return {"collectDailyTime": RADAR_DEFAULT_DAILY_TIME, "collectDailyTimeSource": "legacy", "collectEnabled": True, "aiEnabled": True, "aiDailyTime": RADAR_DEFAULT_AI_TIME}


def normalize_settings(values: Mapping[str, Any]) -> dict[str, Any]:
    source = values if isinstance(values, Mapping) else {}
    defaults = default_settings()
    return {
        "collectDailyTime": normalize_clock(source.get("collectDailyTime")),
        "collectDailyTimeSource": source.get("collectDailyTimeSource") if source.get("collectDailyTimeSource") in {"auto", "manual", "legacy"} else "legacy",
        "collectEnabled": bool(source.get("collectEnabled", defaults["collectEnabled"])),
        "aiEnabled": bool(source.get("aiEnabled", defaults["aiEnabled"])),
        "aiDailyTime": normalize_clock(source.get("aiDailyTime"), fallback=defaults["aiDailyTime"]),
    }


def ai_due_at(settings: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """到点判断；是否「今天已经生成过」由调用方按账号去重。"""
    if not settings.get("aiEnabled", True):
        return False
    hour, minute = clock_parts(settings.get("aiDailyTime") or RADAR_DEFAULT_AI_TIME)
    moment = (now or datetime.now(timezone.utc)).astimezone()
    return (moment.hour, moment.minute) >= (hour, minute)


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
    """建议的稳定标识：同一条建议重新生成后仍是同一个 key，「暂不考虑」不会丢。"""
    if item.get("schemaVersion") == 2 and str(item.get("sourceWorkId") or "").strip():
        return "radar:" + str(item["sourceWorkId"]).strip()
    refs = item.get("references") if isinstance(item.get("references"), list) else []
    seed = f"{str(item.get('title') or '').strip()}|{str(refs[0]) if refs else ''}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def usage_view(data: Mapping[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
    by_day = usage.get("byDay") if isinstance(usage.get("byDay"), Mapping) else {}
    charged_by_day = usage.get("chargedByDay") if isinstance(usage.get("chargedByDay"), Mapping) else {}
    today_counts = by_day.get(local_day()) if isinstance(by_day.get(local_day()), Mapping) else {}
    totals: dict[str, int] = {}
    for bucket in by_day.values():
        if isinstance(bucket, Mapping):
            for kind, count in bucket.items():
                totals[str(kind)] = totals.get(str(kind), 0) + int(count or 0)
    cost = sum(RADAR_REQUEST_COSTS.get(str(kind), 0.0) * count for kind, count in totals.items())
    return {
        "requests": int(usage.get("requests") or 0),
        "todayRequests": sum(int(value or 0) for value in today_counts.values()),
        "todayBreakdown": {str(key): int(value or 0) for key, value in today_counts.items()},
        # 创作服务的真实扣费：总请求数与总费用一起给，供界面汇总展示。
        "chargedTotalPoints": str(usage.get("chargedTotalPoints") or "0.000"),
        "chargedTodayPoints": str(charged_by_day.get(local_day()) or "0.000"),
        "lastChargedRequests": int(usage.get("lastChargedRequests") or 0),
        "estimatedCostUsd": round(cost, 3),
        "lastRequestAt": str(usage.get("lastRequestAt") or ""),
        "costs": dict(RADAR_REQUEST_COSTS),
    }


class RadarStore:
    """雷达数据存储：共享作品 + 按创作账号隔离的关键词、状态与 AI 建议。"""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._path = self._workspace_dir / "radar-data.json"
        self._covers_dir = self._workspace_dir / "radar-covers"
        self._lock = threading.RLock()

    @property
    def covers_dir(self) -> Path:
        """封面缓存目录：抖音封面是签名临时地址，需要本地落盘后才能稳定显示。"""
        return self._covers_dir

    @_locked
    def cover_file(self, work_id: str) -> Path | None:
        target = str(work_id or "").strip()
        if not target or not target.isdigit():
            return None
        for suffix in (".jpg", ".png", ".webp"):
            candidate = self._covers_dir / f"{target}{suffix}"
            if candidate.is_file():
                return candidate
        return None

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
        stored = source.get("settings") if isinstance(source.get("settings"), dict) else {}
        for key in settings:
            if key in stored and stored[key] is not None:
                settings[key] = stored[key]
        if not isinstance(raw, dict):
            minute = 7 * 60 + secrets.randbelow(300)
            settings["collectDailyTime"] = f"{minute // 60:02d}:{minute % 60:02d}"
            settings["collectDailyTimeSource"] = "auto"
        data = {
            "version": RADAR_DATA_VERSION,
            "originalRecommendationMigration": source.get("originalRecommendationMigration") or {},
            "settings": normalize_settings(settings),
            "keywords": {str(k): v for k, v in (source.get("keywords") or {}).items() if isinstance(v, dict)},
            "works": {str(k): v for k, v in (source.get("works") or {}).items() if isinstance(v, dict)},
            "accounts": {str(k): v for k, v in (source.get("accounts") or {}).items() if isinstance(v, dict)},
            "usage": source.get("usage") if isinstance(source.get("usage"), dict) else {},
            "trendCache": {str(k): v for k, v in (source.get("trendCache") or {}).items() if isinstance(v, dict)},
        }
        # Upgrade legacy per-subscription snapshots once; shared cache is authoritative thereafter.
        legacy = {}
        for keyword in data["keywords"].values():
            text = " ".join(str(keyword.get("text") or "").split())
            trend = keyword.get("trend") if isinstance(keyword.get("trend"), Mapping) else {}
            if text in data["trendCache"] or not trend.get("items"):
                continue
            stamp = parse_iso(trend.get("updatedAt"))
            if stamp and (text not in legacy or stamp > parse_iso(legacy[text]["updatedAt"])):
                legacy[text] = {**trend, "successDay": trend_day(stamp) if trend.get("status") == "success" else "", "lastAttemptAt": ""}
        data["trendCache"].update(legacy)
        for keyword in data["keywords"].values():
            text = " ".join(str(keyword.get("text") or "").split())
            if text in data["trendCache"]:
                keyword["trend"] = dict(data["trendCache"][text])
        # Persist the one-time schedule migration so repeated reads cannot postpone it.
        if isinstance(raw, dict) and "collectDailyTime" not in stored:
            self._reschedule_collection(data, datetime.now(timezone.utc))
            self._write(data)
        if not isinstance(raw, dict) or "collectDailyTimeSource" not in stored:
            self._write(data)
        for keyword in data["keywords"].values():
            keyword["dailyTime"] = data["settings"]["collectDailyTime"]
        return data

    @staticmethod
    def _reschedule_collection(data: dict[str, Any], moment: datetime) -> None:
        clock = data["settings"]["collectDailyTime"]
        for keyword in data["keywords"].values():
            keyword["dailyTime"] = clock
            collection = keyword.setdefault("collection", {})
            collection["nextCheckAt"] = _next_daily_at(clock, moment)

    def _write(self, data: Mapping[str, Any]) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(str(account_id))
        if not isinstance(bucket, dict):
            bucket = {}
            data["accounts"][str(account_id)] = bucket
        for key, fallback in (("actions", {}), ("dismissed", {}), ("recommendation", {}), ("recommendationJob", {})):
            if not isinstance(bucket.get(key), dict):
                bucket[key] = fallback
        return bucket

    @staticmethod
    def _empty_collection() -> dict[str, Any]:
        return {
            "status": "idle",
            "lastAttemptAt": "",
            "lastSuccessAt": "",
            "lastError": "",
            "lastErrorCode": "",
            "nextCheckAt": "",
            "window": "",
            "pages": 0,
            "requests": 0,
            "imported": 0,
            "added": 0,
            "lowFansAdded": 0,
            "gapNote": "",
            "truncated": False,
        }

    # ---- 设置 ---------------------------------------------------------

    @_locked
    def get_settings(self) -> dict[str, Any]:
        return dict(self._read()["settings"])

    @_locked
    def save_settings(self, fields: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        data = self._read()
        if "collectDailyTime" in fields and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(fields["collectDailyTime"])):
            raise ValueError("每天采集时间请使用 HH:mm 格式（00:00–23:59）。")
        previous_time = data["settings"]["collectDailyTime"]
        merged = {**data["settings"]}
        for key in ("collectEnabled", "collectDailyTime", "aiEnabled", "aiDailyTime"):
            if key in fields and fields.get(key) is not None:
                merged[key] = fields.get(key)
        if "collectDailyTime" in fields:
            merged["collectDailyTimeSource"] = "manual"
        data["settings"] = normalize_settings(merged)
        if data["settings"]["collectDailyTime"] != previous_time:
            self._reschedule_collection(data, now or datetime.now(timezone.utc))
        self._write(data)
        return dict(data["settings"])

    # ---- 关键词 -------------------------------------------------------

    @_locked
    def add_keyword(
        self,
        account_id: str,
        text: str,
        *,
        kind: str = "normal",
        group: str = "",
        daily_time: str = RADAR_DEFAULT_DAILY_TIME,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """新增一个关键词订阅；同一账号内重复文本直接返回已有记录。"""
        value = " ".join(str(text or "").split())[:40]
        if not value:
            raise ValueError("请填写关键词。")
        data = self._read()
        existing = next(
            (
                keyword
                for keyword in data["keywords"].values()
                if str(keyword.get("accountId")) == str(account_id) and str(keyword.get("text")) == value
            ),
            None,
        )
        if existing is not None:
            return dict(existing)
        owned = [k for k in data["keywords"].values() if str(k.get("accountId")) == str(account_id)]
        if len(owned) >= RADAR_KEYWORD_LIMIT:
            raise ValueError(f"每个账号最多订阅 {RADAR_KEYWORD_LIMIT} 个关键词。")
        stamp = now_iso()
        keyword = {
            "id": uuid.uuid4().hex,
            "accountId": str(account_id),
            "text": value,
            "kind": kind if kind in RADAR_KEYWORD_KINDS else "normal",
            "group": " ".join(str(group or "").split())[:20] or RADAR_UNGROUPED,
            "enabled": True,
            "dailyTime": data["settings"]["collectDailyTime"],
            "createdAt": stamp,
            "updatedAt": stamp,
            "historyImportedAt": "",
            "collection": self._empty_collection(),
            "trend": {"items": [], "updatedAt": "", "status": "idle", "error": ""},
            "suggestions": [],
        }
        # 新订阅的关键词立刻排进下一轮调度：nextCheckAt 留空表示「还没跑过」。
        data["keywords"][keyword["id"]] = keyword
        self._write(data)
        return dict(keyword)

    @_locked
    def get_keyword(self, keyword_id: str) -> dict[str, Any]:
        keyword = self._read()["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        return dict(keyword)

    @_locked
    def update_keyword(self, keyword_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        if "kind" in fields and fields.get("kind") is not None:
            value = str(fields.get("kind"))
            keyword["kind"] = value if value in RADAR_KEYWORD_KINDS else "normal"
        if "group" in fields and fields.get("group") is not None:
            keyword["group"] = " ".join(str(fields.get("group")).split())[:20] or RADAR_UNGROUPED
        if "enabled" in fields and fields.get("enabled") is not None:
            enabled = bool(fields.get("enabled"))
            keyword["enabled"] = enabled
            if enabled:
                collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else self._empty_collection()
                # 恢复订阅后立刻重新排队，不用等下一个自然时刻。
                collection["nextCheckAt"] = ""
                if str(collection.get("status")) in RADAR_BLOCKING_STATUSES:
                    collection["status"] = "idle"
                    collection["lastError"] = ""
                    collection["lastErrorCode"] = ""
                keyword["collection"] = collection
        # Legacy per-keyword time is accepted for compatibility; the global time wins.
        keyword["dailyTime"] = data["settings"]["collectDailyTime"]
        keyword["updatedAt"] = now_iso()
        self._write(data)
        return dict(keyword)

    @_locked
    def remove_keyword(self, keyword_id: str) -> dict[str, Any]:
        """取消订阅：删掉关键词和它的来源关联，其他账号仍引用同一作品时保留作品本身。"""
        data = self._read()
        target = str(keyword_id)
        keyword = data["keywords"].pop(target, None)
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        for work_id, work in list(data["works"].items()):
            sources = work.get("sources") if isinstance(work.get("sources"), dict) else {}
            if target in sources:
                sources.pop(target, None)
                work["sources"] = sources
            if not sources:
                data["works"].pop(work_id, None)
        self._write(data)
        return dict(keyword)

    @_locked
    def account_keyword_ids(self, account_id: str) -> list[str]:
        return [
            keyword_id
            for keyword_id, keyword in self._read()["keywords"].items()
            if str(keyword.get("accountId")) == str(account_id)
        ]

    @_locked
    def due_keywords(self, *, now: datetime | None = None) -> list[str]:
        """到点的关键词：每天在设置的时刻跑一次，失败按最短间隔退避。"""
        data = self._read()
        if not data["settings"].get("collectEnabled", True):
            return []
        return self._due_keyword_ids(data, now or datetime.now(timezone.utc))

    @_locked
    def mark_collect_started(self, keyword_id: str) -> None:
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            return
        collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else self._empty_collection()
        collection["status"] = "running"
        collection["lastError"] = ""
        keyword["collection"] = collection
        self._write(data)

    @_locked
    def record_collection(
        self,
        keyword_id: str,
        *,
        status: str,
        error: str = "",
        error_code: str = "",
        window: str = "",
        pages: int = 0,
        requests: int = 0,
        imported: int = 0,
        added: int = 0,
        low_fans_added: int = 0,
        gap_note: str = "",
        truncated: bool = False,
        summaries: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        moment = now or datetime.now(timezone.utc)
        stamp = moment.isoformat()
        collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else self._empty_collection()
        resolved = status if status in RADAR_STATUSES else "failed"
        collection["status"] = resolved
        collection["lastAttemptAt"] = stamp
        collection["lastError"] = sanitize_message(str(error or ""))[:300]
        collection["lastErrorCode"] = public_code(str(error_code or ""))[:60]
        collection["window"] = window or collection.get("window") or ""
        collection["pages"] = int(pages or 0)
        collection["requests"] = int(collection.get("requests") or 0) + int(requests or 0)
        collection["imported"] = int(imported or 0)
        collection["added"] = int(added or 0)
        collection["lowFansAdded"] = int(low_fans_added or 0)
        collection["gapNote"] = str(gap_note or "")[:200]
        collection["truncated"] = bool(truncated)
        collection["sources"] = dict(summaries or {})
        if resolved in ("success", "partial"):
            collection["lastSuccessAt"] = stamp
            collection["nextCheckAt"] = _next_daily_at(data["settings"]["collectDailyTime"], moment)
            if imported:
                keyword["historyImportedAt"] = stamp
        elif resolved in RADAR_BLOCKING_STATUSES:
            collection["nextCheckAt"] = ""
        else:
            # 失败：不排下一轮日常计划，交由 due_keywords 的最短重试间隔控制。
            collection["nextCheckAt"] = ""
        keyword["collection"] = collection
        keyword["updatedAt"] = stamp
        self._write(data)
        return dict(keyword)

    @_locked
    def schedule_next_check(self, keyword_id: str, *, now: datetime | None = None) -> None:
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            return
        collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else self._empty_collection()
        collection["nextCheckAt"] = _next_daily_at(data["settings"]["collectDailyTime"], now or datetime.now(timezone.utc))
        keyword["collection"] = collection
        self._write(data)

    @_locked
    def reset_running(self) -> list[str]:
        """服务重启后把中断的状态复位，避免界面一直显示「采集中」。"""
        data = self._read()
        reset: list[str] = []
        changed = False
        for keyword_id, keyword in data["keywords"].items():
            collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else {}
            if str(collection.get("status")) in RADAR_ACTIVE_STATUSES:
                collection["status"] = "idle"
                collection["lastError"] = "服务重启，上一轮采集已中断。"
                collection["lastErrorCode"] = ""
                collection["nextCheckAt"] = ""
                keyword["collection"] = collection
                reset.append(keyword_id)
                changed = True
        for bucket in data["accounts"].values():
            job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else None
            if job is not None and str(job.get("status")) == "running":
                job["status"] = "failed"
                job["error"] = "服务重启，本次生成已中断。"
                job["errorCode"] = "status_pending"
                changed = True
        if changed:
            self._write(data)
        return reset

    @_locked
    def release_login_blocks(self) -> dict[str, int]:
        """会话恢复后清理登录类阻断：关键词采集、AI 建议任务、热度榜重试标记。

        登录前写入的 ``auth_required`` 会永久阻断自动采集：会话有效后改回 ``idle`` 并清空错误，交回原有间隔锚点。
        ``insufficient_balance`` 不属于登录问题，保持阻断。
        """
        data = self._read()
        released = 0
        jobs = 0
        trends = 0
        changed = False
        for keyword in data["keywords"].values():
            collection = keyword.get("collection") if isinstance(keyword.get("collection"), dict) else {}
            if str(collection.get("status")) == "auth_required" and self._is_login_error(collection):
                collection["status"] = "idle"
                collection["lastError"] = ""
                collection["lastErrorCode"] = ""
                collection["nextCheckAt"] = ""
                keyword["collection"] = collection
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
        for trend in data["trendCache"].values():
            if not isinstance(trend, dict):
                continue
            if trend.get("items"):
                continue
            if str(trend.get("status")) == "failed" and str(trend.get("error") or "") == "请先登录后再使用该功能。":
                trend["status"] = "idle"
                trend["error"] = ""
                trend["lastAttemptAt"] = ""
                trends += 1
                changed = True
        if changed:
            self._write(data)
        return {"released": released, "jobs": jobs, "trends": trends}

    @staticmethod
    def _is_login_error(record: Mapping[str, Any]) -> bool:
        """判断记录是否属于登录/凭证类问题：新记录看精确码，旧记录回退到文案匹配。"""
        code = str(record.get("lastErrorCode") or record.get("errorCode") or "")
        if code == NEEDS_RELOGIN or code in RELOGIN_CODES:
            return True
        if code:
            return False
        message = str(record.get("lastError") or record.get("error") or "")
        return message == "请先登录后再使用该功能。"

    @_locked
    def schedule_snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        """一次读取给出本轮调度所需的全部信息。

        调度循环每 60 秒跑一次，把「到点关键词」和「今天还没生成建议的账号」合并成
        单次读盘，避免每个判断都占用一次线程池调度。
        """
        data = self._read()
        moment = now or datetime.now(timezone.utc)
        settings = data["settings"]
        due: list[str] = []
        if settings.get("collectEnabled", True):
            due = self._due_keyword_ids(data, moment)
        accounts: list[str] = []
        if ai_due_at(settings, now=moment):
            # 账号列表以「有启用关键词」为准：账号层数据是懒创建的，
            # 刚订阅还没产生任何账号状态时也必须排进 AI 计划。
            owners: dict[str, int] = {}
            for keyword in data["keywords"].values():
                if not keyword.get("enabled", True):
                    continue
                owner = str(keyword.get("accountId") or "")
                if owner:
                    owners[owner] = owners.get(owner, 0) + 1
            for account_id in owners:
                bucket = data["accounts"].get(account_id) if isinstance(data["accounts"].get(account_id), Mapping) else {}
                job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), Mapping) else {}
                if job.get("status") == "failed" or str(job.get("lastRunDay") or "") == local_day(moment):
                    continue
                accounts.append(str(account_id))
        return {"dueKeywords": due, "aiAccounts": accounts}

    def _due_keyword_ids(self, data: Mapping[str, Any], moment: datetime) -> list[str]:
        local = moment.astimezone()
        due: list[str] = []
        for keyword_id, keyword in (data.get("keywords") or {}).items():
            if not keyword.get("enabled", True):
                continue
            collection = keyword.get("collection") if isinstance(keyword.get("collection"), Mapping) else {}
            status = str(collection.get("status") or "idle")
            if status in RADAR_ACTIVE_STATUSES or status in RADAR_BLOCKING_STATUSES or status in {"failed", "partial"}:
                continue
            last_attempt = parse_iso(collection.get("lastAttemptAt"))
            if status in ("failed", "partial") and last_attempt is not None:
                if (moment - last_attempt).total_seconds() < RADAR_MIN_RETRY_SECONDS:
                    continue
            next_check = parse_iso(collection.get("nextCheckAt"))
            if next_check is not None:
                if next_check > moment:
                    continue
            else:
                hour, minute = clock_parts(data["settings"]["collectDailyTime"])
                if (local.hour, local.minute) < (hour, minute):
                    continue
                last_success = parse_iso(collection.get("lastSuccessAt"))
                if last_success is not None and last_success.astimezone().date() == local.date():
                    continue
            due.append(keyword_id)
        return due

    # ---- 作品 ---------------------------------------------------------

    @_locked
    def upsert_works(
        self,
        keyword_id: str,
        works: Iterable[Mapping[str, Any]],
        *,
        source: str,
        collected_at: str,
        baseline: bool = False,
        skip_out_of_window: str = "",
        task_id: str = "",
        batch_id: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """写入一轮采集结果：按作品 ID 去重，只有指标变化才追加快照。

        越界作品（发布时间不在本轮窗口内）不计入新增，只在返回里报数量，
        避免把接口偶尔返回的旧作品混进「最近一天」。
        """
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        account_id = str(keyword.get("accountId") or "")
        keyword_text = str(keyword.get("text") or "")
        source_kind = source if source in RADAR_SOURCES else "search"
        added = 0
        updated = 0
        snapshots = 0
        low_fans_added = 0
        skipped = 0
        invalid_tag = 0
        linked = 0
        received = 0
        for work in works:
            received += 1
            work_id = str(work.get("id") or "").strip()
            if not work_id:
                continue
            published_at = str(work.get("publishedAt") or "")
            window = "week" if source_kind == "lowfans" else skip_out_of_window
            if window and not within_window(published_at, window, now=now):
                skipped += 1
                continue
            if source_kind == "lowfans" and not work.get("lowFans"):
                invalid_tag += 1
                continue
            metrics = {field: (work.get("metrics") or {}).get(field) for field in RADAR_METRIC_FIELDS}
            existing = data["works"].get(work_id)
            was_existing = isinstance(existing, dict)
            if not isinstance(existing, dict):
                record = {
                    "id": work_id,
                    "title": str(work.get("title") or ""),
                    "kind": work.get("kind") if work.get("kind") in RADAR_KINDS else "video",
                    "publishedAt": published_at,
                    "authorName": str(work.get("authorName") or "")[:80],
                    "authorId": str(work.get("authorId") or ""),
                    "authorFollowers": work.get("authorFollowers"),
                    "authorAvatarUrl": str(work.get("authorAvatarUrl") or ""),
                    "coverUrl": str(work.get("coverUrl") or ""),
                    "shareUrl": str(work.get("shareUrl") or ""),
                    "durationSeconds": work.get("durationSeconds"),
                    "imageCount": int(work.get("imageCount") or 0),
                    "metrics": metrics,
                    "lowFans": bool(work.get("lowFans")),
                    "snapshots": [{"at": collected_at, "metrics": dict(metrics)}],
                    "sources": {},
                    "firstSeenAt": collected_at,
                    "discoveredAt": collected_at,
                    "baseline": bool(baseline),
                    "statsUpdatedAt": collected_at,
                    "updatedAt": collected_at,
                }
                data["works"][work_id] = record
                existing = record
                added += 1
                if record["lowFans"] and source_kind == "lowfans":
                    low_fans_added += 1
            else:
                metrics = {key: value if value is not None else (existing.get("metrics") or {}).get(key) for key, value in metrics.items()}
                changed = _metrics_changed(existing.get("metrics"), metrics)
                for field in (
                    "title",
                    "kind",
                    "publishedAt",
                    "authorName",
                    "authorId",
                    "authorFollowers",
                    "authorAvatarUrl",
                    "coverUrl",
                    "shareUrl",
                    "durationSeconds",
                    "imageCount",
                ):
                    value = work.get(field)
                    if value not in (None, ""):
                        existing[field] = value
                if changed:
                    existing["metrics"] = metrics
                    history = existing.get("snapshots") if isinstance(existing.get("snapshots"), list) else []
                    history.append({"at": collected_at, "metrics": dict(metrics)})
                    existing["snapshots"] = history[-RADAR_SNAPSHOT_LIMIT:]
                    existing["statsUpdatedAt"] = collected_at
                    snapshots += 1
                if work.get("lowFans"):
                    existing["lowFans"] = True
                existing["updatedAt"] = collected_at
                updated += 1
            sources = existing.get("sources") if isinstance(existing.get("sources"), dict) else {}
            previous = sources.get(str(keyword_id)) if isinstance(sources.get(str(keyword_id)), Mapping) else {}
            channels = source_channels(previous) if previous else {}
            old_channel = channels.get(source_kind) or {}
            if was_existing and not previous:
                linked += 1
            channel = {
                "keywordId": str(keyword_id), "accountId": account_id, "keyword": keyword_text,
                "source": source_kind, "lowFans": bool(work.get("lowFans")),
                "imported": bool(old_channel.get("imported")) or bool(baseline),
                "firstSeenAt": str(old_channel.get("firstSeenAt") or collected_at),
                "lastSeenAt": collected_at, "taskId": task_id, "batchId": batch_id,
                "validated": True,
            }
            channels[source_kind] = channel
            # Keep a legacy projection for old readers, but never overwrite the other channel.
            preferred = channels.get("search") or channels[source_kind]
            sources[str(keyword_id)] = {**preferred, "channels": channels}
            existing["sources"] = sources
        self._prune_works(data)
        self._write(data)
        return {
            "added": added,
            "updated": updated,
            "snapshots": snapshots,
            "lowFansAdded": low_fans_added,
            "skipped": skipped,
            "invalidTag": invalid_tag,
            "linked": linked,
            "received": received,
        }

    @staticmethod
    def _prune_works(data: dict[str, Any]) -> None:
        """超过总量上限时按发布时间裁掉最旧的；已收藏或被选题引用的记录不裁。"""
        works = data["works"]
        if len(works) <= RADAR_WORK_LIMIT:
            return
        protected: set[str] = set()
        for bucket in data["accounts"].values():
            actions = bucket.get("actions") if isinstance(bucket.get("actions"), Mapping) else {}
            for work_id, action in actions.items():
                if isinstance(action, Mapping) and (action.get("saved") or action.get("topicId")):
                    protected.add(str(work_id))
        candidates = [
            (work_id, work)
            for work_id, work in works.items()
            if work_id not in protected
        ]
        candidates = [item for item in candidates if not item[1].get("quarantinedSources")]
        candidates.sort(key=lambda item: (str(item[1].get("publishedAt") or ""), str(item[0])))
        overflow = len(works) - RADAR_WORK_LIMIT
        for work_id, _ in candidates[:overflow]:
            works.pop(work_id, None)

    @_locked
    def get_work(self, work_id: str) -> dict[str, Any]:
        work = self._read()["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        return dict(work)

    @_locked
    def save_author_identity(self, work_id: str, sec_uid: str) -> None:
        """Persist a verified video-detail identity without touching collection metadata."""
        if not re.fullmatch(r"MS4w[\w-]+", sec_uid, flags=re.ASCII):
            raise ValueError("博主身份无效。")
        data = self._read()
        work = data["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        work["authorId"] = sec_uid
        self._write(data)

    @_locked
    def list_works(
        self,
        account_id: str,
        *,
        tab: str = "latest",
        day: str = RADAR_DEFAULT_DAY,
        work_filter: str = "all",
        keyword_id: str = "",
        keyword_ids: Iterable[str] | None = None,
        min_likes: int = 0,
        max_likes: int | None = None,
        page: int = 1,
        page_size: int = RADAR_PAGE_SIZE,
        offset: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """列出当前账号订阅范围内的作品；分段、日期、状态筛选在这里统一组合。"""
        data = self._read()
        owned_keywords = {
            keyword_key: keyword
            for keyword_key, keyword in data["keywords"].items()
            if str(keyword.get("accountId")) == str(account_id)
        }
        bucket = self._bucket(data, account_id)
        actions = bucket.get("actions") if isinstance(bucket.get("actions"), Mapping) else {}
        moment = now or datetime.now(timezone.utc)
        today = moment.astimezone(ZoneInfo("Asia/Shanghai")).date()
        resolved_tab = tab if tab in RADAR_TABS else "latest"
        resolved_filter = work_filter if work_filter in RADAR_FILTERS else "all"
        selected_keywords = {str(value) for value in (keyword_ids or []) if str(value)}
        if keyword_id:
            selected_keywords.add(str(keyword_id))
        items: list[dict[str, Any]] = []
        for work in data["works"].values():
            sources = work.get("sources") if isinstance(work.get("sources"), Mapping) else {}
            owned = {key: value for key, value in sources.items() if key in owned_keywords}
            action = actions.get(str(work.get("id"))) or {}
            archived_saved = resolved_filter == "saved" and action.get("saved") and any(entry.get("keywordId") in owned_keywords for entry in work.get("quarantinedSources", {}).values())
            if not owned and not archived_saved:
                continue
            selected_sources = {key: value for key, value in owned.items() if not selected_keywords or key in selected_keywords}
            archived_sources = [entry.get("source") for entry in work.get("quarantinedSources", {}).values()
                                if archived_saved and entry.get("keywordId") in owned_keywords
                                and (not selected_keywords or entry.get("keywordId") in selected_keywords)]
            candidates = [*selected_sources.values(), *archived_sources]
            if not candidates:
                continue
            if resolved_tab == "lowfans":
                if not any(isinstance(value, Mapping) and has_source(value, "lowfans") for value in candidates):
                    continue
            elif resolved_tab == "latest":
                if not any(isinstance(value, Mapping) and has_source(value, "search") for value in candidates):
                    continue
            elif not any(isinstance(value, Mapping) and any(has_source(value, kind) for kind in RADAR_SOURCES) for value in candidates):
                continue
            action = actions.get(str(work.get("id"))) if isinstance(actions.get(str(work.get("id"))), Mapping) else {}
            saved = bool(action.get("saved"))
            if resolved_filter == "saved" and not saved:
                continue
            if resolved_filter == "unread" and action.get("read"):
                continue
            if not in_date_range(work.get("publishedAt"), str(day), today):
                continue
            if min_likes > 0 or max_likes is not None:
                metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
                likes = _pick_int(metrics.get("likes"))
                if likes is None or likes < min_likes or (max_likes is not None and likes > max_likes):
                    continue
            items.append(self.work_view(data, work, account_id=account_id, saved=saved, action=action, now=moment))
        items.sort(key=lambda item: (item.get("publishedAt") or "", item.get("id") or ""), reverse=True)
        total = len(items)
        size = max(1, min(int(page_size or RADAR_PAGE_SIZE), RADAR_PAGE_SIZE_MAX))
        page_count = max(1, (total + size - 1) // size)
        current = max(1, min(int(page or 1), page_count))
        start = max(0, int(offset)) if offset is not None else (current - 1) * size
        selected = items[start : start + size]
        result = {
            "items": selected,
            "total": total,
            "page": current,
            "pageCount": page_count,
            "pageSize": size,
            "tab": resolved_tab,
            "filter": resolved_filter,
            "day": str(day),
        }
        if offset is not None:
            result.update(offset=start, nextOffset=start + len(selected), hasMore=start + len(selected) < total)
        return result

    def work_view(
        self,
        data: Mapping[str, Any],
        work: Mapping[str, Any],
        *,
        account_id: str = "",
        saved: bool = False,
        action: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = now or datetime.now(timezone.utc)
        keywords = data.get("keywords") or {}
        sources = work.get("sources") if isinstance(work.get("sources"), Mapping) else {}
        metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
        snapshots = work.get("snapshots") if isinstance(work.get("snapshots"), list) else []
        own = action if isinstance(action, Mapping) else {}
        labels: list[str] = []
        tabs: list[str] = []
        for value in sources.values():
            if not isinstance(value, Mapping):
                continue
            keyword = keywords.get(str(value.get("keywordId"))) or {}
            if account_id and keyword.get("accountId") != account_id:
                continue
            name = str(keyword.get("text") or value.get("keyword") or "").strip()
            if name and name not in labels:
                labels.append(name)
            for source_kind in source_channels(value):
                if source_kind not in tabs:
                    tabs.append(source_kind)
        imported = any(isinstance(value, Mapping) and value.get("imported") for value in sources.values())
        return {
            "id": str(work.get("id") or ""),
            "title": str(work.get("title") or ""),
            "kind": str(work.get("kind") or "video"),
            "coverUrl": str(work.get("coverUrl") or ""),
            "coverSrc": f"/api/radar/covers/{work.get('id')}" if work.get("coverUrl") else "",
            "shareUrl": str(work.get("shareUrl") or ""),
            "publishedAt": str(work.get("publishedAt") or ""),
            "publishedText": published_text(work.get("publishedAt")),
            "discoveredAt": str(work.get("discoveredAt") or ""),
            "durationSeconds": work.get("durationSeconds"),
            "imageCount": int(work.get("imageCount") or 0),
            "authorId": str(work.get("authorId") or ""),
            "authorName": str(work.get("authorName") or ""),
            "authorFollowers": work.get("authorFollowers"),
            "authorAvatarUrl": str(work.get("authorAvatarUrl") or ""),
            "metrics": {field: metrics.get(field) for field in RADAR_METRIC_FIELDS},
            "hasMetrics": any(metrics.get(field) is not None for field in RADAR_METRIC_FIELDS),
            "keywords": labels[:4],
            "sources": tabs,
            "lowFans": work_lowfans(work, {key for key, keyword in (data.get("keywords") or {}).items() if not account_id or keyword.get("accountId") == account_id}),
            "baseline": bool(work.get("baseline")),
            "imported": bool(imported),
            "isNew": is_new_work(work, moment),
            "saved": bool(saved or own.get("saved")),
            "read": bool(own.get("read")),
            "topicId": str(own.get("topicId") or ""),
            "snapshotCount": len(snapshots),
            "statsUpdatedAt": str(work.get("statsUpdatedAt") or ""),
            "accountId": str(account_id or ""),
        }

    @_locked
    def work_detail(self, work_id: str, account_id: str = "") -> dict[str, Any]:
        data = self._read()
        work = data["works"].get(str(work_id))
        if not isinstance(work, dict):
            raise ValueError("作品不存在。")
        bucket = self._bucket(data, account_id) if account_id else {"actions": {}}
        action = bucket.get("actions") if isinstance(bucket.get("actions"), Mapping) else {}
        view = self.work_view(
            data,
            work,
            account_id=account_id,
            saved=bool((action.get(str(work_id)) or {}).get("saved")) if isinstance(action.get(str(work_id)), Mapping) else False,
            action=action.get(str(work_id)) if isinstance(action.get(str(work_id)), Mapping) else {},
        )
        snapshots = work.get("snapshots") if isinstance(work.get("snapshots"), list) else []
        view["snapshots"] = [
            {
                "at": str(item.get("at") or ""),
                "metrics": {field: (item.get("metrics") or {}).get(field) for field in RADAR_METRIC_FIELDS},
            }
            for item in snapshots[-RADAR_SNAPSHOT_LIMIT:]
            if isinstance(item, Mapping)
        ]
        return view

    @_locked
    def set_saved(self, account_id: str, work_id: str, saved: bool) -> bool:
        data = self._read()
        if str(work_id) not in data["works"]:
            raise ValueError("作品不存在。")
        bucket = self._bucket(data, account_id)
        action = bucket["actions"].get(str(work_id))
        if not isinstance(action, dict):
            action = {}
        action["saved"] = bool(saved)
        action["updatedAt"] = now_iso()
        bucket["actions"][str(work_id)] = action
        self._write(data)
        return bool(saved)

    @_locked
    def mark_read(self, account_id: str, work_ids: Iterable[str]) -> int:
        data = self._read()
        bucket = self._bucket(data, account_id)
        stamp = now_iso()
        changed = 0
        for work_id in work_ids:
            target = str(work_id or "").strip()
            if not target or target not in data["works"]:
                continue
            action = bucket["actions"].get(target)
            if not isinstance(action, dict):
                action = {}
            if not action.get("read"):
                action["read"] = True
                changed += 1
            action["updatedAt"] = stamp
            bucket["actions"][target] = action
        if changed:
            self._write(data)
        return changed

    @_locked
    def attach_topic(self, account_id: str, work_id: str, topic_id: str) -> dict[str, Any]:
        data = self._read()
        if str(work_id) not in data["works"]:
            raise ValueError("作品不存在。")
        bucket = self._bucket(data, account_id)
        action = bucket["actions"].get(str(work_id))
        if not isinstance(action, dict):
            action = {}
        action["topicId"] = str(topic_id or "")
        action["read"] = True
        action["updatedAt"] = now_iso()
        bucket["actions"][str(work_id)] = action
        self._write(data)
        return dict(action)

    # ---- 趋势 ---------------------------------------------------------

    @_locked
    def shared_trend(self, text: str) -> dict[str, Any]:
        return dict(self._read()["trendCache"].get(" ".join(text.split())) or {})

    @_locked
    def mark_trend_attempt(self, text: str, *, now: datetime, business_context: Mapping[str, Any] | None = None) -> None:
        data = self._read()
        key = " ".join(text.split())
        existing = dict(data["trendCache"].get(key) or {})
        existing.update(lastAttemptAt=now.isoformat(), status="running", error="")
        existing["businessContext"] = dict(business_context or {})
        data["trendCache"][key] = existing
        self._write(data)

    @_locked
    def save_shared_trend(self, text: str, items: Iterable[Mapping[str, Any]], *,
                          error: str = "", now: datetime | None = None) -> dict[str, Any]:
        data = self._read()
        key = " ".join(text.split())
        moment = now or datetime.now(timezone.utc)
        existing = dict(data["trendCache"].get(key) or {})
        rows = []
        for item in items:
            word = str((item or {}).get("keyword") or "").strip()
            if word:
                labels = item.get("trends") if isinstance(item.get("trends"), list) else []
                rows.append({"keyword": word[:60], "score": _pick_int(item.get("score")),
                             "trends": [str(label)[:30] for label in labels[:RADAR_TREND_ITEM_LIMIT]]})
        if rows and not error:
            existing.update(items=rows[:RADAR_TREND_LIMIT], updatedAt=moment.isoformat(),
                            successDay=trend_day(moment), status="success", error="")
        else:
            existing.setdefault("items", [])
            existing.setdefault("updatedAt", "")
            existing.setdefault("successDay", "")
            existing.update(status="failed", error=sanitize_message(str(error or "热度榜返回空数据，稍后重试。"))[:200])
        existing["lastAttemptAt"] = moment.isoformat()
        data["trendCache"][key] = existing
        self._write(data)
        return dict(existing)

    @_locked
    def save_trend(self, keyword_id: str, items: Iterable[Mapping[str, Any]], *, error: str = "") -> dict[str, Any]:
        keyword = self.get_keyword(keyword_id)
        return self.save_shared_trend(keyword["text"], items, error=error)

    @_locked
    def trend_retry_keywords(self, *, now: datetime | None = None) -> list[str]:
        # 失败/中断后不再自动新建计费任务；用户可通过立即同步显式重试。
        return []

    @_locked
    def save_suggestions(self, keyword_id: str, words: Iterable[str]) -> list[str]:
        data = self._read()
        keyword = data["keywords"].get(str(keyword_id))
        if not isinstance(keyword, dict):
            raise ValueError("关键词不存在。")
        cleaned: list[str] = []
        for word in words:
            text = str(word or "").strip()
            if text and text not in cleaned:
                cleaned.append(text[:60])
        keyword["suggestions"] = cleaned[:RADAR_SUGGEST_LIMIT]
        keyword["suggestionsUpdatedAt"] = now_iso()
        self._write(data)
        return list(keyword["suggestions"])

    # ---- 概览 ---------------------------------------------------------

    @_locked
    def overview(self, account_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        data = self._read()
        moment = now or datetime.now(timezone.utc)
        keywords = [
            keyword for keyword in data["keywords"].values() if str(keyword.get("accountId")) == str(account_id)
        ]
        bucket = self._bucket(data, account_id)
        owned_ids = {str(keyword.get("id")) for keyword in keywords}
        owned_works = [
            work
            for work in data["works"].values()
            if any(key in owned_ids for key in (work.get("sources") or {}))
        ]
        today_new = [work for work in owned_works if is_new_work(work, moment)]
        today_collected = [work for work in owned_works if local_day(parse_iso(work.get("updatedAt"))) == local_day(moment)]
        low_fans = [work for work in owned_works if work_lowfans(work, owned_ids)]
        enabled = [keyword for keyword in keywords if keyword.get("enabled", True)]
        statuses = [str((keyword.get("collection") or {}).get("status") or "idle") for keyword in enabled]
        if not data["settings"].get("collectEnabled", True):
            health = {"key": "paused", "label": "定时采集已关闭", "tone": "muted"}
        elif not enabled:
            health = {"key": "empty", "label": "还没有订阅关键词", "tone": "muted"}
        elif any(status in RADAR_ACTIVE_STATUSES for status in statuses):
            health = {"key": "syncing", "label": "正在同步", "tone": "active"}
        elif any(status == "auth_required" for status in statuses):
            health = {"key": "auth_required", "label": "需要检查数据接口配置", "tone": "warning"}
        elif any(status == "insufficient_balance" for status in statuses):
            health = {"key": "insufficient_balance", "label": "额度不足，已暂停", "tone": "warning"}
        elif any(status in ("failed", "partial") for status in statuses):
            # 部分采集未完成属于「静默降级」：下一次采集会自愈，不该让整个雷达页常驻红色警报。
            # 需要用户动手的情况（登录失效、额度不足）仍在上面的分支里保持 warning。
            health = {"key": "partial", "label": "部分采集未完成", "tone": "muted"}
        else:
            health = {"key": "ok", "label": "内容采集正常", "tone": "ok"}
        last_success = max(
            (str((keyword.get("collection") or {}).get("lastSuccessAt") or "") for keyword in enabled),
            default="",
        )
        groups: dict[str, int] = {}
        for keyword in keywords:
            name = str(keyword.get("group") or RADAR_UNGROUPED)
            groups[name] = groups.get(name, 0) + 1
        return {
            "accountId": str(account_id),
            "keywordCount": len(keywords),
            "enabledKeywordCount": len(enabled),
            "groupCount": len([name for name in groups if name and name != RADAR_UNGROUPED]),
            "todayNewCount": len(today_new),
            "todayNewBySource": {kind: len([w for w in today_new if any(has_source(v, kind) for k, v in w.get("sources", {}).items() if k in owned_ids)]) for kind in RADAR_SOURCES},
            "todayCollected": len(today_collected),
            "lowFansCount": len(low_fans),
            "savedCount": len([action for action in (bucket.get("actions") or {}).values() if isinstance(action, Mapping) and action.get("saved")]),
            "health": health,
            "lastSuccessAt": last_success,
            "lastSuccessText": published_text(last_success) if last_success else "",
            "settings": dict(data["settings"]),
            "usage": {**usage_view(data), "chargedTotalPoints": None, "chargedTodayPoints": None,
                      "syncStatus": "unavailable", "syncedAt": "", "scope": "account"},
            "groups": [{"name": name, "count": count} for name, count in sorted(groups.items(), key=lambda item: item[0])],
            "keywords": [self.keyword_view(data, keyword) for keyword in sorted(keywords, key=lambda item: str(item.get("createdAt") or ""))],
            "trends": self.trend_view(data, account_id),
            "recommendation": self.recommendation_view(data, account_id),
        }

    def keyword_view(self, data: Mapping[str, Any], keyword: Mapping[str, Any]) -> dict[str, Any]:
        keyword_id = str(keyword.get("id") or "")
        works = [
            work
            for work in (data.get("works") or {}).values()
            if keyword_id in (work.get("sources") or {})
        ]
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        collection = keyword.get("collection") if isinstance(keyword.get("collection"), Mapping) else {}
        trend = keyword.get("trend") if isinstance(keyword.get("trend"), Mapping) else {}
        next_check = str(collection.get("nextCheckAt") or "")
        plan = plan_collection(keyword)
        kind = str(keyword.get("kind") or "normal")
        return {
            "id": keyword_id,
            "text": str(keyword.get("text") or ""),
            "kind": kind if kind in RADAR_KEYWORD_KINDS else "normal",
            "kindLabel": RADAR_KEYWORD_KIND_LABELS.get(kind, "普通"),
            "group": str(keyword.get("group") or RADAR_UNGROUPED),
            "enabled": bool(keyword.get("enabled", True)),
            "dailyTime": data["settings"]["collectDailyTime"],
            "createdAt": str(keyword.get("createdAt") or ""),
            "updatedAt": str(keyword.get("updatedAt") or ""),
            "historyImportedAt": str(keyword.get("historyImportedAt") or ""),
            "workCount": len(works),
            "lowFansCount": len([work for work in works if work_lowfans(work, {keyword_id})]),
            "todayNewCount": len([work for work in works if is_new_work(work, today)]),
            "suggestions": [str(word) for word in (keyword.get("suggestions") or [])][:RADAR_SUGGEST_LIMIT],
            "trend": {
                "items": [dict(item) for item in (trend.get("items") or []) if isinstance(item, Mapping)],
                "updatedAt": str(trend.get("updatedAt") or ""),
                "updatedText": published_text(trend.get("updatedAt")) if trend.get("updatedAt") else "",
                "status": str(trend.get("status") or "idle"),
                "error": sanitize_message(str(trend.get("error") or "")),
            },
            "collection": {
                "status": str(collection.get("status") or "idle"),
                "lastAttemptAt": str(collection.get("lastAttemptAt") or ""),
                "lastSuccessAt": str(collection.get("lastSuccessAt") or ""),
                "lastSuccessText": published_text(collection.get("lastSuccessAt")) if collection.get("lastSuccessAt") else "",
                "lastError": sanitize_message(str(collection.get("lastError") or "")),
                "lastErrorCode": public_code(str(collection.get("lastErrorCode") or "")),
                "nextCheckAt": next_check,
                "nextCheckText": published_text(next_check) if next_check else "",
                "window": str(collection.get("window") or ""),
                "windowLabel": RADAR_WINDOW_LABELS.get(str(collection.get("window") or ""), ""),
                "pages": int(collection.get("pages") or 0),
                "requests": int(collection.get("requests") or 0),
                "imported": int(collection.get("imported") or 0),
                "added": int(collection.get("added") or 0),
                "lowFansAdded": int(collection.get("lowFansAdded") or 0),
                "gapNote": str(collection.get("gapNote") or ""),
                "truncated": bool(collection.get("truncated")),
                "sources": dict(collection.get("sources") or {}),
                "planWindow": plan["window"],
                "planWindowLabel": RADAR_WINDOW_LABELS.get(plan["window"], ""),
                "planPages": plan["pages"],
                "planMode": plan["mode"],
            },
        }

    def trend_view(self, data: Mapping[str, Any], account_id: str) -> list[dict[str, Any]]:
        """账号全部订阅词的飙升榜合并视图：按关键词分开保存，这里汇总用于右下角面板。"""
        rows: list[dict[str, Any]] = []
        for keyword in data.get("keywords", {}).values():
            if str(keyword.get("accountId")) != str(account_id):
                continue
            trend = keyword.get("trend") if isinstance(keyword.get("trend"), Mapping) else {}
            items = trend.get("items") if isinstance(trend.get("items"), list) else []
            if not items:
                continue
            rows.append({
                "keywordId": str(keyword.get("id") or ""),
                "keyword": str(keyword.get("text") or ""),
                "group": str(keyword.get("group") or RADAR_UNGROUPED),
                "updatedAt": str(trend.get("updatedAt") or ""),
                "updatedText": published_text(trend.get("updatedAt")) if trend.get("updatedAt") else "",
                "items": [dict(item) for item in items if isinstance(item, Mapping)][:RADAR_TREND_LIMIT],
            })
        rows.sort(key=lambda row: row.get("updatedAt") or "", reverse=True)
        return rows

    # ---- 账号状态 -----------------------------------------------------

    @_locked
    def record_requests(self, kind: str, count: int = 1) -> dict[str, Any]:
        if count <= 0:
            return usage_view(self._read())
        data = self._read()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        by_day = usage.get("byDay") if isinstance(usage.get("byDay"), dict) else {}
        day = local_day()
        bucket = by_day.get(day) if isinstance(by_day.get(day), dict) else {}
        label = kind if kind in RADAR_REQUEST_KINDS else "search"
        bucket[label] = int(bucket.get(label) or 0) + int(count)
        by_day[day] = bucket
        usage["byDay"] = {key: value for key, value in sorted(by_day.items())[-RADAR_USAGE_KEEP_DAYS:]}
        usage["requests"] = int(usage.get("requests") or 0) + int(count)
        usage["lastRequestAt"] = now_iso()
        data["usage"] = usage
        self._write(data)
        return usage_view(data)

    @_locked
    def usage(self) -> dict[str, Any]:
        return usage_view(self._read())

    @_locked
    def record_charge(self, amount_points: str, requests: int = 0) -> dict[str, Any]:
        """记一次真实的创作服务扣费；界面按「总请求数 + 总费用」汇总展示。"""
        from .monitor import _add_points

        data = self._read()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        by_day = usage.get("chargedByDay") if isinstance(usage.get("chargedByDay"), dict) else {}
        day = local_day()
        by_day[day] = str(_add_points(by_day.get(day), amount_points))
        usage["chargedByDay"] = {key: value for key, value in sorted(by_day.items())[-RADAR_USAGE_KEEP_DAYS:]}
        usage["chargedTotalPoints"] = str(_add_points(usage.get("chargedTotalPoints"), amount_points))
        usage["lastChargedRequests"] = int(requests or 0)
        data["usage"] = usage
        self._write(data)
        return usage_view(data)

    @_locked
    def delete_account(self, account_id: str) -> int:
        """账号删除时清掉它的关键词和账号层状态；被其他账号引用的共享作品保留。"""
        data = self._read()
        removed = 0
        for keyword_id, keyword in list(data["keywords"].items()):
            if str(keyword.get("accountId")) != str(account_id):
                continue
            data["keywords"].pop(keyword_id, None)
            removed += 1
            for work_id, work in list(data["works"].items()):
                sources = work.get("sources") if isinstance(work.get("sources"), dict) else {}
                if keyword_id in sources:
                    sources.pop(keyword_id, None)
                    work["sources"] = sources
                if not sources:
                    data["works"].pop(work_id, None)
        data["accounts"].pop(str(account_id), None)
        self._write(data)
        return removed

    # ---- AI 建议 ------------------------------------------------------

    @_locked
    def recommendation_works(
        self,
        account_id: str,
        *,
        since: Any = "",
        limit: int = 200,
        include_baseline: bool = False,
    ) -> list[dict[str, Any]]:
        """给 AI 的候选作品：当前账号订阅范围内、按发现时间过滤后的最近作品。

        默认排除首次导入的历史基线：那些作品不是最近出现的，当成今天的动态会误导选题。
        """
        data = self._read()
        owned = {
            keyword_id
            for keyword_id, keyword in data["keywords"].items()
            if str(keyword.get("accountId")) == str(account_id)
        }
        cutoff = parse_iso(since) if since else None
        rows: list[dict[str, Any]] = []
        for work in data["works"].values():
            sources = work.get("sources") if isinstance(work.get("sources"), Mapping) else {}
            if not any(key in owned for key in sources):
                continue
            discovered = parse_iso(work.get("discoveredAt"))
            if cutoff is not None and (discovered is None or discovered < cutoff):
                continue
            if work.get("baseline") and not include_baseline:
                continue
            metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
            rows.append({
                "id": str(work.get("id") or ""),
                "title": str(work.get("title") or ""),
                "shareUrl": str(work.get("shareUrl") or ""),
                "coverUrl": str(work.get("coverUrl") or ""),
                "coverSrc": f"/api/radar/covers/{work.get('id')}" if work.get("coverUrl") else "",
                "kind": str(work.get("kind") or "video"),
                "authorName": str(work.get("authorName") or ""),
                "authorId": str(work.get("authorId") or ""),
                "statsUpdatedAt": str(work.get("statsUpdatedAt") or ""),
                "authorFollowers": work.get("authorFollowers"),
                "publishedAt": str(work.get("publishedAt") or ""),
                "publishedText": published_text(work.get("publishedAt")),
                "discoveredAt": str(work.get("discoveredAt") or ""),
                "lowFans": work_lowfans(work, {key for key, keyword in (data.get("keywords") or {}).items() if not account_id or keyword.get("accountId") == account_id}),
                "keywords": [
                    str((data["keywords"].get(key) or {}).get("text") or "")
                    for key in sources
                    if key in owned
                ][:4],
                "metrics": {field: metrics.get(field) for field in RADAR_METRIC_FIELDS},
            })
        rows.sort(key=lambda item: (item.get("publishedAt") or "", item.get("discoveredAt") or ""), reverse=True)
        return rows[: max(1, int(limit))]

    @_locked
    def trend_rows(self, account_id: str) -> list[dict[str, Any]]:
        return self.trend_view(self._read(), account_id)

    @_locked
    def save_recommendation(
        self,
        account_id: str,
        items: Iterable[Mapping[str, Any]],
        *,
        message: str = "",
        scope: str = "",
        analysis: Mapping[str, Any] | None = None,
        schema_version: int | None = None,
    ) -> dict[str, Any]:
        items = _original_items(items, schema_version)
        data = self._read()
        bucket = self._bucket(data, account_id)
        previous_record = bucket.get("recommendation") or {}
        previous = {recommendation_key(item): item for item in previous_record.get("items", [])}
        for key in previous_record.get("dismissed") or []:
            bucket["dismissed"].setdefault(str(key), {"key": str(key)})
        stamp = now_iso()
        stored: list[dict[str, Any]] = []
        for item in items:
            entry = dict(item)
            entry["key"] = str(entry.get("key") or recommendation_key(entry))
            old = previous.get(entry["key"], {})
            if old.get("topicId"):
                entry["topicId"] = old["topicId"]
            stored.append(entry)
        bucket["recommendation"] = {
            "schemaVersion": 2,
            "items": stored[:RADAR_RECOMMENDATION_MAX],
            "generatedAt": stamp,
            "generatedText": published_text(stamp),
            "message": str(message or "")[:200],
            "scope": str(scope or "")[:200],
            "analysis": dict(analysis or {}),
        }
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else {}
        job.pop("taskId", None)
        job.pop("prepared", None)
        job["errorCode"] = ""
        job["status"] = "success"
        job["error"] = ""
        job["lastRunAt"] = stamp
        job["lastRunDay"] = local_day()
        bucket["recommendationJob"] = job
        self._write(data)
        return self.recommendation_view(data, account_id)

    @_locked
    def set_recommendation_job(self, account_id: str, status: str, *, error: str = "", error_code: str = "") -> dict[str, Any]:
        data = self._read()
        bucket = self._bucket(data, account_id)
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), dict) else {}
        resolved = status if status in RADAR_RECOMMENDATION_STATUSES else "failed"
        job["status"] = resolved
        job["error"] = sanitize_message(str(error or ""))[:300]
        job["errorCode"] = public_code(str(error_code or ""))[:60]
        job["updatedAt"] = now_iso()
        if resolved in ("success", "skipped", "failed"):
            job["lastRunAt"] = job["updatedAt"]
            job["lastRunDay"] = local_day()
        bucket["recommendationJob"] = job
        self._write(data)
        return dict(job)

    @_locked
    def get_recommendation(self, account_id: str) -> dict[str, Any]:
        return self.recommendation_view(self._read(), account_id)

    @_locked
    def dismiss_recommendation(self, account_id: str, key: str) -> dict[str, Any]:
        data = self._read()
        bucket = self._bucket(data, account_id)
        recommendation = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), dict) else {}
        items = recommendation.get("items") if isinstance(recommendation.get("items"), list) else []
        item = next((item for item in items if str(item.get("key")) == str(key)), None)
        if item is None:
            raise ValueError("这条建议已经不存在，请更新建议后重试。")
        bucket["dismissed"][str(key)] = {**dict(item), "dismissedAt": now_iso()}
        bucket["recommendation"] = recommendation
        self._write(data)
        return self.recommendation_view(data, account_id)

    @_locked
    def restore_recommendation(self, account_id: str, key: str) -> dict[str, Any]:
        data = self._read()
        bucket = self._bucket(data, account_id)
        bucket["dismissed"].pop(str(key), None)
        record = bucket.get("recommendation") or {}
        record["dismissed"] = [value for value in record.get("dismissed", []) if str(value) != str(key)]
        self._write(data)
        return self.recommendation_view(data, account_id)

    @_locked
    def dismissed_recommendations(self, account_id: str) -> list[dict[str, Any]]:
        bucket = self._bucket(self._read(), account_id)
        return [{"key": key, **value} for key, value in bucket["dismissed"].items() if isinstance(value, Mapping)]

    @_locked
    def attach_recommendation_topic(self, account_id: str, key: str, topic_id: str) -> dict[str, Any]:
        data = self._read()
        bucket = self._bucket(data, account_id)
        recommendation = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), dict) else {}
        items = recommendation.get("items") if isinstance(recommendation.get("items"), list) else []
        for item in items:
            if isinstance(item, dict) and str(item.get("key")) == str(key):
                item["topicId"] = str(topic_id or "")
        bucket["recommendation"] = recommendation
        self._write(data)
        return self.recommendation_view(data, account_id)

    @_locked
    def dismissed_recommendation_keys(self, account_id: str) -> set[str]:
        bucket = self._bucket(self._read(), account_id)
        recommendation = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), Mapping) else {}
        keys = recommendation.get("dismissed") if isinstance(recommendation.get("dismissed"), list) else []
        return {str(key) for key in keys} | set(bucket["dismissed"])

    def recommendation_view(self, data: Mapping[str, Any], account_id: str) -> dict[str, Any]:
        accounts = data.get("accounts") if isinstance(data.get("accounts"), Mapping) else {}
        bucket = accounts.get(str(account_id)) if isinstance(accounts.get(str(account_id)), Mapping) else {}
        recommendation = bucket.get("recommendation") if isinstance(bucket.get("recommendation"), Mapping) else {}
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), Mapping) else {}
        items = recommendation.get("items") if isinstance(recommendation.get("items"), list) else []
        dismissed = set(bucket.get("dismissed") or {}) | set(recommendation.get("dismissed") or [])
        generated_at = str(recommendation.get("generatedAt") or "")
        works = data.get("works") if isinstance(data.get("works"), Mapping) else {}

        def reference_view(raw: Any) -> dict[str, Any] | None:
            """把建议里的作品 ID 换成可点击的来源信息；查不到就丢弃，不编造。"""
            work_id = str(raw.get("id") if isinstance(raw, Mapping) else raw or "").strip()
            work = works.get(work_id) if work_id else None
            if not isinstance(work, Mapping):
                return None
            return {
                "id": work_id,
                "title": str(work.get("title") or ""),
                "authorName": str(work.get("authorName") or ""),
                "publishedText": published_text(work.get("publishedAt")),
                "lowFans": work_lowfans(work, {key for key, keyword in (data.get("keywords") or {}).items() if not account_id or keyword.get("accountId") == account_id}),
                "evidenceInvalid": bool(work.get("quarantinedSources")) and not any((data.get("keywords", {}).get(key) or {}).get("accountId") == account_id for key in work.get("sources", {})),
                "shareUrl": str(work.get("shareUrl") or ""),
                "coverSrc": f"/api/radar/covers/{work_id}" if work.get("coverUrl") else "",
            }

        def original_references(item: Mapping[str, Any]) -> list[dict[str, Any]]:
            snapshots = item.get("referenceSnapshots")
            if isinstance(snapshots, list) and snapshots:
                return [dict(ref) for ref in snapshots if isinstance(ref, Mapping)]
            source = item.get("sourceWork") or {}
            result = [dict(source)] if isinstance(source, Mapping) and source else []
            seen = {str(ref.get("id")) for ref in result}
            for raw in item.get("references") or []:
                ref = dict(raw) if isinstance(raw, Mapping) else reference_view(raw)
                if ref and str(ref.get("id")) not in seen:
                    result.append(ref)
                    seen.add(str(ref.get("id")))
            return result

        return {
            "items": [
                {
                    **dict(item),
                    "dismissed": str(item.get("key") or "") in dismissed,
                    "key": str(item.get("key") or ""),
                    "title": str(item.get("title") or ""),
                    "reason": str(item.get("reason") or ""),
                    "angle": str(item.get("angle") or ""),
                    "audience": str(item.get("audience") or ""),
                    "evidence": str(item.get("evidence") or ""),
                    "priority": str(item.get("priority") or "worth"),
                    "references": original_references(item) if item.get("schemaVersion") == 2 else [
                        view
                        for view in (reference_view(ref) for ref in (item.get("references") or []))
                        if view is not None
                    ][:4],
                    "hook": item.get("hook") if isinstance(item.get("hook"), Mapping) else None,
                    "hookReason": str(item.get("hookReason") or ""),
                    "reviewEvidence": str(item.get("reviewEvidence") or ""),
                    "reviewReferences": item.get("reviewReferences") if isinstance(item.get("reviewReferences"), list) else [],
                    "topicId": str(item.get("topicId") or ""),
                }
                for item in items
                if isinstance(item, Mapping) and str(item.get("title") or "")
            ],
            "schemaVersion": recommendation.get("schemaVersion", 1),
            "dismissedItems": [
                {**dict(value), "key": key, "dismissed": True}
                for key, value in (bucket.get("dismissed") or {}).items()
                if isinstance(value, Mapping) and value.get("schemaVersion") == 2
                and key not in {str(item.get("key")) for item in items if isinstance(item, Mapping)}
            ],
            "dismissedCount": len(dismissed),
            "analysis": recommendation.get("analysis") if isinstance(recommendation.get("analysis"), Mapping) else None,
            "generatedAt": generated_at,
            "generatedText": published_text(generated_at) if generated_at else "",
            "message": str(recommendation.get("message") or ""),
            "scope": str(recommendation.get("scope") or ""),
            "job": {
                "status": str(job.get("status") or "idle"),
                "error": sanitize_message(str(job.get("error") or "")),
                "errorCode": public_code(str(job.get("errorCode") or "")),
                "lastRunAt": str(job.get("lastRunAt") or ""),
                "lastRunText": published_text(job.get("lastRunAt")) if job.get("lastRunAt") else "",
                "lastRunDay": str(job.get("lastRunDay") or ""),
            },
        }

    @_locked
    def recommendation_due_today(self, account_id: str, *, now: datetime | None = None) -> bool:
        """今天是否还没生成过建议（用于每日自动生成一次）。"""
        moment = now or datetime.now(timezone.utc)
        bucket = self._bucket(self._read(), account_id)
        job = bucket.get("recommendationJob") if isinstance(bucket.get("recommendationJob"), Mapping) else {}
        return str(job.get("lastRunDay") or "") != local_day(moment)


def _next_daily_at(clock: Any, moment: datetime) -> str:
    """下一个每日时刻（电脑本地日历）；今天已过就排到明天。"""
    hour, minute = clock_parts(clock)
    local = moment.astimezone()
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat()


def is_new_work(work: Mapping[str, Any], today: date | datetime) -> bool:
    """「今日新发现」＝今天采集到的、不是首次历史导入的作品。"""
    if work.get("baseline"):
        return False
    discovered = parse_iso(work.get("discoveredAt"))
    if discovered is None:
        return False
    target = today.astimezone().date() if isinstance(today, datetime) else today
    return discovered.astimezone().date() == target
