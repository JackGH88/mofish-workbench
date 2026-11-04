"""付费能力接入层：四类计费能力统一经创作服务 API 平台的 /workbench/v1。

工作台不再持有任何供应商或运营方 Key：音视频转写、数据查询、封面生成与
文本生成都用当前登录用户的会话凭证调用平台，积分是否足够与应该扣多少一律
由平台判定。模拟通路只服务账户页演示，付费能力统一提示需切换到真实平台。

流程与平台契约一致：免费报价 → 带 Idempotency-Key 提交 → 轮询同一任务 →
取结果。``reconciling`` 表示上游结果未知，继续查同一个任务，绝不重发。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .subscription import public_error_code, SubscriptionError, SubscriptionService

logger = logging.getLogger("douyin-downloader")

# 视频转文案已拆成两个独立、独立计费的服务：
#   链接 → svc.video_parse（按次）；本地 MP3 直传 → svc.audio_transcription（按分钟）。
SPEC_VIDEO_PARSE = "svc.video_parse"
SPEC_AUDIO_TRANSCRIPTION = "svc.audio_transcription"
# 已下线的单一转写规格，仅保留常量供历史数据识别，不再用于新调用。
SPEC_TRANSCRIPTION = "svc.transcription"
# 音频直传限制（与平台一致）：仅 MP3、≤ 50 MB、≤ 60 分钟。
AUDIO_CONTENT_TYPE = "audio/mpeg"
AUDIO_MAX_BYTES = 50 * 1024 * 1024

# 文本规格：平台已按用途拆成六个规格，一次调用计一次单价。旧的单一规格
# （svc.text.generate）已下架，再用它会得到「该能力尚未配置…暂不开放收费调用」
# 而拿不到报价，因此这里必须按场景取规格。
SPEC_TEXT_BY_SCENE: "dict[str, str]" = {
    "script_rewrite": "svc.text.script_rewrite",
    "structure_analysis": "svc.text.structure_analysis",
    "title_copy": "svc.text.title_copy",
    "review_factors": "svc.text.review_factors",
    "radar_topics": "svc.text.radar_topics",
    "hook_match": "svc.text.hook_match",
}
# 文本能力按次计费：报价数量固定为 1，与平台 create_points_task 的 quantity="1" 对齐。
SPEC_TEXT_QUANTITY = "1"

# 封面规格：平台按「方式 + 比例」区分规格号，一次请求一个比例。
SPEC_IMAGE: "dict[tuple[str, str], str]" = {
    ("text-to-image", "3:4"): "svc.image.text_to_image.3-4",
    ("text-to-image", "4:3"): "svc.image.text_to_image.4-3",
    ("image-to-image", "3:4"): "svc.image.image_to_image.3-4",
    ("image-to-image", "4:3"): "svc.image.image_to_image.4-3",
}

# 数据能力 -> 平台规格号，与平台 catalog 一致。
DATA_SPEC_BY_CAPABILITY: "dict[str, str]" = {
    "profile": "svc.data.profile",
    "posts": "svc.data.posts",
    "video": "svc.data.video",
    "search": "svc.data.search",
    "low_fans": "svc.data.low_fans",
    "trends": "svc.data.trends",
    "suggestions": "svc.data.suggestions",
}

# 文本场景：与平台 text_service.SCENES 对齐，只能取这些值。
SCENES = (
    "script_rewrite", "structure_analysis", "title_copy",
    "review_factors", "radar_topics", "hook_match",
)
DEFAULT_SCENE = "script_rewrite"
# 一轮生成的输出上限。平台侧默认 1024，但上游是推理模型：思考 token 也算在
# completion 里，1024 常常在真正输出前就用完，结果是一个 finishReason=length 的
# 空正文（选题建议、脚本仿写都会这样「成功」却拿不到内容）。这里给足余量；
# 上限只抬高天花板，不多计费（文本按次计费），也不会强制模型写满。
DEFAULT_MAX_TOKENS = 8192
MAX_TOKENS_CAP = 32768

POLL_INTERVAL_SECONDS = 3.0
POLL_BUDGET_SECONDS = 600.0
MAX_BACKOFF_SECONDS = 60.0
# 提交收费请求的网络重试次数：重试沿用同一个 Idempotency-Key，平台幂等去重。
SUBMIT_ATTEMPTS = 3
# 轮询中的「暂时态」错误码：结果未知，继续查同一个任务，不判失败也不重发。
TRANSIENT_POLL_CODES = ("timeout", "upstream_unavailable", "rate_limited", "status_pending")


def image_spec(variant: object, ratio: object) -> str:
    """封面规格号；未知组合回退到默认比例，避免静默提交到错规格。"""
    key = (str(variant or "text-to-image"), str(ratio or "3:4"))
    return SPEC_IMAGE.get(key) or SPEC_IMAGE[("text-to-image", "3:4")]


def data_spec(capability: object) -> str:
    return DATA_SPEC_BY_CAPABILITY.get(str(capability or "")) or ""


def normalize_scene(scene: object) -> str:
    text = str(scene or "").strip()
    return text if text in SCENES else DEFAULT_SCENE


def text_spec(scene: object) -> str:
    """文本场景对应的平台规格号；未知场景返回空串，由调用方明确拒绝。"""
    return SPEC_TEXT_BY_SCENE.get(str(scene or "").strip(), "")


def new_idempotency_key() -> str:
    """收费请求的幂等标识：重试沿用同一个，不会新建任务重复付费。"""
    return "wb-" + uuid.uuid4().hex


def _points_text(value: object) -> str:
    """报价积分统一成三位定点文本；非法值返回空串，由调用方决定是否放弃上限。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Decimal(text).quantize(Decimal("0.001")))
    except Exception:  # noqa: BLE001 - 脏值不阻断提交，只是不设上限
        return ""


async def quote(client: Any, spec_id: str, quantity: object,
                *, max_charge_points: Optional[str] = None) -> "dict[str, Any]":
    """免费报价：拿到 quoteId 与 estimatedPoints，作为本次的授权上限。"""
    try:
        return await client.quote(service_id=spec_id, quantity=str(quantity),
                                  max_charge_points=max_charge_points)
    except SubscriptionError as exc:
        names = {SPEC_VIDEO_PARSE: "视频解析", SPEC_AUDIO_TRANSCRIPTION: "音频转写"}
        if exc.code == "service_unavailable" and spec_id in names:
            raise SubscriptionError(
                exc.code,
                f"当前接口平台尚未开放“{names[spec_id]}”或未发布有效价格。请联系平台管理员启用后重试，费用以平台报价为准。",
                status_code=exc.status_code, platform_code=exc.platform_code, details=exc.details,
            ) from exc
        raise


def quote_ceiling(quote_view: Mapping[str, Any]) -> Optional[str]:
    """报价积分直接作为本次授权上限；拿不到就不设上限。"""
    return _points_text(quote_view.get("pointsAmount")) or None


def task_id_of(payload: Mapping[str, Any]) -> str:
    """平台任务视图的任务号字段是 id（不是 taskId）。"""
    return str((payload or {}).get("id") or (payload or {}).get("taskId") or "")


async def poll_task(client: Any, task_id: str, *, interval: float = POLL_INTERVAL_SECONDS,
                    budget: float = POLL_BUDGET_SECONDS) -> "Mapping[str, Any]":
    """轮询同一个任务直到终态；reconciling 继续查，不当失败也不重发。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + budget
    while True:
        try:
            view = await client.task(task_id)
        except SubscriptionError as exc:
            if exc.code in TRANSIENT_POLL_CODES:
                # 暂时不可达/超时/限流：结果未知，继续查同一个任务。
                # 只要还在预算内就不判失败、也不重发；超出预算交回上层按待确认处理。
                if loop.time() >= deadline:
                    raise SubscriptionError("status_pending", "任务结果暂未确认，请稍后继续查询。") from None
                retry = (_points_seconds(getattr(exc, "details", {}).get("retryAfterSeconds"))
                         if exc.code == "rate_limited" else None)
                await asyncio.sleep(min(retry or interval, MAX_BACKOFF_SECONDS))
                continue
            raise
        status = str((view or {}).get("status") or "")
        if status in {"succeeded", "failed", "cancelled"}:
            return view
        if loop.time() >= deadline:
            raise SubscriptionError("status_pending", "任务仍在处理中，请稍后继续查询。")
        await asyncio.sleep(interval)


def _points_seconds(value: object) -> Optional[float]:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


async def _call_with_retry(call: "Callable[[], Any]", *, attempts: int = SUBMIT_ATTEMPTS,
                           interval: float = 1.0) -> "Mapping[str, Any]":
    """执行一次计费链路调用（报价或提交）：暂时性失败时重试。

    报价与提交走的是同一个「用户 + workbench」限流窗口，被账户页读取挤到 429 时
    应该重试，而不是把这一轮采集/生成直接判失败。退避优先采用平台返回的
    retryAfterSeconds；提交请求沿用同一个 Idempotency-Key，平台幂等去重，不会重复计费。
    鉴权/余额/校验类错误立即抛出，不做无谓重试。
    """
    last: Optional[SubscriptionError] = None
    total = max(1, attempts)
    for attempt in range(total):
        try:
            return await call()
        except SubscriptionError as exc:
            if exc.code not in TRANSIENT_POLL_CODES:
                raise
            last = exc
            if attempt + 1 >= total:
                break
            retry = (_points_seconds(getattr(exc, "details", {}).get("retryAfterSeconds"))
                     if exc.code == "rate_limited" else None)
            await asyncio.sleep(min(retry or interval * (attempt + 1), MAX_BACKOFF_SECONDS))
    raise last or SubscriptionError("upstream_unavailable")


async def quote_with_retry(client: Any, spec_id: str, quantity: object,
                           *, max_charge_points: Optional[str] = None) -> "dict[str, Any]":
    """报价：同样可能被读取流量挤到 429 的计费调用，按与提交一致的策略重试。"""
    return await _call_with_retry(
        lambda: quote(client, spec_id, quantity, max_charge_points=max_charge_points)
    )


def require_success(view: Mapping[str, Any]) -> None:
    """终态若不是成功，按平台错误码抛出脱敏中文错误。"""
    status = str((view or {}).get("status") or "")
    if status == "succeeded":
        return
    if status == "cancelled":
        raise SubscriptionError("task_cancelled")
    code = public_error_code((view or {}).get("errorCode"))
    raise SubscriptionError(code)


async def _finish(client: Any, task_view: Mapping[str, Any]) -> "dict[str, Any]":
    """轮询到终态并取结果，返回 (结果载荷, 费用文本, taskId)。"""
    task_id = task_id_of(task_view)
    if not task_id:
        raise SubscriptionError("upstream_unavailable")
    view = await poll_task(client, task_id)
    require_success(view)
    result = await client.task_result(task_id)
    payload = result.get("result") if isinstance(result.get("result"), Mapping) else {}
    charged = result.get("chargedPoints", view.get("chargedPoints"))
    return {
        "taskId": task_id,
        "payload": payload,
        "chargedPoints": _points_text(charged),
        "frozenPoints": _points_text(view.get("frozenPoints")),
        "settlementStatus": str(result.get("settlementStatus") or view.get("settlementStatus") or ""),
    }


# ------------------------------------------------------------------ 上传 / 转写

async def upload_media(service: SubscriptionService, path: object, *, filename: Optional[str] = None) -> str:
    """上传本地素材换取平台素材号；不单独计费。"""
    client = service.business_client()
    upload = await client.upload_file(path, filename=filename)
    upload_id = str((upload or {}).get("id") or "")
    if not upload_id:
        raise SubscriptionError("upstream_unavailable")
    return upload_id


def transcription_quantity(duration_seconds: object) -> str:
    """按平台核验的可信时长折算计费分钟数，必须与平台完全一致。

    平台按 usage_quantity(ceil(秒)) = max(ceil(秒), 1) / 60.0 折分钟，并用
    str(float) 精度校验报价数量；这里用同一表达式、同一精度，避免被拒绝。
    """
    try:
        seconds = float(duration_seconds)
    except (TypeError, ValueError):
        seconds = 0.0
    if not (seconds > 0) or not math.isfinite(seconds):
        seconds = 1.0
    return str(max(math.ceil(seconds), 1) / 60.0)


async def upload_audio(service: SubscriptionService, path: object, *, filename: Optional[str] = None,
                       attempts: int = 3) -> "dict[str, Any]":
    """本地 MP3 直传并核验：create → PUT → complete，返回 uploadId 与可信时长。

    签名过期、对象未落地或上传中断时重建上传记录与地址（全程不收费），
    绝不在核验通过前把素材交给转写。
    """
    client = service.business_client()
    target = Path(path)
    if not target.is_file() or target.stat().st_size == 0:
        raise SubscriptionError("unsupported_input", "找不到可上传的音频文件。", status_code=400)
    data = target.read_bytes()
    if len(data) > AUDIO_MAX_BYTES:
        raise SubscriptionError("unsupported_input", "音频超过 50 MB 上限。", status_code=413)

    last: Optional[SubscriptionError] = None
    for _ in range(max(1, int(attempts))):
        created = await client.audio_upload_create(filename=filename or target.name)
        upload = created.get("upload") if isinstance(created.get("upload"), Mapping) else {}
        upload_id = str(upload.get("id") or "")
        upload_url = str(created.get("uploadUrl") or "")
        headers = created.get("headers") if isinstance(created.get("headers"), Mapping) else {"Content-Type": AUDIO_CONTENT_TYPE}
        if not upload_id or not upload_url:
            raise SubscriptionError("upstream_unavailable")
        status_code = await client.put_audio(upload_url, data=data, headers=headers)
        if status_code not in (200, 201, 204):
            # 直传地址过期或签名无效：重建上传记录再试，不收费。
            last = SubscriptionError("upload_failed", "音频上传失败，已重新获取上传地址。", status_code=status_code or 502)
            continue
        verified = await _complete_audio_upload(client, upload_id)
        if verified is not None:
            return verified
        last = SubscriptionError("upload_failed", "音频核验未通过，正在重新上传。")
    raise last or SubscriptionError("upstream_unavailable")


async def _complete_audio_upload(client: Any, upload_id: str) -> "dict[str, Any] | None":
    """核验直传结果；对象尚未落到存储时短暂重试 complete，不改上传记录。"""
    for attempt in range(3):
        try:
            payload = await client.audio_upload_complete(upload_id)
        except SubscriptionError as exc:
            if exc.code == "object_missing" and attempt < 2:
                await asyncio.sleep(1.0)
                continue
            raise
        record = payload.get("upload") if isinstance(payload.get("upload"), Mapping) else {}
        status = str(record.get("status") or "")
        if status == "ready" and record.get("durationSeconds"):
            return {
                "uploadId": upload_id,
                "durationSeconds": float(record.get("durationSeconds") or 0),
                "sizeBytes": int(record.get("size") or 0),
                "status": status,
            }
        if status == "failed":
            detail = record.get("error") if isinstance(record.get("error"), Mapping) else {}
            raise SubscriptionError("unsupported_input", str(detail.get("message") or "音频核验未通过，请检查素材后重试。"), status_code=422)
        if attempt < 2:
            await asyncio.sleep(1.0)
    return None


# ------------------------------------------------------------------ 数据查询
#
# 一次数据查询就是一个计费单位：幂等键只保证「同一个键」不重复建单，换一个键就是
# 一笔新任务。调度被并发触发、进程反复重启、或外部脚本循环调用时，同一个博主的
# 作品列表会在几十秒内打进来几十次——各建一个任务、各自冻结积分，把用户自己的
# 计费额度打满（平台按用户分桶限流，随后连报价都被 429）。
# 这里对「同一凭证 + 同参数」的数据查询做两层收敛：
#   * 同参数在途合并：并发相同查询共用一个平台调用，结果分发给所有等待者；
#   * 极短时间内的结果复用：重复触发直接复用上一份结果，不再新建计费任务。
QUERY_DEDUPE_SECONDS = 120.0
_query_inflight: "dict[tuple, asyncio.Future]" = {}
_query_recent: "dict[tuple, tuple[float, dict[str, Any]]]" = {}


def _query_signature(service: Any, capability: str, params: "Mapping[str, Any] | None",
                     cursor: Optional[str]) -> "tuple | None":
    """同参数查询的收敛键；取不到会话凭证时返回 None（不做去重）。

    键里带凭证指纹：不同用户即使查询同一博主，也各自取各自的平台结果。
    """
    token = ""
    reader = getattr(service, "token", None)
    if callable(reader):
        try:
            token = str(reader() or "")
        except Exception:  # noqa: BLE001 - 凭证读不出来就不去重，走正常报错路径
            token = ""
    if not token:
        return None
    payload = json.dumps(
        {"capability": str(capability), "params": dict(params or {}), "cursor": cursor or ""},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = hashlib.sha256((token + "\x00" + payload).encode("utf-8")).hexdigest()
    return ("data", digest)


def reset_query_dedupe() -> None:
    """清空查询去重状态；供测试与显式重置使用。"""
    _query_inflight.clear()
    _query_recent.clear()


def _recent_query(key: tuple) -> "dict[str, Any] | None":
    entry = _query_recent.get(key)
    if entry is None:
        return None
    stamp, outcome = entry
    if time.monotonic() - stamp >= QUERY_DEDUPE_SECONDS:
        _query_recent.pop(key, None)
        return None
    return outcome


def _remember_query(key: tuple, outcome: "dict[str, Any]") -> None:
    now = time.monotonic()
    for stale in [item for item, (stamp, _) in _query_recent.items() if now - stamp >= QUERY_DEDUPE_SECONDS]:
        _query_recent.pop(stale, None)
    _query_recent[key] = (now, outcome)


def _reused_view(outcome: "Mapping[str, Any]") -> "dict[str, Any]":
    """复用上一份结果：不新建任务，也不把同一笔消耗再计一次。"""
    return {
        "page": outcome.get("page") if isinstance(outcome.get("page"), Mapping) else {},
        "taskId": str(outcome.get("taskId") or ""),
        "chargedPoints": "0.000",
        "frozenPoints": "0.000",
        "reused": True,
    }


async def _coalesce_submit(key: tuple, submit: "Callable[[], Any]") -> "tuple[Any, bool]":
    """同参数在途合并：并发相同提交只走一次平台，返回 (结果, 是否由本调用发起)。"""
    pending = _query_inflight.get(key)
    if pending is not None:
        return await pending, False
    pending = asyncio.get_running_loop().create_future()
    _query_inflight[key] = pending
    try:
        value = await submit()
    except BaseException as exc:  # noqa: BLE001 - 取消也要唤醒等待者并清理
        _query_inflight.pop(key, None)
        pending.set_exception(exc)
        pending.exception()  # 主动取值，避免「exception was never retrieved」告警
        raise
    _query_inflight.pop(key, None)
    pending.set_result(value)
    return value, True


async def query_data(service: SubscriptionService, capability: str, params: "Mapping[str, Any] | None" = None,
                     *, cursor: Optional[str] = None, business_context: Optional[Mapping[str, Any]] = None) -> "dict[str, Any]":
    """查询一页：一次查询即一个计费单位，翻页用平台下发的不透明游标。

    同凭证同参数在极短时间内重复触发时复用上一份结果，不重复提交计费任务。
    """
    business_context = dict(business_context or {})
    spec_id = data_spec(capability)
    if not spec_id:
        raise SubscriptionError("unsupported_input")
    signature = _query_signature(service, capability, params, cursor)
    if signature is None:
        # 取不到会话凭证（测试替身或异常态）：保持原行为，不做收敛。
        return await _submit_query(service, capability, params, cursor=cursor, business_context=business_context)
    cached = _recent_query(signature)
    if cached is not None:
        logger.info("query_data_reused capability=%s task=%s", capability, cached.get("taskId"))
        return _reused_view(cached)
    outcome, submitted = await _coalesce_submit(
        signature, lambda: _submit_query(service, capability, params, cursor=cursor, business_context=business_context),
    )
    _remember_query(signature, outcome)
    return outcome if submitted else _reused_view(outcome)


async def _submit_query(service: SubscriptionService, capability: str, params: "Mapping[str, Any] | None",
                        *, cursor: Optional[str] = None, business_context: Optional[Mapping[str, Any]] = None) -> "dict[str, Any]":
    """真正提交一次查询：报价 → 提交（重试沿用同一个幂等键）→ 轮询 → 取结果。"""
    client = service.business_client()
    quoted = await quote_with_retry(client, data_spec(capability), "1")
    key = new_idempotency_key()
    created = await _call_with_retry(lambda: client.data_query(
        capability=capability, params=dict(params or {}), cursor=cursor or None,
        quote_id=quoted.get("quoteId"), max_charge_points=quote_ceiling(quoted),
        idempotency_key=key,
        **({"business_context": dict(business_context)} if business_context else {}),
    ))
    outcome = await _finish(client, created)
    page = outcome["payload"]
    return {
        "page": page if isinstance(page, Mapping) else {},
        "taskId": outcome["taskId"],
        "chargedPoints": outcome["chargedPoints"],
        "frozenPoints": outcome["frozenPoints"],
    }


# ------------------------------------------------------------------ 封面生成

async def generate_image(service: SubscriptionService, *, prompt: str, ratio: str, count: int = 1,
                         variant: str = "text-to-image",
                         reference_upload_ids: Optional["list[str]"] = None,
                         business_context: Optional[Mapping[str, Any]] = None,
                         wait_for_result: bool = True) -> "dict[str, Any]":
    """一次封面生成：一个比例一个任务，按成功张数结算。"""
    business_context = dict(business_context or {})
    client = service.business_client()
    spec_id = image_spec(variant, ratio)
    quoted = await quote_with_retry(client, spec_id, str(int(count)))
    key = new_idempotency_key()
    created = await _call_with_retry(lambda: client.image(
        quote_id=quoted.get("quoteId"), prompt=prompt, aspect_ratio=ratio, count=int(count),
        variant=variant, reference_upload_ids=list(reference_upload_ids) if reference_upload_ids else None,
        max_charge_points=quote_ceiling(quoted), idempotency_key=key,
        **({"business_context": business_context} if business_context else {}),
    ))
    if not wait_for_result:
        return {"taskId": task_id_of(created), "ratio": ratio}
    outcome = await _finish(client, created)
    payload = outcome["payload"]
    return {
        "taskId": outcome["taskId"],
        "ratio": ratio,
        "variant": variant,
        "requested": int(payload.get("requested") or count),
        "count": int(payload.get("count") or 0),
        "images": [dict(item) for item in (payload.get("images") or []) if isinstance(item, Mapping)],
        "chargedPoints": outcome["chargedPoints"],
    }


# ------------------------------------------------------------------ 文本生成

async def generate_text(service: SubscriptionService, *, scene: str, messages: "list[Mapping[str, Any]]",
                        model: str = "text-default",
                        temperature: Optional[float] = None, max_tokens: Optional[int] = None,
                        response_format: "Mapping[str, Any] | None" = None,
                        business_context: Optional[Mapping[str, Any]] = None) -> str:
    """一次文本生成：按真实用量计费，返回模型正文。"""
    produced = await generate_text_result(
        service, scene=scene, messages=messages, model=model,
        temperature=temperature, max_tokens=max_tokens, response_format=response_format,
        business_context=business_context,
    )
    return produced["content"]


async def generate_text_result(service: SubscriptionService, *, scene: str, messages: "list[Mapping[str, Any]]",
                        model: str = "text-default",
                               temperature: Optional[float] = None, max_tokens: Optional[int] = None,
                               response_format: "Mapping[str, Any] | None" = None,
                               business_context: Optional[Mapping[str, Any]] = None,
                               max_charge_points: Optional[str] = None,
                               resume_task_id: str = "", on_created: Any = None) -> "dict[str, Any]":
    """一次文本生成：返回正文与上游结束原因，供调用方识别「被长度截断」。"""
    client = service.business_client()
    # 规格决定价格：未知场景不能悄悄落到某个单价上，直接拒绝并给出可读原因。
    business_context = dict(business_context or {})
    normalized_scene = str(scene or "").strip()
    spec_id = text_spec(normalized_scene)
    if not spec_id:
        raise SubscriptionError("unsupported_input", "该文本用途暂未开放收费调用。", status_code=422)
    tokens = int(max_tokens or DEFAULT_MAX_TOKENS)
    if tokens <= 0 or tokens > MAX_TOKENS_CAP:
        tokens = DEFAULT_MAX_TOKENS
    normalized = [dict(item) for item in (messages or []) if isinstance(item, Mapping)]
    if resume_task_id:
        created = {"id": resume_task_id}
    else:
        quoted = await quote_with_retry(client, spec_id, SPEC_TEXT_QUANTITY)
        if max_charge_points is not None:
            amount = _points_text(quoted.get("pointsAmount"))
            ceiling = _points_text(max_charge_points)
            if not amount or not ceiling or Decimal(amount) > Decimal(ceiling):
                raise SubscriptionError("quote_changed", "积分价格已变化，请重新确认后更新。", status_code=409)
        key = new_idempotency_key()
        created = await _call_with_retry(lambda: client.text(
            quote_id=quoted.get("quoteId"), scene=normalized_scene, messages=normalized, model=model,
            temperature=temperature, max_tokens=tokens,
            response_format=dict(response_format) if response_format else None,
            max_charge_points=quote_ceiling(quoted), idempotency_key=key,
            **({"business_context": dict(business_context)} if business_context else {}),
        ))
        if on_created is not None:
            await on_created(task_id_of(created))
    outcome = await _finish(client, created)
    payload = outcome["payload"]
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SubscriptionError("content_unavailable", "模型没有返回可用的内容，请稍后重试。")
    return {"content": content, "finishReason": str(payload.get("finishReason") or "")}


__all__ = [
    "DATA_SPEC_BY_CAPABILITY",
    "SCENES",
    "SPEC_IMAGE",
    "SPEC_TEXT_BY_SCENE",
    "SPEC_TEXT_QUANTITY",
    "SPEC_VIDEO_PARSE",
    "SPEC_AUDIO_TRANSCRIPTION",
    "SPEC_TRANSCRIPTION",
    "data_spec",
    "generate_image",
    "generate_text",
    "generate_text_result",
    "image_spec",
    "new_idempotency_key",
    "normalize_scene",
    "query_data",
    "text_spec",
    "transcription_quantity",
    "upload_audio",
    "upload_media",
]
