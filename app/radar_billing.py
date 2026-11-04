"""Read-only, account-attributed radar settlement totals.

Only complete snapshots are published. The legacy radar usage accumulator is
deliberately not a fallback: it has no account attribution.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
CN_TZ = ZoneInfo("Asia/Shanghai")


def settlement(row):
    """Return an actual task expense (negative for an explicit task refund)."""
    kind = row.get("kind")
    if kind not in ("settle", "adjust", "refund"):
        return None
    if not row.get("taskId") and row.get("refType") != "task":
        return None
    # release returns unspent frozen points; grant/revoke relate to subscriptions.
    amount = -(Decimal(str(row.get("availableDelta") or "0"))
               + Decimal(str(row.get("frozenDelta") or "0")))
    if not amount.is_finite():
        raise ValueError("invalid settlement")
    if kind in ("adjust", "refund") and amount >= 0:
        return None
    if not amount:
        return None
    context = row.get("businessContext") or {}
    if context.get("source") not in (None, "", "radar"):
        return None
    return {"id": str(row["id"]), "taskId": str(row.get("taskId") or row.get("refId") or ""),
            "accountId": str(context.get("accountId") or "") if context.get("source") == "radar" else "",
            "source": str(context.get("source") or ""), "points": format(amount, ".3f"),
            "createdAt": str(row.get("createdAt") or "")}


class RadarBillingCache:
    def __init__(self, workspace: Path, *, ttl=15):
        self.directory = Path(workspace) / "radar-billing"
        self.ttl = ttl
        self._tasks = {}
        self._owners = {}
        self._snapshots = {}
        self._states = {}
        self._checked = {}
        self._locks = {}

    def _path(self, owner):
        return self.directory / (hashlib.sha256(owner.encode()).hexdigest() + ".json")

    def _load(self, owner):
        if owner not in self._snapshots:
            try:
                data = json.loads(self._path(owner).read_text())
                if data.get("version") != 1 or not data.get("complete"):
                    data = {}
            except (OSError, ValueError, AttributeError):
                data = {}
            self._snapshots[owner] = data
        return self._snapshots[owner]

    def _save(self, owner, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(owner)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self._snapshots[owner] = data

    async def sync(self, service):
        key = service.ledger_session_key()
        pending = self._tasks.get(key)
        if pending is None or pending.done():
            pending = asyncio.create_task(self._sync(service, key))
            self._tasks[key] = pending
        await asyncio.shield(pending)

    async def _sync(self, service, key):
        self._states[key] = "syncing"
        try:
            owner, read_page = await service.point_history_reader()
            if service.ledger_session_key() != key:
                raise ValueError("session changed")
            self._owners[key] = owner
            lock = self._locks.setdefault(owner, asyncio.Lock())
            async with lock:
                old = self._load(owner)
                # Offset pagination may move while new settlements arrive. Retry
                # from the head, keeping the old complete snapshot until stable.
                for _ in range(3):
                    first = await read_page(1)
                    total = int(first["total"])
                    head = str(first["items"][0]["id"]) if first["items"] else ""
                    boundary = old.get("headId") if old.get("complete") else None
                    rows, found, page = {}, False, first
                    new_ids = set()
                    number = 1
                    while True:
                        items = page.get("items")
                        if not isinstance(items, list) or (not items and total > (number - 1) * 100):
                            raise ValueError("incomplete ledger page")
                        for row in items:
                            ident = str(row["id"])
                            if not ident:
                                raise ValueError("missing ledger id")
                            if ident == boundary:
                                found = True
                            elif not found:
                                new_ids.add(ident)
                            rows[ident] = row
                        if found or number * 100 >= total:
                            break
                        number += 1
                        page = await read_page(number)
                    last_head = await read_page(1)
                    last_id = str(last_head["items"][0]["id"]) if last_head["items"] else ""
                    if last_id != head or int(last_head["total"]) != total:
                        continue
                    if not found and len(rows) != total:
                        raise ValueError("incomplete ledger history")
                    if found and len(new_ids) != total - int(old["ledgerEntryCount"]):
                        raise ValueError("incomplete incremental history")
                    expenses = dict(old.get("entries") or {}) if found else {}
                    for ident, row in rows.items():
                        value = settlement(row)
                        if value is not None:
                            expenses[ident] = value
                        else:
                            expenses.pop(ident, None)
                    if service.ledger_session_key() != key:
                        raise ValueError("session changed")
                    snapshot = {"version": 1, "complete": True, "headId": head,
                                "ledgerEntryCount": total, "entries": expenses,
                                "syncedAt": datetime.now(timezone.utc).isoformat()}
                    self._save(owner, snapshot)
                    self._states[key] = "ready"
                    break
                else:
                    raise ValueError("ledger changed during pagination")
        except asyncio.CancelledError:
            self._states[key] = "error"
            raise
        except Exception as exc:
            self._states[key] = "error"
            logger.info("radar_billing_sync_failed error=%s", type(exc).__name__)
        finally:
            self._checked[key] = time.monotonic()

    def view(self, service, account_id):
        key = service.ledger_session_key()
        pending = self._tasks.get(key)
        if (pending is None or pending.done()) and time.monotonic() - self._checked.get(key, float("-inf")) >= self.ttl:
            self._states[key] = "syncing"
            self._tasks[key] = asyncio.create_task(self._sync(service, key))
        owner = self._owners.get(key)
        snapshot = self._load(owner) if owner else {}
        total = today = None
        if snapshot.get("complete"):
            total = today = Decimal("0")
            day = datetime.now(CN_TZ).date()
            for row in snapshot["entries"].values():
                if not account_id or row["accountId"] != account_id:
                    continue
                total += Decimal(row["points"])
                if row.get("createdAt") and datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00")).astimezone(CN_TZ).date() == day:
                    today += Decimal(row["points"])
        return {"chargedTotalPoints": format(total, ".3f") if total is not None else None,
                "chargedTodayPoints": format(today, ".3f") if today is not None else None,
                "syncStatus": self._states.get(key, "syncing"),
                "syncedAt": snapshot.get("syncedAt", ""), "scope": "account"}

    def report(self, service):
        owner = self._owners.get(service.ledger_session_key())
        snapshot = self._load(owner) if owner else {}
        accounts, unassigned = {}, []
        for row in (snapshot.get("entries") or {}).values():
            if row["accountId"]:
                accounts[row["accountId"]] = accounts.get(row["accountId"], Decimal("0")) + Decimal(row["points"])
            else:
                unassigned.append(row)
        return {"complete": bool(snapshot.get("complete")), "syncedAt": snapshot.get("syncedAt", ""),
                "ledgerEntryCount": snapshot.get("ledgerEntryCount", 0),
                "accounts": {key: format(value, ".3f") for key, value in accounts.items()},
                "unattributedPoints": format(sum((Decimal(row["points"]) for row in unassigned), Decimal("0")), ".3f"),
                "unattributedEntries": unassigned}
