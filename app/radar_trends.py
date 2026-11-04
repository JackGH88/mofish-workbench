"""Daily shared rising-search cache and in-flight request coalescing."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .creation_data import (
    CAPABILITY_TRENDS,
    PlatformDataError,
    trends_to_rows,
)
from .radar import RADAR_MIN_RETRY_SECONDS, RadarStore, trend_day
from .monitor import parse_iso
from .upstream_errors import sanitize_message

_inflight: dict[tuple[Any, str], asyncio.Task] = {}


def current_time() -> datetime:
    return datetime.now(timezone.utc)


async def collect_trend(store: RadarStore, client: Any, text: str, *, scheduled: bool = False) -> dict[str, Any]:
    text = " ".join(text.split())
    key = (store, text)
    # No await between lookup and registration: all subscribers join the same task.
    task = _inflight.get(key)
    if task is not None:
        result = await asyncio.shield(task)
        return {**result, "requests": 0, "chargedPoints": "0.000"}
    task = asyncio.create_task(_collect(store, client, text, scheduled=scheduled))
    _inflight[key] = task
    task.add_done_callback(lambda finished: _inflight.pop(key, None) if _inflight.get(key) is finished else None)
    return await asyncio.shield(task)


async def _collect(store: RadarStore, client: Any, text: str, *, scheduled: bool) -> dict[str, Any]:
    cached = await asyncio.to_thread(store.shared_trend, text)
    if cached.get("successDay") == trend_day(current_time()) and cached.get("items"):
        return {"requests": 0, "error": ""}
    if scheduled and cached.get("status") in {"failed", "running"}:
        return {"requests": 0, "error": sanitize_message(str(cached.get("error") or "热度榜已暂停自动重试，请手动同步。"))}
    last_attempt = parse_iso(cached.get("lastAttemptAt"))
    if scheduled and last_attempt and (current_time() - last_attempt).total_seconds() < RADAR_MIN_RETRY_SECONDS:
        return {"requests": 0, "error": sanitize_message(str(cached.get("error") or "热度榜等待重试。"))}
    await asyncio.to_thread(store.mark_trend_attempt, text, now=current_time(),
                            business_context=dict(getattr(client, "business_context", {}) or {}))
    error = ""
    rows = []
    charged = 0.0
    try:
        # client 是创作服务数据客户端：热度榜同样是 capability=trends 的一次有效查询。
        result = await client.query(CAPABILITY_TRENDS, {"keyword": text})
        charged = float(result.get("chargedPoints") or 0)
        rows = trends_to_rows(result.get("page") or {})
        if not rows:
            error = "热度榜返回空数据，稍后重试。"
    except PlatformDataError as exc:
        error = exc.message
    except Exception:
        error = "热度榜请求或数据解析失败，稍后重试。"
    finally:
        # Single transport attempt (including timeouts), cache reads cost zero.
        await asyncio.to_thread(store.record_requests, "trend", 1)
    await asyncio.to_thread(store.save_shared_trend, text, rows, error=error, now=current_time())
    return {"requests": 1, "error": error, "chargedPoints": "%0.3f" % charged}
