"""抖音官方数据：解析后台导出的表格，并直接用后台自己的接口读逐日数据。

复盘 V2 的每日趋势以抖音后台的官方数字为准：数据中心的「作品数据 / 粉丝数据」和
作品详情的「流量 / 粉丝 → 每天」都能读到逐日明细，所以电脑漏开一天，恢复之后照样
能补回后台仍然提供的日期。

采集优先走接口读取（不点「导出」）：这台机器上的 Chrome 在点导出时会让浏览器进程
崩掉，而接口返回的就是同一个页面上看到的数字。read_report 保留下来用于解析后台
导出的表格文件（例如人工导出的报表或历史留档）。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .review import DOUYIN_SCROLL_SCRIPT, ReviewCollectionError, logger

DOUYIN_DATA_CENTER_URL = "https://creator.douyin.com/creator-micro/data-center/operation"
DOUYIN_CONTENT_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
DOUYIN_WORK_DETAIL_MARK = "/work-management/work-detail/"

# 后台自己的数据接口。
REVIEW_API_OVERVIEW = "/janus/douyin/creator/data/overview/dashboard"
REVIEW_API_OVERVIEW_FANS = "/janus/douyin/creator/data/overview/dashboard/fans"
REVIEW_API_ITEM_TREND = "/janus/douyin/creator/data/item_analysis/metrics_trend"

REPORT_ACCOUNT_WORKS = "account-works"
REPORT_ACCOUNT_FANS = "account-fans"
REPORT_WORK_VIEWS = "work-views"
REPORT_WORK_FANS = "work-fans"
REPORT_KINDS = (REPORT_ACCOUNT_WORKS, REPORT_ACCOUNT_FANS, REPORT_WORK_VIEWS, REPORT_WORK_FANS)

REPORT_RECENT_SCOPE_DAYS = 30
REPORT_MAX_SCOPE_DAYS = 90
REPORT_WORK_SYNC_LIMIT = 20
REPORT_WORK_CARD_SCROLL_ROUNDS = 25
REPORT_WORK_CARD_SCROLL_PAUSE_MS = 700
REPORT_SYNC_TIME_BUDGET_SECONDS = 900
REPORT_PAGE_READY_TIMEOUT_MS = 45000
REPORT_API_TIMEOUT_MS = 30000
REPORT_WORK_DETAIL_ID_TIMEOUT_MS = 20000

_EMPTY_VALUES = {"", "-", "--", "—", "暂无", "null", "None", "/"}
# 接口给的是紧凑日期（20260911），报表和作品接口给的是带分隔符的日期或时间。
_COMPACT_DATE_RE = re.compile(r"^(20\d{2})(\d{2})(\d{2})$")
_DATE_RE = re.compile(r"^(20\d{2})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})")
_SECONDS_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*s\s*$")
_PERCENT_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*$")
_NUMBER_RE = re.compile(r"^-?[0-9][0-9,]*(?:\.[0-9]+)?$")

# 接口字段 → 存储字段。同一含义在接口和导出表格里用不同的名字。
API_METRIC_FIELDS = {
    "play_cnt": "views",
    "digg_cnt": "likes",
    "share_count": "shares",
    "comment_cnt": "comments",
    "publish_cnt": "submissions",
    "cover_click_ratio": "coverClickRate",
    "completion_rate_5s": "completionRate5s",
    "bounce_rate_2s": "bounceRate2s",
    "avg_view_second": "avgWatchSeconds",
    "homepage_view_cnt": "homepageViews",
    "net_fans_cnt": "fansNet",
    "cancel_fans_cnt": "fansLost",
    "new_fans_cnt": "fansGained",
    "total_fans_cnt": "totalFans",
    "home_view_fans_cnt": "returningFans",
}
# 接口里的比率是 0–1 的小数，报表里是百分数；统一按百分数存储。
API_RATIO_FIELDS = ("coverClickRate", "completionRate5s", "bounceRate2s")
# 作品逐日接口：播放量和涨粉分别对应一个指标。
API_WORK_METRICS = {"view_count": "views", "subscribe_count": "fansGained"}

ACCOUNT_WORK_COLUMNS = {
    "投稿量": "submissions",
    "总播放量": "views",
    "总点赞量": "likes",
    "总分享量": "shares",
    "总评论量": "comments",
    "5秒完播率": "completionRate5s",
    "2秒跳出率": "bounceRate2s",
    "封面点击率": "coverClickRate",
    "平均播放时长": "avgWatchSeconds",
}
ACCOUNT_FAN_COLUMNS = {
    "总粉丝量": "totalFans",
    "粉丝净增": "fansNet",
    "吸粉量": "fansGained",
    "脱粉量": "fansLost",
    "回访粉丝量": "returningFans",
}
WORK_TREND_COLUMNS = {
    "播放量": ("views", "viewsDouyin", "viewsDouyinJingxuan"),
    "涨粉量": ("fansGained", "fansGainedDouyin", "fansGainedDouyinJingxuan"),
}

ACCOUNT_COUNT_FIELDS = ("views", "likes", "shares", "comments", "submissions", "homepageViews")
ACCOUNT_PERCENT_FIELDS = ("completionRate5s", "bounceRate2s", "coverClickRate")
ACCOUNT_DECIMAL_FIELDS = ("avgWatchSeconds",)
ACCOUNT_FAN_COUNT_FIELDS = ("totalFans", "fansNet", "fansGained", "fansLost", "returningFans")
WORK_COUNT_FIELDS = (
    "views", "viewsDouyin", "viewsDouyinJingxuan",
    "fansGained", "fansGainedDouyin", "fansGainedDouyinJingxuan",
)


def _text(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def normalize_report_date(value: Any) -> str:
    """报表或接口里的日期统一成 YYYY-MM-DD；解析不出来返回空串。"""
    raw = _text(value)
    if not raw:
        return ""
    compact = _COMPACT_DATE_RE.match(raw)
    match = compact or _DATE_RE.match(raw.replace("/", "-").replace(".", "-"))
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def parse_report_number(value: Any) -> Any:
    """把单元格或接口值转成数字：空值保持 None，百分比转数值，时长转秒。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # 接口里已经是数字：小数保留精度，别在这里先四舍五入丢掉有效位。
        return int(value) if float(value).is_integer() else round(float(value), 4)
    raw = _text(value)
    if raw in _EMPTY_VALUES:
        return None
    seconds = _SECONDS_RE.match(raw)
    if seconds:
        return round(float(seconds.group(1)), 2)
    percent = _PERCENT_RE.match(raw)
    if percent:
        return round(float(percent.group(1)), 2)
    if _NUMBER_RE.match(raw):
        number = float(raw.replace(",", ""))
        return int(number) if number.is_integer() else round(number, 2)
    return None


# ----------------------------------------------------------------------
# 接口读取
# ----------------------------------------------------------------------


def fetch_json(page: Any, url: str, *, timeout_ms: int = REPORT_API_TIMEOUT_MS) -> dict[str, Any]:
    """在同一来源里带 cookie 取接口数据；失败时抛出可读的采集错误。"""
    try:
        payload = page.evaluate(
            """async (args) => {
              const controller = new AbortController();
              const timer = setTimeout(() => controller.abort(), args.timeout);
              try {
                const response = await fetch(args.url, { credentials: 'include', signal: controller.signal });
                const text = await response.text();
                return { ok: response.ok, status: response.status, body: text.slice(0, 2000000) };
              } finally {
                clearTimeout(timer);
              }
            }""",
            {"url": url, "timeout": timeout_ms},
        )
    except Exception as exc:
        raise ReviewCollectionError("api_unavailable", "后台接口请求失败，稍后重试。") from exc
    if not isinstance(payload, Mapping) or not payload.get("ok"):
        raise ReviewCollectionError("api_failed", "后台接口没有返回数据，稍后重试。")
    try:
        body = json.loads(str(payload.get("body") or ""))
    except (ValueError, TypeError) as exc:
        raise ReviewCollectionError("api_invalid", "后台接口返回的内容无法解析。") from exc
    if not isinstance(body, dict):
        raise ReviewCollectionError("api_invalid", "后台接口返回的内容无法解析。")
    if body.get("status_code") not in (None, 0) and not body.get("metrics"):
        raise ReviewCollectionError("api_login_required", "后台接口要求重新登录该账号。")
    return body


def _trend_points(entry: Any) -> list[Mapping[str, Any]]:
    """取 trend_map 里的一条曲线。

    接口会把同一份数据按请求的 metrics_group 重复返回（0、1、3 各一份，数值完全相同），
    所以只取第一组；把各组合并会把当天的播放量算成好几倍。
    """
    if isinstance(entry, list):
        candidates: list[Any] = [entry]
    elif isinstance(entry, Mapping):
        preferred = entry.get("0")
        if isinstance(preferred, list):
            candidates = [preferred]
        else:
            candidates = [value for value in entry.values()]
    else:
        return []
    for item in candidates:
        if isinstance(item, list):
            return [point for point in item if isinstance(point, Mapping)]
        if isinstance(item, Mapping):
            return [item]
    return []


def account_rows_from_payloads(
    works_payload: Mapping[str, Any],
    fans_payload: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """把账号接口的返回转成 {报表种类: {日期: 指标}}，和导出表格解析出同一形状。"""
    work_fields = {field for field in API_METRIC_FIELDS.values() if field not in ACCOUNT_FAN_COUNT_FIELDS}
    fan_fields = set(ACCOUNT_FAN_COUNT_FIELDS)
    merged: dict[str, dict[str, Any]] = {}
    for payload, allowed in ((works_payload, work_fields), (fans_payload, fan_fields)):
        if not isinstance(payload, Mapping):
            continue
        for metric in payload.get("metrics") or []:
            if not isinstance(metric, Mapping):
                continue
            field = API_METRIC_FIELDS.get(str(metric.get("english_metric_name") or ""))
            if not field or field not in allowed:
                continue
            for point in metric.get("trends") or []:
                if not isinstance(point, Mapping):
                    continue
                day = normalize_report_date(point.get("date_time"))
                if not day:
                    continue
                if field in API_RATIO_FIELDS:
                    # 接口给 0–1 的比例，先缩放再取两位小数，避免先四舍五入再放大。
                    try:
                        value = round(float(point.get("value")) * 100, 2)
                    except (TypeError, ValueError):
                        continue
                else:
                    value = parse_report_number(point.get("value"))
                    if value is None:
                        continue
                merged.setdefault(day, {})[field] = value
    if not merged:
        return {}
    return {REPORT_ACCOUNT_WORKS: dict(sorted(merged.items()))}


def work_rows_from_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """把作品逐日接口的返回转成 {日期: 指标}。"""
    rows: dict[str, dict[str, Any]] = {}
    trend_map = payload.get("trend_map") if isinstance(payload, Mapping) else None
    if not isinstance(trend_map, Mapping):
        return rows
    for source, field in API_WORK_METRICS.items():
        for point in _trend_points(trend_map.get(source)):
            day = normalize_report_date(point.get("date_time"))
            value = parse_report_number(point.get("value"))
            if not day or value is None:
                continue
            # 同一天可能有多条（后台按小时返回）：加起来才是当天的值。
            rows.setdefault(day, {}).setdefault(field, 0)
            rows[day][field] += int(value)
    return dict(sorted(rows.items()))


def merge_work_rows(
    existing: Mapping[str, Mapping[str, Any]],
    incoming: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {day: dict(metrics) for day, metrics in existing.items()}
    for day, metrics in incoming.items():
        merged.setdefault(day, {}).update(metrics)
    return dict(sorted(merged.items()))


def fetch_account_rows(page: Any, *, days: int = REPORT_RECENT_SCOPE_DAYS) -> dict[str, dict[str, dict[str, Any]]]:
    """读取账号级的逐日数据（播放、互动、粉丝）。"""
    window = max(1, min(int(days or REPORT_RECENT_SCOPE_DAYS), REPORT_MAX_SCOPE_DAYS))
    # 接口是相对路径，且要带这个域名的 cookie：先把页面开到数据中心。
    page.goto(DOUYIN_DATA_CENTER_URL)
    _wait_for_text(page, "作品数据")
    works = fetch_json(page, f"{REVIEW_API_OVERVIEW}?recent_days={window}")
    fans = fetch_json(page, f"{REVIEW_API_OVERVIEW_FANS}?recent_days={window}")
    rows = account_rows_from_payloads(works, fans)
    if not rows:
        raise ReviewCollectionError("api_empty", "后台没有返回账号的逐日数据，稍后重试。")
    logger.info("review_account_api_ok days=%s", len(next(iter(rows.values()))))
    return rows


def item_id_from_url(url: str) -> str:
    """作品详情地址里的作品 ID。"""
    raw = str(url or "")
    index = raw.find(DOUYIN_WORK_DETAIL_MARK)
    if index < 0:
        return ""
    match = re.match(r"(\d+)", raw[index + len(DOUYIN_WORK_DETAIL_MARK):])
    return match.group(1) if match else ""


def fetch_work_rows(page: Any, item_id: str) -> dict[str, dict[str, Any]]:
    """读取一条作品的逐日播放和逐日涨粉（后台按「每天」返回）。"""
    rows: dict[str, dict[str, Any]] = {}
    for metric in API_WORK_METRICS:
        url = (
            f"{REVIEW_API_ITEM_TREND}?aid=2906&app_name=aweme_creator_platform&device_platform=web"
            f"&item_id={item_id}&trend_type=1&time_unit=1&metrics_group=0,1,3&metrics={metric}"
        )
        rows = merge_work_rows(rows, work_rows_from_payload(fetch_json(page, url)))
    return rows


def open_work_detail(page: Any, *, title: str, rounds: int = REPORT_WORK_CARD_SCROLL_ROUNDS) -> Any:
    """在内容管理里点开一条作品，返回详情页；找不到卡片时抛出可读错误。"""
    reused = str(getattr(page, "url", "")).split("?", 1)[0].rstrip("/") == DOUYIN_CONTENT_MANAGE_URL
    if not reused:
        page.goto(DOUYIN_CONTENT_MANAGE_URL)
    found = _find_work_card(page, title=title, rounds=rounds)
    if found != "ok" and reused:
        # 虚拟列表可能卸载已滚过的卡片。找不到时重新加载，保留原来的完整查找路径。
        page.goto(DOUYIN_CONTENT_MANAGE_URL)
        found = _find_work_card(page, title=title, rounds=rounds)
    if found != "ok":
        raise ReviewCollectionError("work_card_missing", "在内容管理里没有找到这条作品，稍后重试。")
    try:
        with page.context.expect_page(timeout=REPORT_PAGE_READY_TIMEOUT_MS) as waiting:
            page.locator('[data-review-work-metric="1"]').first.click()
        detail = waiting.value
    except Exception as exc:
        raise ReviewCollectionError("work_detail_unavailable", "作品详情页没有打开，稍后重试。") from exc
    try:
        detail.wait_for_load_state(state="domcontentloaded", timeout=REPORT_PAGE_READY_TIMEOUT_MS)
    except Exception:
        logger.info("review_work_detail_load_slow")
    # 详情页是前端路由：地址里的作品 ID 要等路由跳转完成才出现。
    for _ in range(int(REPORT_WORK_DETAIL_ID_TIMEOUT_MS / 500)):
        if item_id_from_url(str(getattr(detail, "url", ""))):
            break
        detail.wait_for_timeout(500)
    else:
        logger.info("review_work_detail_id_missing url=%s", str(getattr(detail, "url", ""))[:80])
    return detail


def close_page(page: Any) -> None:
    if page is None:
        return
    closed = getattr(page, "is_closed", None)
    try:
        if callable(closed) and closed():
            return
    except Exception:
        return
    close = getattr(page, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.info("review_work_detail_close_failed")


def _bring_to_front(page: Any) -> None:
    """后台标签页会被 Chrome 降速，页面渲染和接口都可能卡住；操作前先切到前台。"""
    front = getattr(page, "bring_to_front", None)
    if not callable(front):
        return
    try:
        front()
    except Exception:
        logger.info("review_bring_to_front_failed")


def _wait_for_text(page: Any, label: str, *, timeout_ms: int = REPORT_PAGE_READY_TIMEOUT_MS) -> None:
    """等关键文字渲染出来；后台页面是前端渲染，goto 返回时可能还是空壳。"""
    try:
        page.get_by_text(label, exact=True).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        logger.info(
            "review_wait_text_timeout label=%s url=%s",
            label,
            str(getattr(page, "url", ""))[:80],
        )


def _find_work_card(page: Any, *, title: str, rounds: int = REPORT_WORK_CARD_SCROLL_ROUNDS) -> str:
    """在内容管理里找到这条作品的卡片。

    列表是懒加载的：目标作品可能还没渲染出来，所以要边滚动边找，否则会把
    「还没滚到」误判成「作品不存在」。
    """
    for attempt in range(rounds):
        marked = page.evaluate(DOUYIN_MARK_WORK_SCRIPT, {"title": title})
        if marked == "ok":
            return "ok"
        if attempt == rounds - 1:
            return str(marked)
        _bring_to_front(page)
        page.evaluate(DOUYIN_SCROLL_SCRIPT)
        page.wait_for_timeout(REPORT_WORK_CARD_SCROLL_PAUSE_MS)
    return "missing"


DOUYIN_MARK_WORK_SCRIPT = r"""
(payload) => {
  const title = String((payload && payload.title) || '').trim();
  const classOf = (el) => ((el && el.className) || '').toString();
  const hasPrefix = (el, prefix) => classOf(el).split(/\s+/).some((name) => name.startsWith(prefix));
  const text = (el) => ((el && el.textContent) || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-review-work-card],[data-review-work-metric]').forEach((el) => {
    el.removeAttribute('data-review-work-card');
    el.removeAttribute('data-review-work-metric');
  });
  const cards = [...document.querySelectorAll('div')].filter(
    (el) => hasPrefix(el, 'video-card-') && !(el.parentElement && hasPrefix(el.parentElement, 'video-card-')),
  );
  const card = cards.find((item) => {
    const node = [...item.querySelectorAll('*')].find((child) => hasPrefix(child, 'info-title-text-'));
    const label = text(node) || text(item);
    return label === title || (label && label.includes(title));
  });
  if (!card) return 'missing';
  const value = [...card.querySelectorAll('*')].find(
    (el) => hasPrefix(el, 'metric-value-') && text(el) && text(el) !== '-',
  );
  if (!value) return 'no-metric';
  card.setAttribute('data-review-work-card', '1');
  value.setAttribute('data-review-work-metric', '1');
  return 'ok';
}
"""


# ----------------------------------------------------------------------
# 后台导出的表格（历史留档与人工核对）
# ----------------------------------------------------------------------


def _load_sheets(path: Path) -> dict[str, list[list[Any]]]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确原因
        raise ReviewCollectionError(
            "report_parser_unavailable",
            "缺少 openpyxl，无法解析抖音导出的表格。",
        ) from exc
    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise ReviewCollectionError("report_unreadable", "导出的表格无法打开。") from exc
    try:
        return {str(sheet.title): [list(row) for row in sheet.iter_rows(values_only=True)] for sheet in workbook.worksheets}
    finally:
        workbook.close()


def _header_map(row: Iterable[Any]) -> dict[str, int]:
    return {_text(cell): index for index, cell in enumerate(row) if _text(cell)}


def _account_columns(header: Mapping[str, int], mapping: Mapping[str, str]) -> dict[str, int]:
    return {field: header[label] for label, field in mapping.items() if label in header}


def _trend_columns(header: Mapping[str, int], total_label: str) -> dict[str, int]:
    total, platform_a, platform_b = WORK_TREND_COLUMNS[total_label]
    columns = {total: header[total_label]}
    if "抖音" in header:
        columns[platform_a] = header["抖音"]
    if "抖音精选" in header:
        columns[platform_b] = header["抖音精选"]
    return columns


def _collect_daily_rows(rows: Iterable[list[Any]], columns: Mapping[str, int]) -> dict[str, dict[str, Any]]:
    daily: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row:
            continue
        day = normalize_report_date(row[0] if row else "")
        if not day:
            continue
        metrics: dict[str, Any] = {}
        for field, column in columns.items():
            if column >= len(row):
                continue
            metrics[field] = parse_report_number(row[column])
        if not metrics:
            continue
        if day in daily:
            for field, value in metrics.items():
                if daily[day].get(field) is None:
                    daily[day][field] = value
        else:
            daily[day] = metrics
    return daily


def read_report(path: Path) -> dict[str, Any]:
    """解析一份后台导出的表格，返回 {kind, sheet, rows}。

    rows 是 {业务日期: {字段: 数值}}；只有后台给出数值的日期才有值，
    缺少的单元格保持 None，不会被当成 0。
    """
    sheets = _load_sheets(path)
    for title, rows in sheets.items():
        if "趋势数据" not in title or "每小时" in title or not rows:
            continue
        for total_label in WORK_TREND_COLUMNS:
            if total_label not in title:
                continue
            columns = _trend_columns(_header_map(rows[0]), total_label)
            if not columns:
                break
            kind = REPORT_WORK_VIEWS if total_label == "播放量" else REPORT_WORK_FANS
            return {"kind": kind, "sheet": title, "rows": _collect_daily_rows(rows[1:], columns)}
    for title, rows in sheets.items():
        if not rows:
            continue
        header = _header_map(rows[0])
        if "总播放量" in header:
            return {
                "kind": REPORT_ACCOUNT_WORKS,
                "sheet": title,
                "rows": _collect_daily_rows(rows[1:], _account_columns(header, ACCOUNT_WORK_COLUMNS)),
            }
        if "总粉丝量" in header:
            return {
                "kind": REPORT_ACCOUNT_FANS,
                "sheet": title,
                "rows": _collect_daily_rows(rows[1:], _account_columns(header, ACCOUNT_FAN_COLUMNS)),
            }
    raise ReviewCollectionError("report_unrecognized", "无法识别这份导出表格，请确认它来自抖音后台。")
