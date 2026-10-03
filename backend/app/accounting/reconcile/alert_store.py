"""Persistent alerts: one document per condition key, opened when it fires and resolved when it clears."""
import logging
from typing import Iterable, List

from ...database import system_alerts_collection as coll
from ...models import now_ms
from .alerts import Alert

log = logging.getLogger(__name__)
SEVERITY_ORDER = {"error": 0, "warning": 1}


class AlertStore:
    async def apply(self, active: Iterable[Alert], managed_keys: Iterable[str]) -> None:
        """Open/refresh every active alert, and resolve open ones in `managed_keys` that are no longer active.
        Callers pass only the keys their own check is authoritative for."""
        active = list(active)
        now = now_ms()
        for alert in active:
            await self._raise(alert, now)
        firing = {a.key for a in active}
        stale = [k for k in managed_keys if k not in firing]
        if stale:
            await coll.update_many({"_id": {"$in": stale}, "status": "open"},
                                   {"$set": {"status": "resolved", "resolvedAt": now}})

    async def _raise(self, alert: Alert, now: int) -> None:
        existing = await coll.find_one({"_id": alert.key, "status": "open"}, {"_id": 1})
        if existing:
            await coll.update_one({"_id": alert.key}, {"$set": {"message": alert.message, "lastSeenAt": now},
                                                       "$inc": {"count": 1}})
            return
        log.error("ALERT %s: %s", alert.title, alert.message)
        await coll.replace_one({"_id": alert.key}, {
            "_id": alert.key, "severity": alert.severity, "title": alert.title, "message": alert.message,
            "status": "open", "firstSeenAt": now, "lastSeenAt": now, "count": 1,
            "acknowledgedAt": None, "acknowledgedBy": None, "resolvedAt": None}, upsert=True)

    async def list(self, include_resolved: bool = False, limit: int = 100) -> List[dict]:
        query = {} if include_resolved else {"status": "open"}
        rows = await coll.find(query).sort("lastSeenAt", -1).limit(limit).to_list(limit)
        rows.sort(key=lambda r: (r["status"] != "open", SEVERITY_ORDER.get(r["severity"], 9)))
        return [{**{k: v for k, v in r.items() if k != "_id"}, "key": r["_id"]} for r in rows]

    async def acknowledge(self, key: str, user_id: str) -> bool:
        res = await coll.update_one({"_id": key, "status": "open"},
                                    {"$set": {"acknowledgedAt": now_ms(), "acknowledgedBy": user_id}})
        return res.matched_count == 1

    async def summary(self) -> dict:
        """What the bell shows: open alerts the user hasn't acknowledged, and the worst severity among them."""
        rows = await coll.find({"status": "open", "acknowledgedAt": None}, {"severity": 1}).to_list(None)
        worst = min((r["severity"] for r in rows), key=lambda s: SEVERITY_ORDER.get(s, 9), default=None)
        return {"unacknowledged": len(rows), "severity": worst}
