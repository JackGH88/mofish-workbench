"""复盘（review）模块。

按账号读取抖音创作者后台「内容管理」里已发布作品的表现，保存历史快照，
让运营把每条作品的表现转成复盘笔记、选题和下一条脚本的依据。

采集复用「脚本 → 发布」的账号专用浏览器：每个账号一个独立资料目录，同一账号的
发布与采集在同一个单线程 worker 上排队，采集只使用自己创建的临时标签页。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger("douyin-downloader")

REVIEW_PLATFORM_DOUYIN = "douyin"
REVIEW_CONTENT_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"

REVIEW_MODES = ("interval", "daily")
REVIEW_INTERVAL_OPTIONS = (30, 60, 120, 360, 720)
REVIEW_DEFAULT_INTERVAL_MINUTES = 60
REVIEW_DEFAULT_DAILY_TIME = "12:30"
REVIEW_SCOPES = ("recent30", "recent90", "all")
REVIEW_SCOPE_DAYS = {"recent30": 30, "recent90": 90, "all": 0}
REVIEW_DEFAULT_SCOPE = "recent30"

REVIEW_NOTE_LIMIT = 4000
REVIEW_WORK_LIMIT = 800
REVIEW_SNAPSHOT_LIMIT = 120
REVIEW_HISTORY_LIMIT = 20
REVIEW_MANUAL_TITLE_LIMIT = 160
REVIEW_MANUAL_OUTLINE_LIMIT = 2000

# 采集状态：采集是按账号串行的，状态同时描述「上次结果」和「当前是否在跑」。
REVIEW_STATUSES = ("idle", "queued", "running", "success", "partial", "failed", "login_required")
REVIEW_ACTIVE_STATUSES = ("queued", "running")

# 采集节奏与平台更新节奏是两件事：抖音作品数据每日 10 点更新前一日数据，
# 高频繁采集只是更早拿到「还没更新」的同一份数字，界面上要分开说明。
REVIEW_MIN_RETRY_SECONDS = 300
REVIEW_COLLECT_TIME_BUDGET_SECONDS = 240
REVIEW_LIST_READY_TIMEOUT_SECONDS = 60
REVIEW_SCROLL_ROUNDS = 40
REVIEW_SCROLL_PAUSE_SECONDS = 1.2

METRIC_FIELDS = {
    "播放": "views",
    "点赞": "likes",
    "评论": "comments",
    "分享": "shares",
    "收藏": "saves",
    "完播率": "completionRate",
    "2秒跳出率": "bounceRate2s",
    "吸粉量": "fansGained",
    "划走率": "skipRate",
    "文案展开率": "captionExpandRate",
    "平均浏览图片数": "avgImagesViewed",
}
COUNT_FIELDS = ("views", "likes", "comments", "shares", "saves", "fansGained")
PERCENT_FIELDS = ("completionRate", "bounceRate2s", "skipRate", "captionExpandRate")
# 图文作品的平均浏览图片数是普通小数，既不是计数也不是百分比。
DECIMAL_FIELDS = ("avgImagesViewed",)
METRIC_ORDER = (
    "views", "likes", "comments", "shares", "saves",
    "completionRate", "bounceRate2s", "fansGained",
    "skipRate", "captionExpandRate", "avgImagesViewed",
)

_COUNT_RE = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万|亿)?\s*$")
_PERCENT_RE = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*%\s*$")
_DECIMAL_RE = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*张?\s*$")
_PUBLISHED_RE = re.compile(r"(20\d{2})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})\D{0,3}(\d{1,2}):(\d{2})")
_DURATION_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_IMAGE_COUNT_RE = re.compile(r"^(\d+)\s*张$")
_EMPTY_VALUES = {"", "-", "--", "—", "暂无", "null", "None"}


class ReviewCollectionError(Exception):
    """采集失败，带一个给界面看的代码和一句话原因。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ----------------------------------------------------------------------
# 时间与配置
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# 报表版本、趋势与内容因子
# ----------------------------------------------------------------------

# 数据文件版本：V2 增加官方日报表和作品因子，读取旧文件时先备份再补字段。
REVIEW_DATA_VERSION = 2
REVIEW_DAILY_RETENTION_DAYS = 400

REVIEW_TREND_RANGES = (7, 30, 90)
REVIEW_TREND_DEFAULT_DAYS = 30
REVIEW_TREND_SCOPES = ("account", "tracked")
REVIEW_TREND_DEFAULT_SCOPE = "account"
REVIEW_DAILY_FIELD_LIMIT = 40

# 因子维度：内容因子（需要确认）与发布属性（直接读采集结果）分开。
REVIEW_FACTOR_DIMENSIONS = ("topic", "hook", "structure", "time", "format", "platform", "origin")
REVIEW_CONTENT_DIMENSIONS = ("topic", "hook", "structure")
REVIEW_AUTOMATIC_DIMENSIONS = ("time", "format", "platform", "origin")
REVIEW_FACTOR_METRICS = ("median", "mean", "fans", "conversion")
REVIEW_FACTOR_WINDOW_DAYS = 7
REVIEW_FACTOR_DEFAULT_DIMENSION = "hook"
REVIEW_FACTOR_DEFAULT_METRIC = "median"
REVIEW_FACTOR_DEFAULT_RANGE_DAYS = 30
REVIEW_FACTOR_RANGES = (30, 90)
REVIEW_SMALL_SAMPLE = 5
REVIEW_FACTOR_EXCLUDED_LIMIT = 12
REVIEW_FACTOR_HISTORY_LIMIT = 20
REVIEW_DAY_CONTRIBUTION_LIMIT = 20


REVIEW_REPORT_HISTORY_LIMIT = 20

REVIEW_ORIGINS = ("direct", "reference", "unknown")
REVIEW_TIME_BUCKETS = (
    {"key": "00-06", "label": "00:00–06:00", "start": 0},
    {"key": "06-12", "label": "06:00–12:00", "start": 6},
    {"key": "12-18", "label": "12:00–18:00", "start": 12},
    {"key": "18-24", "label": "18:00–24:00", "start": 18},
)
REVIEW_PLATFORM_LABELS = {"douyin": "抖音", "channels": "视频号"}
REVIEW_KIND_LABELS = {"video": "视频", "image": "图文"}
REVIEW_ORIGIN_LABELS = {"direct": "直接创建", "reference": "参考链接", "unknown": "来源未知"}
REVIEW_FACTOR_PENDING = "待确认"
REVIEW_FACTOR_CONFIRMED_ABSENT = "未分类"
REVIEW_METRIC_LABELS = {
    "median": "播放量中位数",
    "mean": "平均播放量",
    "fans": "平均吸粉量",
    "conversion": "每千次播放吸粉数",
}

ACCOUNT_DAILY_COUNT_FIELDS = ("views", "likes", "shares", "comments", "submissions", "totalFans", "fansNet", "fansGained", "fansLost", "returningFans")
ACCOUNT_DAILY_PERCENT_FIELDS = ("completionRate5s", "bounceRate2s", "coverClickRate")
WORK_DAILY_COUNT_FIELDS = (
    "views", "viewsDouyin", "viewsDouyinJingxuan",
    "fansGained", "fansGainedDouyin", "fansGainedDouyinJingxuan",
)
ACCOUNT_DAILY_ORDER = (
    "views", "likes", "shares", "comments", "submissions",
    "completionRate5s", "bounceRate2s", "coverClickRate", "avgWatchSeconds",
    "totalFans", "fansNet", "fansGained", "fansLost", "returningFans",
)
WORK_DAILY_ORDER = (
    "views", "viewsDouyin", "viewsDouyinJingxuan",
    "fansGained", "fansGainedDouyin", "fansGainedDouyinJingxuan",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def options() -> dict[str, Any]:
    """前端需要的可选项，避免在两个地方各写一份枚举。"""
    return {
        "modes": list(REVIEW_MODES),
        "intervalMinutes": list(REVIEW_INTERVAL_OPTIONS),
        "scopes": [{"key": key, "days": REVIEW_SCOPE_DAYS[key]} for key in REVIEW_SCOPES],
        "defaultIntervalMinutes": REVIEW_DEFAULT_INTERVAL_MINUTES,
        "defaultDailyTime": REVIEW_DEFAULT_DAILY_TIME,
        "defaultScope": REVIEW_DEFAULT_SCOPE,
        "metricOrder": list(METRIC_ORDER),
        "countFields": list(COUNT_FIELDS),
        "percentFields": list(PERCENT_FIELDS),
        "noteLimit": REVIEW_NOTE_LIMIT,
        "platformUpdateNote": (
            "抖音作品数据每日 10 点更新前一日数据、作品总览每日 12 点更新；"
            "采集频率只决定检查后台的次数，不会让平台数据提前更新。"
        ),
        "collectionNote": "采集使用该账号在「脚本 → 发布」里的专用浏览器，不使用日常浏览器。",
        "trendNote": (
            "趋势直接使用抖音后台导出的逐日报表（账号每日 10 点、总览每日 12 点更新前一日数据）；"
            "采集频率只决定多久检查一次后台，不会让平台数据提前更新。"
        ),
        "trendScopeNote": "账号口径来自数据中心日报表；已跟踪作品口径只汇总有逐日明细的作品。",
        "factorNote": (
            "内容因子以最终发布内容为准，参考链接的作品不继承参考视频的分类；"
            f"比较窗口固定为发布日起 {REVIEW_FACTOR_WINDOW_DAYS} 个自然日，缺任何一天都不参与比较。"
        ),
        "factorCatalogNote": "分类沿用账号现有的选题分类与写作素材库，改名或删除不会改写已经确认的历史因子。",
        "factorWindowDays": REVIEW_FACTOR_WINDOW_DAYS,
        "reportScopeDays": 30,

    }


def default_config(platform: str = REVIEW_PLATFORM_DOUYIN) -> dict[str, Any]:
    """首次进入复盘页时的默认设置：默认不自动采集。"""
    return {
        "platform": platform if platform in {"douyin", "channels"} else REVIEW_PLATFORM_DOUYIN,
        "enabled": False,
        "mode": "interval",
        "intervalMinutes": REVIEW_DEFAULT_INTERVAL_MINUTES,
        "dailyTime": REVIEW_DEFAULT_DAILY_TIME,
        "scope": REVIEW_DEFAULT_SCOPE,
        "nextRunAt": "",
        "lastAttemptAt": "",
        "lastSuccessAt": "",
        "status": "idle",
        "message": "",
        "lastResult": {},
    }


def normalize_scope(value: Any) -> str:
    scope = str(value or "").strip()
    return scope if scope in REVIEW_SCOPES else REVIEW_DEFAULT_SCOPE


def scope_days(scope: str) -> int:
    return REVIEW_SCOPE_DAYS.get(normalize_scope(scope), 0)


def normalize_config_fields(fields: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    """校验并归一化客户端提交的采集设置，未知字段直接拒绝。"""
    allowed = {"enabled", "mode", "intervalMinutes", "dailyTime", "scope", "platform"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError("采集设置字段无效。")
    config = {**base, **{key: fields[key] for key in fields}}

    if "enabled" in fields:
        if not isinstance(fields["enabled"], bool):
            raise ValueError("自动采集开关无效。")
        config["enabled"] = fields["enabled"]
    if "mode" in fields:
        mode = str(fields["mode"] or "").strip()
        if mode not in REVIEW_MODES:
            raise ValueError("采集方式无效。")
        config["mode"] = mode
    if "intervalMinutes" in fields:
        try:
            minutes = int(fields["intervalMinutes"])
        except (TypeError, ValueError) as exc:
            raise ValueError("采集间隔无效。") from exc
        if minutes not in REVIEW_INTERVAL_OPTIONS:
            raise ValueError("采集间隔无效。")
        config["intervalMinutes"] = minutes
    if "dailyTime" in fields:
        config["dailyTime"] = _normalize_daily_time(fields["dailyTime"])
    if "scope" in fields:
        scope = str(fields["scope"] or "").strip()
        if scope not in REVIEW_SCOPES:
            raise ValueError("采集范围无效。")
        config["scope"] = scope
    if "platform" in fields:
        platform = str(fields["platform"] or "").strip()
        if platform not in {"douyin", "channels"}:
            raise ValueError("复盘平台无效。")
        config["platform"] = platform
    return config


def _normalize_daily_time(value: Any) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        raise ValueError("每天采集时间无效。")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("每天采集时间无效。")
    return f"{hour:02d}:{minute:02d}"


def compute_next_run(config: Mapping[str, Any], *, now: datetime | None = None) -> str:
    """按设置算出下一次执行时间；关闭自动采集时清空。"""
    if not config.get("enabled"):
        return ""
    current = now or datetime.now().astimezone()
    if str(config.get("mode")) == "daily":
        hour, minute = (int(part) for part in str(config.get("dailyTime") or REVIEW_DEFAULT_DAILY_TIME).split(":"))
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        while candidate <= current:
            candidate += timedelta(days=1)
    else:
        minutes = int(config.get("intervalMinutes") or REVIEW_DEFAULT_INTERVAL_MINUTES)
        candidate = current + timedelta(minutes=max(1, minutes))
    return candidate.astimezone(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# 指标解析
# ----------------------------------------------------------------------


def parse_metric(field: str, value: Any) -> Any:
    """把后台文本转成数字；后台显示「—」「-」「--」时返回 None，不能当成 0。"""
    text = str(value if value is not None else "").strip()
    if text in _EMPTY_VALUES:
        return None
    if field in COUNT_FIELDS:
        match = _COUNT_RE.match(text)
        if not match:
            return None
        number = float(match.group(1).replace(",", ""))
        unit = match.group(2)
        if unit == "万":
            number *= 10000
        elif unit == "亿":
            number *= 100000000
        return int(round(number))
    if field in PERCENT_FIELDS:
        match = _PERCENT_RE.match(text)
        if not match:
            return None
        return round(float(match.group(1).replace(",", "")), 2)
    if field in DECIMAL_FIELDS:
        match = _DECIMAL_RE.match(text)
        if not match:
            return None
        return round(float(match.group(1).replace(",", "")), 2)
    return None


def normalize_published_text(value: Any) -> tuple[str, str]:
    """返回 (原始展示文本, ISO 时间)；解析不出来时 ISO 为空。"""
    text = " ".join(str(value or "").split())[:40]
    match = _PUBLISHED_RE.search(text)
    if not match:
        return text, ""
    year, month, day, hour, minute = (int(part) for part in match.groups())
    try:
        moment = datetime(year, month, day, hour, minute).astimezone()
    except ValueError:
        return text, ""
    return text, moment.astimezone(timezone.utc).isoformat()


def duration_seconds(text: Any) -> int | None:
    raw = str(text or "").strip()
    if not _DURATION_RE.match(raw):
        return None
    parts = [int(part) for part in raw.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]


def work_fingerprint(*, published_at: str, duration_text: str, title: str) -> str:
    """作品在列表里没有稳定 ID，用「发布时间+时长+标题」做指纹。

    抖音内容管理列表不暴露作品 ID 或链接，导出文件也没有可直接对应的主键，
    因此用平台自己的三个字段组合去重；标题或时间被改动时会当成新作品，
    由人工在复盘里合并，而不是猜一个可能错的 ID。
    """
    raw = "\u0001".join([published_at.strip(), duration_text.strip(), " ".join(title.split())])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def normalize_douyin_work(raw: Mapping[str, Any], *, account_id: str, collected_at: str) -> dict[str, Any] | None:
    """把页面抓到的原始卡片转成存储记录；没有标题的卡片直接丢弃。"""
    title = " ".join(str(raw.get("title") or "").split())
    if not title:
        return None
    status_text = " ".join(str(raw.get("statusText") or "").split())
    visibility = "private" if (bool(raw.get("privateBadge")) or "私密" in status_text) else "public"
    duration_text = str(raw.get("durationText") or "").strip()
    published_text, published_iso = normalize_published_text(raw.get("publishedText"))
    kind = "image" if (not duration_text and str(raw.get("imageCount") or "").strip()) else "video"
    metrics: dict[str, Any] = {}
    for label, value_text in (raw.get("metrics") or {}).items():
        field = METRIC_FIELDS.get(str(label))
        if field:
            metrics[field] = parse_metric(field, value_text)
    if not metrics:
        metrics = {field: None for field in METRIC_ORDER}
    return {
        "fingerprint": work_fingerprint(published_at=published_text, duration_text=duration_text, title=title),
        "title": title[:300],
        "coverUrl": str(raw.get("coverUrl") or "")[:2000],
        "publishedText": published_text,
        "publishedAtIso": published_iso,
        "durationText": duration_text,
        "durationSeconds": duration_seconds(duration_text),
        "visibility": visibility,
        "kind": kind,
        "pinned": bool(raw.get("pinned")),
        "metrics": metrics,
        "collectedAt": collected_at,
        "accountId": account_id,
    }


def metric_has_data(metrics: Mapping[str, Any] | None) -> bool:
    """是否至少有一项平台给了数值；全为 None 表示后台只显示「—」。"""
    if not isinstance(metrics, Mapping):
        return False
    return any(metrics.get(field) is not None for field in METRIC_ORDER)


# ----------------------------------------------------------------------
# 页面抓取
# ----------------------------------------------------------------------

# 抖音的类名带哈希后缀（video-card-sfaSzz），前缀是稳定的，所以按前缀匹配，
# 再按标签文字兜底。卡片里没有作品 ID 或链接，只能读到标题、时间、时长和指标。
DOUYIN_EXTRACT_SCRIPT = r"""
() => {
  const classOf = (el) => ((el && el.className) || '').toString();
  const hasPrefix = (el, prefix) => classOf(el).split(/\s+/).some((name) => name.startsWith(prefix));
  const text = (el) => ((el && el.textContent) || '').replace(/\s+/g, ' ').trim();
  const firstWithPrefix = (root, prefix) => [...root.querySelectorAll('*')].find((el) => hasPrefix(el, prefix)) || null;
  const cards = [...document.querySelectorAll('div')].filter(
    (el) => hasPrefix(el, 'video-card-') && !(el.parentElement && hasPrefix(el.parentElement, 'video-card-')),
  );
  const works = [];
  for (const card of cards) {
    const record = { metrics: {} };
    const cover = firstWithPrefix(card, 'video-card-cover-');
    if (cover) {
      const background = (cover.style && cover.style.backgroundImage) || '';
      const match = /url\(["']?(.*?)["']?\)/.exec(background);
      if (match) record.coverUrl = match[1];
      const badges = [...cover.querySelectorAll('span')].map(text).filter(Boolean);
      const duration = badges.find((item) => /^\d{1,2}:\d{2}(:\d{2})?$/.test(item));
      if (duration) record.durationText = duration;
      const imageCount = badges.find((item) => /^\d+\s*张$/.test(item));
      if (imageCount) record.imageCount = imageCount;
      record.pinned = badges.some((item) => item.includes('置顶'));
    }
    const titleNode = firstWithPrefix(card, 'info-title-text-');
    // 权限徽标是封面里的 <span class="private-mark-*">（带一个锁图标，所以不是
    // 纯文本叶子节点），类名前缀稳定、哈希后缀不稳定，按前缀匹配，再用徽标文字兜底。
    const privateBadge = [...card.querySelectorAll('span')].find(
      (el) => hasPrefix(el, 'private-mark-') || text(el) === '私密',
    );
    record.privateBadge = Boolean(privateBadge);
    let titleText = text(titleNode);
    if (privateBadge && titleNode && titleNode.contains(privateBadge) && titleText.startsWith('私密')) {
      titleText = titleText.slice(2).trim();
    }
    record.title = titleText;
    record.publishedText = text(firstWithPrefix(card, 'info-time-'));
    record.statusText = text(firstWithPrefix(card, 'info-status-'));
    const items = [...card.querySelectorAll('*')].filter(
      (el) => hasPrefix(el, 'metric-item-') && ![...el.querySelectorAll('*')].some((child) => hasPrefix(child, 'metric-item-')),
    );
    for (const item of items) {
      const label = text(firstWithPrefix(item, 'metric-label-') || item);
      const value = text(firstWithPrefix(item, 'metric-value-'));
      if (label) record.metrics[label] = value;
    }
    if (!record.title && !Object.keys(record.metrics).length) continue;
    works.push(record);
  }
  return { works: works, hasList: cards.length > 0, bodyText: (document.body.innerText || '').slice(0, 4000) };
}
"""

DOUYIN_SCROLL_SCRIPT = r"""
() => {
  const classOf = (el) => ((el && el.className) || '').toString();
  const scroller = [...document.querySelectorAll('div')].find((el) =>
    classOf(el).split(/\s+/).some((name) => name.startsWith('list-scroll-')) && el.scrollHeight > el.clientHeight + 40);
  if (scroller) {
    scroller.scrollTop = scroller.scrollHeight;
    return { target: 'list', top: scroller.scrollTop, height: scroller.scrollHeight };
  }
  window.scrollTo(0, document.body.scrollHeight);
  return { target: 'window', top: window.scrollY, height: document.body.scrollHeight };
}
"""

_LOGIN_HINTS = ("login", "passport")
# 后台在账号还没有作品时给的空状态文案，用来和「选择器没命中」区分开。
_EMPTY_LIST_HINTS = ("暂无", "还没有", "没有更多作品", "去发布作品")


def _page_url(page: Any) -> str:
    try:
        return str(page.url or "")
    except Exception:  # pragma: no cover - 浏览器已关闭时取不到 URL
        return ""


def _looks_like_login(url: str, body_text: str) -> bool:
    lowered = url.lower()
    if any(hint in lowered for hint in _LOGIN_HINTS):
        return True
    return "登录后" in body_text and "扫码登录" in body_text


def collect_douyin_works(
    page: Any,
    *,
    scope: str = REVIEW_DEFAULT_SCOPE,
    cover_dir: Path | None = None,
    account_id: str = "",
    time_budget_seconds: float = REVIEW_COLLECT_TIME_BUDGET_SECONDS,
    list_ready_timeout_seconds: float = REVIEW_LIST_READY_TIMEOUT_SECONDS,
    sleep: Any = None,
) -> dict[str, Any]:
    """在已登录的抖音后台页面读取作品列表，返回归一化后的作品记录。

    调用方负责把页面打开到内容管理页所在账号；这里只做只读抓取：滚动列表、
    提取卡片、按范围过滤，不改动任何作品。
    """
    pause = sleep or time.sleep
    started = time.monotonic()
    collected_at = now_iso()
    # 后台标签页会被 Chrome 降速，SPA 可能一直不渲染（读到的 body 为空）。采集前先切到前台。
    front = getattr(page, "bring_to_front", None)
    if callable(front):
        try:
            front()
        except Exception:
            logger.info("review_bring_to_front_failed account=%s", account_id)
    try:
        page.goto(REVIEW_CONTENT_MANAGE_URL)
    except Exception as exc:
        # Playwright 仍按需加载；只转换已知导航故障，不把程序错误归因于网络。
        from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout

        detail = str(exc)
        if isinstance(exc, BrowserTimeout):
            code = "page_load_timeout"
            message = "抖音管理后台加载超时，暂时无法同步。请检查网络；如开启了代理或 VPN，请检查抖音的直连规则后重试。"
        elif isinstance(exc, BrowserError) and any(token in detail for token in (
            "net::ERR_PROXY_CONNECTION_FAILED", "net::ERR_TUNNEL_CONNECTION_FAILED",
            "net::ERR_NO_SUPPORTED_PROXIES", "net::ERR_PROXY_AUTH_REQUESTED",
        )):
            code = "proxy_connection_failed"
            message = "连接抖音管理后台时代理连接失败。请检查代理或 VPN 设置，让抖音后台直连后重试。"
        elif isinstance(exc, BrowserError) and any(token in detail for token in (
            "net::ERR_CONNECTION_", "net::ERR_NAME_NOT_RESOLVED", "net::ERR_INTERNET_DISCONNECTED",
            "net::ERR_NETWORK_CHANGED", "net::ERR_TIMED_OUT", "net::ERR_ADDRESS_UNREACHABLE",
        )):
            code = "network_connection_failed"
            reason = "连接中断" if any(token in detail for token in (
                "net::ERR_CONNECTION_CLOSED", "net::ERR_CONNECTION_RESET",
            )) else "网络连接异常"
            message = f"抖音管理后台{reason}，暂时无法同步。请检查网络及代理或 VPN 的直连规则后重试。"
        else:
            raise
        logger.warning("review_navigation_failed account=%s code=%s detail=%s", account_id, code, detail)
        raise ReviewCollectionError(code, message + "已保留上一次的数据。") from exc

    first_payload: dict[str, Any] = {}
    deadline = started + min(list_ready_timeout_seconds, time_budget_seconds)
    while time.monotonic() < deadline:
        payload = page.evaluate(DOUYIN_EXTRACT_SCRIPT)
        if isinstance(payload, dict) and payload.get("hasList"):
            first_payload = payload
            break
        body_text = str((payload or {}).get("bodyText") or "") if isinstance(payload, dict) else ""
        if _looks_like_login(_page_url(page), body_text):
            raise ReviewCollectionError("login_required", "抖音登录已失效，请重新登录该账号。")
        pause(1.0)
    if not first_payload:
        payload = page.evaluate(DOUYIN_EXTRACT_SCRIPT)
        body_text = str((payload or {}).get("bodyText") or "") if isinstance(payload, dict) else ""
        if _looks_like_login(_page_url(page), body_text):
            raise ReviewCollectionError("login_required", "抖音登录已失效，请重新登录该账号。")
        hint = next((item for item in _EMPTY_LIST_HINTS if item in body_text), "")
        if isinstance(payload, dict) and hint:
            logger.info("review_list_empty account=%s hint=%s bodyLength=%s", account_id, hint, len(body_text))
            return {"works": [], "rounds": 0, "truncated": False, "elapsed": round(time.monotonic() - started, 1)}
        # 读到页面却没有卡片，也没有空状态文案：不能当成「0 条作品」，否则会把
        # 页面改版写成运营的失败数据。
        logger.warning(
            "review_list_unavailable account=%s url=%s bodyLength=%s",
            account_id, _page_url(page)[:120], len(body_text),
        )
        raise ReviewCollectionError("list_unavailable", "没有读到作品列表，请确认该账号能打开抖音内容管理页。")

    cutoff = None
    days = scope_days(scope)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    seen: dict[str, dict[str, Any]] = {}
    rounds = 0
    idle_rounds = 0
    truncated = False
    payload = first_payload
    while rounds <= REVIEW_SCROLL_ROUNDS:
        before = len(seen)
        for raw in payload.get("works") or []:
            record = normalize_douyin_work(raw, account_id=account_id, collected_at=collected_at)
            if record is not None:
                seen.setdefault(record["fingerprint"], record)
        idle_rounds = idle_rounds + 1 if len(seen) == before else 0
        rounds += 1
        if time.monotonic() - started > time_budget_seconds:
            truncated = True
            break
        if cutoff is not None and _reached_cutoff(seen.values(), cutoff):
            break
        if idle_rounds >= 2:
            break
        page.evaluate(DOUYIN_SCROLL_SCRIPT)
        pause(REVIEW_SCROLL_PAUSE_SECONDS)
        payload = page.evaluate(DOUYIN_EXTRACT_SCRIPT)
        if not isinstance(payload, dict):
            break

    works = [record for record in seen.values() if _within_scope(record, cutoff)]
    works.sort(key=lambda item: (item.get("publishedAtIso") or "", item.get("title") or ""), reverse=True)
    if cover_dir is not None and account_id:
        _cache_covers(page, works, cover_dir=cover_dir, account_id=account_id)
    return {
        "works": works,
        "rounds": rounds,
        "truncated": truncated,
        "elapsed": round(time.monotonic() - started, 1),
    }


def _within_scope(record: Mapping[str, Any], cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    published = _parse_iso(record.get("publishedAtIso"))
    if published is None:
        return True
    return published >= cutoff


def _reached_cutoff(records: Iterable[Mapping[str, Any]], cutoff: datetime) -> bool:
    """列表按最新发布排序，出现早于范围的作品就可以停止滚动。"""
    for record in records:
        published = _parse_iso(record.get("publishedAtIso"))
        if published is not None and published < cutoff:
            return True
    return False


def _cache_covers(page: Any, works: list[dict[str, Any]], *, cover_dir: Path, account_id: str) -> None:
    """把封面下载到本地：抖音封面链接是带签名的临时地址，过期后列表就没有图了。"""
    request = getattr(page, "request", None)
    if request is None:
        return
    target_dir = cover_dir / account_id
    for record in works:
        url = str(record.get("coverUrl") or "")
        if not url:
            continue
        target = target_dir / f"{record['fingerprint']}.jpg"
        if target.is_file():
            record["coverPath"] = str(target)
            continue
        try:
            response = request.get(url, timeout=15000)
            if not getattr(response, "ok", False):
                continue
            body = response.body()
            if not body:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            record["coverPath"] = str(target)
        except Exception as exc:  # 封面失败不影响数据采集
            logger.info("review_cover_download_failed account=%s reason=%s", account_id, type(exc).__name__)


# ----------------------------------------------------------------------
# 存储
# ----------------------------------------------------------------------


class ReviewStore:
    """复盘数据存储：按账号保存作品、快照、笔记和采集设置。"""

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._path = self._workspace_dir / "review-data.json"
        self._covers_dir = self._workspace_dir / "review-covers"
        self._lock = threading.RLock()

    @property
    def covers_dir(self) -> Path:
        """封面缓存目录：抖音封面是带签名的临时链接，下载后列表才不会花版。"""
        return self._covers_dir

    # ---- 基础读写 ----------------------------------------------------

    @staticmethod
    def _clean_daily(raw: Any) -> dict[str, Any]:
        """官方日报表：账号一张、作品一张，按业务日期保存。"""
        source = raw if isinstance(raw, Mapping) else {}
        daily: dict[str, Any] = {"account": {}, "works": {}, "reports": []}
        account = source.get("account") if isinstance(source.get("account"), Mapping) else {}
        raw_days = account.get("days") if isinstance(account.get("days"), Mapping) else {}
        days: dict[str, Any] = {}
        for day, entry in raw_days.items():
            normalized = normalize_report_day(day)
            if not normalized or not isinstance(entry, Mapping):
                continue
            days[normalized] = {
                "metrics": _clean_daily_metrics(entry.get("metrics"), ACCOUNT_DAILY_ORDER),
                "sources": [str(item)[:40] for item in (entry.get("sources") or []) if str(item).strip()][:8],
                "updatedAt": str(entry.get("updatedAt") or ""),
                "revisions": int(entry.get("revisions") or 0),
            }
        if days:
            daily["account"] = {
                "days": days,
                "updatedAt": str(account.get("updatedAt") or ""),
                "scope": dict(account.get("scope") or {}) if isinstance(account.get("scope"), Mapping) else {},
            }
        works = source.get("works") if isinstance(source.get("works"), Mapping) else {}
        for work_id, entry in works.items():
            if not isinstance(entry, Mapping):
                continue
            raw_work_days = entry.get("days") if isinstance(entry.get("days"), Mapping) else {}
            work_days: dict[str, Any] = {}
            for day, day_entry in raw_work_days.items():
                normalized = normalize_report_day(day)
                if not normalized or not isinstance(day_entry, Mapping):
                    continue
                work_days[normalized] = {
                    "metrics": _clean_daily_metrics(day_entry.get("metrics"), WORK_DAILY_ORDER),
                    "updatedAt": str(day_entry.get("updatedAt") or ""),
                    "revisions": int(day_entry.get("revisions") or 0),
                }
            if not work_days:
                continue
            daily["works"][str(work_id)] = {
                "days": work_days,
                "updatedAt": str(entry.get("updatedAt") or ""),
            }
        reports = source.get("reports")
        if isinstance(reports, list):
            daily["reports"] = [dict(item) for item in reports if isinstance(item, Mapping)][-REVIEW_REPORT_HISTORY_LIMIT:]
        return daily

    @staticmethod
    def _clean_factors(raw: Any) -> dict[str, Any]:
        """作品因子快照：内容因子、创作来源与确认记录。"""
        source = raw if isinstance(raw, Mapping) else {}
        factors: dict[str, Any] = {}
        for work_id, entry in source.items():
            if not isinstance(entry, Mapping):
                continue
            factors[str(work_id)] = {
                "topic": normalize_factor_selection(entry.get("topic")),
                "hook": normalize_factor_selection(entry.get("hook")),
                "structure": normalize_factor_selection(entry.get("structure")),
                "origin": normalize_origin(entry.get("origin")),
                "source": str(entry.get("source") or "manual")[:40],
                "confirmedAt": str(entry.get("confirmedAt") or ""),
                "updatedAt": str(entry.get("updatedAt") or ""),
                "history": [dict(item) for item in (entry.get("history") or []) if isinstance(item, Mapping)][-REVIEW_FACTOR_HISTORY_LIMIT:],
            }
        return factors

    def _backup_previous_version(self) -> None:
        """升级到 V2 前留一份旧数据副本；迁移出问题时还能找回原来的作品和笔记。"""
        if not self._path.is_file():
            return
        backup = self._workspace_dir / f"review-data.v{REVIEW_DATA_VERSION - 1}.backup.json"
        try:
            if not backup.exists():
                shutil.copy2(self._path, backup)
                logger.info("review_data_backup_created name=%s", backup.name)
        except OSError:
            logger.warning("review_data_backup_failed")

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        upgrade_needed = isinstance(raw, dict) and int(raw.get("version") or 1) < REVIEW_DATA_VERSION
        accounts: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("accounts"), dict):
            for account_id, bucket in raw["accounts"].items():
                if not isinstance(bucket, dict):
                    continue
                accounts[str(account_id)] = {
                    "config": bucket.get("config") if isinstance(bucket.get("config"), dict) else {},
                    "works": [work for work in bucket.get("works", []) if isinstance(work, dict)] if isinstance(bucket.get("works"), list) else [],
                    "history": [item for item in bucket.get("history", []) if isinstance(item, dict)] if isinstance(bucket.get("history"), list) else [],
                    "daily": self._clean_daily(bucket.get("daily")),
                    "factors": self._clean_factors(bucket.get("factors")),
                }
        if upgrade_needed:
            self._backup_previous_version()
        return {"version": REVIEW_DATA_VERSION, "accounts": accounts}

    def _write(self, data: Mapping[str, Any]) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _bucket(data: dict[str, Any], account_id: str) -> dict[str, Any]:
        bucket = data["accounts"].get(account_id)
        if not isinstance(bucket, dict):
            bucket = {"config": {}, "works": [], "history": [], "daily": {}, "factors": {}}
            data["accounts"][account_id] = bucket
        if not isinstance(bucket.get("works"), list):
            bucket["works"] = []
        if not isinstance(bucket.get("history"), list):
            bucket["history"] = []
        if not isinstance(bucket.get("config"), dict):
            bucket["config"] = {}
        if not isinstance(bucket.get("daily"), dict):
            bucket["daily"] = {}
        if not isinstance(bucket.get("factors"), dict):
            bucket["factors"] = {}
        return bucket

    # ---- 视图 --------------------------------------------------------

    @staticmethod
    def _work_view(work: Mapping[str, Any], *, with_snapshots: bool = False) -> dict[str, Any]:
        snapshots = [item for item in work.get("snapshots", []) if isinstance(item, dict)]
        metrics = work.get("metrics") if isinstance(work.get("metrics"), dict) else {}
        view = {
            "id": str(work.get("id") or ""),
            "accountId": str(work.get("accountId") or ""),
            "platform": str(work.get("platform") or REVIEW_PLATFORM_DOUYIN),
            "title": str(work.get("title") or ""),
            "coverUrl": str(work.get("coverUrl") or ""),
            "coverSrc": "",
            "publishedText": str(work.get("publishedText") or ""),
            "publishedAtIso": str(work.get("publishedAtIso") or ""),
            "durationText": str(work.get("durationText") or ""),
            "durationSeconds": work.get("durationSeconds"),
            "visibility": str(work.get("visibility") or "public"),
            "kind": str(work.get("kind") or "video"),
            "pinned": bool(work.get("pinned")),
            "scriptId": str(work.get("scriptId") or ""),
            "note": str(work.get("note") or ""),
            "reviewedAt": str(work.get("reviewedAt") or ""),
            "metrics": {field: metrics.get(field) for field in METRIC_ORDER},
            "hasData": metric_has_data(metrics),
            "collectedAt": str(work.get("collectedAt") or ""),
            "snapshotCount": len(snapshots),
            "updatedAt": str(work.get("updatedAt") or ""),
        }
        cover_path = str(work.get("coverPath") or "")
        if cover_path:
            view["coverSrc"] = f"/api/review/covers/{view['accountId']}/{Path(cover_path).name}"
        if with_snapshots:
            view["snapshots"] = [
                {
                    "collectedAt": str(item.get("collectedAt") or ""),
                    "metrics": {field: (item.get("metrics") or {}).get(field) for field in METRIC_ORDER},
                }
                for item in snapshots
            ]
        return view

    def _config_view(self, account_id: str, bucket: Mapping[str, Any]) -> dict[str, Any]:
        config = {**default_config(), **(bucket.get("config") or {})}
        works = bucket.get("works") or []
        config["accountId"] = account_id
        config["running"] = str(config.get("status")) in REVIEW_ACTIVE_STATUSES
        config["workCount"] = len(works)
        config["pendingReviewCount"] = sum(1 for work in works if not str(work.get("reviewedAt") or ""))
        config["history"] = [dict(item) for item in (bucket.get("history") or [])][:REVIEW_HISTORY_LIMIT]
        return config

    # ---- 读取接口 ----------------------------------------------------

    def get_config(self, account_id: str) -> dict[str, Any]:
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            return self._config_view(account_id, bucket)

    def list_works(self, account_id: str) -> list[dict[str, Any]]:
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            works = [self._work_view(work) for work in (bucket.get("works") or [])]
        works.sort(key=lambda item: (item.get("publishedAtIso") or "", item.get("updatedAt") or ""), reverse=True)
        return works

    def recommendation_works(self, account_id: str) -> list[dict[str, Any]]:
        """Read this account's works and saved factors in one snapshot, without collection."""
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            factors = self._clean_factors(bucket.get("factors"))
            return [
                {**self._work_view(work), "factors": factors.get(str(work.get("id")), {})}
                for work in (bucket.get("works") or [])
            ]

    def get_work(self, work_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            work = self._locate(data, work_id)
            return self._work_view(work, with_snapshots=True)

    def account_of(self, work_id: str) -> str:
        with self._lock:
            return str(self._locate(self._read(), work_id).get("accountId") or "")

    @staticmethod
    def _locate(data: Mapping[str, Any], work_id: str) -> dict[str, Any]:
        target = str(work_id or "").strip()
        if not target:
            raise ValueError("作品不存在。")
        for bucket in (data.get("accounts") or {}).values():
            for work in bucket.get("works") or []:
                if str(work.get("id") or "") == target:
                    return work
        raise ValueError("作品不存在。")

    def overview(self, account_id: str) -> dict[str, Any]:
        """复盘页首屏：设置、作品列表和汇总口径一起返回。"""
        with self._lock:
            data = self._read()
            bucket = data["accounts"].get(account_id) or {}
            config = self._config_view(account_id, bucket)
            works = [self._work_view(work) for work in (bucket.get("works") or [])]
        works.sort(key=lambda item: (item.get("publishedAtIso") or "", item.get("updatedAt") or ""), reverse=True)
        return {"accountId": account_id, "config": config, "works": works, "summary": summarize(works)}

    # ---- 写入接口 ----------------------------------------------------

    def save_config(self, account_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            bucket = self._bucket(data, account_id)
            base = {**default_config(), **(bucket.get("config") or {})}
            config = normalize_config_fields(fields, base)
            # 每次保存都按「现在」重算下一次执行时间，改频率后不会沿用旧节奏。
            config["nextRunAt"] = compute_next_run(config)
            if not config.get("enabled"):
                config["message"] = "自动采集已关闭。"
            elif str(config.get("status")) not in REVIEW_ACTIVE_STATUSES:
                config["message"] = "已开启自动采集，到点后使用该账号的专用浏览器采集。"
            bucket["config"] = config
            self._write(data)
            return self._config_view(account_id, bucket)

    def record_status(
        self,
        account_id: str,
        status: str,
        message: str,
        *,
        result: Mapping[str, Any] | None = None,
        advance_schedule: bool = False,
    ) -> dict[str, Any]:
        """写入一次采集状态；只有真正执行过才推进下一次执行时间。"""
        with self._lock:
            data = self._read()
            bucket = self._bucket(data, account_id)
            config = {**default_config(), **(bucket.get("config") or {})}
            safe_status = status if status in REVIEW_STATUSES else "failed"
            config["status"] = safe_status
            config["message"] = str(message or "")[:500]
            if safe_status in REVIEW_ACTIVE_STATUSES:
                config["lastAttemptAt"] = now_iso()
            if safe_status in {"success", "partial"}:
                config["lastSuccessAt"] = config.get("lastAttemptAt") or now_iso()
            if result is not None:
                config["lastResult"] = {key: value for key, value in result.items() if isinstance(key, str)}
            if advance_schedule:
                config["nextRunAt"] = compute_next_run(config)
            bucket["config"] = config
            entry = {
                "at": now_iso(),
                "status": safe_status,
                "message": str(message or "")[:500],
                "result": dict(result or {}),
            }
            bucket["history"] = [entry] + [item for item in bucket["history"] if isinstance(item, dict)][: REVIEW_HISTORY_LIMIT - 1]
            self._write(data)
            return self._config_view(account_id, bucket)

    def due_account_ids(self, *, now: datetime | None = None, respect_retry_delay: bool = True) -> list[str]:
        """返回到点该采集的账号；重启后错过的任务会在第一次检查时补一次。"""
        current = now or datetime.now(timezone.utc)
        due: list[str] = []
        with self._lock:
            for account_id, bucket in (self._read().get("accounts") or {}).items():
                config = {**default_config(), **(bucket.get("config") or {})}
                if not config.get("enabled"):
                    continue
                if str(config.get("status")) in REVIEW_ACTIVE_STATUSES or str(config.get("status")) in {"failed", "partial", "login_required"}:
                    continue
                if respect_retry_delay and not _due_for_retry(config, current):
                    continue
                next_run = _parse_iso(config.get("nextRunAt"))
                if next_run is None or next_run <= current:
                    due.append(str(account_id))
        return due

    def reset_running(self) -> list[str]:
        """服务重启后把「采集中」还原成待采集，避免状态永久卡住。"""
        touched: list[str] = []
        with self._lock:
            data = self._read()
            for account_id, bucket in (data.get("accounts") or {}).items():
                config = bucket.get("config") if isinstance(bucket.get("config"), dict) else {}
                if str(config.get("status")) not in REVIEW_ACTIVE_STATUSES:
                    continue
                config["status"] = "idle"
                config["message"] = "服务重启，采集已中断，稍后重试一次。"
                config["nextRunAt"] = compute_next_run(config)
                touched.append(str(account_id))
            if touched:
                self._write(data)
        return touched

    def upsert_works(
        self,
        account_id: str,
        records: Iterable[Mapping[str, Any]],
        *,
        collected_at: str,
    ) -> dict[str, Any]:
        """按指纹合并本次采集：新作品入库，已有作品追加一次快照。"""
        incoming = [dict(record) for record in records if isinstance(record, Mapping)]
        created = 0
        updated = 0
        unchanged = 0
        with self._lock:
            data = self._read()
            bucket = self._bucket(data, account_id)
            existing = {str(work.get("fingerprint") or ""): work for work in bucket["works"]}
            for record in incoming:
                fingerprint = str(record.get("fingerprint") or "")
                if not fingerprint:
                    continue
                work = existing.get(fingerprint)
                metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
                if work is None:
                    work = {
                        "id": str(uuid.uuid4()),
                        "accountId": account_id,
                        "platform": str(record.get("platform") or REVIEW_PLATFORM_DOUYIN),
                        "fingerprint": fingerprint,
                        "snapshots": [],
                        "scriptId": "",
                        "note": "",
                        "reviewedAt": "",
                        "createdAt": collected_at,
                    }
                    bucket["works"].append(work)
                    existing[fingerprint] = work
                    created += 1
                else:
                    updated += 1
                for field in ("title", "coverUrl", "coverPath", "publishedText", "publishedAtIso", "durationText", "durationSeconds", "visibility", "kind", "pinned", "platform"):
                    if record.get(field) is not None and field in record:
                        work[field] = record[field]
                previous = work.get("metrics") if isinstance(work.get("metrics"), dict) else None
                if previous == metrics and work.get("snapshots"):
                    unchanged += 1
                else:
                    snapshots = [item for item in work.get("snapshots", []) if isinstance(item, dict)]
                    snapshots.append({"collectedAt": collected_at, "metrics": dict(metrics)})
                    work["snapshots"] = snapshots[-REVIEW_SNAPSHOT_LIMIT:]
                work["metrics"] = dict(metrics)
                work["collectedAt"] = collected_at
                work["updatedAt"] = collected_at
            if len(bucket["works"]) > REVIEW_WORK_LIMIT:
                bucket["works"] = bucket["works"][-REVIEW_WORK_LIMIT:]
            self._write(data)
        return {"created": created, "updated": updated, "unchanged": unchanged, "total": len(incoming)}

    def save_note(self, work_id: str, *, note: Any, reviewed: bool | None = None) -> dict[str, Any]:
        text = str(note or "").strip()
        if len(text) > REVIEW_NOTE_LIMIT:
            raise ValueError(f"复盘笔记不能超过{REVIEW_NOTE_LIMIT}个字符。")
        with self._lock:
            data = self._read()
            work = self._locate(data, work_id)
            work["note"] = text
            now = now_iso()
            if reviewed is None:
                work["reviewedAt"] = now if text else ""
            else:
                work["reviewedAt"] = now if reviewed else ""
            work["updatedAt"] = now
            self._write(data)
            return self._work_view(work, with_snapshots=True)

    def link_script(self, work_id: str, script_id: Any) -> dict[str, Any]:
        target = str(script_id or "").strip()
        with self._lock:
            data = self._read()
            work = self._locate(data, work_id)
            work["scriptId"] = target
            work["updatedAt"] = now_iso()
            self._write(data)
            return self._work_view(work, with_snapshots=True)

    def unlink_script(self, script_id: str) -> None:
        """脚本被删除时解除关联，历史快照保留。"""
        with self._lock:
            data = self._read()
            touched = False
            for bucket in (data.get("accounts") or {}).values():
                for work in bucket.get("works") or []:
                    if str(work.get("scriptId") or "") == script_id:
                        work["scriptId"] = ""
                        work["updatedAt"] = now_iso()
                        touched = True
            if touched:
                self._write(data)

    def delete_account(self, account_id: str) -> int:
        with self._lock:
            data = self._read()
            bucket = data["accounts"].pop(account_id, None)
            count = len((bucket or {}).get("works") or [])
            if bucket is not None:
                self._write(data)
        # 封面缓存也属于这个账号，跟着账号一起清掉，避免留下无主的图片目录。
        covers = self._covers_dir / str(account_id or "")
        if covers.is_dir() and not covers.is_symlink():
            shutil.rmtree(covers, ignore_errors=True)
        return count

    def cover_file(self, account_id: str, name: str) -> Path | None:
        safe_account = str(account_id or "").strip()
        safe_name = Path(str(name or "")).name
        if not safe_account or not safe_name or safe_name != str(name):
            return None
        path = (self._covers_dir / safe_account / safe_name).resolve()
        try:
            path.relative_to(self._covers_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None


    # ---- 官方日报表 --------------------------------------------------
    # ---- 采集目标 ----------------------------------------------------

    def work_report_targets(
        self,
        account_id: str,
        *,
        limit: int = 20,
        max_age_days: int = 90,
        now: datetime | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """挑出还需要补逐日明细的作品：先补缺口，再复查最近可能被后台修正的作品。

        列表按发布时间从新到旧排：历史作品只在后台还能查到明细时才有意义，
        因此超过 max_age_days 的作品不再自动补采，避免每轮都重扫。
        force=True 时（手动同步）连已经完整的作品也重新拉一遍，方便修正历史数据。
        """
        today = _beijing_today(now)
        oldest = _shift_date(today, -max_age_days)
        deadline = _shift_date(today, -1)
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            works = [dict(work) for work in (bucket.get("works") or [])]
            daily = self._clean_daily(bucket.get("daily"))
        missing: list[dict[str, Any]] = []
        refresh: list[dict[str, Any]] = []
        for work in works:
            published = _parse_iso(work.get("publishedAtIso"))
            if published is None:
                continue
            start = published.astimezone().date().isoformat()
            if start < oldest:
                continue
            if not metric_has_data(work.get("metrics")):
                # 私密或后台不给指标的作品没有明细可导出，不浪费一次页面访问。
                continue
            entry = (daily.get("works") or {}).get(str(work.get("id"))) or {}
            days = entry.get("days") or {}
            window = [
                _shift_date(start, offset)
                for offset in range(REVIEW_FACTOR_WINDOW_DAYS)
            ]
            open_days = [day for day in window if day <= deadline]
            if not open_days:
                continue
            gaps = [
                day for day in open_days
                if any((days.get(day, {}).get("metrics") or {}).get(field) is None
                       for field in ("views", "fansGained"))
            ]
            updated_at = _parse_iso(entry.get("updatedAt"))
            target = {
                "workId": str(work.get("id") or ""),
                "title": str(work.get("title") or ""),
                "publishedAtIso": str(work.get("publishedAtIso") or ""),
                "itemId": str(work.get("itemId") or ""),
                "missingDays": len(gaps),
                "hasWindow": not gaps,
            }
            if gaps:
                missing.append(target)
                continue
            if force:
                refresh.append(target)
                continue
            if open_days[-1] < _shift_date(today, -(REVIEW_FACTOR_WINDOW_DAYS - 1)):
                # 观察窗口已经结束且数据完整，只在需要修正复查时再拉一次。
                continue
            if updated_at is not None and _beijing_today(updated_at) == today:
                continue
            refresh.append(target)
        targets = missing + refresh
        return targets[: max(1, int(limit))]



    def record_daily_reports(
        self,
        account_id: str,
        *,
        account_rows: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
        work_rows: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]] | None = None,
        reports: Iterable[Mapping[str, Any]] = (),
        collected_at: str = "",
        scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把官方逐日报表写入本地：同一账号、同一业务日期重复采集只更新，不累加。"""
        stamp = collected_at or now_iso()
        changed_days: set[str] = set()
        inserted_works = 0
        changed_work_days = 0
        with self._lock:
            data = self._read()
            bucket = self._bucket(data, account_id)
            daily = self._clean_daily(bucket.get("daily"))
            account = daily["account"] if daily["account"] else {"days": {}, "updatedAt": "", "scope": {}}
            account_days = account.get("days") or {}
            for kind, rows in (account_rows or {}).items():
                if kind not in {"account-works", "account-fans"} or not isinstance(rows, Mapping):
                    continue
                for day, metrics in rows.items():
                    normalized = normalize_report_day(day)
                    cleaned = _clean_daily_metrics(metrics, ACCOUNT_DAILY_ORDER)
                    if not normalized or not cleaned:
                        continue
                    entry = account_days.get(normalized)
                    if entry is None:
                        account_days[normalized] = {
                            "metrics": cleaned,
                            "sources": [kind],
                            "updatedAt": stamp,
                            "revisions": 0,
                        }
                        changed_days.add(normalized)
                        continue
                    merged = dict(entry.get("metrics") or {})
                    changed = False
                    for field, value in cleaned.items():
                        if merged.get(field) != value:
                            merged[field] = value
                            changed = True
                    if changed:
                        entry["revisions"] = int(entry.get("revisions") or 0) + 1
                        changed_days.add(normalized)
                    entry["metrics"] = merged
                    entry["sources"] = sorted({*(entry.get("sources") or []), kind})
                    entry["updatedAt"] = stamp
            if account_days:
                account["days"] = self._prune_days(account_days)
                account["updatedAt"] = stamp
                if scope:
                    account["scope"] = {str(key): value for key, value in scope.items() if isinstance(value, (str, int, float, bool))}
                daily["account"] = account
            work_days_store = daily["works"]
            for work_id, kinds in (work_rows or {}).items():
                key = str(work_id or "")
                if not key or not isinstance(kinds, Mapping):
                    continue
                entry = work_days_store.get(key) or {"days": {}, "updatedAt": ""}
                days = entry.get("days") or {}
                if not days:
                    inserted_works += 1
                for kind, rows in kinds.items():
                    if kind not in {"work-views", "work-fans"} or not isinstance(rows, Mapping):
                        continue
                    for day, metrics in rows.items():
                        normalized = normalize_report_day(day)
                        cleaned = _clean_daily_metrics(metrics, WORK_DAILY_ORDER)
                        if not normalized or not cleaned:
                            continue
                        day_entry = days.get(normalized)
                        if day_entry is None:
                            days[normalized] = {"metrics": cleaned, "updatedAt": stamp, "revisions": 0}
                            changed_work_days += 1
                            continue
                        merged = dict(day_entry.get("metrics") or {})
                        changed = False
                        for field, value in cleaned.items():
                            if merged.get(field) != value:
                                merged[field] = value
                                changed = True
                        if changed:
                            day_entry["revisions"] = int(day_entry.get("revisions") or 0) + 1
                            changed_work_days += 1
                        day_entry["metrics"] = merged
                        day_entry["updatedAt"] = stamp
                if days:
                    entry["days"] = self._prune_days(days)
                    entry["updatedAt"] = stamp
                    work_days_store[key] = entry
            daily["works"] = work_days_store
            history = [dict(item) for item in daily["reports"] if isinstance(item, Mapping)]
            works_by_id = {str(work.get("id")): work for work in bucket["works"]}
            for report in reports:
                # ID 来自该作品的详情地址，仅在本账号内保存；列表刷新不会清空它。
                item_id = str(report.get("itemId") or "")
                work = works_by_id.get(str(report.get("workId") or ""))
                if work is not None and item_id.isascii() and item_id.isdigit():
                    work["itemId"] = item_id
                history.append({
                    "kind": str(report.get("kind") or "")[:40],
                    "name": str(report.get("name") or "")[:120],
                    "workId": str(report.get("workId") or "")[:80],
                    "fetchedAt": str(report.get("fetchedAt") or stamp),
                })
            daily["reports"] = history[-REVIEW_REPORT_HISTORY_LIMIT:]
            bucket["daily"] = daily
            self._write(data)
        return {
            "accountDays": len(changed_days),
            "workDays": changed_work_days,
            "works": inserted_works,
            "latestDay": max(changed_days) if changed_days else "",
        }

    @staticmethod
    def _prune_days(days: Mapping[str, Any]) -> dict[str, Any]:
        ordered = sorted(days.items(), key=lambda item: item[0])
        return dict(ordered[-REVIEW_DAILY_RETENTION_DAYS:])

    def daily_view(self, account_id: str) -> dict[str, Any]:
        """给接口看的官方日数据概览：覆盖的日期范围、作品数量与最近同步时间。"""
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            daily = self._clean_daily(bucket.get("daily"))
        account_days = sorted((daily["account"].get("days") or {}).keys())
        works = {key: sorted((value.get("days") or {}).keys()) for key, value in (daily["works"] or {}).items()}
        return {
            "accountDays": account_days,
            "accountFirstDay": account_days[0] if account_days else "",
            "accountLastDay": account_days[-1] if account_days else "",
            "workCount": len([key for key, value in works.items() if value]),
            "works": works,
            "reports": [dict(item) for item in daily["reports"]],
            "updatedAt": str((daily["account"] or {}).get("updatedAt") or ""),
        }

    def trend(self, account_id: str, *, days: Any = REVIEW_TREND_DEFAULT_DAYS, scope: Any = REVIEW_TREND_DEFAULT_SCOPE, now: datetime | None = None) -> dict[str, Any]:
        """每日播放与吸粉趋势：只使用官方日报表，不用本地快照做差值。"""
        window_days = int(days) if str(days).strip().isdigit() and int(days) in REVIEW_TREND_RANGES else REVIEW_TREND_DEFAULT_DAYS
        selected = str(scope or "").strip()
        if selected not in REVIEW_TREND_SCOPES:
            selected = REVIEW_TREND_DEFAULT_SCOPE
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            daily = self._clean_daily(bucket.get("daily"))
        today = _beijing_today(now)
        dates = _date_range(_shift_date(today, -(window_days - 1)), today)
        account_days = daily["account"].get("days") or {}
        work_entries = [value for value in (daily["works"] or {}).values() if isinstance(value, Mapping)]
        points: list[dict[str, Any]] = []
        for day in dates:
            tracked = 0
            if selected == "account":
                entry = account_days.get(day)
                metrics = (entry or {}).get("metrics") if isinstance(entry, Mapping) else None
                views = (metrics or {}).get("views") if isinstance(metrics, Mapping) else None
                fans = (metrics or {}).get("fansGained") if isinstance(metrics, Mapping) else None
            else:
                views_total = 0
                fans_total = 0
                has_views = False
                has_fans = False
                for work in work_entries:
                    day_entry = (work.get("days") or {}).get(day)
                    metrics = (day_entry or {}).get("metrics") if isinstance(day_entry, Mapping) else None
                    if not isinstance(metrics, Mapping):
                        continue
                    tracked += 1
                    if isinstance(metrics.get("views"), (int, float)) and not isinstance(metrics.get("views"), bool):
                        views_total += int(metrics["views"])
                        has_views = True
                    if isinstance(metrics.get("fansGained"), (int, float)) and not isinstance(metrics.get("fansGained"), bool):
                        fans_total += int(metrics["fansGained"])
                        has_fans = True
                views = views_total if has_views else None
                fans = fans_total if has_fans else None
            has_value = isinstance(views, (int, float)) or isinstance(fans, (int, float))
            status = "missing"
            if has_value:
                status = "pending" if day == today else "ok"
            points.append({
                "date": day,
                "views": int(views) if isinstance(views, (int, float)) and not isinstance(views, bool) else None,
                "fans": int(fans) if isinstance(fans, (int, float)) and not isinstance(fans, bool) else None,
                "status": status,
                "trackedWorks": tracked,
            })
        complete = [point for point in points if point["status"] == "ok"]
        view_points = [point for point in complete if isinstance(point["views"], int)]
        fan_points = [point for point in complete if isinstance(point["fans"], int)]
        fans_total = sum(point["fans"] for point in fan_points)
        return {
            "days": window_days,
            "scope": selected,
            "scopeOptions": [
                {"key": "account", "label": "账号整体"},
                {"key": "tracked", "label": "已跟踪作品"},
            ],
            "rangeOptions": list(REVIEW_TREND_RANGES),
            "points": points,
            "summary": {
                "views": sum(point["views"] for point in view_points),
                "fans": fans_total,
                "avgFansPerDay": round(fans_total / len(fan_points), 1) if fan_points else None,
                "coveredDays": len(complete),
                "viewDays": len(view_points),
                "fanDays": len(fan_points),
                "windowDays": window_days,
                "latestDate": complete[-1]["date"] if complete else "",
            },
            "coverage": {
                "accountFirstDay": min(account_days) if account_days else "",
                "accountLastDay": max(account_days) if account_days else "",
                "trackedWorks": len([work for work in work_entries if work.get("days")]),
            },
            "timezone": "Asia/Shanghai",
            "updatedAt": str((daily["account"] or {}).get("updatedAt") or ""),
        }

    # ---- 作品因子 ----------------------------------------------------
    def day_contributions(self, account_id: str, day: Any) -> dict[str, Any]:
        """某一天的账号总量与已采集作品明细；账号总量不强行拆给某条作品。"""
        normalized = normalize_report_day(day)
        if not normalized:
            raise ValueError("日期无效。")
        with self._lock:
            bucket = self._read()["accounts"].get(account_id) or {}
            works = [dict(work) for work in (bucket.get("works") or [])]
            daily = self._clean_daily(bucket.get("daily"))
        account_entry = (daily["account"].get("days") or {}).get(normalized) or {}
        account_metrics = account_entry.get("metrics") if isinstance(account_entry, Mapping) else {}
        items: list[dict[str, Any]] = []
        for work in works:
            entry = ((daily.get("works") or {}).get(str(work.get("id"))) or {}).get("days") or {}
            day_entry = entry.get(normalized) or {}
            metrics = day_entry.get("metrics") if isinstance(day_entry, Mapping) else None
            if not isinstance(metrics, Mapping):
                continue
            views = metrics.get("views")
            fans = metrics.get("fansGained")
            if not isinstance(views, (int, float)) and not isinstance(fans, (int, float)):
                continue
            items.append({
                "workId": str(work.get("id") or ""),
                "title": str(work.get("title") or ""),
                "kind": str(work.get("kind") or "video"),
                "publishedText": str(work.get("publishedText") or ""),
                "views": int(views) if isinstance(views, (int, float)) and not isinstance(views, bool) else None,
                "fans": int(fans) if isinstance(fans, (int, float)) and not isinstance(fans, bool) else None,
            })
        items.sort(key=lambda item: (item.get("views") or -1), reverse=True)
        tracked_views = sum(item["views"] for item in items if isinstance(item.get("views"), int))
        tracked_fans = sum(item["fans"] for item in items if isinstance(item.get("fans"), int))
        account_views = (account_metrics or {}).get("views")
        account_fans = (account_metrics or {}).get("fansGained")
        covered = bool(items)
        note = "账号总量来自后台日报表；下方作品明细只包含已经采集到逐日数据的作品。"
        if isinstance(account_views, int) and covered and tracked_views != account_views:
            note = f"账号当天播放 {account_views}，已采集作品合计 {tracked_views}；差额来自未采集逐日明细的作品。"
        return {
            "date": normalized,
            "account": {
                "views": account_views if isinstance(account_views, int) else None,
                "fans": account_fans if isinstance(account_fans, int) else None,
                "sources": [str(item)[:40] for item in (account_entry.get("sources") or [])][:8],
            },
            "works": items[:REVIEW_DAY_CONTRIBUTION_LIMIT],
            "workCount": len(items),
            "trackedViews": tracked_views,
            "trackedFans": tracked_fans,
            "note": note,
        }




    def work_factors(self, work_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            work = self._locate(data, work_id)
            account_id = str(work.get("accountId") or "")
            bucket = data["accounts"].get(account_id) or {}
            stored = (bucket.get("factors") or {}).get(str(work.get("id")))
            factors = self._clean_factors({str(work.get("id")): stored}).get(str(work.get("id"))) if stored else None
            daily = self._clean_daily(bucket.get("daily"))
        return {
            "workId": str(work.get("id") or ""),
            "accountId": account_id,
            "factors": factors or {},
            "confirmed": bool((factors or {}).get("confirmedAt")),
            "daily": self._work_daily_window(daily, work),
        }

    def _work_daily_window(self, daily: Mapping[str, Any], work: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        days = ((daily.get("works") or {}).get(str(work.get("id"))) or {}).get("days") or {}
        today = _beijing_today(now)
        result = factor_window_metrics(days, str(work.get("publishedAtIso") or ""), today=today)
        return {**result, "days": len(days)}

    def save_work_factors(
        self,
        work_id: str,
        fields: Mapping[str, Any],
        *,
        source: str = "manual",
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        """保存人工确认后的因子快照；不改脚本、不改分类库。"""
        allowed = {"topic", "hook", "structure", "origin", "confirmed"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError("作品因子字段无效。")
        stamp = recorded_at or now_iso()
        with self._lock:
            data = self._read()
            work = self._locate(data, work_id)
            account_id = str(work.get("accountId") or "")
            bucket = self._bucket(data, account_id)
            work_key = str(work.get("id") or "")
            previous = self._clean_factors({work_key: (bucket.get("factors") or {}).get(work_key)}).get(work_key) or {}
            record = {
                "topic": normalize_factor_selection(fields["topic"]) if "topic" in fields else previous.get("topic", {"id": "", "name": ""}),
                "hook": normalize_factor_selection(fields["hook"]) if "hook" in fields else previous.get("hook", {"id": "", "name": ""}),
                "structure": normalize_factor_selection(fields["structure"]) if "structure" in fields else previous.get("structure", {"id": "", "name": ""}),
                "origin": normalize_origin(fields["origin"]) if "origin" in fields else previous.get("origin", "unknown"),
                "source": str(source or "manual")[:40],
                "confirmedAt": "",
                "updatedAt": stamp,
                "history": list(previous.get("history") or []),
            }
            confirmed = fields.get("confirmed")
            if confirmed is None:
                confirmed = str(previous.get("confirmedAt") or "") != ""
            if confirmed:
                record["confirmedAt"] = stamp
            record["history"] = (record["history"] + [{
                "at": stamp,
                "source": record["source"],
                "topic": record["topic"]["name"],
                "hook": record["hook"]["name"],
                "structure": record["structure"]["name"],
                "origin": record["origin"],
                "confirmed": bool(record["confirmedAt"]),
            }])[-REVIEW_FACTOR_HISTORY_LIMIT:]
            factors = bucket.setdefault("factors", {})
            factors[work_key] = record
            work["factorsUpdatedAt"] = stamp
            self._write(data)
        return self.work_factors(work_id)

    def factor_overview(
        self,
        account_id: str,
        *,
        dimension: Any = REVIEW_FACTOR_DEFAULT_DIMENSION,
        metric: Any = REVIEW_FACTOR_DEFAULT_METRIC,
        days: Any = REVIEW_FACTOR_DEFAULT_RANGE_DAYS,
        origins: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """按统一观察窗口（发布日起 7 个自然日）分组比较作品表现。"""
        selected_dimension = str(dimension or "").strip()
        if selected_dimension not in REVIEW_FACTOR_DIMENSIONS:
            selected_dimension = REVIEW_FACTOR_DEFAULT_DIMENSION
        selected_metric = str(metric or "").strip()
        if selected_metric not in REVIEW_FACTOR_METRICS:
            selected_metric = REVIEW_FACTOR_DEFAULT_METRIC
        window_days = int(days) if str(days).strip().isdigit() and int(days) in REVIEW_FACTOR_RANGES else REVIEW_FACTOR_DEFAULT_RANGE_DAYS
        today = _beijing_today(now)
        cutoff = _shift_date(today, -window_days)
        with self._lock:
            data = self._read()
            bucket = data["accounts"].get(account_id) or {}
            works = [dict(work) for work in (bucket.get("works") or [])]
            daily = self._clean_daily(bucket.get("daily"))
            factors = self._clean_factors(bucket.get("factors"))
        origin_map = {str(key): normalize_origin(value) for key, value in (origins or {}).items()}
        eligible: list[dict[str, Any]] = []
        excluded: dict[str, int] = {}
        out_of_range = 0
        for work in works:
            published = _parse_iso(work.get("publishedAtIso"))
            published_day = published.astimezone().date().isoformat() if published is not None else ""
            if published_day and published_day < cutoff:
                out_of_range += 1
                continue
            window = self._work_daily_window(daily, work, now=now)
            if not window.get("ok"):
                key = str(window.get("reason") or "无法参与比较")
                excluded[key] = excluded.get(key, 0) + 1
                continue
            record = factors.get(str(work.get("id"))) or {}
            confirmed = bool(record.get("confirmedAt"))
            label, grouped = self._factor_group_label(selected_dimension, work, record, origin_map, published)
            if selected_dimension in REVIEW_CONTENT_DIMENSIONS and not grouped:
                excluded[REVIEW_FACTOR_PENDING] = excluded.get(REVIEW_FACTOR_PENDING, 0) + 1
                continue
            eligible.append({
                "workId": str(work.get("id") or ""),
                "title": str(work.get("title") or ""),
                "group": label,
                "confirmed": confirmed,
                "origin": origin_map.get(str(work.get("id")), normalize_origin(record.get("origin"))),
                "views": window["views"],
                "fans": window["fans"],
                "publishedText": str(work.get("publishedText") or ""),
                "publishedAtIso": str(work.get("publishedAtIso") or ""),
                "window": {"startDate": window["startDate"], "endDate": window["endDate"]},
            })
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in eligible:
            groups.setdefault(item["group"], []).append(item)
        rendered = []
        for name, items in groups.items():
            value = factor_group_value(selected_metric, items)
            rendered.append({
                "name": name,
                "sampleCount": len(items),
                "smallSample": len(items) < REVIEW_SMALL_SAMPLE,
                "value": None if value is None else round(value, 1),
                "works": sorted(items, key=lambda item: item.get("views") or 0, reverse=True)[:REVIEW_FACTOR_EXCLUDED_LIMIT],
            })
        rendered.sort(key=lambda group: (group["value"] is None, -(group["value"] or 0), group["name"]))
        pending = sum(1 for work in works if not (factors.get(str(work.get("id"))) or {}).get("confirmedAt"))
        return {
            "dimension": selected_dimension,
            "dimensions": [
                {"key": "topic", "label": "选题分类"},
                {"key": "hook", "label": "钩子"},
                {"key": "structure", "label": "结构"},
                {"key": "time", "label": "时段"},
                {"key": "format", "label": "形态"},
                {"key": "platform", "label": "平台"},
                {"key": "origin", "label": "创作来源"},
            ],
            "metric": selected_metric,
            "metricLabel": REVIEW_METRIC_LABELS.get(selected_metric, ""),
            "metricOptions": [{"key": key, "label": REVIEW_METRIC_LABELS[key]} for key in REVIEW_FACTOR_METRICS],
            "rangeDays": window_days,
            "rangeOptions": list(REVIEW_FACTOR_RANGES),
            "windowDays": REVIEW_FACTOR_WINDOW_DAYS,
            "groups": rendered,
            "coverage": {
                "total": len(works),
                "eligible": len(eligible),
                "outOfRange": out_of_range,
                "pendingFactors": pending,
                "smallSampleLimit": REVIEW_SMALL_SAMPLE,
                "excluded": [{"reason": reason, "count": count} for reason, count in sorted(excluded.items(), key=lambda item: -item[1])],
            },
            "automatic": selected_dimension in REVIEW_AUTOMATIC_DIMENSIONS,
        }

    @staticmethod
    def _factor_group_label(
        dimension: str,
        work: Mapping[str, Any],
        record: Mapping[str, Any],
        origin_map: Mapping[str, str],
        published: datetime | None,
    ) -> tuple[str, bool]:
        """返回 (分组名, 是否算作已确认的内容因子)。"""
        work_id = str(work.get("id") or "")
        if dimension in REVIEW_CONTENT_DIMENSIONS:
            selection = record.get(dimension) if isinstance(record.get(dimension), Mapping) else {}
            name = str((selection or {}).get("name") or "").strip()
            confirmed = bool(record.get("confirmedAt"))
            if confirmed and name:
                return name, True
            if name:
                return name, False
            return REVIEW_FACTOR_CONFIRMED_ABSENT, False
        if dimension == "time":
            bucket = time_bucket_of(work.get("publishedAtIso"))
            label = next((item["label"] for item in REVIEW_TIME_BUCKETS if item["key"] == bucket), "")
            return label or "发布时间未知", True
        if dimension == "format":
            return REVIEW_KIND_LABELS.get(str(work.get("kind") or "video"), "视频"), True
        if dimension == "platform":
            return REVIEW_PLATFORM_LABELS.get(str(work.get("platform") or "douyin"), "抖音"), True
        if dimension == "origin":
            origin = origin_map.get(work_id) or normalize_origin(record.get("origin"))
            return REVIEW_ORIGIN_LABELS.get(origin, "来源未知"), True
        return "未分类", True

    def pending_factor_works(self, account_id: str) -> list[dict[str, Any]]:
        """还没有确认内容因子的作品，供「补全作品因子」使用。"""
        with self._lock:
            data = self._read()
            bucket = data["accounts"].get(account_id) or {}
            works = [dict(work) for work in (bucket.get("works") or [])]
            factors = self._clean_factors(bucket.get("factors"))
        pending = []
        for work in works:
            record = factors.get(str(work.get("id"))) or {}
            if record.get("confirmedAt"):
                continue
            pending.append({
                "workId": str(work.get("id") or ""),
                "title": str(work.get("title") or ""),
                "publishedText": str(work.get("publishedText") or ""),
                "publishedAtIso": str(work.get("publishedAtIso") or ""),
                "scriptId": str(work.get("scriptId") or ""),
                "kind": str(work.get("kind") or "video"),
            })
        return pending


def summarize(works: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """按作品累计值汇总；只统计平台给过数值的作品，并说明覆盖数量。"""
    items = list(works)
    totals = {field: 0 for field in COUNT_FIELDS}
    counted = 0
    with_data = 0
    for work in items:
        metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
        if metric_has_data(metrics):
            with_data += 1
            counted += 1
            for field in COUNT_FIELDS:
                value = metrics.get(field)
                if isinstance(value, (int, float)):
                    totals[field] += value
    return {
        "workCount": len(items),
        "worksWithData": with_data,
        "worksPendingReview": sum(1 for work in items if not str(work.get("reviewedAt") or "")),
        "metricTotals": totals,
        "metricBasis": "所选作品最近一次采集快照的累计值之和",
        "countedWorks": counted,
    }


def _beijing_today(now: datetime | None = None) -> str:
    """北京时间自然日；报表的业务日期按这个口径对齐。"""
    current = now or datetime.now(timezone.utc)
    return current.astimezone().date().isoformat()


def _shift_date(day: str, offset: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=offset)).isoformat()


def _date_range(start: str, end: str) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    days: list[str] = []
    current = first
    while current <= last:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _clean_daily_metrics(metrics: Mapping[str, Any] | None, allowed: Iterable[str]) -> dict[str, Any]:
    """只保留认识的字段；数值缺失保持 None，不把「没有数据」写成 0。"""
    if not isinstance(metrics, Mapping):
        return {}
    cleaned: dict[str, Any] = {}
    for field in allowed:
        if field not in metrics:
            continue
        value = metrics.get(field)
        if value is None:
            cleaned[field] = None
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            cleaned[field] = value
    return cleaned


def normalize_origin(value: Any) -> str:
    origin = str(value or "").strip()
    return origin if origin in REVIEW_ORIGINS else "unknown"


_REPORT_DAY_RE = re.compile(r"^\s*(20\d{2})-(\d{1,2})-(\d{1,2})")


def normalize_report_day(value: Any) -> str:
    """已入库的业务日期统一成 YYYY-MM-DD。"""
    match = _REPORT_DAY_RE.match(str(value or ""))
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def time_bucket_of(iso: Any) -> str:
    """按实际发布时间的北京时间小时分成四段；时间不明返回空串。"""
    moment = _parse_iso(iso)
    if moment is None:
        return ""
    hour = moment.astimezone().hour
    for bucket in reversed(REVIEW_TIME_BUCKETS):
        if hour >= bucket["start"]:
            return str(bucket["key"])
    return ""


def _clock(iso: Any) -> str:
    moment = _parse_iso(iso)
    if moment is None:
        return ""
    return moment.astimezone().strftime("%H:%M")


def normalize_factor_selection(value: Any, *, allow_empty: bool = True) -> dict[str, Any]:
    """内容因子只存标识和名称快照，分类库改名或删除都不会改写历史。"""
    if value is None:
        return {"id": "", "name": ""}
    if not isinstance(value, Mapping):
        name = " ".join(str(value).split())[:80]
        if not name and not allow_empty:
            raise ValueError("因子分类无效。")
        return {"id": "", "name": name}
    name = " ".join(str(value.get("name") or "").split())[:80]
    if not name and not allow_empty:
        raise ValueError("因子分类无效。")
    return {"id": str(value.get("id") or "")[:120], "name": name}


def factor_window_metrics(days: Mapping[str, Any], published_at: str, *, today: str) -> dict[str, Any]:
    """取发布日起 7 个自然日的官方合计；缺少任何一天就不参与比较。"""
    published = _parse_iso(published_at)
    if published is None:
        return {"ok": False, "reason": "发布时间未知"}
    start = published.astimezone().date()
    window = [(start + timedelta(days=offset)).isoformat() for offset in range(REVIEW_FACTOR_WINDOW_DAYS)]
    if window[-1] >= today:
        return {"ok": False, "reason": "还没满 7 个自然日"}
    views = 0
    fans = 0
    for day in window:
        entry = days.get(day) if isinstance(days, Mapping) else None
        metrics = (entry or {}).get("metrics") if isinstance(entry, Mapping) else None
        if not isinstance(metrics, Mapping):
            return {"ok": False, "reason": "缺少窗口内的官方日数据"}
        day_views = metrics.get("views")
        day_fans = metrics.get("fansGained")
        if not isinstance(day_views, (int, float)) or not isinstance(day_fans, (int, float)):
            return {"ok": False, "reason": "窗口内的日指标不完整"}
        views += day_views
        fans += day_fans
    return {
        "ok": True,
        "startDate": window[0],
        "endDate": window[-1],
        "views": int(round(views)),
        "fans": int(round(fans)),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def factor_group_value(metric: str, items: Iterable[Mapping[str, Any]]) -> float | None:
    """按选中的指标算一组作品的代表值；分母为零时返回 None 而不是 0。"""
    rows = list(items)
    if not rows:
        return None
    views = [float(row.get("views") or 0) for row in rows]
    fans = [float(row.get("fans") or 0) for row in rows]
    if metric == "median":
        return _median(views)
    if metric == "mean":
        return sum(views) / len(rows)
    if metric == "fans":
        return sum(fans) / len(rows)
    if metric == "conversion":
        total_views = sum(views)
        if total_views <= 0:
            return None
        return sum(fans) / total_views * 1000
    raise ValueError("因子指标无效。")
def _due_for_retry(config: Mapping[str, Any], now: datetime) -> bool:
    """采集失败后不要立刻重跑：最近一次尝试在冷却期内就等下一轮。"""
    last_attempt = _parse_iso(config.get("lastAttemptAt"))
    if last_attempt is None:
        return True
    if str(config.get("status")) not in {"failed", "login_required", "partial"}:
        return True
    return (now - last_attempt).total_seconds() >= REVIEW_MIN_RETRY_SECONDS

_HASHTAG_RE = re.compile(r"[#＃][^\s#＃]+")
REVIEW_MANUAL_TITLE_TEXT_LIMIT = 40


def _topic_title_from_work(title: str) -> str:
    """派生选题标题：去掉话题标签和多余空白，太长就截断，保留可读性。"""
    stripped = _HASHTAG_RE.sub(" ", str(title or ""))
    cleaned = " ".join(stripped.split())
    if len(cleaned) > REVIEW_MANUAL_TITLE_TEXT_LIMIT:
        cleaned = cleaned[:REVIEW_MANUAL_TITLE_TEXT_LIMIT].rstrip() + "…"
    return cleaned


def build_manual_topic_fields(work: Mapping[str, Any], *, week_start: Any = None) -> dict[str, Any]:
    """把复盘结论整理成选题表单的预填字段，最终仍由运营确认保存。"""
    raw_title = str(work.get("title") or "").strip()
    short_title = _topic_title_from_work(raw_title)
    note = str(work.get("note") or "").strip()
    metrics = work.get("metrics") if isinstance(work.get("metrics"), Mapping) else {}
    lines = []
    if note:
        lines.append(f"上一条复盘：{note}")
    labels = {"views": "播放", "likes": "点赞", "comments": "评论", "shares": "分享", "saves": "收藏", "completionRate": "完播率"}
    snapshot = "，".join(f"{name} {metrics[field]}" for field, name in labels.items() if metrics.get(field) is not None)
    if snapshot:
        lines.append(f"来源作品数据：{snapshot}")
    if work.get("publishedText"):
        lines.append(f"来源作品：{raw_title}（{work.get('publishedText')}）")
    outline = "\n".join(lines)[:REVIEW_MANUAL_OUTLINE_LIMIT]
    fields = {
        "title": (f"{short_title}（优化版）" if short_title else "")[:REVIEW_MANUAL_TITLE_LIMIT],
        "outline": outline,
        "category": "test",
        "format": "video",
        # 后台列表不提供作品链接，封面是带签名的临时地址（会过期）。这里不填一个
        # 之后必然失效的地址，素材由运营按实际需要补充。
        "materials": "",
    }
    if week_start:
        fields["weekStart"] = week_start
    return fields
