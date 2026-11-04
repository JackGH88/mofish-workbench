"""Shared frozen account inputs for monitor and radar recommendations; no collection or model side effects."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .radar import parse_iso
from .review import METRIC_ORDER, PERCENT_FIELDS


class EmptyHookLibraryError(ValueError):
    """The operator removed every usable hook in this workspace."""


def build_account_inputs(account_id: str, workspace, review_store, *, now=None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=30)
    scripts = {str(s.get("id")): s for s in workspace.list_scripts(account_id)
               if str(s.get("accountId")) == account_id}
    works = []
    unknown_dates = 0
    for work in review_store.recommendation_works(account_id):
        if str(work.get("accountId")) != account_id or work.get("kind", "video") != "video":
            continue
        published = parse_iso(str(work.get("publishedAtIso") or "").replace("Z", "+00:00"))
        if published is None:
            unknown_dates += 1
            continue
        if not cutoff <= published <= moment:
            continue
        script = scripts.get(str(work.get("scriptId") or "")) or {}
        writing = script.get("writingState") or {}
        content = str((writing.get("content") if script.get("source") == "link" else script.get("content")) or "")
        factors = work.get("factors") or {}
        works.append({
            "id": str(work.get("id") or ""), "title": str(work.get("title") or ""),
            "publishedAt": work.get("publishedAtIso"), "collectedAt": work.get("collectedAt") or None,
            "metrics": {key: (work.get("metrics") or {}).get(key) for key in METRIC_ORDER},
            "factors": {key: factors.get(key) for key in ("topic", "hook", "structure", "confirmedAt", "source")},
            "scriptOpening": content[:400] or None, "scriptOpeningTruncated": len(content) > 400,
            "note": work.get("note") or None,
        })
    works.sort(key=lambda w: parse_iso(str(w["publishedAt"]).replace("Z", "+00:00")), reverse=True)
    gaps = []
    if not works:
        gaps.append("最近30天没有当前账号的复盘视频，建议没有本账号历史表现支持。")
    missing_hooks = sum(not (w["factors"].get("hook") or {}).get("name") for w in works)
    missing_scripts = sum(not w["scriptOpening"] for w in works)
    missing_metrics = sum(any(v is None for v in w["metrics"].values()) for w in works)
    if missing_hooks:
        gaps.append(f"{missing_hooks}条视频未标注开头钩子，不得推测为已确认类型。")
    if missing_scripts:
        gaps.append(f"{missing_scripts}条视频没有可关联的脚本开头。")
    if missing_metrics:
        gaps.append(f"{missing_metrics}条视频存在缺失指标，null不代表0。")
    if unknown_dates:
        gaps.append(f"{unknown_dates}条视频发布时间未知，未纳入30天窗口。")
    review = {"from": cutoff.isoformat(), "to": moment.isoformat(), "windowDays": 30,
              "total": len(works), "submitted": len(works), "truncated": False,
              "selectionRule": "按发布时间取最近30天全部视频，不按表现筛选；关联脚本仅取前400字。",
              "metricUnits": {key: "百分比数值，例如25表示25%" if key in PERCENT_FIELDS else "计数" for key in METRIC_ORDER},
              "gaps": gaps, "works": works}
    review["metricUnits"]["avgImagesViewed"] = "张"
    return {"review": review}
