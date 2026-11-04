"""抖音数据采集的接入层：监控与雷达统一走创作服务平台的 /workbench/v1。

监控与雷达原先直连供应商接口，现在统一走 ``POST /workbench/v1/data/query``：

* 用 ``capability`` 区分七类能力，一次查询就是一页、就是一个计费单位；
* 分页用平台下发的不透明游标，不再透传供应商的 ``max_cursor``；
* 字段是平台归一化后的稳定结构（``items[]`` 含 id/desc/createTime/cover/author/statistics，
  统计字段缺失就是 None），所以这里不再假设 ``aweme_list`` / ``business_data`` 的嵌套；
* 空结果是有效查询并照常计费，不能显示成错误；
* 游标失效返回 ``invalid_cursor``，要明确提示重新查询，不从第一页静默重跑。

上游供应商凭据与采购价全部留在平台侧：本模块不持有任何 Key，用当前登录用户的
会话凭证计价，积分是否足够与应该扣多少一律由平台判定。
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from . import workbench
from .subscription import SubscriptionError, SubscriptionService

logger = logging.getLogger("douyin-downloader")

# 数据能力取值，与平台 /v1/services 的 data.capabilityCodes 一致。
CAPABILITY_PROFILE = "profile"
CAPABILITY_POSTS = "posts"
CAPABILITY_VIDEO = "video"
CAPABILITY_SEARCH = "search"
CAPABILITY_LOW_FANS = "low_fans"
CAPABILITY_TRENDS = "trends"
CAPABILITY_SUGGESTIONS = "suggestions"

# 需要翻页时，平台游标放在查询参数之外单独传，参数里不再出现供应商游标名。
_SERVER_FIELDS = ("play_count", "comment_count", "digg_count", "share_count", "collect_count", "follower_count")


class PlatformDataError(Exception):
    """对外可读的数据查询失败；code 已收敛，message 不含平台内部原文。"""

    def __init__(self, code: str, message: str = "", *, status_code: Optional[int] = None,
                 needs_subscription: bool = False):
        super().__init__(message or "数据查询失败，请稍后重试。")
        self.code = code
        self.message = message or "数据查询失败，请稍后重试。"
        self.status_code = status_code
        self.needs_subscription = bool(needs_subscription)


class RoundUsage:
    """一轮采集的用量：总请求数 + 已消耗 / 已冻结积分。

    一轮监控/雷达可能包含多次调用，界面按这两个数汇总展示，而不是伪装成一个固定价格。
    积分口径与平台一致：不用人民币折算，也不在本地缓存余额。
    """

    def __init__(self) -> None:
        self.requests = 0
        self._charged = Decimal("0")
        self._frozen = Decimal("0")

    def add(self, charged: Any = None, *, frozen: Any = None, requests: int = 1) -> None:
        self.requests += max(0, int(requests))
        self._charged += _decimal(charged)
        self._frozen += _decimal(frozen)

    @property
    def chargedPoints(self) -> str:
        return _points(self._charged)

    @property
    def frozenPoints(self) -> str:
        return _points(self._frozen)

    def view(self) -> "dict[str, Any]":
        return {
            "requests": self.requests,
            "chargedPoints": self.chargedPoints,
            "frozenPoints": self.frozenPoints,
        }

    def __iadd__(self, other: "RoundUsage") -> "RoundUsage":
        self.requests += other.requests
        self._charged += other._charged
        self._frozen += other._frozen
        return self


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - 缺字段或格式异常都按 0 计
        return Decimal("0")


def _points(value: Decimal) -> str:
    """积分统一成三位定点文本，与平台口径一致。"""
    try:
        return str(value.quantize(Decimal("0.001")))
    except InvalidOperation:  # pragma: no cover - Decimal 已在上游收敛
        return "0.000"


class PlatformDataClient:
    """把一次数据查询跑成「提交 → 轮询 → 取结果」，并回报本次消耗的积分。"""

    def __init__(self, service: SubscriptionService):
        self._service = service
        self.business_context: dict[str, Any] = {}

    @classmethod
    def from_settings(cls, settings: Any, *, store: Any) -> "PlatformDataClient":
        return cls(SubscriptionService(store, settings))

    async def query(self, capability: str, params: "Mapping[str, Any] | None" = None,
                    *, cursor: Optional[str] = None) -> "dict[str, Any]":
        """查询一页。返回 ``{page, taskId, chargedPoints, frozenPoints}``；失败抛 PlatformDataError。"""
        try:
            outcome = await workbench.query_data(self._service, capability, params, cursor=cursor,
                **({"business_context": dict(self.business_context)} if self.business_context else {}))
        except SubscriptionError as exc:
            raise _from_subscription_error(exc) from None
        return {
            "page": outcome.get("page") if isinstance(outcome.get("page"), Mapping) else {},
            "taskId": str(outcome.get("taskId") or ""),
            "chargedPoints": str(outcome.get("chargedPoints") or ""),
            "frozenPoints": str(outcome.get("frozenPoints") or ""),
        }


def _from_subscription_error(exc: SubscriptionError) -> PlatformDataError:
    return PlatformDataError(exc.code, exc.message, status_code=exc.status_code,
                             needs_subscription=exc.needs_subscription)


def page_items(page: "Mapping[str, Any] | None") -> "list[dict[str, Any]]":
    """平台归一化后的作品列表；空结果返回空数组，不是错误。"""
    rows = (page or {}).get("items")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def next_cursor(page: "Mapping[str, Any] | None") -> str:
    """平台的不透明游标；没有下一页时为空。"""
    if not (page or {}).get("hasMore"):
        return ""
    return str((page or {}).get("cursor") or "")


# ---------------------------------------------------------------- 字段适配
# 平台给的是稳定字段；下面的适配把一条记录还原成工作台内部既有的形状，
# 这样监控/雷达的规范化、去重与快照逻辑可以原样保留。

def _url_list(value: Any) -> "dict[str, list[str]] | None":
    text = str(value or "").strip()
    return {"url_list": [text]} if text else None


def _statistics(stats: Any) -> "dict[str, Any]":
    source = stats if isinstance(stats, Mapping) else {}
    return {key: source.get(key) for key in _SERVER_FIELDS}


def posts_item_to_aweme(item: "Mapping[str, Any]") -> "dict[str, Any]":
    """作品列表/搜索条目 → 工作台内部的作品结构。"""
    author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
    cover = str(item.get("cover") or "").strip()
    duration = item.get("duration")
    return {
        "aweme_id": str(item.get("id") or ""),
        "desc": str(item.get("desc") or ""),
        "create_time": item.get("createTime"),
        "share_url": str(item.get("shareUrl") or ""),
        "video": {
            "duration": duration,
            "cover": _url_list(cover),
        },
        "author": {
            "sec_uid": str(author.get("secUid") or ""),
            "uid": str(author.get("uid") or ""),
            "nickname": str(author.get("nickname") or ""),
            "unique_id": str(author.get("uniqueId") or ""),
            "follower_count": author.get("followerCount"),
        },
        "statistics": _statistics(item.get("statistics")),
    }


def profile_to_user(profile: "Mapping[str, Any] | None") -> "dict[str, Any]":
    """博主资料 → 工作台内部的用户结构。"""
    node = profile if isinstance(profile, Mapping) else {}
    stats = node.get("statistics") if isinstance(node.get("statistics"), Mapping) else {}
    avatar = str(node.get("avatar") or "").strip()
    return {
        "sec_uid": str(node.get("secUid") or ""),
        "uid": str(node.get("uid") or ""),
        "unique_id": str(node.get("uniqueId") or ""),
        "nickname": str(node.get("nickname") or ""),
        "signature": str(node.get("signature") or ""),
        "avatar_larger": _url_list(avatar),
        "follower_count": stats.get("followerCount"),
        "following_count": stats.get("followingCount"),
        "aweme_count": stats.get("awemeCount"),
        "total_favorited": stats.get("totalFavorited"),
    }


def low_fans_item_to_row(item: "Mapping[str, Any]") -> "dict[str, Any]":
    """低粉爆款条目 → 工作台内部的扁平结构。"""
    author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
    tags = item.get("tags") if isinstance(item.get("tags"), Mapping) else {}
    return {
        "itemId": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "thumbnail": str(item.get("cover") or ""),
        "likes": item.get("likes"),
        "duration": item.get("duration"),
        "createTime": item.get("createTime"),
        "nickname": str(author.get("nickname") or ""),
        "avatarUrl": str(author.get("avatar") or ""),
        "fans": item.get("fans"),
        "isLowFansButHot": tags.get("lowFansButHot"),
        "isHighLikeRate": tags.get("highLikeRate"),
        "isHighPlayOverRate": tags.get("highPlayOverRate"),
        "isHighFansRiseRate": tags.get("highFansRiseRate"),
    }


def trends_to_rows(page: "Mapping[str, Any] | None") -> "list[dict[str, Any]]":
    """热度飙升榜 → 雷达直接入库的行结构（keyword / score / trends 标签）。"""
    rows: "list[dict[str, Any]]" = []
    for entry in page_items(page):
        word = str(entry.get("word") or "").strip()
        if not word:
            continue
        points = entry.get("trend")
        labels = []
        if isinstance(points, list):
            for point in points:
                if isinstance(point, Mapping):
                    label = str(point.get("label") or "").strip()
                    if label:
                        labels.append(label)
                elif point:
                    labels.append(str(point))
        rows.append({"keyword": word[:60], "score": entry.get("score"), "trends": labels})
    return rows


def suggestion_words(page: "Mapping[str, Any] | None") -> "list[str]":
    words = (page or {}).get("words")
    if not isinstance(words, list):
        return []
    return [str(word).strip() for word in words if str(word or "").strip()]
