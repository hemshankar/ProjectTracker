"""Durable queue of usage events awaiting delivery. `_id` = callId, so enqueue is idempotent."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..database import usage_outbox_collection as coll
from ..models import now_ms


class OutboxRepository:
    async def enqueue(self, event: dict) -> bool:
        """False if this callId was already queued."""
        now = now_ms()
        try:
            await coll.insert_one({"_id": event["callId"], "event": event, "status": "pending", "attempts": 0,
                                   "nextAttemptAt": now, "lastError": None, "createdAt": now})
        except DuplicateKeyError:
            return False
        return True

    async def claim(self, limit: int, lease_ms: int, now: Optional[int] = None) -> List[dict]:
        """Atomically lease up to `limit` due rows. Rows whose lease expired are reclaimable."""
        now = now if now is not None else now_ms()
        due = {"$or": [{"status": "pending", "nextAttemptAt": {"$lte": now}},
                       {"status": "sending", "leaseUntil": {"$lt": now}}]}
        claimed: List[dict] = []
        while len(claimed) < limit:
            doc = await coll.find_one_and_update(
                due, {"$set": {"status": "sending", "leaseUntil": now + lease_ms}},
                sort=[("nextAttemptAt", 1)], return_document=ReturnDocument.AFTER)
            if doc is None:
                break
            claimed.append(doc)
        return claimed

    async def mark_delivered(self, ids: List[str]) -> None:
        if ids:
            await coll.update_many({"_id": {"$in": ids}}, {"$set": {
                "status": "delivered", "deliveredAt": datetime.now(timezone.utc), "leaseUntil": None}})

    async def mark_rejected(self, call_id: str, reason: str) -> None:
        await coll.update_one({"_id": call_id}, {"$set": {"status": "rejected", "lastError": reason,
                                                          "leaseUntil": None}})

    async def reschedule(self, call_id: str, error: str, next_attempt_at: int) -> None:
        await coll.update_one({"_id": call_id}, {
            "$set": {"status": "pending", "lastError": error, "nextAttemptAt": next_attempt_at, "leaseUntil": None},
            "$inc": {"attempts": 1}})

    async def undelivered_ids(self, ids: List[str]) -> List[str]:
        """Ids still queued (pending/sending): expected to be missing from the ledger, so not drift."""
        found = coll.find({"_id": {"$in": ids}, "status": {"$in": ["pending", "sending"]}}, {"_id": 1})
        return [d["_id"] async for d in found]

    async def requeue(self, event: dict) -> None:
        """Repair: put an event back in the queue even if an earlier row (delivered/rejected) exists."""
        if not await self.enqueue(event):
            await coll.update_one({"_id": event["callId"]}, {"$set": {
                "event": event, "status": "pending", "attempts": 0, "nextAttemptAt": now_ms(),
                "lastError": None, "leaseUntil": None}})

    async def stats(self) -> dict:
        pending = await coll.count_documents({"status": {"$in": ["pending", "sending"]}})
        rejected = await coll.count_documents({"status": "rejected"})
        oldest = await coll.find_one({"status": {"$in": ["pending", "sending"]}}, {"createdAt": 1},
                                     sort=[("createdAt", 1)])
        age = (now_ms() - oldest["createdAt"]) // 1000 if oldest else 0
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        delivered = await coll.count_documents({"status": "delivered", "deliveredAt": {"$gte": hour_ago}})
        return {"pending": pending, "rejected": rejected, "oldestPendingAgeSeconds": age,
                "deliveredLastHour": delivered}
