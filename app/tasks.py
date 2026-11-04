from __future__ import annotations

from .author_identity import read_author_identity

import asyncio
import json
import logging
import math
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from .audio import AudioPreparationError, extract_mp3
from .creation_service import CreationServiceError, DEFAULT_LINK_MAX_SECONDS
from .text_service import TextClient, TextServiceError
from .media_download import DOWNLOAD_DIR, extract_douyin_url
from .media_compat import preview_poster_status, safari_compatibility_status
from .settings import AppSettings
from .subscription import SubscriptionError, SubscriptionService
from . import workbench
from .upstream_errors import public_error, sanitize_message
from .waveform import audio_waveform_peaks


TaskPhase = Literal[
    "queued", "parsing", "downloading", "extracting", "uploading",
    "transcribing", "fetching", "rewriting", "complete", "failed",
]
# 旧任务落盘用的阶段名，加载时归一化到上面的集合，历史记录照常可读。
LEGACY_PHASES: "dict[str, str]" = {
    "submitting": "parsing",
    "preparing_audio": "extracting",
    "uploading_audio": "uploading",
}
KNOWN_PHASES = set(TaskPhase.__args__) | set(LEGACY_PHASES)
RewriteStatus = Literal["pending", "running", "complete", "failed"]
# 转写来源：分享链接先做付费解析（平台只回媒体直链），本地音视频跳过解析。
MediaSource = Literal["link", "upload"]
logger = logging.getLogger("douyin-downloader")
REWRITE_MODELS = ("text-default", "text-option-2", "text-option-3")
REWRITE_MODEL_LABELS = dict(zip(REWRITE_MODELS, ("默认模型", "模型二", "模型三")))
REWRITE_FILENAMES = {
    "text-default": "rewrite.json",
    "text-option-2": "rewrite-text-option-2.json",
    "text-option-3": "rewrite-text-option-3.json",
}

# 轮询平台任务的节奏与上限：超时只保留任务号继续等，绝不新建任务重复付费。
PLATFORM_POLL_INTERVAL_SECONDS = 3.0
PLATFORM_POLL_BUDGET_SECONDS = 900.0
# 本地下载上游直链的尝试次数：失败先重试下载，直链过期才回到重新解析。
MEDIA_DOWNLOAD_ATTEMPTS = 2
# 上游直链过期/失效的状态码：需要重新解析（会再次计费）。
MEDIA_LINK_EXPIRED_STATUS = {401, 403, 404, 410}
# 单次请求的退避上限，用于 rate_limited 的 retryAfterSeconds。
PLATFORM_RATE_LIMIT_MAX_BACKOFF_SECONDS = 60.0


class _PlatformPollingTimeout(Exception):
    """本轮轮询预算用尽：任务仍然有效，保留任务号等待下次继续查询。"""

    def __init__(self, platform_task_id: str):
        super().__init__("创作服务任务仍在处理中")
        self.platform_task_id = platform_task_id


class _PipelineStop(Exception):
    """当前阶段已按失败落盘（或需等待下次续查）：停止推进，不再抛给上层重复处理。"""


def _points_text(value: object) -> str:
    """积分字段统一成文本；空值返回空串，避免把 None 写成 "None"。"""
    text = str(value or "").strip()
    return "" if text in {"", "None", "null"} else text


def format_generated_rewrite(content: str) -> str:
    """Normalize model-generated paragraph breaks without changing its wording."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", normalized) if paragraph.strip()]
    if len(paragraphs) > 1:
        return "\n\n".join(paragraphs)

    paragraph = paragraphs[0]
    sentences = [sentence for sentence in re.findall(r"[^。！？!?]+[。！？!?]+(?:[”’\"'）】》]+)?|[^。！？!?]+$", paragraph, flags=re.DOTALL) if sentence]
    if len(sentences) <= 1:
        return paragraph
    return "\n\n".join("".join(sentences[index:index + 2]) for index in range(0, len(sentences), 2))


def format_rewrite_source(transcript: str, segments: list[dict[str, Any]]) -> str:
    """Build the user message while retaining the source video's spoken timing."""
    lines = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        start = segment.get("start")
        end = segment.get("end")
        if not text or isinstance(start, bool) or isinstance(end, bool):
            continue
        try:
            start_seconds = float(start)
            end_seconds = float(end)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start_seconds) or not math.isfinite(end_seconds) or start_seconds < 0 or end_seconds <= start_seconds:
            continue
        start_minutes, start_remainder = divmod(int(start_seconds), 60)
        end_minutes, end_remainder = divmod(int(end_seconds), 60)
        lines.append(f"{start_minutes:02d}:{start_remainder:02d} — {end_minutes:02d}:{end_remainder:02d}\n{text}")

    body = "\n\n".join(lines) if lines else transcript.strip()
    return f"以下是用户提供的原始口播稿：\n\n{body}"


@dataclass
class TaskRecord:
    task_id: str
    share_text: str
    # 转写来源与本地素材：链接走平台解析，上传来源跳过解析直接转写。
    source: str = "link"
    media_path: str = ""
    media_name: str = ""
    # 平台任务档案：任务号、幂等标识、费用上限与结算信息全部持久化，
    # 工作台重开后凭它们继续查询，不新建任务重复付费。
    platform: dict[str, Any] = field(default_factory=dict)
    rewrite_system_prompt: str = ""
    phase: TaskPhase = "queued"
    rewrite_status: RewriteStatus = "pending"
    rewrite_models: dict[str, dict[str, str]] = field(default_factory=dict)
    directory: Optional[Path] = None
    error_code: str = ""
    failed_phase: str = ""
    download_stage: str = ""
    warning_code: str = ""
    warning_message: str = ""
    message: str = "任务已创建，等待处理。"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def public_view(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "phase": self.phase,
            "source": self.source,
            "message": self.message,
            "errorCode": self.error_code,
            **({"downloadStage": self.download_stage} if self.download_stage else {}),
            **({"failedPhase": self.failed_phase} if self.failed_phase else {}),
            "rewriteStatus": self.rewrite_status,
            "warningCode": self.warning_code,
            "warningMessage": self.warning_message,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "creationService": self.platform_view(),
        }

    def platform_view(self) -> dict[str, Any]:
        """创作服务任务的对外视图：视频解析与音频转写两段各自的费用、状态与数量。"""
        platform = self.platform if isinstance(self.platform, dict) else {}
        if not self.platform_engaged(platform):
            return {}
        parse = {
            "taskId": str(platform.get("parseTaskId") or ""),
            "status": str(platform.get("parseStatus") or ""),
            "statusLabel": str(platform.get("parseStatusLabel") or ""),
            "chargedPoints": str(platform.get("parseChargedPoints") or ""),
            "maxChargePoints": str(platform.get("parseMaxChargePoints") or ""),
            "quantity": str(platform.get("parseQuantity") or ""),
            "unit": str(platform.get("parseUnit") or "次"),
            "unitPricePoints": str(platform.get("parseUnitPricePoints") or ""),
            "errorCode": str(platform.get("parseErrorCode") or ""),
            "errorMessage": str(platform.get("parseErrorMessage") or ""),
            "mediaUrl": str(platform.get("mediaUrl") or ""),
            "title": str(platform.get("mediaTitle") or ""),
            "coverUrl": str(platform.get("mediaCoverUrl") or ""),
        }
        transcription = {
            "taskId": str(platform.get("transcriptionTaskId") or ""),
            "status": str(platform.get("transcriptionStatus") or ""),
            "statusLabel": str(platform.get("transcriptionStatusLabel") or ""),
            "chargedPoints": str(platform.get("transcriptionChargedPoints") or ""),
            "frozenPoints": str(platform.get("transcriptionFrozenPoints") or ""),
            "maxChargePoints": str(platform.get("transcriptionMaxChargePoints") or ""),
            "quantity": str(platform.get("transcriptionQuantity") or ""),
            "unit": str(platform.get("transcriptionUnit") or "分钟"),
            "unitPricePoints": str(platform.get("transcriptionUnitPricePoints") or ""),
            "errorCode": str(platform.get("transcriptionErrorCode") or ""),
            "errorMessage": str(platform.get("transcriptionErrorMessage") or ""),
        }
        return {
            "source": self.source,
            "localTaskId": str(platform.get("localTaskId") or self.task_id),
            "parse": parse,
            "transcription": transcription,
            "mediaSource": str(platform.get("mediaSource") or ""),
            "expiresAt": str(platform.get("expiresAt") or ""),
            "mediaUrlExpired": bool(platform.get("mediaUrlExpired")),
            # 兼容旧的扁平字段：旧调用方按 taskId / chargedPoints 读取转写段。
            "taskId": transcription["taskId"],
            "status": transcription["status"],
            "statusLabel": transcription["statusLabel"],
            "currentStage": platform.get("currentStage"),
            "failedStage": platform.get("failedStage"),
            "maxChargePoints": transcription["maxChargePoints"],
            "chargedPoints": transcription["chargedPoints"],
            "frozenPoints": transcription["frozenPoints"],
            "quantity": transcription["quantity"],
            "unit": transcription["unit"],
            "unitPricePoints": transcription["unitPricePoints"],
        }

    @staticmethod
    def platform_engaged(platform: Mapping[str, Any]) -> bool:
        """是否已与平台建立任一段任务（解析或转写），决定是否对外暴露费用视图。"""
        return bool(platform.get("parseTaskId") or platform.get("transcriptionTaskId") or platform.get("taskId"))


class LocalTaskStore:
    def __init__(self, settings_loader, *, workbench_service=None):
        self._settings_loader = settings_loader
        # 付费能力（转写 / 仿写）统一走创作服务平台，由调用方注入会话入口。
        self._workbench_service_factory = workbench_service
        self._records: dict[str, TaskRecord] = {}
        self._platform_locks: dict[str, asyncio.Lock] = {}
        self._rewrite_jobs: dict[tuple[str, str], asyncio.Task] = {}

    def _text_service_client(self) -> TextClient:
        """仿写等文本能力统一走创作服务平台，本地不再持有模型 Key。"""

        async def transport(**kwargs: Any) -> str:
            return await workbench.generate_text(self._workbench_service(), **kwargs)

        return TextClient(platform=transport)

    def _workbench_service(self) -> SubscriptionService:
        if self._workbench_service_factory is None:
            raise CreationServiceError(
                "platform_unavailable", "工作台尚未接入创作服务平台，暂时无法转写。", status_code=503,
            )
        return self._workbench_service_factory()

    def _platform_lock(self, task_id: str) -> asyncio.Lock:
        """同一个本地任务只允许一个推进中的提交/轮询，避免重复付费。"""
        lock = self._platform_locks.get(task_id)
        if lock is None:
            lock = asyncio.Lock()
            self._platform_locks[task_id] = lock
        return lock

    def create(self, share_text: str, *, source: str = "link", media_path: str = "", media_name: str = "",
               business_context: Optional[Mapping[str, Any]] = None) -> TaskRecord:
        # 工作台不再持有任何 Key：转写时统一用当前登录用户的会话凭证调用平台。
        normalized_source = "upload" if source == "upload" else "link"
        if normalized_source == "upload" and not str(media_path or ""):
            raise ValueError("请先选择本地音视频文件。")
        platform: "dict[str, Any]" = {"localTaskId": str(uuid.uuid4())}
        if business_context:
            platform["businessContext"] = dict(business_context)
        task = TaskRecord(
            task_id=platform["localTaskId"],
            share_text=share_text,
            source=normalized_source,
            media_path=str(media_path or ""),
            media_name=str(media_name or ""),
            rewrite_models=self._default_rewrite_models(),
            platform=platform,
        )
        self._records[task.task_id] = task
        if business_context:
            self._task_directory(task)
            self._write_task(task)
        return task

    def get(self, task_id: str) -> TaskRecord:
        if task_id not in self._records:
            self._records[task_id] = self._load_saved_task(task_id)
        return self._records[task_id]

    @staticmethod
    def _default_rewrite_models() -> dict[str, dict[str, str]]:
        return {
            model: {"status": "pending", "errorCode": "", "errorMessage": ""}
            for model in REWRITE_MODELS
        }

    @classmethod
    def _normalized_rewrite_models(
        cls,
        raw: Any,
        directory: Path | None = None,
        *,
        recover_running: bool = False,
    ) -> dict[str, dict[str, str]]:
        models = cls._default_rewrite_models()
        if isinstance(raw, dict):
            for model in REWRITE_MODELS:
                saved = raw.get(model)
                if isinstance(saved, dict):
                    status = str(saved.get("status") or "")
                    if status in {"pending", "running", "complete", "failed"}:
                        models[model] = {
                            "status": status,
                            "errorCode": str(saved.get("errorCode") or ""),
                            "errorMessage": str(saved.get("errorMessage") or ""),
                        }
        if directory and (directory / REWRITE_FILENAMES["text-default"]).is_file() and models["text-default"]["status"] == "pending":
            models["text-default"]["status"] = "complete"
        if recover_running:
            for state in models.values():
                if state["status"] == "running":
                    state.update(status="failed", errorCode="rewrite_interrupted", errorMessage="服务重启，脚本生成已中断，请重试。")
        return models

    def delete_failed(self, task_id: str) -> None:
        """Permanently remove the artifacts for a failed task and forget its record."""
        task = self.get(task_id)
        if task.phase != "failed":
            raise ValueError("仅可删除处理失败的任务。")
        self.delete(task_id)

    def reset_for_retry(self, task_id: str) -> TaskRecord:
        """就地重跑一个失败的任务：复用已保存的解析结果与本地素材。

        解析已成功时不再重新解析（解析费不退也不重复收）；音频素材只能用于一次转写，
        失败时已清掉 uploadId，重跑会自动重新上传本地已有的 MP3。
        """
        task = self.get(task_id)
        if task.phase != "failed":
            raise ValueError("仅可重试处理失败的任务。")
        task.error_code = ""
        task.failed_phase = ""
        task.warning_code = ""
        task.warning_message = ""
        self._set_phase(task, "queued", "已重新开始拆解。")
        return task

    def delete(self, task_id: str) -> None:
        """Permanently remove a task record and the directory it owns."""
        task = self.get(task_id)
        if task.directory and task.directory.exists():
            task_metadata_path = task.directory / "task.json"
            try:
                task_metadata = json.loads(task_metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("任务文件无法确认，未执行删除。") from exc
            if not isinstance(task_metadata, dict) or task_metadata.get("taskId") != task_id:
                raise ValueError("任务文件不匹配，未执行删除。")
            shutil.rmtree(task.directory)
        self._records.pop(task_id, None)

    def resumable_platform_tasks(self) -> list[str]:
        """需要继续查询平台任务号的本地任务：工作台重开后按原任务号续查。

        只包含已经提交过（有平台任务号）且未结束的任务，所以不会产生第二笔消费。
        """
        resumable: list[str] = []
        for task_path in sorted(DOWNLOAD_DIR.glob("*/task.json")):
            try:
                payload = json.loads(task_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            platform = payload.get("platform") if isinstance(payload.get("platform"), dict) else {}
            task_id = str(payload.get("taskId") or "")
            phase = str(payload.get("phase") or "")
            if not task_id:
                continue
            if phase in {"complete", "failed"}:
                continue
            # 只续查已经与平台建单的任务：解析、直传核验或转写任一任务号在手，
            # 重启后才按原任务号继续，不重复解析、不重复上传、不重复提交。
            engaged = (platform.get("taskId") or platform.get("parseTaskId")
                       or platform.get("transcriptionTaskId") or platform.get("audioUploadId"))
            if not engaged:
                continue
            resumable.append(task_id)
        return resumable

    @staticmethod
    def _load_saved_task(task_id: str) -> TaskRecord:
        """Restore a completed task after the server process has restarted."""
        if not task_id or Path(task_id).name != task_id:
            raise KeyError(task_id)

        direct_task_path = DOWNLOAD_DIR / task_id / "task.json"
        task_paths = [direct_task_path, *DOWNLOAD_DIR.glob("*/task.json")]
        for task_path in task_paths:
            try:
                payload = json.loads(task_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            if not isinstance(payload, dict) or payload.get("taskId") != task_id:
                continue

            raw_phase = str(payload.get("phase") or "")
            if raw_phase not in KNOWN_PHASES:
                continue
            phase = LEGACY_PHASES.get(raw_phase, raw_phase)

            rewrite_status = str(payload.get("rewriteStatus") or "")
            if rewrite_status not in {"pending", "running", "complete", "failed"}:
                rewrite_status = "complete" if phase == "complete" and (task_path.parent / "rewrite.json").is_file() else "pending"

            return TaskRecord(
                task_id=task_id,
                share_text=str(payload.get("shareText") or ""),
                source="upload" if payload.get("source") == "upload" else "link",
                media_path=str(payload.get("mediaPath") or ""),
                media_name=str(payload.get("mediaName") or ""),
                platform=payload.get("platform") if isinstance(payload.get("platform"), dict) else {},
                rewrite_system_prompt=str(payload.get("rewriteSystemPrompt") or ""),
                phase=phase,
                rewrite_status=rewrite_status,
                rewrite_models=LocalTaskStore._normalized_rewrite_models(
                    payload.get("rewriteModels"), task_path.parent, recover_running=True
                ),
                directory=task_path.parent,
                failed_phase=str(payload.get("failedPhase") or ""),
                download_stage=str(payload.get("downloadStage") or ""),
                error_code=public_error(str(payload.get("errorCode") or ""), "")[0],
                warning_code=public_error(str(payload.get("warningCode") or ""), "")[0],
                warning_message=sanitize_message(str(payload.get("warningMessage") or "")),
                message=sanitize_message(str(payload.get("message") or "处理完成")),
                created_at=str(payload.get("createdAt") or ""),
                updated_at=str(payload.get("updatedAt") or ""),
            )

        raise KeyError(task_id)

    def _write_task(self, task: TaskRecord) -> None:
        if not task.directory:
            return
        payload = task.public_view()
        # 平台任务档案必须落盘：工作台重开后凭它继续查询，不新建任务重复付费。
        payload["shareText"] = task.share_text
        payload["mediaPath"] = task.media_path
        payload["mediaName"] = task.media_name
        payload["platform"] = task.platform
        payload["rewriteModels"] = task.rewrite_models
        if task.rewrite_system_prompt:
            payload["rewriteSystemPrompt"] = task.rewrite_system_prompt
        payload["downloadCompleted"] = True
        (task.directory / "task.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _set_phase(self, task: TaskRecord, phase: TaskPhase, message: str) -> None:
        task.phase, task.message, task.updated_at = phase, message, datetime.now(timezone.utc).isoformat()
        self._write_task(task)

    def _fail(self, task: TaskRecord, code: str, message: str) -> None:
        code, message = public_error(code, message)
        task.error_code = code
        task.failed_phase = task.phase
        self._set_phase(task, "failed", message)

    @staticmethod
    def _set_rewrite_status(
        task: TaskRecord,
        status: RewriteStatus,
        *,
        warning_code: str = "",
        warning_message: str = "",
    ) -> None:
        task.rewrite_status = status
        task.warning_code = warning_code
        task.warning_message = warning_message

    def _rewrite_state(self, task: TaskRecord, model: str) -> dict[str, str]:
        if model not in REWRITE_MODELS:
            raise ValueError("仿写模型无效。")
        if not task.rewrite_models:
            task.rewrite_models = self._default_rewrite_models()
        return task.rewrite_models[model]

    def _set_model_rewrite_status(
        self,
        task: TaskRecord,
        model: str,
        status: RewriteStatus,
        *,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        error_code, error_message = public_error(error_code, error_message)
        state = self._rewrite_state(task, model)
        state.update(status=status, errorCode=error_code, errorMessage=error_message)
        text_service = self._rewrite_state(task, "text-default")
        task.rewrite_status = text_service["status"]  # compatibility for older task clients
        task.warning_code = text_service["errorCode"]
        task.warning_message = text_service["errorMessage"]
        self._write_task(task)

    async def run(self, task_id: str, *, auto_rewrite: bool = True) -> None:
        """跑一遍拆分后的视频转文案管道：本地下载 → 本地 MP3 → 直传核验 → 转写。

        链接来源先做付费「视频解析」，把平台下发的直链在工作台本地下载；本地来源
        跳过解析，直接从暂存件提取 MP3。音频在本机提取后直传，平台只核验与转写。
        解析与转写各自带幂等标识落盘：重启后按已保存任务号续查，不重复解析、不重复
        上传、不重复提交。``auto_rewrite`` 服务旧的链接仿写流程；拆解视频只要文案。
        """
        task = self.get(task_id)
        try:
            settings: AppSettings = self._settings_loader()
            service = self._workbench_service()
            client = service.business_client()
            async with self._platform_lock(task.task_id):
                await self._transcribe_pipeline(client, task)
            transcript_text = (task.directory / "transcript.txt").read_text(encoding="utf-8") if task.directory else ""
            if auto_rewrite:
                for model in REWRITE_MODELS:
                    self._set_model_rewrite_status(task, model, "running")
                self._set_phase(task, "complete", "视频与原稿已就绪，正在生成三份仿写稿。")
                for model in REWRITE_MODELS:
                    self._start_automatic_rewrite(task, model, transcript_text, settings)
            else:
                self._set_phase(task, "complete", "视频与文案已就绪。")
        except _PlatformPollingTimeout as exc:
            # 超时不等于失败：保留任务号与冻结，等下一次继续查询同一个任务。
            logger.info("pipeline_polling_timeout task_id=%s platform=%s", task.task_id, exc.platform_task_id)
            self._set_phase(task, task.phase, "任务仍在处理，工作台会在空闲时继续查询。")
        except _PipelineStop:
            # 已按真实阶段落盘失败（或需等待续查），上层无需再处理。
            pass
        except CreationServiceError as exc:
            self._fail(task, exc.code, exc.message)
        except SubscriptionError as exc:
            # 未登录 / 模拟通路 / 积分不足等平台类错误：保留它自己的中文文案。
            self._fail(task, exc.code, exc.message)
        except AudioPreparationError as exc:
            self._fail(task, exc.code, exc.message)
        except TextServiceError as exc:
            self._fail(task, exc.code, exc.message)
        except Exception:
            logger.exception("pipeline_task_failed task_id=%s", task.task_id)
            self._fail(task, "pipeline_unexpected_error", "处理任务发生未知错误。")

    # ------------------------------------------------------------ 创作服务任务

    def _task_directory(self, task: TaskRecord) -> Path:
        """本任务的本地目录：与旧版下载目录同址，历史任务保持可读。"""
        if task.directory is None:
            task.directory = DOWNLOAD_DIR / task.task_id
        task.directory.mkdir(parents=True, exist_ok=True)
        return task.directory

    def _record_parse_view(self, task: TaskRecord, view: Mapping[str, Any] | None) -> None:
        """把「视频解析」任务的费用字段写回本地档案（按次计费）。"""
        if not isinstance(view, Mapping):
            return
        platform = task.platform
        for key, field in (
            ("status", "parseStatus"), ("statusLabel", "parseStatusLabel"),
            ("quantity", "parseQuantity"), ("unit", "parseUnit"),
            ("unitPrice", "parseUnitPricePoints"),
            ("errorCode", "parseErrorCode"), ("errorMessage", "parseErrorMessage"),
        ):
            if view.get(key) is not None:
                platform[field] = view.get(key)
        if view.get("chargedPoints") is not None:
            platform["parseChargedPoints"] = _points_text(view.get("chargedPoints"))
        if view.get("id"):
            platform["parseTaskId"] = str(view["id"])
        self._write_task(task)

    def _record_transcription_view(self, task: TaskRecord, view: Mapping[str, Any] | None) -> None:
        """把「音频转写」任务的费用字段写回本地档案（按分钟计费）。"""
        if not isinstance(view, Mapping):
            return
        platform = task.platform
        for key, field in (
            ("status", "transcriptionStatus"), ("statusLabel", "transcriptionStatusLabel"),
            ("quantity", "transcriptionQuantity"), ("unit", "transcriptionUnit"),
            ("unitPrice", "transcriptionUnitPricePoints"),
            ("frozenPoints", "transcriptionFrozenPoints"),
            ("errorCode", "transcriptionErrorCode"), ("errorMessage", "transcriptionErrorMessage"),
        ):
            if view.get(key) is not None:
                platform[field] = view.get(key)
        if view.get("chargedPoints") is not None:
            platform["transcriptionChargedPoints"] = _points_text(view.get("chargedPoints"))
        if view.get("id"):
            platform["transcriptionTaskId"] = str(view["id"])
        # 兼容旧扁平字段：其他调用方与旧记录仍按 taskId / chargedPoints 读取。
        platform["taskId"] = str(platform.get("transcriptionTaskId") or "")
        platform["maxChargePoints"] = str(platform.get("transcriptionMaxChargePoints") or "")
        platform["chargedPoints"] = str(platform.get("transcriptionChargedPoints") or "")
        platform["status"] = str(platform.get("transcriptionStatus") or "")
        self._write_task(task)

    # ------------------------------------------------------------ 本地素材与音频

    def _audio_verified(self, task: TaskRecord) -> bool:
        """音频已通过平台核验：有 uploadId 且拿到可信时长，就不再重复上传。"""
        return bool(str(task.platform.get("audioUploadId") or "")) and bool(task.platform.get("audioDurationSeconds"))

    @staticmethod
    def _account_label(task: TaskRecord) -> str:
        context = task.platform.get("businessContext")
        if isinstance(context, Mapping):
            return str(context.get("accountName") or "")[:200]
        return ""

    @staticmethod
    def _business_context(task: TaskRecord) -> "dict[str, Any] | None":
        context = task.platform.get("businessContext")
        return dict(context) if isinstance(context, Mapping) and context else None

    @classmethod
    def _stage_business_context(cls, task: TaskRecord, action: str) -> "dict[str, Any] | None":
        """按阶段改写操作备注：解析与转写是两个独立结算任务，积分明细要能分开。

        账号、来源等归属快照沿用本地任务保存的原值，只把 ``action`` 换成
        ``parse_video`` / ``transcribe_audio``；本地任务里的原始快照保持不变，
        重试与恢复因此仍复用同一次任务号和幂等键。
        """
        context = cls._business_context(task)
        if context is None:
            return None
        context["action"] = action
        return context

    async def _transcribe_pipeline(self, client: Any, task: TaskRecord) -> None:
        """本地素材 → 提取 MP3 → 直传核验 → 提交并轮询转写；每一步先复用已落盘成果。"""
        directory = self._task_directory(task)
        task.platform.setdefault("localTaskId", task.task_id)

        if task.source == "upload":
            source_media = Path(task.media_path) if task.media_path else None
            if source_media is None or not source_media.is_file():
                raise CreationServiceError("unsupported_input", "本地素材已不可用，请重新选择文件。", status_code=400)
            self._keep_local_video(source_media, directory / "video.mp4")
        else:
            source_media = await self._ensure_local_video(client, task, directory)

        if not self._audio_verified(task):
            await self._prepare_and_upload_audio(task, source_media, directory)

        await self._submit_and_await_transcription(client, task)

    @staticmethod
    def _keep_local_video(source: Path, target: Path) -> None:
        """把本地来源视频复制一份到任务目录供预览；音频素材或同址文件不复制。"""
        try:
            if source.resolve() == target.resolve() or target.is_file():
                return
            shutil.copy2(source, target)
        except OSError:
            logger.warning("local_video_copy_skipped name=%s", source.name)

    async def _ensure_local_video(self, client: Any, task: TaskRecord, directory: Path) -> Path:
        """链接来源：本地下载上游直链；直链过期才回到重新解析（按次再次计费）。"""
        target = directory / "video.mp4"
        if target.is_file() and target.stat().st_size > 0:
            return target
        media_url = await self._ensure_media_url(client, task)
        self._set_phase(task, "downloading", "正在下载视频")
        try:
            await client.download_asset(media_url, target, timeout=180.0)
            return target
        except SubscriptionError as exc:
            status = 410 if exc.code in {"media_link_expired", "result_expired"} else 0
            if exc.status_code in {401, 403}:
                raise

        if status in MEDIA_LINK_EXPIRED_STATUS:
            # 直链过期：清掉本次解析结果，下次重新解析（会再次计费）。
            for key in ("parseTaskId", "parseIdempotencyKey", "mediaUrl"):
                task.platform.pop(key, None)
            task.platform["mediaUrlExpired"] = True
            self._write_task(task)
            self._fail(task, "media_link_expired", "视频直链已过期，请重新拆解（将重新解析并再次计费）。")
            raise _PipelineStop()
        self._fail(task, "media_download_failed", "视频下载失败，请稍后重试。")
        raise _PipelineStop()

    async def _ensure_media_url(self, client: Any, task: TaskRecord) -> str:
        """视频解析（按次）：只解析一次，结果落盘复用；重启后按任务号续查。"""
        platform = task.platform
        existing = str(platform.get("mediaUrl") or "")
        if existing:
            return existing
        parse_task_id = str(platform.get("parseTaskId") or "")
        if not parse_task_id:
            parse_task_id = await self._submit_video_parse(client, task)
        view = await self._await_platform_task(client, task, parse_task_id, stage="parse")
        if str(view.get("status") or "") != "succeeded":
            self._fail_stage(task, view, "parse")
            # 解析失败可重试，且属于新的按次计费：清掉旧任务与幂等标识才能重新收单。
            self._reset_parse_for_retry(task)
            raise _PipelineStop()
        result = await client.task_result(parse_task_id)
        payload = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        media_url = str(payload.get("mediaUrl") or "").strip()
        platform["parseTaskId"] = parse_task_id
        platform["mediaTitle"] = str(payload.get("title") or "")
        platform["authorIdentity"] = payload.get("authorIdentity") if isinstance(payload.get("authorIdentity"), dict) else {}
        platform["metrics"] = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        platform["author"] = payload.get("author") if isinstance(payload.get("author"), (str, dict)) else ""
        platform["mediaCoverUrl"] = ""
        cover_url = str(payload.get("coverUrl") or "")
        if cover_url:
            cover_target = self._task_directory(task) / "cover.jpg"
            try:
                await client.download_asset(cover_url, cover_target)
                platform["mediaCoverUrl"] = "/api/files/" + self._task_directory(task).name + "/cover.jpg"
            except (SubscriptionError, OSError, ValueError):
                logger.warning("media_cover_download_failed task_id=%s", task.task_id)
        platform["parseMediaType"] = str(payload.get("mediaType") or "")
        platform["parseChargedPoints"] = _points_text(result.get("chargedPoints"))
        if not media_url:
            self._write_task(task)
            self._fail(task, "content_unavailable", "解析结果没有可下载的媒体地址，请更换链接后重试。")
            raise _PipelineStop()
        platform["mediaUrl"] = media_url
        self._write_task(task)
        return media_url

    async def _submit_video_parse(self, client: Any, task: TaskRecord) -> str:
        """提交一次解析任务；幂等标识先落盘，崩溃重选也拿回同一个任务。"""
        platform = task.platform
        existing = str(platform.get("parseTaskId") or "")
        if existing:
            return existing
        if not platform.get("parseIdempotencyKey"):
            platform["parseIdempotencyKey"] = workbench.new_idempotency_key()
            self._write_task(task)
        source_url = extract_douyin_url(task.share_text)
        if not source_url:
            raise CreationServiceError("unsupported_input", "请提供有效的视频分享链接。", status_code=422)
        self._set_phase(task, "parsing", "正在解析分享链接")
        quoted = await workbench.quote_with_retry(client, workbench.SPEC_VIDEO_PARSE, "1")
        platform["parseMaxChargePoints"] = str(workbench.quote_ceiling(quoted) or "")
        self._write_task(task)
        created = await workbench._call_with_retry(lambda: client.video_parse(
            quote_id=quoted.get("quoteId"), url=source_url,
            max_charge_points=workbench.quote_ceiling(quoted),
            local_task_id=task.task_id, account_label=self._account_label(task),
            business_context=self._stage_business_context(task, "parse_video"),
            idempotency_key=str(platform["parseIdempotencyKey"]),
        ))
        parse_task_id = workbench.task_id_of(created) if isinstance(created, Mapping) else ""
        if not parse_task_id:
            raise CreationServiceError("upstream_unavailable")
        platform["parseTaskId"] = parse_task_id
        self._record_parse_view(task, created if isinstance(created, Mapping) else None)
        logger.info("video_parse_submitted local=%s platform=%s", task.task_id, parse_task_id)
        return parse_task_id

    def _reset_parse_for_retry(self, task: TaskRecord) -> None:
        """解析失败后的重试属于一次全新的按次计费：清掉旧任务号与幂等标识。"""
        for key in (
            "parseTaskId", "parseIdempotencyKey", "parseStatus", "parseStatusLabel",
            "parseChargedPoints", "parseFrozenPoints", "parseMaxChargePoints",
            "parseErrorCode", "parseErrorMessage", "mediaUrl", "mediaTitle",
            "mediaCoverUrl", "parseMediaType", "mediaUrlExpired", "metrics", "author", "authorIdentity",
        ):
            task.platform.pop(key, None)
        self._write_task(task)

    def _reset_audio_for_retry(self, task: TaskRecord) -> None:
        """转写失败后的重跑：音频只能用于一次转写，必须重新上传再提交。"""
        for key in (
            "audioUploadId", "audioDurationSeconds", "audioSizeBytes",
            "transcriptionTaskId", "transcriptionIdempotencyKey",
            "transcriptionStatus", "transcriptionStatusLabel", "transcriptionQuantity",
            "transcriptionChargedPoints", "transcriptionFrozenPoints",
            "transcriptionMaxChargePoints", "transcriptionUnitPricePoints",
            "transcriptionErrorCode", "transcriptionErrorMessage",
            "taskId", "status", "statusLabel", "chargedPoints", "maxChargePoints",
        ):
            task.platform.pop(key, None)
        self._write_task(task)

    async def _prepare_and_upload_audio(self, task: TaskRecord, source_media: Path, directory: Path) -> None:
        """提取单声道 16k/64kbps MP3 并直传核验；核验时长是唯一计费依据。"""
        audio_path = directory / "audio.mp3"
        self._set_phase(task, "extracting", "正在准备转写音频")
        await asyncio.to_thread(extract_mp3, source_media, audio_path)
        task.platform["audioPath"] = str(audio_path)
        self._write_task(task)
        self._set_phase(task, "uploading", "正在上传音频")
        upload = await workbench.upload_audio(self._workbench_service(), audio_path, filename="audio.mp3")
        task.platform["audioUploadId"] = str(upload.get("uploadId") or "")
        task.platform["audioDurationSeconds"] = float(upload.get("durationSeconds") or 0)
        task.platform["audioSizeBytes"] = int(upload.get("sizeBytes") or 0)
        self._write_task(task)

    async def _submit_and_await_transcription(self, client: Any, task: TaskRecord) -> None:
        """提交转写（按核验分钟报价）并轮询同一任务；reconciling 继续查、不重发。"""
        platform = task.platform
        task_id = str(platform.get("transcriptionTaskId") or "")
        if not task_id:
            task_id = await self._submit_transcription(client, task)
        view = await self._await_platform_task(client, task, task_id, stage="transcribe")
        if str(view.get("status") or "") != "succeeded":
            self._fail_stage(task, view, "transcribe")
            # 音频只能用于一次转写：失败后重跑必须重新上传再提交。
            self._reset_audio_for_retry(task)
            raise _PipelineStop()
        self._set_phase(task, "fetching", "正在获取转写结果")
        result = await client.task_result(task_id)
        await self._store_transcript(client, task, result)

    async def _submit_transcription(self, client: Any, task: TaskRecord) -> str:
        """提交一次转写任务；音频只能用于一次转写，失败重跑要重新上传后提交。"""
        platform = task.platform
        existing = str(platform.get("transcriptionTaskId") or "")
        if existing:
            return existing
        if task.source == "link" and float(platform.get("audioDurationSeconds") or 0) > DEFAULT_LINK_MAX_SECONDS:
            self._fail(task, "duration_limit_exceeded", "最长支持转写 10 分钟以内视频，超出上限会中止！")
            raise _PipelineStop()
        if not platform.get("transcriptionIdempotencyKey"):
            platform["transcriptionIdempotencyKey"] = workbench.new_idempotency_key()
            self._write_task(task)
        quantity = workbench.transcription_quantity(platform.get("audioDurationSeconds"))
        self._set_phase(task, "transcribing", "正在提交转写任务")
        quoted = await workbench.quote_with_retry(client, workbench.SPEC_AUDIO_TRANSCRIPTION, quantity)
        platform["transcriptionQuantity"] = quantity
        platform["transcriptionMaxChargePoints"] = str(workbench.quote_ceiling(quoted) or "")
        self._write_task(task)
        created = await workbench._call_with_retry(lambda: client.audio_transcription(
            quote_id=quoted.get("quoteId"), upload_id=str(platform.get("audioUploadId") or ""),
            max_charge_points=workbench.quote_ceiling(quoted),
            local_task_id=task.task_id, account_label=self._account_label(task),
            business_context=self._stage_business_context(task, "transcribe_audio"),
            idempotency_key=str(platform["transcriptionIdempotencyKey"]),
        ))
        task_id = workbench.task_id_of(created) if isinstance(created, Mapping) else ""
        if not task_id:
            raise CreationServiceError("upstream_unavailable")
        platform["transcriptionTaskId"] = task_id
        platform["estimateOnly"] = False
        self._record_transcription_view(task, created if isinstance(created, Mapping) else None)
        logger.info("audio_transcription_submitted local=%s platform=%s", task.task_id, task_id)
        return task_id

    async def _await_platform_task(self, client: Any, task: TaskRecord, platform_task_id: str, *,
                                   stage: str = "transcribe") -> Mapping[str, Any]:
        """轮询同一个平台任务直到终态。

        ``reconciling`` 表示上游结果未知：继续查同一个任务，不当失败也不重发。
        轮询预算用尽时抛出可恢复的超时，保留任务号，由启动恢复继续查询。
        """
        deadline = time.monotonic() + PLATFORM_POLL_BUDGET_SECONDS
        stage_phase = {"parse": "parsing", "transcribe": "transcribing"}
        stage_message = {"parse": "创作服务正在解析分享链接", "transcribe": "创作服务正在转写视频文案"}
        while True:
            try:
                view = await client.task(platform_task_id)
            except (CreationServiceError, SubscriptionError) as exc:
                if exc.code == "rate_limited":
                    if time.monotonic() >= deadline:
                        raise _PlatformPollingTimeout(platform_task_id) from None
                    retry_after = None
                    details = getattr(exc, "details", None)
                    if isinstance(details, Mapping):
                        retry_after = details.get("retryAfterSeconds")
                    if retry_after is None:
                        retry_after = getattr(exc, "retry_after", None)
                    backoff = min(float(retry_after or PLATFORM_POLL_INTERVAL_SECONDS), PLATFORM_RATE_LIMIT_MAX_BACKOFF_SECONDS)
                    await asyncio.sleep(max(backoff, 1.0))
                    continue
                raise
            task.platform["currentStage"] = view.get("currentStage")
            task.platform["failedStage"] = view.get("failedStage")
            if stage == "parse":
                self._record_parse_view(task, view)
            else:
                self._record_transcription_view(task, view)
            status = str(view.get("status") or "")
            if status in {"succeeded", "failed", "cancelled"}:
                return view
            task.phase = stage_phase.get(stage, "transcribing")
            task.message = stage_message.get(stage, "创作服务正在处理任务，阶段待确认。")
            self._write_task(task)
            if time.monotonic() >= deadline:
                raise _PlatformPollingTimeout(platform_task_id)
            await asyncio.sleep(PLATFORM_POLL_INTERVAL_SECONDS)

    def _fail_stage(self, task: TaskRecord, view: Mapping[str, Any], stage: str) -> None:
        """按解析 / 转写各自的终态落一个可读的失败原因，不出现平台内部原文。"""
        from .subscription import PUBLIC_ERROR_MESSAGES, public_error_code

        status = str(view.get("status") or "")
        code = public_error_code(view.get("errorCode")) or "upstream_unavailable"
        if status == "cancelled":
            self._fail(task, "task_cancelled", "任务已取消。")
            return
        default = "视频解析失败，请检查链接后重试。" if stage == "parse" else "创作服务未能完成本次转写，请稍后重试。"
        message = PUBLIC_ERROR_MESSAGES.get(code) or default
        if code == "charge_limit_exceeded":
            message = "本次费用超过授权上限，请提高上限后重新提交。"
        elif code == "content_unavailable":
            message = "该内容暂时无法获取，请更换链接后重试。"
        elif code in {"upstream_unavailable", "upstream_error"}:
            message = "视频链接解析失败，请检查链接或稍后重试。" if stage == "parse" else "语音识别失败，请稍后重试。"
        self._fail(task, code, message)

    async def _store_transcript(self, client: Any, task: TaskRecord, result: Mapping[str, Any]) -> None:
        """保存文案；原视频与 MP3 都已在本地，平台不再回传云端媒体地址。"""
        directory = self._task_directory(task)
        payload = result.get("result") if isinstance(result.get("result"), Mapping) else {}
        text = str(payload.get("text") or "").strip()
        segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
        duration = payload.get("durationSeconds")
        media_source = str(payload.get("mediaSource") or "local")
        expires_at = str(payload.get("expiresAt") or "")
        audio_upload_id = str(payload.get("audioUploadId") or task.platform.get("audioUploadId") or "")

        task.platform["mediaSource"] = media_source
        task.platform["expiresAt"] = expires_at
        task.platform["audioUploadId"] = audio_upload_id
        if duration is not None:
            task.platform["verifiedDurationSeconds"] = float(duration or 0)
        if result.get("chargedPoints") is not None:
            task.platform["transcriptionChargedPoints"] = _points_text(result.get("chargedPoints"))
            task.platform["chargedPoints"] = _points_text(result.get("chargedPoints"))

        if not text:
            raise CreationServiceError("content_unavailable", "创作服务没有返回可用的文案，请稍后重试。")

        (directory / "transcript.txt").write_text(text, encoding="utf-8")
        (directory / "transcript.json").write_text(
            json.dumps(
                {
                    "source": "creation-service",
                    "text": text,
                    "segments": segments,
                    "durationSeconds": duration,
                    "mediaSource": media_source,
                    "audioUploadId": audio_upload_id,
                    "expiresAt": expires_at,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        video_path = directory / "video.mp4"
        if video_path.is_file() and video_path.stat().st_size > 0:
            (directory / "video.json").write_text(
                json.dumps(
                    {"title": str(task.platform.get("mediaTitle") or ""), "duration_seconds": duration, "source": media_source, "metrics": task.platform.get("metrics", {}), "author": task.platform.get("author", ""), "authorIdentity": task.platform.get("authorIdentity", {})},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        self._write_task(task)
    def _start_automatic_rewrite(self, task: TaskRecord, model: str, transcript: str, settings: AppSettings) -> None:
        key = (task.task_id, model)
        existing = self._rewrite_jobs.get(key)
        if existing and not existing.done():
            return

        async def generate() -> None:
            try:
                source = format_rewrite_source(transcript, self._saved_transcript_segments(task.directory))
                content = format_generated_rewrite(await self._text_service_client().rewrite(
                    source,
                    task.rewrite_system_prompt or settings.rewrite_system_prompt,
                    model=model,
                ))
                self._write_rewrite(task.directory, content, task.rewrite_system_prompt or settings.rewrite_system_prompt, "automatic", model)
                self._set_model_rewrite_status(task, model, "complete")
            except TextServiceError as exc:
                self._set_model_rewrite_status(task, model, "failed", error_code=exc.code, error_message=exc.message)
            except Exception:
                logger.exception("automatic_rewrite_failed task_id=%s model=%s", task.task_id, model)
                self._set_model_rewrite_status(task, model, "failed", error_code="rewrite_unexpected_error", error_message="仿写生成失败，请重试。")
            finally:
                self._rewrite_jobs.pop(key, None)

        self._rewrite_jobs[key] = asyncio.create_task(generate())

    @staticmethod
    def _write_rewrite(directory: Path, content: str, system_prompt: str, source: str, model: str = "text-default") -> None:
        if model not in REWRITE_MODELS:
            raise ValueError("仿写模型无效。")
        (directory / REWRITE_FILENAMES[model]).write_text(json.dumps({"content": content, "systemPrompt": system_prompt, "source": source, "model": model, "savedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _workspace_video_metadata(directory: Path) -> dict[str, Any]:
        """Return the display metadata saved alongside a completed task."""
        try:
            metadata = json.loads((directory / "video.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}

        if not isinstance(metadata, dict):
            metadata = {}
        try:
            share_text = json.loads((directory / "task.json").read_text(encoding="utf-8")).get("shareText", "")
        except (OSError, ValueError, AttributeError):
            share_text = ""
        identity = read_author_identity(metadata, share_text)
        post = metadata.get("mediaMetadata") if isinstance(metadata.get("mediaMetadata"), dict) else {}
        raw_title = str(metadata.get("title") or metadata.get("desc") or "").strip()
        post_title = str(post.get("title") or post.get("description") or post.get("text") or "").strip()
        title = raw_title if raw_title and raw_title != "douyin_video" else post_title
        author = ""
        for source in (metadata.get("author"), post.get("author")):
            names = [source] if isinstance(source, str) else [source.get(key) for key in ("nickname", "name", "display_name")] if isinstance(source, dict) else []
            author = next((name.strip() for name in names if isinstance(name, str) and name.strip() and name.strip() not in ("未知作者", "作者未提供", "—")), "")
            if author:
                break
        published_at = post.get("published_at") or post.get("created_at") or metadata.get("create_time") or "未知发布时间"
        if isinstance(published_at, (int, float)) or (isinstance(published_at, str) and published_at.isdigit()):
            try:
                published_at = datetime.fromtimestamp(float(published_at)).strftime("%Y-%m-%d %H:%M:%S")
            except (OverflowError, OSError, ValueError):
                pass

        raw_duration = metadata.get("duration_seconds")
        try:
            duration = float(raw_duration) if not isinstance(raw_duration, bool) else 0.0
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration <= 0:
            duration = 0.0

        statistics = metadata.get("statistics") if isinstance(metadata.get("statistics"), dict) else {}
        standard = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
        snap_stats = post.get("stats") if isinstance(post.get("stats"), dict) else {}
        metrics = {}
        for key, source_key, snap_key in (("likes", "digg_count", "like_count"), ("comments", "comment_count", "comment_count"), ("collects", "collect_count", None), ("shares", "share_count", "share_count")):
            for value in (standard.get(key), statistics.get(source_key), snap_stats.get(snap_key)):
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    metrics[key] = int(value)
                    break
        return {
            "metrics": metrics,
            "title": title or "未命名视频",
            "author": author or "—",
            "authorIdentity": identity,
            "publishedAt": str(published_at).strip() or "未知发布时间",
            "duration": duration,
        }

    def _workspace_source_video_path(self, directory: Path) -> Path | None:
        preferred = directory / "video.mp4"
        if preferred.is_file() and preferred.stat().st_size > 0:
            return preferred
        return next(
            (path for path in sorted(directory.glob("*.mp4")) if path.is_file() and not path.name.endswith(".safari.mp4")),
            None,
        )

    def _workspace_video_file(self, directory: Path) -> str:
        video_path = self._workspace_source_video_path(directory)
        if video_path is None:
            return ""
        compatibility = safari_compatibility_status(video_path)
        playback_path = compatibility.playback_path if compatibility.status == "ready" else video_path
        return playback_path.relative_to(DOWNLOAD_DIR).as_posix()

    def _workspace_poster(self, video_path: Path | None) -> tuple[str, str]:
        if video_path is None:
            return "", "unavailable"
        poster = preview_poster_status(video_path)
        if poster.status != "ready" or poster.poster_path is None:
            return "", poster.status
        try:
            return poster.poster_path.resolve().relative_to(DOWNLOAD_DIR.resolve()).as_posix(), "ready"
        except ValueError:
            return "", "unavailable"

    @staticmethod
    def _workspace_audio_file(directory: Path) -> Path | None:
        preferred = directory / "audio.mp3"
        if preferred.is_file() and preferred.stat().st_size > 0:
            return preferred
        audio_extensions = {".aac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}
        return next(
            (path for path in sorted(directory.iterdir()) if path.is_file() and path.suffix.lower() in audio_extensions and path.stat().st_size > 0),
            None,
        )

    def _transcript_segments(self, transcript: str) -> list[dict[str, Any]]:
        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n+", transcript.strip())
            if paragraph.strip()
        ]
        if len(paragraphs) == 1:
            segments_text = [
                sentence.strip()
                for sentence in re.split(r"(?<=[。！？!?])\s*", paragraphs[0])
                if sentence.strip()
            ]
        else:
            segments_text = paragraphs

        start = 0.0
        segments = []
        for text in segments_text:
            duration = max(0.5, len(re.sub(r"\s+", "", text)) * 0.2)
            end = round(start + duration, 2)
            segments.append({"start": start, "end": end, "text": text})
            start = end
        return segments

    @staticmethod
    def _saved_transcript_segments(directory: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        # 创作服务回来的是秒级 {start,end,text}；旧任务仍是毫秒 utterances。
        normalized = LocalTaskStore._normalized_segments(payload.get("segments") if isinstance(payload, dict) else None)
        if normalized:
            return normalized

        result = payload.get("result") if isinstance(payload, dict) else None
        utterances = result.get("utterances") if isinstance(result, dict) else None
        if not isinstance(utterances, list):
            return []

        segments = []
        for utterance in utterances:
            if not isinstance(utterance, dict):
                continue
            text = str(utterance.get("text") or "").strip()
            raw_start = utterance.get("start_time")
            raw_end = utterance.get("end_time")
            if not text or isinstance(raw_start, bool) or isinstance(raw_end, bool):
                continue
            try:
                start = float(raw_start) / 1000
                end = float(raw_end) / 1000
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                continue
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})

        return sorted(segments, key=lambda segment: (segment["start"], segment["end"]))

    @staticmethod
    def _normalized_segments(raw: Any) -> list[dict[str, Any]]:
        """解析创作服务返回的秒级句级时间码。"""
        if not isinstance(raw, list):
            return []
        segments = []
        for segment in raw:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or "").strip()
            start, end = segment.get("start"), segment.get("end")
            if not text or isinstance(start, bool) or isinstance(end, bool):
                continue
            try:
                start_seconds, end_seconds = float(start), float(end)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start_seconds) or not math.isfinite(end_seconds):
                continue
            if start_seconds < 0 or end_seconds <= start_seconds:
                continue
            segments.append({"start": round(start_seconds, 3), "end": round(end_seconds, 3), "text": text})
        return sorted(segments, key=lambda segment: (segment["start"], segment["end"]))

    def workspace(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if not task.directory:
            return {
                **task.public_view(),
                "transcript": "",
                "rewrite": "",
                "rewriteAvailable": False,
                "title": "未命名视频",
                "author": "—",
                "publishedAt": "未知发布时间",
                "duration": 0,
                "videoFile": "",
                "transcriptSegments": [],
                "waveformPeaks": [],
            }
        transcript_path = task.directory / "transcript.txt"
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.is_file() else ""
        task.rewrite_models = self._normalized_rewrite_models(task.rewrite_models, task.directory)
        rewrites = {}
        for model in REWRITE_MODELS:
            rewrite_path = task.directory / REWRITE_FILENAMES[model]
            try:
                rewrite_data = json.loads(rewrite_path.read_text(encoding="utf-8")) if rewrite_path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                rewrite_data = {}
            state = self._rewrite_state(task, model)
            content = str(rewrite_data.get("content") or "")
            rewrites[model] = {
                "content": content,
                "available": bool(content),
                "status": state["status"],
                "errorCode": state["errorCode"],
                "errorMessage": state["errorMessage"],
            }
        rewrite_data = rewrites["text-default"]
        transcript_segments = self._saved_transcript_segments(task.directory)
        audio_path = self._workspace_audio_file(task.directory)
        video_path = self._workspace_source_video_path(task.directory)
        compatibility = safari_compatibility_status(video_path) if video_path else None
        poster_file, poster_status = self._workspace_poster(video_path)
        return {
            **task.public_view(),
            **self._workspace_video_metadata(task.directory),
            "transcript": transcript,
            "rewrites": rewrites,
            "rewrite": rewrite_data["content"],
            "rewriteAvailable": rewrite_data["available"],
            "videoFile": self._workspace_video_file(task.directory),
            "safariCompatibility": compatibility.status if compatibility else "unavailable",
            "posterFile": poster_file,
            "posterStatus": poster_status,
            "transcriptSegments": transcript_segments or self._transcript_segments(transcript),
            "waveformPeaks": audio_waveform_peaks(audio_path) if audio_path else [],
        }

    async def rewrite(self, task_id: str, system_prompt: str, model: str = "text-default") -> dict[str, Any]:
        task = self.get(task_id)
        workspace = self.workspace(task_id)
        if not task.directory or not workspace["transcript"]:
            raise ValueError("当前任务尚无可用的转写内容。")
        settings = self._settings_loader()
        state = self._rewrite_state(task, model)
        if state["status"] == "running":
            raise ValueError("该模型正在生成脚本。")
        self._set_model_rewrite_status(task, model, "running")
        try:
            content = format_generated_rewrite(await self._text_service_client().rewrite(
                format_rewrite_source(workspace["transcript"], workspace["transcriptSegments"]), system_prompt, model=model
            ))
            self._write_rewrite(task.directory, content, system_prompt, "manual", model)
            self._set_model_rewrite_status(task, model, "complete")
        except TextServiceError as exc:
            self._set_model_rewrite_status(task, model, "failed", error_code=exc.code, error_message=exc.message)
            raise
        return self.workspace(task_id)

    def save_rewrite(self, task_id: str, content: str, model: str = "text-default") -> dict[str, Any]:
        task = self.get(task_id)
        if not task.directory:
            raise ValueError("当前任务尚未下载完成。")
        if self._rewrite_state(task, model)["status"] == "running":
            raise ValueError("该模型正在生成脚本。")
        self._write_rewrite(task.directory, content.strip(), self._settings_loader().rewrite_system_prompt, "manual-edit", model)
        self._set_model_rewrite_status(task, model, "complete")
        return self.workspace(task_id)
