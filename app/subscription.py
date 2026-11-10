"""工作台订阅与积分接入层。

与平台 ``/workbench/v1`` 契约对应，契约见
工作台订阅积分接口契约。

两条数据通路，对外方法完全相同：

* ``live``：调用创作服务 API 平台的 /workbench/v1，鉴权用当前登录用户凭证；
* ``mock``：本地模拟账本，供平台接口就绪前后端联调与演示使用。

约定与 ``creation_service`` 保持一致：成功取 data，失败收敛成 SubscriptionError；
平台 message 只进日志，对外只给本模块定义的中文文案。
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import io

import hashlib
import json
import logging
import os
import re
import time
import uuid
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Optional

import qrcode
import qrcode.image.svg

if TYPE_CHECKING:  # 只为类型标注导入，避免与 settings 形成循环导入
    from .settings import AppSettings

logger = logging.getLogger("douyin-downloader")

API_PREFIX = "/workbench/v1"
DEFAULT_PLATFORM_MODE = "mock"
PLATFORM_MODES = ("mock", "live")

# 积分最小单位 0.001；一律用定点十进制字符串进出，不经过浮点数。
POINT_QUANTUM = Decimal("0.001")
CN_TZ = timezone(timedelta(hours=8))

# 支付渠道：接口一律用渠道标识，中文文案由工作台按标识渲染。
PAY_CHANNEL_IDS: "dict[str, str]" = {"微信支付": "wechat", "支付宝": "alipay"}
PAY_CHANNEL_IDS_BY_ID = {value: value for value in PAY_CHANNEL_IDS.values()}

PLAN_CATALOG: "tuple[dict[str, Any], ...]" = (
    {"planId": "basic", "name": "基础版", "priceCents": 6990, "points": "699.000"},
    {"planId": "pro", "name": "专业版", "priceCents": 9900, "points": "990.000"},
    {"planId": "pro_plus", "name": "高级版", "priceCents": 19900, "points": "1990.000"},
)

PLAN_PRICE_VERSION = "pricing-v1"

# 工作台已确认的功能权益，三档一致，仅价格与积分不同。
PLAN_ENTITLEMENTS: "tuple[str, ...]" = (
    "全部现有工作台功能",
    "不额外限制创作账号数量",
)

PLAN_CAPABILITIES: "tuple[str, ...]" = (
    "内容采集",
    "行业关键词",
    "监控对标博主",
    "AI 选题推荐",
    "音视频转文案",
    "拆解视频",
    "脚本生成与仿写",
    "生成标题",
    "生成封面",
    "数据复盘分析",
)

# 业务计费规格：单价为积分，mock 结算与报价共用。
POINT_SPECS: "dict[str, dict[str, str]]" = {
    "svc.cover_image": {"name": "封面生成", "unit": "张", "pointsPerUnit": "6.000"},
    "svc.transcription": {"name": "音视频转文案", "unit": "分钟", "pointsPerUnit": "2.000"},
    "svc.data_query": {"name": "数据采集", "unit": "次", "pointsPerUnit": "0.200"},
    "svc.text_generate": {"name": "文本生成", "unit": "次", "pointsPerUnit": "1.000"},
}

# 工作台对外文案：平台错误码 -> 中文提示。绝不透传平台原文。
PUBLIC_ERROR_MESSAGES: "dict[str, str]" = {
    "redemption_invalid": "兑换码无效，请检查后重试。",
    "wechat_not_configured": "微信支付尚未配置完成，请联系运营方。",
    "wechat_pending": "渠道结果尚未确认，将继续查询原订单。",
    "wechat_busy": "渠道正在处理，请稍候查询原订单。",
    "wechat_legacy_order": "历史订单没有真实支付记录，请先处理原订单。",
    "unsupported_channel": "该支付渠道暂未开放。",
    "not_found": "订单不存在或不属于当前账户。",
    "redemption_used": "该兑换码已使用。",
    "redemption_expired": "该兑换码已过期。",
    "redemption_revoked": "该兑换码已作废。",
    "redemption_plan_mismatch": "兑换码与所选套餐不匹配，请选择对应套餐。",
    "plan_unavailable": "该套餐已下架，暂时无法兑换。",
    "plan_changed": "套餐权益已更新，请重新预览并确认。",
    "unfinished_order": "存在未完成订单，请先查看并处理该订单后重试。",
    "redemption_unavailable": "兑换码状态已变化，请重新检查。",
    "idempotency_key_required": "缺少有效请求标识，请重新预览。",
    "validation_error": "兑换参数有误，请检查后重新预览。",
    "unauthorized": "请先登录后再使用该功能。",
    "session_revoked": "登录已失效，请重新登录。",
    "account_disabled": "账号已停用，请联系客服。",
    "permission_denied": "当前账号没有该能力权限。",
    "subscription_required": "需要先订阅套餐后使用该功能。",
    "subscription_expired": "订阅已到期，请重新订阅后使用。",
    "insufficient_points": "积分不足，请先订阅套餐。",
    "quote_changed": "价格已更新，请重新发起。",
    "charge_limit_exceeded": "本次费用上限低于预计费用。",
    "idempotency_conflict": "请求标识已用于其他内容，请重新发起。",
    "rate_limited": "请求过于频繁，请稍后重试。",
    # 短信与登录：平台在这些场景会返回明确原因，不能统一压成“服务不可用”。
    "invalid_phone": "请输入 11 位有效手机号。",
    "invalid_code_format": "请输入收到的验证码。",
    "sms_code_invalid": "验证码不正确，请重新输入。",
    "sms_code_expired": "验证码已失效，请重新获取。",
    "sms_code_locked": "验证码错误次数过多，请重新获取。",
    "sms_rate_limited": "短信发送过于频繁，请稍后再试。",
    "sms_template_invalid": "短信签名或模板配置有误，请联系运营方。",
    "sms_channel_unavailable": "短信服务暂时不可用，请稍后再试。",
    "sms_send_failed": "验证码发送失败，请稍后再试。",
    "image_generation_timeout": "生成超过 30 分钟，可重新生成。",
    "status_pending": "任务结果待确认，请稍后继续查询。",
    "result_expired": "成果已过保留期，需要重新发起。",
    "unsupported_input": "不支持该输入，请检查内容后重试。",
    "invalid_cursor": "分页游标已失效，请重新发起一次查询。",
    "content_unavailable": "该内容暂时无法获取，请更换后重试。",
    "media_link_expired": "媒体链接已失效，请重新解析（将按次计费）。",
    "upstream_unavailable": "创作服务暂时不可用，请稍后重试。",
    "unreachable": "无法连接创作服务，请确认服务已启动后重试。",
    "timeout": "创作服务响应超时，正在继续确认结果，请稍后重试。",
    # 付费能力统一走真实平台：模拟通路只用于账户页演示，不承接任何计费调用。
    "platform_mode_required": "当前为模拟通路，付费能力需要切换到真实创作服务平台后使用。",
    "service_unavailable": "创作服务平台尚未开放此能力或未配置有效价格，请联系平台管理员。",
    "task_cancelled": "任务已取消。",
}

# 需要弹出订阅入口的错误码：工作台只在积分或订阅不足时打断用户。
SUBSCRIBE_HINTS = ("subscription_required", "subscription_expired", "insufficient_points")

# 即使本地会话还在，平台也会拒绝失效的凭证：这两类错误要求重新登录。
RELOGIN_CODES = ("unauthorized", "session_revoked")
# 工作台对外口径：当这些错误落盘时用它标记，前端据此渲染可点击的「登录已失效，请重新登录」。
NEEDS_RELOGIN = "needs_relogin"

_STATUS_BY_CODE = {
    "unauthorized": 401,
    "session_revoked": 401,
    "account_disabled": 403,
    "permission_denied": 403,
    "subscription_required": 402,
    "subscription_expired": 402,
    "insufficient_points": 402,
    "charge_limit_exceeded": 402,
    "quote_changed": 409,
    "idempotency_conflict": 409,
    "rate_limited": 429,
    "result_expired": 410,
    "invalid_cursor": 400,
    "unreachable": 503,
    "timeout": 504,
    "upstream_unavailable": 502,
    "platform_mode_required": 409,
    "service_unavailable": 503,
    "task_cancelled": 409,
}


from .upstream_errors import public_details


class SubscriptionError(Exception):
    """对外安全的订阅/积分错误：code 与 message 均已脱敏。"""

    def __init__(self, code: str, message: str = "", *, status_code: Optional[int] = None,
                 platform_code: Optional[str] = None, details: Optional[Mapping[str, Any]] = None):
        resolved = message or PUBLIC_ERROR_MESSAGES.get(code) or "订阅服务调用失败，请稍后重试。"
        super().__init__(resolved)
        self.code = code
        self.message = resolved
        self.status_code = status_code or _STATUS_BY_CODE.get(code, 502)
        self.platform_code = platform_code or code
        self.details = public_details(details)

    @property
    def needs_subscription(self) -> bool:
        return self.code in SUBSCRIBE_HINTS

    def public_payload(self) -> "dict[str, Any]":
        payload: "dict[str, Any]" = {"code": self.code, "message": self.message}
        if self.needs_subscription:
            payload["needsSubscription"] = True
        if self.details:
            payload["details"] = public_details(self.details)
        return payload


def public_error_code(code: object) -> str:
    text = str(code or "").strip()
    return text if text in PUBLIC_ERROR_MESSAGES else "upstream_unavailable"


def points(value: object) -> Decimal:
    """把接口值解析成定点积分；非法值归零，避免脏数据污染余额。"""
    try:
        return Decimal(str(value).strip() or "0").quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.000")


def points_text(value: object) -> str:
    return str(points(value))


def charge_points(unit_price: object, units: object) -> Decimal:
    """按「单价 × 数量」向上取整到 0.001，只在最终结果舍入一次。

    单价先归到 0.001 精度：正单价不能被量化成 0，否则会把付费能力静默变成免费。
    """
    try:
        count = Decimal(str(units).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        count = Decimal("0")
    if count <= 0:
        return Decimal("0.000")
    unit = points(unit_price)
    if unit <= 0:
        try:
            raw = Decimal(str(unit_price).strip() or "0")
        except (InvalidOperation, ValueError, TypeError):
            raw = Decimal("0")
        if raw <= 0:
            return Decimal("0.000")
        unit = POINT_QUANTUM
    return (unit * count).quantize(POINT_QUANTUM, rounding=ROUND_CEILING)


def mask_phone(value: object) -> str:
    """对外只展示中间四位打码的手机号。"""
    text = str(value or "").strip()
    if len(text) < 7:
        return text
    return text[:3] + "****" + text[-4:]


def is_valid_phone(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 11 and text.isdigit() and text.startswith("1")


def pay_channel_id(value: object) -> str:
    """把中文支付方式或渠道标识统一成接口用的渠道标识；无法识别时返回空串。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return PAY_CHANNEL_IDS.get(text) or PAY_CHANNEL_IDS_BY_ID.get(text, "")


def _now_text() -> str:
    """本地时间的 ISO 8601 文本，按北京时间。"""
    return datetime.now(CN_TZ).replace(microsecond=0).isoformat()


def normalize_platform_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in PLATFORM_MODES else DEFAULT_PLATFORM_MODE


def plan_view(plan: Mapping[str, Any]) -> "dict[str, Any]":
    """把套餐目录补全成工作台展示结构，价格与积分只由平台决定。"""
    price_cents = int(plan.get("priceCents") or 0)
    return {
        "planId": str(plan.get("planId") or ""),
        "name": str(plan.get("name") or ""),
        "priceCents": price_cents,
        "priceText": "%d.%02d" % (price_cents // 100, price_cents % 100),
        "points": points_text(plan.get("points")),
        "periodType": "natural_month",
        "status": "on_sale",
        "version": PLAN_PRICE_VERSION,
        "entitlements": list(PLAN_ENTITLEMENTS),
        "capabilities": list(PLAN_CAPABILITIES),
    }


def plans_view() -> "dict[str, Any]":
    return {"items": [plan_view(plan) for plan in PLAN_CATALOG], "priceVersion": PLAN_PRICE_VERSION}


def find_plan(plan_id: object) -> "dict[str, Any]":
    wanted = str(plan_id or "").strip()
    for plan in PLAN_CATALOG:
        if plan["planId"] == wanted:
            return plan
    raise SubscriptionError("unsupported_input", "选择的套餐不存在，请刷新后重试。", status_code=400)


# --------------------------------------------------------------------- 本地存储

class SubscriptionStore:
    """登录态与演示账本的本地存储。

    只保存会话与模拟账本；真实模式下余额一律来自平台，不在此缓存。
    文件权限 0600，与 .env 一致。
    """

    def __init__(self, workspace: Path):
        self._path = Path(workspace) / "subscription.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> "dict[str, Any]":
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("subscription_store_read_failed")
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name("." + self._path.name + ".tmp")
        temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self._path)
        os.chmod(self._path, 0o600)

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            return


# --------------------------------------------------------------------- 模拟通路

MOCK_CODE = "123456"
MOCK_PERIOD_START = "2026-09-27T15:30:00+08:00"
MOCK_PERIOD_END = "2026-10-27T15:30:00+08:00"

# 模拟账本的初始数据：数值与已确认界面一致，且各条流水能对上余额。
# 990 - 283.3 - 12 - 0.2 = 694.5（已消耗）；再冻结 12 作为在途任务。
MOCK_SEED_AVAILABLE = "682.500"
MOCK_SEED_FROZEN = "12.000"
MOCK_SEED_PLAN_ID = "pro"
MOCK_SEED_ORDER_ID = "WB0927002"
MOCK_SEED_LEDGER: "tuple[dict[str, Any], ...]" = (
    {"id": "PL-SEED-0001", "type": "grant", "status": "done", "pointsChange": "+990.000",
     "createdAt": "2026-09-27T15:30:00+08:00", "business": "专业版订阅", "businessCode": "plan_grant",
     "refType": "order", "refId": MOCK_SEED_ORDER_ID},
    {"id": "PL-SEED-0002", "type": "settle", "status": "done", "pointsChange": "-0.200",
     "createdAt": "2026-09-27T16:05:00+08:00", "business": "数据采集", "businessCode": "svc.data_query",
     "refType": "task", "refId": "T-1023"},
    {"id": "PL-SEED-0003", "type": "settle", "status": "done", "pointsChange": "-12.000",
     "createdAt": "2026-09-27T16:20:00+08:00", "business": "封面生成", "businessCode": "svc.cover_image",
     "refType": "task", "refId": "T-1024"},
    {"id": "PL-SEED-0004", "type": "settle", "status": "done", "pointsChange": "-283.300",
     "createdAt": "2026-09-27T16:32:00+08:00", "business": "音视频转文案", "businessCode": "svc.transcription",
     "refType": "task", "refId": "T-1026"},
    # 冻结中的流水：只是把额度先占住，最终按任务结果结算。
    {"id": "PL-SEED-0005", "type": "freeze", "status": "processing", "pointsChange": "-12.000",
     "createdAt": "2026-09-27T16:18:00+08:00", "business": "封面生成", "businessCode": "svc.cover_image",
     "refType": "task", "refId": "T-1025"},
)


class MockPlatform:
    """本地模拟平台：形状与契约一致，供前端联调与演示。

    不发送短信、不生成真实支付订单、不调用真实上游。
    """

    def __init__(self, session: "dict[str, Any]", ledger: "list[dict[str, Any]]", orders: "list[dict[str, Any]]",
                 *, seeded: bool = False):
        self.session = session
        self.ledger = ledger
        self.orders = orders
        # 读取时若发现演示账本缺失，调用方据此把补种结果写回本地。
        self.seeded = seeded

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "MockPlatform":
        mock = state.get("mock") if isinstance(state.get("mock"), Mapping) else {}
        ledger = mock.get("ledger") if isinstance(mock.get("ledger"), list) else []
        orders = mock.get("orders") if isinstance(mock.get("orders"), list) else []
        session = mock.get("session") if isinstance(mock.get("session"), Mapping) else {}
        platform = cls(dict(session), [dict(item) for item in ledger], [dict(item) for item in orders])
        # 升级到带演示数据的版本后，已登录的旧本地状态要补一次，否则列表会一直是空的。
        if platform.logged_in() and not platform.ledger:
            platform.seed_demo_data()
            platform.seeded = True
        if platform.logged_in():
            before = json.dumps(platform.dump(), sort_keys=True)
            platform.refresh_batches()
            platform.seeded |= before != json.dumps(platform.dump(), sort_keys=True)
        return platform

    def dump(self) -> "dict[str, Any]":
        return {"session": self.session, "ledger": self.ledger, "orders": self.orders}

    def seed_demo_data(self) -> None:
        """按已确认界面补一份能对账的演示账本与订单。"""
        # 列表按时间倒序展示，最新的在最上面。
        ordered = sorted(MOCK_SEED_LEDGER, key=lambda entry: str(entry.get("createdAt") or ""), reverse=True)
        self.ledger = [self._seed_entry(entry) for entry in ordered]
        self.orders = [{
            "orderId": MOCK_SEED_ORDER_ID,
            "status": "paid",
            "planId": MOCK_SEED_PLAN_ID,
            "planName": "专业版",
            "priceCents": 9900,
            "points": "990.000",
            "createdAt": MOCK_PERIOD_START,
            "paidAt": "2026-09-27T15:30:12+08:00",
            "payChannel": "wechat",
        }]

    # -- 会话

    def logged_in(self) -> bool:
        return bool(self.session.get("accessToken"))

    def require_session(self) -> "dict[str, Any]":
        if not self.logged_in():
            raise SubscriptionError("unauthorized")
        return self.session

    def start_session(self, phone: str, *, registered: bool) -> "dict[str, Any]":
        self.session = {
            "accessToken": "mock-" + uuid.uuid4().hex,
            "refreshToken": "mockr-" + uuid.uuid4().hex,
            "phone": mask_phone(phone),
            "status": "active",
            "registered": registered,
            "subscription": {
                "status": "active",
                "planId": MOCK_SEED_PLAN_ID,
                "planName": "专业版",
                "periodStart": MOCK_PERIOD_START,
                "currentPeriodEnd": MOCK_PERIOD_END,
                "periodPoints": "990.000",
            },
            "points": {"available": MOCK_SEED_AVAILABLE, "frozen": MOCK_SEED_FROZEN},
        }
        # 登录即刻给演示账本一份可对账的初始数据：新记录在前，与列表顺序一致。
        self.seed_demo_data()
        self.seeded = True
        self.refresh_batches()
        return self.session

    @staticmethod
    def _seed_entry(entry: Mapping[str, Any]) -> "dict[str, Any]":
        seeded = dict(entry)
        seeded.setdefault("periodStart", MOCK_PERIOD_START)
        seeded.setdefault("priceVersion", PLAN_PRICE_VERSION)
        return seeded

    def end_session(self) -> None:
        self.session = {}

    @staticmethod
    def _batch_time(value: object) -> datetime:
        """Legacy mock timestamps without an offset are Beijing local time."""
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=CN_TZ)).astimezone(CN_TZ)

    @classmethod
    def _batch_sort_key(cls, cycle: Mapping[str, Any]) -> tuple:
        # Missing creation timestamps sort first; IDs resolve equal timestamps.
        created = datetime.min.replace(tzinfo=CN_TZ)
        for key in ("createdAt", "startedAt"):
            try:
                created = cls._batch_time(cycle.get(key))
                break
            except (ValueError, TypeError):
                pass
        return cls._batch_time(cycle["expiresAt"]), created, str(cycle.get("id") or "")

    def refresh_batches(self) -> None:
        """Migrate only the remaining balance; historical grants are never replayed."""
        balance = self.session.setdefault("points", {})
        subscription = self.session.get("subscription") or {}
        cycles = balance.setdefault("cycles", [])
        if not self.session.get("batchesInitialized"):
            if not any(c.get("source", "subscription") != "trial_gift" for c in cycles):
                remaining = points(balance.get("subscriptionAvailable",
                                   points(balance.get("available")) - points(balance.get("trialAvailable"))))
                cycles.append({"id": "legacy-subscription", "source": "subscription",
                               "status": subscription.get("status", "expired"),
                               "planName": subscription.get("planName", ""),
                               "startedAt": subscription.get("periodStart", ""),
                               "expiresAt": subscription.get("currentPeriodEnd", ""),
                               "granted": subscription.get("periodPoints", "0.000"),
                               "available": points_text(max(remaining, Decimal(0)))})
            self.session["batchesInitialized"] = True
        trial_cycles = [c for c in cycles if c.get("source") == "trial_gift"]
        if not any(c.get("available") is not None for c in trial_cycles):
            dated_trials = []
            for cycle in trial_cycles:
                try:
                    dated_trials.append((self._batch_time(cycle.get("expiresAt")), cycle))
                except (ValueError, TypeError):
                    pass
            if dated_trials:
                # A legacy summary with known expiry must join global ordering.
                # If multiple metadata rows exist, use the earliest known deadline
                # rather than inventing an allocation that extends its validity.
                _, earliest = min(dated_trials, key=lambda item: item[0])
                cycles.append({**earliest, "id": "legacy-trial-summary",
                               "available": points_text(balance.get("trialAvailable"))})
        now = self._batch_time(_now_text())
        for cycle in cycles:
            cycle.setdefault("status", "active")
            cycle.setdefault("source", "subscription")
            if not cycle.get("createdAt") and cycle.get("startedAt"):
                cycle["createdAt"] = cycle["startedAt"]
            for key in ("expiresAt", "startedAt", "createdAt"):
                if cycle.get(key):
                    try:
                        cycle[key] = self._batch_time(cycle[key]).isoformat()
                    except (ValueError, TypeError):
                        pass
            # Legacy trial summaries without per-batch balances stay summary-based.
            if cycle.get("available") is None:
                continue
            remaining = points(cycle["available"])
            try:
                expired = self._batch_time(cycle.get("expiresAt", "")) <= now
            except (ValueError, TypeError):
                expired = True
            if expired and cycle.get("status", "active") == "active":
                cycle["status"] = "expired"
                cycle["available"] = "0.000"
                if remaining > 0:
                    entry = self.add_entry(kind="expire", change=-remaining, business="周期结束失效",
                                           business_code="period_expire", ref_id=str(cycle.get("id", "")))
                    entry.update(cycleId=cycle.get("id"), periodStart=cycle.get("startedAt", ""), refType="cycle")
        self._sum_batches()
        try:
            if self._batch_time(subscription.get("currentPeriodEnd", "")) <= now:
                subscription["status"] = "expired"
        except (ValueError, TypeError):
            pass

    def _sum_batches(self) -> None:
        balance = self.session["points"]
        cycles = balance["cycles"]
        def total(source: str) -> Decimal:
            return sum((points(c.get("available")) for c in cycles
                        if c.get("source", "subscription") == source and c.get("status", "active") == "active"), Decimal(0))
        balance["subscriptionAvailable"] = points_text(total("subscription"))
        if any(c.get("source") == "trial_gift" and c.get("available") is not None for c in cycles):
            balance["trialAvailable"] = points_text(total("trial_gift"))
        balance["available"] = points_text(total("subscription") + points(balance.get("trialAvailable")))

    def subscription_view(self) -> "dict[str, Any]":
        """当前订阅视图；expiringPoints 只包含当前周期的可用积分。"""
        self.require_session()
        subscription = dict(self.session.get("subscription") or {})
        balance = self.session.get("points") or {}
        subscription["expiringPoints"] = points_text(sum((points(c.get("available"))
            for c in balance.get("cycles", []) if c.get("source", "subscription") == "subscription"
            and c.get("status", "active") == "active"
            and (c.get("id") == subscription["cycleId"] if subscription.get("cycleId")
                 else c.get("startedAt") == subscription.get("periodStart"))), Decimal(0)))
        subscription["autoRenew"] = False
        return subscription

    # -- 账本

    def add_entry(self, *, kind: str, change: Decimal, business: str, business_code: str,
                  ref_id: str, status: str = "done") -> "dict[str, Any]":
        entry = {
            "id": "PL-" + uuid.uuid4().hex[:8].upper(),
            "type": kind,
            "status": status,
            "pointsChange": (("+" if change > 0 else "") + str(change)) if change != 0 else "0.000",
            "createdAt": _now_text(),
            "business": business,
            "businessCode": business_code,
            "refType": "task",
            "refId": ref_id,
            "periodStart": (self.session.get("subscription") or {}).get("periodStart", MOCK_PERIOD_START),
            "priceVersion": PLAN_PRICE_VERSION,
        }
        self.ledger.insert(0, entry)
        return entry

    def spend(self, spec_id: str, units: object, *, ref_id: str) -> "dict[str, Any]":
        """模拟一次计费业务：可用积分包含体验额度，成功后写结算流水。"""
        self.require_session()
        self.refresh_batches()
        spec = POINT_SPECS.get(spec_id)
        if spec is None:
            raise SubscriptionError("unsupported_input", "未知的计费项目。", status_code=400)
        required = charge_points(spec["pointsPerUnit"], units)
        available = points((self.session.get("points") or {}).get("available"))
        frozen = points((self.session.get("points") or {}).get("frozen"))
        if required > available:
            raise SubscriptionError(
                "insufficient_points",
                details={"requiredPoints": str(required), "availablePoints": str(available), "frozenPoints": str(frozen)},
            )
        balance = dict(self.session.get("points") or {})
        remaining = required
        # Compatibility only: old summary-only trial balances have no expiry to
        # compare. Keep their historical trial-first behavior until batches exist.
        # Explicit trial batches participate in the same expiry ordering as paid ones.
        if not any(c.get("source") == "trial_gift" and c.get("available") is not None
                   for c in balance["cycles"]):
            trial_used = min(remaining, points(balance.get("trialAvailable")))
            balance["trialAvailable"] = points_text(points(balance.get("trialAvailable")) - trial_used)
            remaining -= trial_used
        batches = sorted((c for c in balance["cycles"]
                          if c.get("source") in ("subscription", "trial_gift")
                          and c.get("status") == "active" and c.get("available") is not None),
                         key=self._batch_sort_key)
        for cycle in batches:
            used = min(remaining, points(cycle["available"]))
            cycle["available"] = points_text(points(cycle["available"]) - used)
            remaining -= used
        self.session["points"] = balance
        self._sum_batches()
        self.add_entry(kind="settle", change=-required, business=spec["name"], business_code=spec_id, ref_id=ref_id)
        return {"taskId": ref_id, "specId": spec_id, "chargedPoints": str(required),
                "available": self.session["points"]["available"], "billingStatus": "settled"}

    def purchase(self, plan_id: str, method: str = "") -> "dict[str, Any]":
        """模拟支付成功：新增自然月批次，旧批次保留原到期时间。"""
        session = self.require_session()
        plan = find_plan(plan_id)
        self.refresh_batches()
        started = datetime.fromisoformat(_now_text())
        year, month = (started.year + 1, 1) if started.month == 12 else (started.year, started.month + 1)
        expires = started.replace(year=year, month=month, day=min(started.day, calendar.monthrange(year, month)[1]))
        granted = points(plan["points"])
        cycle_id = "C-" + uuid.uuid4().hex
        session["subscription"] = {
            "status": "active", "planId": plan["planId"], "planName": plan["name"],
            "cycleId": cycle_id, "periodStart": started.isoformat(),
            "currentPeriodEnd": expires.isoformat(), "periodPoints": str(granted),
        }
        session["points"]["cycles"].append({
            "id": cycle_id, "source": "subscription", "status": "active", "planName": plan["name"],
            "startedAt": started.isoformat(), "createdAt": started.isoformat(),
            "expiresAt": expires.isoformat(),
            "granted": str(granted), "available": str(granted),
        })
        self._sum_batches()
        entry = self.add_entry(kind="grant", change=granted, business=str(plan["name"]) + "订阅",
                              business_code="plan_grant", ref_id=cycle_id)
        entry.update(cycleId=cycle_id, refType="order")
        order = {
            "orderId": "WB" + uuid.uuid4().hex[:8].upper(),
            "status": "paid",
            "planId": plan["planId"],
            "planName": plan["name"],
            "priceCents": plan["priceCents"],
            "points": str(granted),
            "createdAt": _now_text(),
        }
        entry["refId"] = order["orderId"]
        # 模拟支付即为成功：同时记录支付渠道与支付时间，订单详情才完整。
        order["paidAt"] = order["createdAt"]
        order["payChannel"] = pay_channel_id(method) or "wechat"
        self.orders.insert(0, order)
        return order


# --------------------------------------------------------------------- live 通路

# 长轮询读请求（查任务、取结果）用更长的超时：任务执行可能接近这个量级，
# 用普通写请求的 30 秒会把平台侧偶发的慢响应误判成「服务未启动」。
POLL_REQUEST_TIMEOUT_SECONDS = 60.0


def _network_error_code(exc: Exception) -> str:
    """区分「连不上服务」与「响应超时/中断」。

    连接被拒或 DNS 失败说明服务没起来，保留 unreachable 与对应文案；
    读超时、连接中断属于可重试的暂时态，收敛成 timeout，由上层按
    「结果未知、继续查同一个任务」处理，避免误报成服务未启动。
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - 依赖缺失属部署问题
        return "unreachable"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "unreachable"
    return "timeout"


class PlatformWorkbenchClient:
    """调用平台 /workbench/v1 的 HTTP 客户端。

    访问凭证只有 2 小时有效期，平台对过期凭证一律回 401；``refresh`` 是续期回调，
    客户端收到 401 时用它换一张新凭证再重试原请求，避免出现「本地仍显示已登录、
    但每一次平台调用都被拒」的错位。
    """

    def __init__(self, token: str, *, base_url: str, timeout: float = 30.0, client: Optional[Any] = None,
                 refresh: Optional[Callable[[str], "Awaitable[str]"]] = None):
        self._token = str(token or "").strip()
        self._base_url = str(base_url or "").strip().rstrip("/")
        self._timeout = timeout
        self._client = client
        self._refresh = refresh

    def _headers(self, idempotency_key: Optional[str] = None) -> "dict[str, str]":
        headers = {"Accept": "application/json", "Content-Type": "application/json", "X-Workbench-Contract": "2"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def request(self, method: str, path: str, *, json_body: Any = None,
                      idempotency_key: Optional[str] = None, params: Optional[Mapping[str, Any]] = None,
                      timeout: Optional[float] = None) -> Any:
        try:
            return await self._send(method, path, json_body=json_body, idempotency_key=idempotency_key,
                                    params=params, timeout=timeout)
        except SubscriptionError as exc:
            # 凭证过期或被撤销：先续期，成功了就用新凭证重试这一次（只重试一次）。
            # 续期失败时回调会清掉本地会话；这里如实抛出原始鉴权错误，让上层按契约处理。
            if self._refresh is None or not self._token or exc.code not in RELOGIN_CODES:
                raise
            renewed = await self._refresh(self._token)
            if not renewed or renewed == self._token:
                raise
            self._token = renewed
            return await self._send(method, path, json_body=json_body, idempotency_key=idempotency_key,
                                    params=params, timeout=timeout)

    async def _send(self, method: str, path: str, *, json_body: Any = None,
                    idempotency_key: Optional[str] = None, params: Optional[Mapping[str, Any]] = None,
                    timeout: Optional[float] = None) -> Any:
        url = self._base_url + API_PREFIX + path
        kwargs: "dict[str, Any]" = {"headers": self._headers(idempotency_key)}
        if json_body is not None:
            kwargs["json"] = json_body
        if params:
            kwargs["params"] = dict(params)
        limit = self._timeout if timeout is None else timeout
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                try:
                    import httpx
                except ImportError as exc:  # pragma: no cover - 依赖缺失属部署问题
                    raise SubscriptionError("unreachable") from exc
                async with httpx.AsyncClient(timeout=limit, follow_redirects=False) as client:
                    response = await client.request(method, url, **kwargs)
        except SubscriptionError:
            raise
        except Exception as exc:  # 网络层失败：不在客户端重试业务
            code = _network_error_code(exc)
            logger.warning("workbench_platform_network_failed method=%s path=%s error=%s code=%s",
                           method, path, type(exc).__name__, code)
            raise SubscriptionError(code) from exc

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - 非 JSON 响应统一按上游异常处理
            payload = None

        if getattr(response, "status_code", 0) == 200 and isinstance(payload, Mapping) and payload.get("ok") is True:
            return payload.get("data") or {}
        error = self._error_from_response(response, payload)
        if path.startswith("/redemptions"):
            # Never expose an upstream echo of the code or user credentials.
            order_id = error.details.get("orderId")
            error.details = {"orderId": order_id} if isinstance(order_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", order_id) else {}
            retry = getattr(response, "headers", {}).get("Retry-After", "")
            if str(retry).isdigit():
                error.details["retryAfterSeconds"] = int(retry)
        raise error

    def _error_from_response(self, response: Any, payload: Any) -> SubscriptionError:
        status_code = int(getattr(response, "status_code", 0) or 0)
        error = payload.get("error") if isinstance(payload, Mapping) and isinstance(payload.get("error"), Mapping) else {}
        platform_code = str(error.get("code") or "")
        details = error.get("details") if isinstance(error, Mapping) else None
        request_id = payload.get("requestId") if isinstance(payload, Mapping) else None
        logger.warning("workbench_platform_error status=%s platform_code=%s request_id=%s",
                       status_code, public_error_code(platform_code), request_id or "-")
        return SubscriptionError(public_error_code(platform_code), status_code=status_code or None,
                                 platform_code=platform_code, details=details if isinstance(details, Mapping) else None)


    # ---------------------------------------------------------------- 付费能力

    # 工作台不再持有任何供应商或运营方 Key：上传、报价与四类计费能力
    # 一律用当前登录用户凭证调用 /workbench/v1，计费由平台在服务端完成。

    async def _multipart(self, path: str, *, files: Mapping[str, Any]) -> Any:
        """multipart 上传：与 JSON 请求共用信封解析，但不发送 application/json。"""
        response = await self._multipart_send(path, files=files)
        if getattr(response, "status_code", 0) == 401 and self._refresh is not None and self._token:
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001 - 非 JSON 响应交由 _error_from_response 兜底
                payload = None
            if self._error_from_response(response, payload).code in RELOGIN_CODES:
                renewed = await self._refresh(self._token)
                if renewed and renewed != self._token:
                    self._token = renewed
                    # 重试前把文件句柄退回起点，否则第二次上传的是空内容。
                    for value in files.values():
                        handle = value[1] if isinstance(value, tuple) and len(value) > 1 else None
                        seek = getattr(handle, "seek", None)
                        if callable(seek):
                            seek(0)
                    response = await self._multipart_send(path, files=files)
        return response

    async def _multipart_send(self, path: str, *, files: Mapping[str, Any]) -> Any:
        url = self._base_url + API_PREFIX + path
        headers = {"Accept": "application/json", "X-Workbench-Contract": "2"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        try:
            if self._client is not None:
                return await self._client.request("POST", url, headers=headers, files=dict(files))
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - 依赖缺失属部署问题
                raise SubscriptionError("unreachable") from exc
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                return await client.request("POST", url, headers=headers, files=dict(files))
        except SubscriptionError:
            raise
        except Exception as exc:
            code = _network_error_code(exc)
            logger.warning("workbench_upload_network_failed path=%s error=%s code=%s",
                           path, type(exc).__name__, code)
            raise SubscriptionError(code) from exc

    async def upload_file(self, path: Path, *, filename: Optional[str] = None,
                          content_type: Optional[str] = None) -> "dict[str, Any]":
        """上传本地素材：不单独计费，返回平台素材号（upload.id）。"""
        target = Path(path)
        if not target.is_file():
            raise SubscriptionError("unsupported_input", "本地素材不存在，无法上传。", status_code=400)
        with target.open("rb") as handle:
            files = {"file": (filename or target.name, handle, content_type or "application/octet-stream")}
            response = await self._multipart("/uploads", files=files)
        payload = None
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - 非 JSON 响应统一按上游异常处理
            payload = None
        if getattr(response, "status_code", 0) == 200 and isinstance(payload, Mapping) and payload.get("ok") is True:
            data = payload.get("data") or {}
            upload = data.get("upload") if isinstance(data, Mapping) else None
            return dict(upload) if isinstance(upload, Mapping) else {}
        raise self._error_from_response(response, payload)

    async def quote(self, *, service_id: object, quantity: object = "1",
                    max_charge_points: Optional[str] = None,
                    budget_id: Optional[str] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"serviceId": str(service_id or ""), "quantity": str(quantity)}
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if budget_id:
            body["budgetId"] = str(budget_id)
        return await self.request("POST", "/quotes", json_body=body)

    # 视频解析与音频转写已拆成两个独立、独立计费的服务：
    #   链接 → /video-parses（按次）；本地 MP3 直传 → /audio-uploads + /audio-transcriptions（按分钟）。
    # 工作台在本地下载原视频、提取 MP3 并直传，平台不再下载原视频、不再回传云端媒体地址。

    async def video_parse(self, *, quote_id: object, url: str, max_charge_points: Optional[str] = None,
                          local_task_id: Optional[str] = None, account_label: Optional[str] = None,
                          business_context: Optional[Mapping[str, Any]] = None,
                          idempotency_key: Optional[str] = None) -> "dict[str, Any]":
        """分享链接解析：成功按次结算，仅返回可下载媒体地址与元信息。"""
        body: "dict[str, Any]" = {"quoteId": str(quote_id or ""), "url": str(url or "")}
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if local_task_id:
            body["localTaskId"] = str(local_task_id)
        if account_label:
            body["accountLabel"] = str(account_label)
        if business_context:
            body["businessContext"] = dict(business_context)
        return await self.request("POST", "/video-parses", json_body=body, idempotency_key=idempotency_key)

    async def audio_upload_create(self, *, filename: Optional[str] = None) -> "dict[str, Any]":
        """登记待上传音频，取回单对象直传地址；不收费。"""
        return await self.request("POST", "/audio-uploads", json_body={"filename": str(filename or "audio.mp3")})

    async def audio_upload_complete(self, upload_id: object) -> "dict[str, Any]":
        """确认直传完成并核验时长；返回 {upload: {..., durationSeconds}}，不收费。"""
        return await self.request("POST", "/audio-uploads/" + str(upload_id) + "/complete", json_body={})

    async def audio_transcription(self, *, quote_id: object, upload_id: object,
                                  max_charge_points: Optional[str] = None,
                                  local_task_id: Optional[str] = None, account_label: Optional[str] = None,
                                  business_context: Optional[Mapping[str, Any]] = None,
                                  idempotency_key: Optional[str] = None) -> "dict[str, Any]":
        """音频转写：只接受已核验的 uploadId，交付文案后按核验分钟结算。"""
        body: "dict[str, Any]" = {"quoteId": str(quote_id or ""), "uploadId": str(upload_id or "")}
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if local_task_id:
            body["localTaskId"] = str(local_task_id)
        if account_label:
            body["accountLabel"] = str(account_label)
        if business_context:
            body["businessContext"] = dict(business_context)
        return await self.request("POST", "/audio-transcriptions", json_body=body, idempotency_key=idempotency_key)

    def _owned_url(self, value: object) -> str:
        from urllib.parse import urljoin, urlsplit
        url = urljoin(self._base_url + "/", str(value or ""))
        base, target = urlsplit(self._base_url), urlsplit(url)
        if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port) or target.username or target.password or not target.path.startswith("/workbench/v1/"):
            raise SubscriptionError("unsupported_input", "成果地址无效。", status_code=400)
        return url

    async def put_audio(self, url: str, *, data: bytes, headers: Optional[Mapping[str, Any]] = None,
                        timeout: float = 300.0) -> int:
        """Upload only to an authenticated platform-owned media endpoint."""
        import httpx
        destination = self._owned_url(url)
        safe_headers = {**self._headers(), "Content-Type": "audio/mpeg"}
        try:
            if self._client is not None:
                response = await self._client.request("PUT", destination, content=data, headers=safe_headers)
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    response = await client.put(destination, content=data, headers=safe_headers)
        except Exception as exc:
            raise SubscriptionError(_network_error_code(exc)) from None
        return int(response.status_code)

    async def data_query(self, *, capability: object, params: "Mapping[str, Any] | None" = None,
                         cursor: Optional[str] = None, quote_id: object = "",
                         max_charge_points: Optional[str] = None,
                         idempotency_key: Optional[str] = None,
                         business_context: Optional[Mapping[str, Any]] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"quoteId": str(quote_id or ""), "capability": str(capability or ""),
                                  "params": dict(params or {})}
        if cursor:
            body["cursor"] = str(cursor)
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if business_context:
            body["businessContext"] = dict(business_context)
        return await self.request("POST", "/data/query", json_body=body, idempotency_key=idempotency_key)

    async def image(self, *, quote_id: object, prompt: str, aspect_ratio: str, count: int = 1,
                    variant: str = "text-to-image", reference_upload_ids: Optional["list[str]"] = None,
                    max_charge_points: Optional[str] = None,
                    idempotency_key: Optional[str] = None,
                    business_context: Optional[Mapping[str, Any]] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"quoteId": str(quote_id or ""), "prompt": str(prompt or ""),
                                  "aspectRatio": str(aspect_ratio or "3:4"), "count": int(count or 1),
                                  "variant": str(variant or "text-to-image")}
        if reference_upload_ids:
            body["referenceUploadIds"] = list(reference_upload_ids)
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if business_context:
            body["businessContext"] = dict(business_context)
        return await self.request("POST", "/images", json_body=body, idempotency_key=idempotency_key)

    async def text(self, *, quote_id: object, scene: str, messages: "list[dict[str, Any]]",
                   model: Optional[str] = None, temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None, response_format: "dict[str, Any] | None" = None,
                   max_charge_points: Optional[str] = None,
                   idempotency_key: Optional[str] = None,
                         business_context: Optional[Mapping[str, Any]] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"quoteId": str(quote_id or ""), "scene": str(scene or "script_rewrite"),
                                  "messages": list(messages or [])}
        if model:
            body["model"] = str(model)
        if temperature is not None:
            body["temperature"] = float(temperature)
        if max_tokens:
            body["maxTokens"] = int(max_tokens)
        if response_format:
            body["responseFormat"] = dict(response_format)
        if max_charge_points is not None:
            body["maxChargePoints"] = str(max_charge_points)
        if business_context:
            body["businessContext"] = dict(business_context)
        return await self.request("POST", "/texts", json_body=body, idempotency_key=idempotency_key)

    async def task(self, task_id: object) -> "dict[str, Any]":
        return await self.request("GET", "/tasks/" + str(task_id), timeout=POLL_REQUEST_TIMEOUT_SECONDS)

    async def task_result(self, task_id: object) -> "dict[str, Any]":
        return await self.request("GET", "/tasks/" + str(task_id) + "/result",
                                  timeout=POLL_REQUEST_TIMEOUT_SECONDS)

    async def cancel_task(self, task_id: object) -> "dict[str, Any]":
        return await self.request("POST", "/tasks/" + str(task_id) + "/cancel", json_body={})

    async def services(self) -> "dict[str, Any]":
        return await self.request("GET", "/services")

    async def download_asset(self, asset_path_or_url: object, target: Path, *, timeout: float = 120.0) -> Path:
        """Stream an authenticated platform asset atomically; never follow redirects."""
        from contextlib import AsyncExitStack
        import httpx
        import uuid
        url = self._owned_url(asset_path_or_url)
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        try:
            async with AsyncExitStack() as stack:
                client = self._client or await stack.enter_async_context(httpx.AsyncClient(timeout=timeout, follow_redirects=False))
                response = await stack.enter_async_context(client.stream("GET", url, headers={**self._headers(), "Accept": "*/*"}, follow_redirects=False))
                if response.status_code != 200:
                    await response.aread()
                    try: payload = response.json()
                    except ValueError: payload = None
                    raise self._error_from_response(response, payload)
                with temporary.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
                if temporary.stat().st_size == 0:
                    raise SubscriptionError("content_unavailable", "成果文件为空。")
                temporary.replace(destination)
        except SubscriptionError:
            raise
        except Exception as exc:
            logger.warning("workbench_asset_download_failed error=%s", type(exc).__name__)
            raise SubscriptionError("unreachable") from None
        finally:
            temporary.unlink(missing_ok=True)
        return destination


# ---------------------------------------------------------------- 只读缓存
#
# 账户页一次刷新会连打 5 个只读接口，多开标签页或反复刷新时还会并发重复。
# 平台侧只读额度已经独立，这里再做两层收敛，避免把只读额度也打满：
#   * 套餐清单很少变：做 60 秒进程内 TTL 缓存；
#   * 明细合并快照按会话缓存 15 秒，翻页与类型筛选复用；主动刷新绕过缓存。
#   * 其余只读调用只做「同参数在途合并」——并发相同请求共用一个平台调用，
#     不缓存结果，因此不会返回陈旧数据。
# 缓存按会话凭证分键：不同用户之间不共享，也不会互相看到对方的余额。
_PLANS_TTL_SECONDS = 60.0
_plans_cache: "dict[str, tuple[float, dict[str, Any]]]" = {}
_inflight_reads: "dict[tuple, asyncio.Future]" = {}
_LEDGER_TTL_SECONDS = 15.0
_ledger_snapshots: dict = {}
_ledger_cache_revision = 0
# 续期锁按会话存储文件保存：并发的多个请求同时撞上过期凭证时，只允许一个真正
# 走一次轮换，其余复用新凭证；否则后一个会拿着刚失效的 refreshToken 续期失败，
# 把明明只是过期的会话误判成需要重新登录。
_refresh_locks: "dict[str, asyncio.Lock]" = {}


def _cached_plans(token: str) -> "dict[str, Any] | None":
    entry = _plans_cache.get(token)
    if entry is None:
        return None
    stamp, value = entry
    if time.monotonic() - stamp >= _PLANS_TTL_SECONDS:
        _plans_cache.pop(token, None)
        return None
    return value


def _store_plans(token: str, value: "dict[str, Any]") -> None:
    _plans_cache[token] = (time.monotonic(), value)


def invalidate_subscription_cache(token: str = "") -> None:
    """购买/登出后清掉只读缓存：套餐清单按凭证清，空凭证表示全部清空。"""
    global _ledger_cache_revision
    _ledger_cache_revision += 1
    _ledger_snapshots.clear()
    if token:
        _plans_cache.pop(token, None)
    else:
        _plans_cache.clear()


async def _coalesce_read(key: tuple, factory: "Callable[[], Any]") -> Any:
    """同参数在途合并：并发相同只读请求只打一次平台，结果分发给所有等待者。"""
    pending = _inflight_reads.get(key)
    if pending is not None:
        return await asyncio.shield(pending)
    pending = asyncio.get_running_loop().create_future()
    _inflight_reads[key] = pending
    try:
        value = await factory()
    except BaseException as exc:  # noqa: BLE001 - 取消也要唤醒等待者并清理
        _inflight_reads.pop(key, None)
        pending.set_exception(exc)
        pending.exception()  # 主动取值，避免「exception was never retrieved」告警
        raise
    _inflight_reads.pop(key, None)
    pending.set_result(value)
    return value


# ---------------------------------------------------------------------- 门面

class SubscriptionService:
    """工作台统一入口：真实通路与模拟通路对外方法一致。

    是否有足够积分、应该扣多少，一律由平台判定；本类不缓存余额、不自行扣费。
    """

    def __init__(self, store: SubscriptionStore, settings: "AppSettings", *, http_client: Optional[Any] = None):
        self._store = store
        self._settings = settings
        self._http_client = http_client

    @classmethod
    def from_workspace(cls, workspace: Path, settings: "AppSettings", **kwargs: Any) -> "SubscriptionService":
        return cls(SubscriptionStore(Path(workspace)), settings, **kwargs)

    @property
    def mode(self) -> str:
        return normalize_platform_mode(getattr(self._settings, "workbench_platform_mode", DEFAULT_PLATFORM_MODE))

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    # -- 本地状态

    def _state(self) -> "dict[str, Any]":
        return self._store.load()

    def _save(self, state: "dict[str, Any]") -> None:
        try:
            self._store.save(state)
        except OSError:
            logger.warning("subscription_store_write_failed")

    def token(self) -> str:
        state = self._state()
        session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
        return str(session.get("accessToken") or "")

    def session_view(self) -> "dict[str, Any]":
        state = self._state()
        session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
        return {
            "loggedIn": bool(session.get("accessToken")),
            "phone": str(session.get("phone") or ""),
            "mode": self.mode,
            "paymentOwner": self.payment_owner() if session.get("accessToken") else "",
        }

    def payment_owner(self) -> str:
        session = self._state().get("session") or {}
        source = str(getattr(self._settings, "workbench_api_base_url", ""))
        identity = str(session.get("paymentIdentity") or session.get("accessToken") or "")
        return hashlib.sha256((source + "|" + identity).encode()).hexdigest()

    def _payment_client(self) -> PlatformWorkbenchClient:
        owner = self.payment_owner()
        async def refresh(token: str) -> str:
            if self.payment_owner() != owner:
                raise SubscriptionError("unauthorized")
            return await self._refresh_access_token(token, payment_owner=owner)
        return PlatformWorkbenchClient(self.token(), base_url=getattr(self._settings, "workbench_api_base_url", ""),
                                       client=self._http_client, refresh=refresh)

    def _save_session(self, session: Mapping[str, Any]) -> None:
        state = self._state()
        state["session"] = dict(session)
        self._save(state)

    def _client(self) -> PlatformWorkbenchClient:
        token = self.token()
        if not token:
            raise SubscriptionError("unauthorized")
        return PlatformWorkbenchClient(token, base_url=getattr(self._settings, "workbench_api_base_url", ""),
                                       client=self._http_client, refresh=self._refresh_access_token)

    def _refresh_lock(self) -> asyncio.Lock:
        key = str(self._store.path)
        lock = _refresh_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _refresh_locks[key] = lock
        return lock

    async def _refresh_access_token(self, failed_token: str, *, payment_owner: str = "") -> str:
        """用 refreshToken 换一张新的访问凭证；被平台拒绝时清掉本地会话并返回空串。

        访问凭证只有 2 小时有效期，而 refreshToken 有 30 天：这段时间内应当
        「静默续期」而不是「要求重新登录」，否则界面显示已登录、平台却拒绝一切调用。

        平台暂时不可达/限流不属于凭证失效，此时保留本地会话并把错误抛给调用方，
        避免一次网络抖动就把用户登出。
        """
        async with self._refresh_lock():
            if payment_owner and self.payment_owner() != payment_owner:
                raise SubscriptionError("unauthorized")
            state = self._state()
            session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
            current = str(session.get("accessToken") or "")
            # 并发请求里别人已经续期过：直接复用新凭证重试，不再轮换一次。
            if current and current != failed_token:
                return current
            refresh_token = str(session.get("refreshToken") or "")
            if not refresh_token:
                self._forget_session(failed_token)
                return ""
            try:
                data = await self._anon_client().request("POST", "/auth/refresh",
                                                         json_body={"refreshToken": refresh_token})
            except SubscriptionError as exc:
                if payment_owner and self.payment_owner() != payment_owner:
                    raise SubscriptionError("unauthorized") from None
                if exc.code in RELOGIN_CODES or exc.code == "account_disabled":
                    logger.info("workbench_session_refresh_rejected code=%s", exc.code)
                    self._forget_session(failed_token)
                    return ""
                logger.warning("workbench_session_refresh_unavailable code=%s", exc.code)
                raise
            if payment_owner and self.payment_owner() != payment_owner:
                raise SubscriptionError("unauthorized")
            access = str(data.get("accessToken") or "")
            rotated = str(data.get("refreshToken") or "")
            if not access or not rotated:
                logger.warning("workbench_session_refresh_incomplete")
                self._forget_session(failed_token)
                return ""
            invalidate_subscription_cache(failed_token)
            self._save_session({
                "accessToken": access,
                "refreshToken": rotated,
                "phone": str(session.get("phone") or ""),
                "paymentIdentity": session.get("paymentIdentity") or failed_token,
                "accessExpiresAt": str(data.get("accessExpiresAt") or ""),
                "refreshExpiresAt": str(data.get("refreshExpiresAt") or ""),
            })
            logger.info("workbench_session_refreshed")
            return access

    def _forget_session(self, token: str = "") -> None:
        """平台已拒绝且无法续期：清掉本地会话，让界面如实回到未登录。"""
        state = self._state()
        session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
        invalidate_subscription_cache(str(session.get("accessToken") or token))
        state.pop("session", None)
        if state:
            self._save(state)
        else:
            self._store.clear()

    def _anon_client(self) -> PlatformWorkbenchClient:
        """未登录也能调用的接口（发送验证码、登录）用无凭证客户端。"""
        return PlatformWorkbenchClient("", base_url=getattr(self._settings, "workbench_api_base_url", ""),
                                       client=self._http_client)

    def business_client(self) -> PlatformWorkbenchClient:
        """付费能力共用的带会话凭证客户端；模拟通路不承接任何计费调用。"""
        if self.is_mock:
            raise SubscriptionError("platform_mode_required")
        return self._client()

    def _mock(self) -> MockPlatform:
        mock = MockPlatform.from_state(self._state())
        if mock.seeded:
            self._save_mock(mock)
        return mock

    def _save_mock(self, mock: MockPlatform) -> None:
        state = self._state()
        state["mock"] = mock.dump()
        self._save(state)

    def _require_login(self) -> None:
        state = self._state()
        session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
        if not session.get("accessToken"):
            raise SubscriptionError("unauthorized")

    # -- 身份

    async def send_code(self, phone: object) -> "dict[str, Any]":
        if not is_valid_phone(phone):
            raise SubscriptionError("unsupported_input", "请输入 11 位手机号。", status_code=400)
        if self.is_mock:
            return {"sent": True, "expiresInSeconds": 300, "retryAfterSeconds": 60, "demoCode": MOCK_CODE}
        data = await self._anon_client().request("POST", "/auth/sms/send", json_body={"phone": str(phone).strip()})
        return {
            "sent": bool(data.get("sent", True)),
            "expiresInSeconds": int(data.get("expiresIn") or 300),
            "retryAfterSeconds": int(data.get("cooldown") or 60),
            "demoCode": str(data.get("mockCode") or ""),
        }

    async def login(self, phone: object, code: object) -> "dict[str, Any]":
        if not is_valid_phone(phone):
            raise SubscriptionError("unsupported_input", "请输入 11 位手机号。", status_code=400)
        if self.is_mock:
            if str(code or "").strip() != MOCK_CODE:
                raise SubscriptionError("unsupported_input", "验证码不正确。", status_code=400)
            mock = self._mock()
            registered = not mock.logged_in()
            session = mock.start_session(str(phone).strip(), registered=registered)
            self._save_mock(mock)
            self._save_session({"accessToken": session["accessToken"], "refreshToken": session["refreshToken"],
                                "phone": session["phone"], "registered": registered})
            return {"registered": registered, "user": {"phone": session["phone"], "status": "active"}}
        data = await self._anon_client().request("POST", "/auth/login",
                                                json_body={"phone": str(phone).strip(), "code": str(code or "").strip(),
                                                           "agreementVersion": "v1"})
        self._save_session({"accessToken": str(data.get("accessToken") or ""),
                            "refreshToken": str(data.get("refreshToken") or ""),
                            "paymentIdentity": hashlib.sha256(str(phone).strip().encode()).hexdigest(),
                            "phone": str((data.get("user") or {}).get("maskedPhone") or mask_phone(phone)),
                            "accessExpiresAt": str(data.get("accessExpiresAt") or ""),
                            "refreshExpiresAt": str(data.get("refreshExpiresAt") or "")})
        return {"registered": bool(data.get("created")), "user": dict(data.get("user") or {})}

    async def logout(self) -> "dict[str, Any]":
        invalidate_subscription_cache(self.token())
        if not self.is_mock:
            try:
                await self._client().request("POST", "/auth/logout")
            except SubscriptionError as exc:
                # 平台不可达或凭证已失效都不该拦着用户退出：本地会话一律清掉。
                logger.warning("workbench_logout_platform_failed code=%s", exc.code)
        self._store.clear()
        return {"loggedOut": True}

    async def me(self) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            mock = self._mock()
            session = mock.require_session()
            return {"user": {"phone": session.get("phone"), "status": session.get("status")},
                    "subscription": mock.subscription_view(),
                    "points": dict(session.get("points") or {})}
        return await self._client().request("GET", "/auth/me")

    def ledger_session_key(self) -> str:
        """Opaque in-memory session key; never persist session credentials."""
        source = str(getattr(self._settings, "workbench_api_base_url", "")).rstrip("/")
        return hashlib.sha256(f"{self.mode}|{source}|{self.token()}".encode()).hexdigest()

    async def point_history_reader(self):
        """Authenticate once, then pin every history page to that same user.

        A concurrent login or credential rotation aborts this snapshot. A later
        sync starts with the new session rather than mixing two users' pages.
        """
        self._require_login()
        if self.is_mock:
            raise SubscriptionError("platform_mode_required")
        key = self.ledger_session_key()
        identity = await self.me()
        user_id = str((identity.get("user") or {}).get("id") or "")
        if not user_id or self.ledger_session_key() != key:
            raise SubscriptionError("unreachable")
        source = str(getattr(self._settings, "workbench_api_base_url", "")).rstrip("/")
        owner = hashlib.sha256(f"{source}|{user_id}".encode()).hexdigest()
        # No refresh callback: a long scan must not resume under another login.
        client = PlatformWorkbenchClient(self.token(), base_url=source, client=self._http_client)

        async def read_page(page: int):
            if self.ledger_session_key() != key:
                raise SubscriptionError("unreachable")
            data = await client.request("GET", "/points/entries", params={"page": page, "pageSize": 100})
            if self.ledger_session_key() != key:
                raise SubscriptionError("unreachable")
            return data

        return owner, read_page

    # -- 商品与订阅

    async def plans(self, *, refresh: bool = False) -> "dict[str, Any]":
        """可售套餐：平台对 /plans 同样要求会话凭证，不能匿名调用。

        未登录时返回空清单即可——账户页此时只显示登录引导、不渲染套餐卡片，
        否则匿名请求会被平台按 401 拒绝，连带整页报错。
        """
        if self.is_mock:
            return plans_view()
        token = self.token()
        if not token:
            return {"items": []}
        cached = None if refresh else _cached_plans(token)
        if cached is not None:
            return cached
        data = await self._client().request("GET", "/plans")
        items = data.get("items") if isinstance(data, Mapping) else None
        view = {"items": [_live_plan_view(row) for row in (items or []) if isinstance(row, Mapping)]}
        _store_plans(token, view)
        return view

    async def subscription(self, *, points_view: "Mapping[str, Any] | None" = None) -> "dict[str, Any]":
        """当前订阅。调用方已经取过 /points 时传进来，避免同一屏重复消耗平台配额。"""
        self._require_login()
        if self.is_mock:
            return self._mock().subscription_view()
        if points_view is not None:
            # 余额由调用方自带且因请求而异，不参与在途合并，避免交叉到别人的数据。
            view = await self._client().request("GET", "/subscription")
            return _live_subscription_view(view, points_view)

        async def _fetch() -> "dict[str, Any]":
            client = self._client()
            view = await client.request("GET", "/subscription")
            try:
                fetched = await client.request("GET", "/points")
            except SubscriptionError:
                fetched = {}
            return _live_subscription_view(view, fetched)

        return await _coalesce_read(("subscription", self.token()), _fetch)

    def _trial_owner(self, expected: str = "") -> str:
        self._require_login()
        owner = self.payment_owner()
        if expected and owner != expected:
            raise SubscriptionError("owner_changed", "登录身份已变化，请刷新后重试。", status_code=409)
        return owner

    async def trial_gift(self, *, owner: str = "") -> "dict[str, Any]":
        identity = self._trial_owner(owner)
        source = str(getattr(self._settings, "workbench_api_base_url", ""))
        if self.is_mock:
            return {"visible": False, "claimed": False, "amount": "0.000", "validityMonths": 1,
                    "qrCodeUrl": None, "guideText": "", "grant": None, "userId": "",
                    "paymentOwner": identity}
        client = self._payment_client()

        async def fetch():
            self._trial_owner(identity)
            try:
                data = await client.request("GET", "/trial-gift")
            except SubscriptionError:
                self._trial_owner(identity)
                raise
            self._trial_owner(identity)
            return dict(data, paymentOwner=identity)

        result = await _coalesce_read(("trial-gift", identity, source), fetch)
        # Every waiter has its own store; a shared response cannot bypass its fence.
        self._trial_owner(identity)
        return dict(result)

    async def trial_gift_qrcode(self, *, owner: str = "") -> "tuple[bytes, str]":
        identity = self._trial_owner(owner)
        guide = await self.trial_gift(owner=identity)
        path = guide.get("qrCodeUrl")
        if (not guide.get("visible") or guide.get("claimed") or not isinstance(path, str)
                or not re.fullmatch(r"/api/trial-gift/qrcodes/[a-f0-9]{32}\.(?:png|jpg|webp)", path)):
            raise SubscriptionError("not_found", "当前没有可展示的领取二维码。", status_code=404)
        base = urlsplit(str(getattr(self._settings, "workbench_api_base_url", "")))
        if base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password:
            raise SubscriptionError("upstream_unavailable")
        url = base.scheme + "://" + base.netloc + path
        # Public QR only: no user credential and no redirects, including injected clients.
        try:
            import httpx
            if self._http_client is not None:
                response = await self._http_client.request("GET", url, follow_redirects=False,
                                                           headers={"Accept": "image/png,image/jpeg,image/webp"})
            else:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    response = await client.get(url, headers={"Accept": "image/png,image/jpeg,image/webp"})
        except Exception as exc:
            self._trial_owner(identity)
            raise SubscriptionError(_network_error_code(exc)) from exc
        self._trial_owner(identity)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status_code != 200 or media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise SubscriptionError("upstream_unavailable")
        return response.content, media_type

    # -- 积分

    async def balance(self) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            mock = self._mock()
            session = mock.require_session()
            subscription = session.get("subscription") or {}
            current = points((session.get("points") or {}).get("available"))
            frozen = points((session.get("points") or {}).get("frozen"))
            return {
                "available": str(current),
                **{key: (session.get("points") or {})[key]
                   for key in ("subscriptionAvailable", "trialAvailable", "cycles")
                   if (session.get("points") or {}).get(key) is not None},
                "frozen": str(frozen),
                "periodPoints": points_text(subscription.get("periodPoints")),
                "periodStart": subscription.get("periodStart"),
                "currentPeriodEnd": subscription.get("currentPeriodEnd"),
                "subscriptionStatus": subscription.get("status"),
            }
        async def _fetch() -> "dict[str, Any]":
            return _live_balance_view(await self._client().request("GET", "/points"))

        return await _coalesce_read(("balance", self.token()), _fetch)

    async def ledger(self, *, page: int = 1, page_size: int = 10, period: str = "current", entry_type: str = "all", refresh: bool = False) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            mock = self._mock()
            mock.require_session()
            # 读取时统一按时间倒序，避免历史本地数据的顺序不一致。
            source = [] if period == "last" else [_mock_entry_view(item) for item in mock.ledger]
            rows = _filter_ledger(_merge_task_rows(source), entry_type)
            result = _paginate(rows, page, page_size)
            result["truncated"] = False
            return result
        global _ledger_cache_revision
        owner = self.ledger_session_key()
        if refresh:
            _ledger_snapshots.pop(owner, None)
            _ledger_cache_revision += 1
        revision = _ledger_cache_revision
        now = time.monotonic()
        for key, (stamp, _) in list(_ledger_snapshots.items()):
            if now - stamp >= _LEDGER_TTL_SECONDS:
                _ledger_snapshots.pop(key, None)
        cached = _ledger_snapshots.get(owner)

        async def _fetch():
            raw, truncated = await self._live_ledger_entries()
            if self.ledger_session_key() != owner:
                raise SubscriptionError("unreachable")
            snapshot = (_merge_task_rows([_live_entry_view(row) for row in raw]), truncated)
            if revision == _ledger_cache_revision:
                _ledger_snapshots[owner] = (time.monotonic(), snapshot)
            return snapshot

        rows, truncated = cached[1] if cached else await _coalesce_read(
            ("ledger-snapshot", owner, revision), _fetch)
        result = _paginate(_filter_ledger(rows, entry_type), page, page_size)
        result["truncated"] = truncated
        return result

    async def _live_ledger_entries(self) -> "tuple[list[Mapping[str, Any]], bool]":
        """一次取全部流水再分页：合并任务行必须同时看到冻结与结算两条。

        平台每页上限 100；最多取 20 页，超出时由调用方提示只展示了最近的部分。
        """
        client = self._client()
        first = await client.request("GET", "/points/entries",
                                     params={"page": 1, "pageSize": _LEDGER_PAGE_SIZE})
        items = first.get("items") if isinstance(first, Mapping) else None
        collected = [row for row in (items or []) if isinstance(row, Mapping)]
        total = first.get("total") if isinstance(first, Mapping) else None
        try:
            total_value = int(total)
        except (TypeError, ValueError):
            total_value = len(collected)
        page_count = max(1, (max(total_value, len(collected)) + _LEDGER_PAGE_SIZE - 1) // _LEDGER_PAGE_SIZE)
        truncated = page_count > _LEDGER_MAX_PAGES
        wanted = list(range(2, min(page_count, _LEDGER_MAX_PAGES) + 1))
        if wanted:
            responses = await asyncio.gather(*[
                client.request("GET", "/points/entries",
                               params={"page": number, "pageSize": _LEDGER_PAGE_SIZE})
                for number in wanted
            ])
            for data in responses:
                extra = data.get("items") if isinstance(data, Mapping) else None
                collected.extend(row for row in (extra or []) if isinstance(row, Mapping))
        return collected, truncated

    # -- 订单

    async def orders(self, *, page: int = 1, page_size: int = 10, status: str = "all", period: str = "3m") -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            mock = self._mock()
            mock.require_session()
            items = sorted(mock.orders, key=lambda item: str(item.get("createdAt") or ""), reverse=True)
            if status and status != "all":
                items = [item for item in items if item.get("status") == status]
            return _paginate([_order_view(item) for item in items], page, page_size)
        async def _fetch() -> "dict[str, Any]":
            data = await self._client().request("GET", "/orders", params={"page": page, "pageSize": page_size})
            rows = data.get("items") if isinstance(data, Mapping) else None
            rows = [_live_order_view(row) for row in (rows or []) if isinstance(row, Mapping)]
            if status and status != "all":
                rows = [item for item in rows if item.get("status") == status]
            return _paginate(rows, page, page_size)

        key = ("orders", self.token(), page, page_size, status, period)
        return await _coalesce_read(key, _fetch)

    async def order(self, order_id: object) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            wanted = str(order_id or "").strip()
            for item in self._mock().orders:
                if str(item.get("orderId")) == wanted:
                    return _order_view(item)
            raise SubscriptionError("content_unavailable", "订单不存在或已不可查看。", status_code=404)
        return _live_order_view(await self._payment_client().request("GET", "/orders/" + str(order_id)))

    async def purchase(self, plan_id: object, *, method: str = "", idempotency_key: str = "") -> "dict[str, Any]":
        """Create only; entitlement changes belong exclusively to the platform."""
        self._require_login()
        if not self.is_mock:
            if not re.fullmatch(r"[\x21-\x7e]{1,80}", idempotency_key):
                raise SubscriptionError("idempotency_key_required", status_code=422)
            if method and pay_channel_id(method) != "wechat":
                raise SubscriptionError("unsupported_channel", status_code=422)
            created = await self._payment_client().request(
                "POST", "/orders",
                json_body={"planCode": str(plan_id or "").strip(), "payChannel": "wechat"},
                idempotency_key=idempotency_key,
            )
            invalidate_subscription_cache(self.token())
            return _live_order_view(created)
        mock = self._mock()
        order = mock.purchase(str(plan_id or "").strip(), method)
        self._save_mock(mock)
        return _order_view(order)

    async def query_order(self, order_id: str) -> "dict[str, Any]":
        self._require_login()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", order_id):
            raise SubscriptionError("validation_error", status_code=422)
        if self.is_mock:
            return await self.order(order_id)
        result = await self._payment_client().request("POST", "/orders/" + order_id + "/query", json_body={})
        if result.get("status") == "granted":
            invalidate_subscription_cache(self.token())
        return _live_order_view(result)

    async def close_order(self, order_id: str) -> "dict[str, Any]":
        self._require_login()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", order_id):
            raise SubscriptionError("validation_error", status_code=422)
        if self.is_mock:
            raise SubscriptionError("platform_mode_required")
        result = await self._payment_client().request("POST", "/orders/" + order_id + "/close", json_body={})
        invalidate_subscription_cache(self.token())
        return _live_order_view(result)

    async def redemption_preview(self, code: str, plan_code: str) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            raise SubscriptionError("platform_mode_required")
        return await self._client().request("POST", "/redemptions/preview",
                                            json_body={"code": code, "planCode": plan_code})

    async def redeem(self, code: str, plan_code: str, plan_version: int, key: str) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            raise SubscriptionError("platform_mode_required")
        result = await self._client().request("POST", "/redemptions",
            json_body={"code": code, "planCode": plan_code, "planVersion": plan_version},
            idempotency_key=key)
        invalidate_subscription_cache(self.token())
        return {"order": _live_order_view(result.get("order") or {}),
                "reused": bool(result.get("reused"))}

    # -- 业务计费

    async def spend(self, spec_id: object, units: object, *, ref_id: str = "") -> "dict[str, Any]":
        """模拟一次付费业务。真实通路下计费由对应业务接口在平台侧完成。"""
        self._require_login()
        if not self.is_mock:
            raise SubscriptionError("unsupported_input", "真实模式下计费由平台业务接口完成。", status_code=400)
        mock = self._mock()
        result = mock.spend(str(spec_id or "").strip(), units, ref_id=ref_id or ("T-" + uuid.uuid4().hex[:6].upper()))
        self._save_mock(mock)
        return result

    async def services(self) -> "dict[str, Any]":
        self._require_login()
        if self.is_mock:
            return {
                "priceVersion": PLAN_PRICE_VERSION,
                "items": [{"specId": spec_id, "name": spec["name"], "unit": spec["unit"],
                           "pointsPerUnit": spec["pointsPerUnit"]} for spec_id, spec in POINT_SPECS.items()],
            }
        return await self._client().request("GET", "/services")


def _paginate(items: "list[dict[str, Any]]", page: int, page_size: int) -> "dict[str, Any]":
    size = max(1, min(int(page_size or 10), 100))
    total = len(items)
    page_count = max(1, (total + size - 1) // size)
    current = max(1, min(int(page or 1), page_count))
    start = (current - 1) * size
    return {"items": items[start:start + size], "page": current, "pageSize": size,
            "total": total, "pageCount": page_count}


def _order_view(order: Mapping[str, Any]) -> "dict[str, Any]":
    price_cents = int(order.get("priceCents") or 0)
    view = dict(order)
    view["priceText"] = "%d.%02d" % (price_cents // 100, price_cents % 100)
    view["points"] = points_text(order.get("points"))
    return view


# --------------------------------------------------------------------- live 视图
#
# 平台字段与工作台界面字段并不一一对应：这里统一把平台 /workbench/v1 的返回
# 收敛成界面已经在用的结构，界面与本地接口形状保持不变。

_ENTRY_BUSINESS = {
    "order": "套餐订阅",
    "cycle": "周期结算",
    "task": "任务消费",
    "adjust": "人工调整",
}
# 平台流水类型 -> 界面流水类型；只有撤销用词不同。
_ENTRY_TYPE = {"revoke": "refund_revoke"}
# 界面筛选值 -> 合并后的流水类型；合并后没有对应类型的行不会出现在该筛选里。
_ENTRY_KIND = {"consumed": "settle", "frozen": "freeze", "issued": "grant", "expired": "expire"}
# 单次补齐流水时的页大小与页数上限：100 × 20 = 2000 条。
_LEDGER_PAGE_SIZE = 100
_LEDGER_MAX_PAGES = 20
# 平台在冻结与结算流水上的备注文案：任务名只能从冻结行里取。
_TASK_FREEZE_PREFIX = "任务预冻结"
_TASK_SETTLE_NOTE = "工作台任务结算"
# 同一任务有多条流水时的胜出优先级：结算 > 释放 > 失效 > 冻结。
_TASK_ROW_PRIORITY = {"settle": 4, "release": 3, "expire": 2, "freeze": 1}
# 平台订单状态 -> 界面订单状态。
_ORDER_STATUS = {
    "created": "created",
    "paid": "paid",
    "granted": "granted",
    "refund_pending": "refunding",
    "refunded": "refunded",
    "closed": "closed",
    "failed": "failed",
}


def _live_plan_view(plan: Mapping[str, Any]) -> "dict[str, Any]":
    """平台套餐视图 -> 工作台套餐卡片结构（planId 用平台 code）。"""
    amount_fen = int(plan.get("amountFen") or 0)
    original_fen = plan.get("originalAmountFen")
    # Optional display-only list price; amountFen remains the payable amount.
    discounted = (type(original_fen) is int and original_fen > 0 and 0 <= amount_fen < original_fen)
    return {
        "planId": str(plan.get("code") or ""),
        "name": str(plan.get("name") or ""),
        "priceCents": amount_fen,
        "priceText": "%d.%02d" % (amount_fen // 100, amount_fen % 100),
        "originalPriceCents": original_fen if discounted else None,
        "originalPriceText": ("%d.%02d" % (original_fen // 100, original_fen % 100)) if discounted else None,
        "points": points_text(plan.get("points")),
        "periodType": str(plan.get("periodType") or "natural_month"),
        "status": "on_sale" if str(plan.get("status")) == "on" else "off_sale",
        "version": str(plan.get("version") or ""),
        "entitlements": list(plan.get("benefits") or PLAN_ENTITLEMENTS),
        "capabilities": list(PLAN_CAPABILITIES),
    }


def _live_subscription_view(view: Mapping[str, Any], points_view: Mapping[str, Any]) -> "dict[str, Any]":
    """平台当前订阅 + 积分视图 -> 界面汇总卡结构。"""
    plan = view.get("plan") if isinstance(view.get("plan"), Mapping) else {}
    cycle = view.get("cycle") if isinstance(view.get("cycle"), Mapping) else {}
    available = cycle.get("available")
    if available is None and cycle.get("id"):
        available = next((item.get("available") for item in (points_view.get("cycles") or [])
                          if item.get("id") == cycle["id"]), None)
    return {
        "status": str(view.get("status") or "none"),
        "statusLabel": str(view.get("statusLabel") or ""),
        "planId": str(plan.get("code") or ""),
        "planName": str(plan.get("name") or ""),
        "periodStart": str(cycle.get("startedAt") or ""),
        "currentPeriodEnd": str(cycle.get("expiresAt") or ""),
        "periodPoints": points_text(cycle.get("granted")),
        "daysLeft": int(view.get("daysLeft") or 0),
        "expiringPoints": points_text(available) if available is not None else None,
        "autoRenew": False,
    }


def _live_balance_view(view: Mapping[str, Any]) -> "dict[str, Any]":
    """平台 /points -> 界面要的可用与冻结积分。"""
    return {
        "available": points_text(view.get("available")),
        "frozen": points_text(view.get("frozen")),
        "totalGranted": points_text(view.get("totalGranted")),
        "totalUsed": points_text(view.get("totalUsed")),
        "totalExpired": points_text(view.get("totalExpired")),
        **{key: points_text(view[key]) for key in ("subscriptionAvailable", "trialAvailable")
           if view.get(key) is not None},
        **({"cycles": list(view["cycles"])} if view.get("cycles") is not None else {}),
    }


def _live_entry_view(entry: Mapping[str, Any]) -> "dict[str, Any]":
    """平台积分流水 -> 界面积分明细行。"""
    kind = str(entry.get("kind") or "")
    ref_type = str(entry.get("refType") or "")
    note = str(entry.get("note") or "").strip()
    business = _task_name_from_note(note) if ref_type == "task" else note
    if not business:
        business = _ENTRY_BUSINESS.get(ref_type, str(entry.get("kindLabel") or "积分变动"))
    return {
        "id": str(entry.get("id") or ""),
        "type": _ENTRY_TYPE.get(kind, kind),
        "status": "processing" if kind == "freeze" else "done",
        "pointsChange": _entry_amount(entry),
        "business": business,
        "businessContext": dict(entry.get("businessContext") or {}),
        "interface": dict(entry.get("interface") or {}),
        "refType": ref_type,
        "refId": str(entry.get("refId") or ""),
        "createdAt": str(entry.get("createdAt") or ""),
    }


def _entry_amount(entry: Mapping[str, Any]) -> str:
    """积分变化取可用变化，可用变化为零时退回冻结变化。

    结算与旧周期失效只动冻结额度，availableDelta 为 0；只读可用变化就会显示成「0」。
    """
    available = str(entry.get("availableDelta") or "").strip()
    if available and points(available) != 0:
        return available
    frozen = str(entry.get("frozenDelta") or "").strip()
    if frozen and points(frozen) != 0:
        return frozen
    return available or "0.000"


def _task_name_from_note(note: object) -> str:
    """从流水备注里取任务名；平台通用文案与裸「任务预冻结」不算业务名。"""
    text = str(note or "").strip()
    if not text or text == _TASK_SETTLE_NOTE:
        return ""
    if text.startswith(_TASK_FREEZE_PREFIX):
        return text[len(_TASK_FREEZE_PREFIX):].lstrip(" ·").strip()
    return text


def _mock_entry_view(entry: Mapping[str, Any]) -> "dict[str, Any]":
    """本地模拟流水 -> 与 live 一致的界面行，两条通路的合并结果因此相同。"""
    row = dict(entry)
    row["pointsChange"] = _mock_points_change(entry)
    ref_type = str(entry.get("refType") or "")
    note = str(entry.get("business") or "").strip()
    if ref_type == "task":
        row["business"] = _task_name_from_note(note) or _ENTRY_BUSINESS.get(ref_type, note or "任务消费")
    row["refType"] = ref_type
    row["refId"] = str(entry.get("refId") or "")
    row["createdAt"] = str(entry.get("createdAt") or "")
    return row


def _mock_points_change(entry: Mapping[str, Any]) -> str:
    """本地历史数据里的冻结行可能写作「冻结 12.000」；统一成 live 的负数口径。"""
    raw = str(entry.get("pointsChange") or "").strip()
    if raw:
        try:
            Decimal(raw)
            return raw
        except (InvalidOperation, ValueError):
            pass
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return raw or "0.000"
    value = match.group(0)
    if str(entry.get("type") or "") == "freeze" and not value.startswith("-"):
        value = "-" + value
    return value


def _task_business(entries: "list[dict[str, Any]]", fallback: str) -> str:
    """业务名优先取冻结行（形如「任务预冻结 · 关键词视频搜索」）里的任务名。"""
    ordered = sorted(entries, key=lambda item: 0 if str(item.get("type") or "") == "freeze" else 1)
    for entry in ordered:
        name = _task_name_from_note(entry.get("business"))
        if name:
            return name
    return fallback


def _task_row(ref_id: str, entries: "list[dict[str, Any]]") -> "dict[str, Any]":
    """一个任务的合并行：状态、金额与时间取优先级最高的那条流水。"""
    winner = entries[0]
    for entry in entries[1:]:
        if _TASK_ROW_PRIORITY.get(str(entry.get("type") or ""), 0) > _TASK_ROW_PRIORITY.get(str(winner.get("type") or ""), 0):
            winner = entry
    row = dict(winner)
    row["business"] = _task_business(entries, str(winner.get("business") or ""))
    for field in ("businessContext", "interface"):
        row[field] = next((dict(entry[field]) for entry in entries if entry.get(field)), {})
    row["refType"] = "task"
    row["refId"] = ref_id
    return row


def _merge_task_rows(items: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """把同一任务的冻结与后续结果合并成一行，其余流水原样保留，最后按时间倒序。

    只有组内确实出现过冻结行的任务才合并：既收敛了「处理中 + 已结算」两行，
    也不会把恰好共用 refId 的其他流水（例如本地模拟的周期发放与失效）并到一起。
    """
    groups: "dict[str, list[dict[str, Any]]]" = {}
    for item in items:
        if str(item.get("refType") or "") == "task" and str(item.get("refId") or ""):
            groups.setdefault(str(item["refId"]), []).append(item)
    mergeable = {
        ref_id for ref_id, entries in groups.items()
        if any(str(entry.get("type") or "") == "freeze" for entry in entries)
    }
    rows: "list[dict[str, Any]]" = []
    emitted: "set[str]" = set()
    for item in items:
        ref_id = str(item.get("refId") or "") if str(item.get("refType") or "") == "task" else ""
        if ref_id not in mergeable:
            rows.append(item)
            continue
        if ref_id in emitted:
            continue
        emitted.add(ref_id)
        rows.append(_task_row(ref_id, groups[ref_id]))
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return rows


def _filter_ledger(rows: "list[dict[str, Any]]", entry_type: object) -> "list[dict[str, Any]]":
    """按界面类型筛选：合并后消耗对应已结算、冻结对应处理中。"""
    wanted = _ENTRY_KIND.get(str(entry_type or ""))
    if not wanted:
        return rows
    return [row for row in rows if str(row.get("type") or "") == wanted]


def _live_order_view(order: Mapping[str, Any]) -> "dict[str, Any]":
    """平台订单 -> 界面订单行；planId 由 planCode 映射。"""
    amount_fen = int(order.get("amountFen") or 0)
    status = _ORDER_STATUS.get(str(order.get("status") or ""), str(order.get("status") or ""))
    payment = dict(order["payment"]) if isinstance(order.get("payment"), Mapping) else None
    qr_image = None
    if (payment and payment.get("status") == "ready" and not payment.get("mock")
            and status == "created" and str(payment.get("codeUrl") or "").startswith("weixin://")):
        output = io.BytesIO()
        qrcode.make(payment["codeUrl"], image_factory=qrcode.image.svg.SvgPathFillImage,
                    border=4).save(output)
        qr_image = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()
    return {
        "orderId": str(order.get("orderId") or ""),
        "status": status,
        "payment": payment,
        "qrImage": qr_image,
        "expiresAt": str(order.get("expiresAt") or ""),
        "reused": bool(order.get("reused")),
        "planId": str(order.get("planCode") or ""),
        "planName": str(order.get("planName") or ""),
        "priceCents": amount_fen,
        "priceText": "%d.%02d" % (amount_fen // 100, amount_fen % 100),
        "points": points_text(order.get("points")),
        "payChannel": str(order.get("payChannel") or ""),
        "createdAt": str(order.get("createdAt") or ""),
        "paidAt": str(order.get("paidAt") or ""),
    }


__all__ = [
    "API_PREFIX",
    "DEFAULT_PLATFORM_MODE",
    "MOCK_CODE",
    "PLAN_CAPABILITIES",
    "PLAN_CATALOG",
    "PLAN_ENTITLEMENTS",
    "POINT_SPECS",
    "PUBLIC_ERROR_MESSAGES",
    "PlatformWorkbenchClient",
    "MockPlatform",
    "SubscriptionError",
    "SubscriptionService",
    "SubscriptionStore",
    "charge_points",
    "mask_phone",
    "normalize_platform_mode",
    "plan_view",
    "plans_view",
    "pay_channel_id",
    "points",
    "points_text",
    "public_error_code",
]
