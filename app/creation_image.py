"""封面生成接入创作服务。

一个封面任务就是一次 ``POST /v1/images/generations``：

* 两种比例一起提交时按各规格分别计价，冻结额是各规格售价之和；
* 只有成功张数结算，失败张数不计费，失败项带 ``errorCode`` / ``errorMessage``；
* 结果图片的 ``url`` 是受控地址，下载后保存到现有封面目录，复用原有展示与恢复交互；
* 参考图先用 ``POST /v1/uploads`` 换成素材号，再放进 ``referenceUploadIds``。

供应商凭据留在平台侧，这里只使用工作台自己的创作服务 Key。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

from . import workbench
from .subscription import SubscriptionError, SubscriptionService

logger = logging.getLogger("douyin-downloader")

VARIANT_TEXT_TO_IMAGE = "text-to-image"
VARIANT_IMAGE_TO_IMAGE = "image-to-image"

class CreationImageError(Exception):
    """对外安全的封面生成错误；code 与 message 都已脱敏。"""

    def __init__(self, code: str, message: str = "", *, status_code: Optional[int] = None, terminal: bool = False):
        super().__init__(message or "封面生成失败，请稍后重试。")
        self.code = code
        self.message = message or "封面生成失败，请稍后重试。"
        self.status_code = status_code
        self.terminal = terminal


class CreationImageClient:
    """封面生成：平台一次请求一个比例，所以每个比例各自报价、各自提交一个任务。"""

    def __init__(self, service: SubscriptionService):
        self._service = service
        self.business_context: dict[str, Any] = {}

    @classmethod
    def from_settings(cls, settings: Any, *, store: Any) -> "CreationImageClient":
        return cls(SubscriptionService(store, settings))

    async def upload_reference(self, path: Path) -> str:
        """把参考图换成平台素材号，供 image-to-image 使用。"""
        try:
            return await workbench.upload_media(self._service, Path(path))
        except SubscriptionError as exc:
            raise CreationImageError(exc.code, exc.message, status_code=exc.status_code) from None

    async def submit(self, prompt: str, ratios: "list[str]", *,
                     reference_upload_ids: Optional["list[str]"] = None) -> "dict[str, str]":
        """每个比例各自提交一个任务；返回「比例 -> 平台任务号」。"""
        variant = VARIANT_IMAGE_TO_IMAGE if reference_upload_ids else VARIANT_TEXT_TO_IMAGE
        task_ids: "dict[str, str]" = {}
        try:
            for ratio in ratios:
                outcome = await workbench.generate_image(
                    self._service, prompt=prompt, ratio=ratio, count=1, variant=variant,
                    wait_for_result=False,
                    reference_upload_ids=list(reference_upload_ids) if reference_upload_ids else None,
                    **({"business_context": dict(self.business_context)} if self.business_context else {}),
                )
                task_id = str(outcome.get("taskId") or "")
                if not task_id:
                    raise CreationImageError("upstream_unavailable", "封面生成任务提交失败，请稍后重试。")
                task_ids[ratio] = task_id
        except SubscriptionError as exc:
            raise CreationImageError(exc.code, exc.message, status_code=exc.status_code) from None
        logger.info("creation_image_submitted ratios=%s", ",".join(ratios))
        return task_ids

    async def await_task(self, task_id: str, ratio: str) -> "dict[str, Any]":
        """查询一个比例的任务结果；``reconciling`` 由平台侧确认，这里只查同一个任务。"""
        client = None
        view = {}
        try:
            client = self._service.business_client()
            view = await workbench.poll_task(client, task_id)
            workbench.require_success(view)
            result = await client.task_result(task_id)
        except SubscriptionError as exc:
            raise CreationImageError(exc.code, exc.message, status_code=exc.status_code,
                                     terminal=view.get("status") in {"failed", "cancelled"}) from None
        payload = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        images: "list[dict[str, Any]]" = []
        for index, entry in enumerate(payload.get("images") or []):
            if not isinstance(entry, Mapping):
                continue
            item = dict(entry)
            item["index"] = index
            item["ratio"] = ratio
            images.append(item)
        return {
            "taskId": task_id,
            "ratio": ratio,
            "requested": int(payload.get("requested") or 0),
            "count": int(payload.get("count") or 0),
            "images": images,
            "chargedPoints": str(result.get("chargedPoints") or view.get("chargedPoints") or ""),
        }

    async def download(self, task_id: str, index: int, target: Path) -> Path:
        """按受控成果地址下载：工作台用会话凭证走 /workbench/v1 的任务下载路由。"""
        path = "/workbench/v1/tasks/%s/download?index=%d" % (task_id, int(index))
        try:
            return await self._service.business_client().download_asset(path, Path(target))
        except SubscriptionError as exc:
            raise CreationImageError(exc.code, exc.message, status_code=exc.status_code) from None
