"""Not-yet-delivered usage, read from the outbox: the delta between the service total and reality."""
from typing import Dict, List, Optional

from ..database import usage_outbox_collection as coll

_UNDELIVERED = {"status": {"$in": ["pending", "sending"]}}


class PendingUsage:
    async def by_scope(self, field: str, ids: List[str]) -> Dict[str, float]:
        """Sum of undelivered event USD per board/task id (`field` is 'boardId' or 'taskId')."""
        if not ids:
            return {}
        path = f"event.{field}"
        pipeline = [{"$match": {**_UNDELIVERED, path: {"$in": ids}}},
                    {"$group": {"_id": f"${path}", "usd": {"$sum": "$event.usd"}}}]
        return {r["_id"]: r["usd"] async for r in coll.aggregate(pipeline)}

    async def for_agent(self, agent_id: str) -> float:
        pipeline = [{"$match": {**_UNDELIVERED, "event.agentId": agent_id}},
                    {"$group": {"_id": None, "usd": {"$sum": "$event.usd"}}}]
        return next(iter([r["usd"] async for r in coll.aggregate(pipeline)]), 0.0)

    async def since_total(self, field: Optional[str], scope_id: Optional[str], since_ms: int) -> float:
        """Undelivered USD for a counter scope (`field` None = global) with event ts >= since_ms."""
        match: dict = {**_UNDELIVERED, "event.ts": {"$gte": since_ms}}
        if field:
            match[f"event.{field}"] = scope_id
        rows = [r async for r in coll.aggregate([{"$match": match}, {"$group": {"_id": None, "usd": {"$sum": "$event.usd"}}}])]
        return rows[0]["usd"] if rows else 0.0
