import time
from typing import Any, Dict, Optional


class AuditService:
    """Append-only. Never receives payload contents (args/results)."""

    def __init__(self, db):
        self._col = db["audit_log"]

    async def record(self, actor: str, action: str, target: str, outcome: str = "ok",
                     duration_ms: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> None:
        await self._col.insert_one({"actor": actor, "action": action, "target": target, "outcome": outcome,
                                    "durationMs": duration_ms, "extra": extra or {}, "at": int(time.time() * 1000)})

    async def list(self, limit: int = 50, skip: int = 0) -> list:
        cursor = self._col.find({}, {"_id": 0}).sort("at", -1).skip(skip).limit(limit)
        return [doc async for doc in cursor]
