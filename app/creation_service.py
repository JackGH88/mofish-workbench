"""旧版创作服务 /v1 客户端及公共错误定义。

工作台业务已迁移到 /workbench/v1 登录会话通路，不再从本地配置加载旧版 Key。
本模块保留协议兼容代码及共用错误类型，不读取或记录供应商 Key、采购价或
平台内部错误原文。

与平台 ``docs/工作台接入.md`` 一致的调用约定：

* 统一前缀 ``/v1``，鉴权头 ``Authorization: Bearer <创作服务 Key>``；
* 成功 ``{"ok": true, "data": {...}}``，失败 ``{"ok": false, "error": {...}, "requestId"}``；
* 收费请求带 ``Idempotency-Key``，网络重试沿用同一标识；
* ``reconciling`` 表示结果待确认，继续轮询同一任务，不重发、不当失败；
* 对外只暴露本模块定义的中文文案，平台的 ``message`` 与 ``requestId`` 只进日志。
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger("douyin-downloader")

DEFAULT_BASE_URL = "http://127.0.0.1:8010"

# 展示用的 Key 状态：与平台 /v1/me 的返回和错误码一一对应。
KEY_STATUS_LABELS: "dict[str, str]" = {
    "unconfigured": "未配置",
    "active": "可用",
    "invalid": "无效",
    "revoked": "已撤销",
    "restricted": "已受限",
    "insufficient_balance": "余额不足",
    # 下面两个不是 Key 状态，而是连接状态：限流与网络不可达都属暂时性，
    # 不能显示成「已受限」，否则用户会误以为 Key 被封而去重建。
    "busy": "请求频繁",
    "unreachable": "无法连接",
}

# 平台错误码 → 工作台对外文案。绝不透传平台原文，避免带出供应商或平台内部细节。
PUBLIC_ERROR_MESSAGES: "dict[str, str]" = {
    "invalid_key": "创作服务 Key 无效，请在个人中心确认后重新填写。",
    "permission_denied": "创作服务 Key 已被停用或账号受限，请在个人中心启用或新建 Key。",
    "insufficient_balance": "创作服务余额不足，请先充值后重试。",
    "charge_limit_exceeded": "本次费用上限低于预计费用，请提高上限后重试。",
    "rate_limited": "创作服务请求过于频繁，请稍后重试。",
    "unsupported_input": "创作服务不支持该输入，请检查内容后重试。",
    "content_unavailable": "该内容暂时无法获取，请更换后重试。",
    "upstream_unavailable": "创作服务暂时不可用，请稍后重试。",
    "image_generation_timeout": "生成超过 30 分钟，可重新生成。",
    "status_pending": "任务结果待确认，请稍后继续查询同一任务。",
    "result_expired": "该成果已过保留期，需要重新发起任务。",
    "idempotency_conflict": "同一请求标识已用于不同参数，请重新发起任务。",
    "invalid_cursor": "分页游标已失效，请重新发起查询。",
    "invalid_max_charge": "费用上限格式不正确，请重新填写。",
    "unreachable": "无法连接创作服务，请确认服务已启动后重试。",
}

# 同一个 invalid_key 里还分「无效」与「已撤销」，permission_denied 是「已受限」：
# 三类都要给出各自独立、可执行的提示，不能共用一个泛化文案。
KEY_STATUS_MESSAGES: "dict[str, str]" = {
    "invalid": "创作服务 Key 无效，请在个人中心确认后重新填写。",
    "revoked": "创作服务 Key 已被撤销，请在个人中心新建 Key 后再试。",
    "restricted": "创作服务 Key 已被停用或账号受限，请在个人中心启用或新建 Key。",
}

# 对外接口状态码：能明确区分的按语义返回，其余统一按上游不可用处理。
_STATUS_BY_CODE = {
    "invalid_key": 401,
    "permission_denied": 403,
    "insufficient_balance": 402,
    "charge_limit_exceeded": 402,
    "rate_limited": 429,
    "unreachable": 503,
    "upstream_unavailable": 502,
}

# 平台对「已撤销」与「无效」都返回 401 + invalid_key，只有文案不同；
# 这里按平台文案里的「撤销」二字区分，用于给出各自独立的提示。
_REVOKED_HINT = "撤销"

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,200}$")

# 转写能力的规格号与计费单位；链接来源时长未知，先按一个最长时长估一个授权上限。
TRANSCRIPTION_SPEC_ID = "svc.transcription"
TRANSCRIPTION_SPEC_KEY = "transcription"
DEFAULT_LINK_MAX_SECONDS = 600.0


class CreationServiceError(Exception):
    """对外安全的创作服务错误：code 与 message 都已脱敏。"""

    def __init__(self, code: str, message: str = "", *, status_code: Optional[int] = None,
                 platform_code: Optional[str] = None, retry_after: Optional[int] = None,
                 key_status: Optional[str] = None):
        resolved = (
            message
            or KEY_STATUS_MESSAGES.get(str(key_status or ""))
            or PUBLIC_ERROR_MESSAGES.get(code)
            or "创作服务调用失败，请稍后重试。"
        )
        super().__init__(resolved)
        self.code = code
        self.message = resolved
        self.status_code = status_code or _STATUS_BY_CODE.get(code, 502)
        self.platform_code = platform_code or code
        self.retry_after = retry_after
        self.key_status = key_status


def public_error_code(code: object) -> str:
    """把平台错误码收敛成本模块使用的码；未知码归为 upstream_unavailable。"""
    text = str(code or "").strip()
    return text if text in PUBLIC_ERROR_MESSAGES else "upstream_unavailable"


def normalize_base_url(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    return text or DEFAULT_BASE_URL


def creation_apply_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/console/keys-create.html"


def creation_recharge_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/console/billing.html"


def new_idempotency_key() -> str:
    """收费请求的幂等标识：重试沿用同一个，不能新建任务。"""
    return "wb-" + uuid.uuid4().hex


def is_valid_key_shape(value: object) -> bool:
    return bool(_KEY_PATTERN.match(str(value or "").strip()))


def classify_key_status(status_code: int, platform_code: str, detail_message: str = "") -> str:
    """把一次 /v1/me 失败归类成展示状态：无效 / 已撤销 / 已受限。"""
    if status_code == 401:
        return "revoked" if _REVOKED_HINT in str(detail_message or "") else "invalid"
    if status_code == 403:
        return "restricted"
    return ""


def format_cny(value: Any) -> str:
    """把元金额统一成两位小数字符串。"""
    try:
        return "%0.2f" % float(str(value))
    except (TypeError, ValueError):
        return ""


def charge_ceiling_cny(unit_price: float, seconds: float, *, headroom_minutes: float = 1.0) -> str:
    """按「预估最长时长 × 每分钟单价」算一个授权上限。

    平台按 ``ceil(秒数) / 60`` 折算分钟，所以这里同样向上取整到分钟，
    再多留一点余量，避免刚好卡在边界上把正常时长判成超上限。
    """
    price = float(unit_price or 0)
    if price <= 0:
        return ""
    minutes = math.ceil(max(float(seconds or 0), 0.0)) / 60.0
    return "%0.2f" % (price * (minutes + max(0.0, headroom_minutes)))


async def transcription_price(client: "CreationServiceClient") -> "dict[str, Any]":
    """读取转写能力的已发布单价（免费 /v1/services，不使用任何付费生成）。"""
    data = await client.services()
    for item in data.get("items") or []:
        if str(item.get("specId") or "") != TRANSCRIPTION_SPEC_ID:
            continue
        try:
            unit_price = float(str(item.get("unitPrice") or 0))
        except (TypeError, ValueError):
            unit_price = 0.0
        return {
            "unitPrice": unit_price,
            "unitPriceText": format_cny(item.get("unitPriceText") or unit_price),
            "unitLabel": str(item.get("unitLabel") or "分钟"),
            "billingRule": str(item.get("billingRule") or ""),
        }
    return {"unitPrice": 0.0, "unitPriceText": "", "unitLabel": "分钟", "billingRule": ""}


class CreationServiceClient:
    """同步调用风格保留在内部；对外只用 async，方便在 FastAPI 里直接 await。"""

    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0,
                 client: Optional[Any] = None):
        self._api_key = str(api_key or "").strip()
        self._base_url = normalize_base_url(base_url)
        self._timeout = timeout
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self, *, idempotency_key: Optional[str] = None, json_body: bool = True) -> "dict[str, str]":
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._api_key:
            raise CreationServiceError("unconfigured", "尚未配置创作服务 Key。", status_code=400)
        if self._client is not None:
            return await self._client.request(method, self._base_url + path, **kwargs)
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - 依赖缺失属部署问题
            raise CreationServiceError("unreachable", "缺少网络请求依赖，无法调用创作服务。") from exc
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await client.request(method, self._base_url + path, **kwargs)

    async def _request(self, method: str, path: str, *, json: Any = None,
                       idempotency_key: Optional[str] = None, **kwargs: Any) -> Any:
        """发一次 /v1 请求并解信封；失败统一抛 CreationServiceError。"""
        headers = self._headers(idempotency_key=idempotency_key, json_body=json is not None)
        try:
            response = await self._send(method, path, headers=headers, json=json, **kwargs)
        except CreationServiceError:
            raise
        except Exception as exc:  # 网络层失败：不重试业务，交由调用方决定
            logger.warning("creation_service_unreachable method=%s path=%s error=%s", method, path, type(exc).__name__)
            raise CreationServiceError("unreachable") from exc

        payload: Any
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - 非 JSON 响应统一按上游异常处理
            payload = None

        if getattr(response, "status_code", 0) == 200 and isinstance(payload, Mapping) and payload.get("ok") is True:
            data = payload.get("data")
            return data if isinstance(data, Mapping) else (data or {})

        raise self._error_from_response(response, payload)

    def _error_from_response(self, response: Any, payload: Any) -> CreationServiceError:
        status_code = int(getattr(response, "status_code", 0) or 0)
        error = payload.get("error") if isinstance(payload, Mapping) and isinstance(payload.get("error"), Mapping) else {}
        platform_code = str(error.get("code") or "")
        detail_message = str(error.get("message") or "")
        request_id = payload.get("requestId") if isinstance(payload, Mapping) else None
        code = public_error_code(platform_code)
        retry_after = None
        details = error.get("details") if isinstance(error, Mapping) else None
        if isinstance(details, Mapping) and details.get("retryAfterSeconds") is not None:
            try:
                retry_after = int(details["retryAfterSeconds"])
            except (TypeError, ValueError):
                retry_after = None
        key_status = classify_key_status(status_code, platform_code, detail_message)
        # 只记平台错误码与追踪标识，不记平台文案、Key 或任何供应商信息。
        logger.warning(
            "creation_service_error status=%s platform_code=%s request_id=%s",
            status_code, platform_code or "unknown", request_id or "-",
        )
        return CreationServiceError(
            code,
            status_code=status_code or None,
            platform_code=platform_code,
            retry_after=retry_after,
            key_status=key_status or None,
        )

    # ------------------------------------------------------------------ 免费接口

    async def me(self) -> "dict[str, Any]":
        return await self._request("GET", "/v1/me")

    async def wallet(self) -> "dict[str, Any]":
        return await self._request("GET", "/v1/wallet")

    async def services(self) -> "dict[str, Any]":
        return await self._request("GET", "/v1/services")

    async def usage(self) -> "dict[str, Any]":
        return await self._request("GET", "/v1/usage")

    async def quote(self, **body: Any) -> "dict[str, Any]":
        return await self._request("POST", "/v1/quotes", json=body)

    # ------------------------------------------------------------------ 转写

    async def create_transcription(self, *, url: Optional[str] = None, upload_id: Optional[str] = None,
                                   max_charge_cny: Optional[str] = None, local_task_id: Optional[str] = None,
                                   account_label: Optional[str] = None,
                                   idempotency_key: Optional[str] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {}
        if url:
            body["url"] = url
        if upload_id:
            body["uploadId"] = upload_id
        if max_charge_cny:
            body["max_charge_cny"] = max_charge_cny
        if local_task_id:
            body["localTaskId"] = local_task_id
        if account_label:
            body["accountLabel"] = account_label
        return await self._request("POST", "/v1/transcriptions", json=body,
                                   idempotency_key=idempotency_key or new_idempotency_key())

    # ------------------------------------------------------------------ 上传

    async def upload_media(self, path: Path, *, filename: Optional[str] = None,
                           content_type: Optional[str] = None) -> "dict[str, Any]":
        """上传本地音视频素材，返回 upload.id；不单独收业务费。"""
        if not self._api_key:
            raise CreationServiceError("unconfigured", "尚未配置创作服务 Key。", status_code=400)
        target = Path(path)
        if not target.is_file():
            raise CreationServiceError("unsupported_input", "本地素材不存在，无法上传。", status_code=400)
        headers = self._headers(json_body=False)
        try:
            with target.open("rb") as handle:
                files = {"file": (filename or target.name, handle, content_type or "application/octet-stream")}
                response = await self._send("POST", "/v1/uploads", headers=headers, files=files)
        except CreationServiceError:
            raise
        except Exception as exc:
            logger.warning("creation_service_upload_failed error=%s", type(exc).__name__)
            raise CreationServiceError("unreachable") from exc
        payload = None
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = None
        if int(getattr(response, "status_code", 0) or 0) == 200 and isinstance(payload, Mapping) and payload.get("ok") is True:
            data = payload.get("data") or {}
            upload = data.get("upload") if isinstance(data, Mapping) else None
            return upload if isinstance(upload, Mapping) else {}
        raise self._error_from_response(response, payload)

    # ------------------------------------------------------------------ 数据

    async def data_query(self, *, capability: str, params: "dict[str, Any]", cursor: Optional[str] = None,
                         max_charge_cny: Optional[str] = None,
                         idempotency_key: Optional[str] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"capability": capability, "params": dict(params or {})}
        if cursor:
            body["cursor"] = cursor
        if max_charge_cny:
            body["max_charge_cny"] = max_charge_cny
        return await self._request("POST", "/v1/data/douyin/query", json=body,
                                   idempotency_key=idempotency_key or new_idempotency_key())

    # ------------------------------------------------------------------ 图片

    async def create_images(self, *, prompt: str, aspect_ratios: "list[str]",
                            counts: Optional["dict[str, int]"] = None, variant: str = "text-to-image",
                            reference_upload_ids: Optional["list[str]"] = None,
                            idempotency_key: Optional[str] = None) -> "dict[str, Any]":
        body: "dict[str, Any]" = {"prompt": prompt, "aspectRatios": list(aspect_ratios or []), "variant": variant}
        if counts:
            body["counts"] = dict(counts)
        if reference_upload_ids:
            body["referenceUploadIds"] = list(reference_upload_ids)
        return await self._request("POST", "/v1/images/generations", json=body,
                                   idempotency_key=idempotency_key or new_idempotency_key())

    # ------------------------------------------------------------------ 任务

    async def task(self, task_id: str) -> "dict[str, Any]":
        return await self._request("GET", "/v1/tasks/" + str(task_id))

    async def task_result(self, task_id: str) -> "dict[str, Any]":
        return await self._request("GET", "/v1/tasks/" + str(task_id) + "/result")

    async def cancel_task(self, task_id: str) -> "dict[str, Any]":
        return await self._request("POST", "/v1/tasks/" + str(task_id) + "/cancel")

    # ------------------------------------------------------------------ 受控成果下载

    async def download_asset(self, asset_path_or_url: str, target: Path, *, timeout: float = 120.0) -> Path:
        """按受控地址下载成果：带 Key 跟随 302，不缓存跳转结果，也不记签名地址。"""
        if not self._api_key:
            raise CreationServiceError("unconfigured", "尚未配置创作服务 Key。", status_code=400)
        url = str(asset_path_or_url or "").strip()
        if not url:
            raise CreationServiceError("unsupported_input", "缺少可下载的成果地址。", status_code=400)
        if not url.startswith("http"):
            url = self._base_url + ("" if url.startswith("/") else "/") + url
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers(json_body=False)
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise CreationServiceError("unreachable", "缺少网络请求依赖，无法下载成果。") from exc
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        payload = None
                        try:
                            payload = response.json()
                        except Exception:  # noqa: BLE001
                            payload = None
                        raise self._error_from_response(response, payload)
                    with destination.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
        except CreationServiceError:
            raise
        except Exception as exc:
            logger.warning("creation_service_asset_download_failed error=%s", type(exc).__name__)
            raise CreationServiceError("unreachable") from exc
        return destination


async def probe_key(api_key: str, *, base_url: str = DEFAULT_BASE_URL,
                    client: Optional[Any] = None) -> "dict[str, Any]":
    """用免费 /v1/me 校验一个 Key；成功返回状态视图，失败抛 CreationServiceError。

    只做校验，不产生任何付费调用；已保存的 Key 也走同一条路径。
    """
    service = CreationServiceClient(api_key, base_url=base_url, client=client)
    data = await service.me()
    wallet = data.get("wallet") if isinstance(data.get("wallet"), Mapping) else {}
    key = data.get("key") if isinstance(data.get("key"), Mapping) else {}
    available_micro = _to_float(wallet.get("available"))
    status = "insufficient_balance" if (available_micro is not None and available_micro <= 0) else "active"
    return {
        "status": status,
        "statusLabel": KEY_STATUS_LABELS.get(status, KEY_STATUS_LABELS["active"]),
        "channelName": str(key.get("channelName") or ""),
        "maskedKey": str(key.get("maskedKey") or ""),
        "balanceAvailableText": _money_text(wallet.get("availableText"), wallet.get("available")),
        "balanceFrozenText": _money_text(wallet.get("frozenText"), wallet.get("frozen")),
        "lowBalance": bool(wallet.get("lowBalance")),
    }


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _money_text(text: Any, micro: Any) -> str:
    raw = str(text or "").strip()
    if raw:
        try:
            return "%0.2f" % float(raw)
        except (TypeError, ValueError):
            return raw
    value = _to_float(micro)
    return "%0.2f" % value if value is not None else "0.00"
