"""Running USD spend per scope, so cap checks are one indexed read instead of a sum over llm_calls."""
from typing import Dict, Optional

from pymongo import UpdateOne

from ..database import spend_counters_collection
from ..models import now_ms

GLOBAL_SCOPE = "global"


def board_scope(board_id: str) -> str:
    return f"board:{board_id}"


def agent_scope(agent_id: str) -> str:
    return f"agent:{agent_id}"


class SpendCounters:
    async def add(self, agent_id: Optional[str], board_id: Optional[str], usd: float) -> None:
        scopes = [GLOBAL_SCOPE]
        if board_id:
            scopes.append(board_scope(board_id))
        if agent_id:
            scopes.append(agent_scope(agent_id))
        now = now_ms()
        await spend_counters_collection.bulk_write([
            UpdateOne({"_id": s}, {"$inc": {"usd": usd}, "$set": {"updatedAt": now},
                                   "$setOnInsert": {"seededAt": now, "seedUsd": 0.0}}, upsert=True)
            for s in scopes
        ], ordered=False)

    async def get(self, scope: str) -> float:
        doc = await spend_counters_collection.find_one({"_id": scope}, {"usd": 1})
        return float((doc or {}).get("usd", 0.0))

    async def set_many(self, totals: dict) -> None:
        """Overwrite counters (seeding). `totals` maps scope -> usd."""
        if not totals:
            return
        now = now_ms()
        await spend_counters_collection.bulk_write([
            UpdateOne({"_id": s}, {"$set": {"usd": usd, "updatedAt": now, "seededAt": now, "seedUsd": usd}}, upsert=True)
            for s, usd in totals.items()
        ], ordered=False)

    async def all(self) -> Dict[str, dict]:
        """Every counter as `{scope: {usd, seededAt, seedUsd}}`: its total began at `seedUsd` at `seededAt`
        (a seed from llm_calls, or 0 at first spend). Counters from before this marker have `seededAt` None."""
        return {d["_id"]: {"usd": float(d.get("usd", 0.0)), "seededAt": d.get("seededAt"),
                           "seedUsd": float(d.get("seedUsd", 0.0))}
                async for d in spend_counters_collection.find({})}

    async def correct(self, scope: str, usd: float) -> None:
        """Explicit repair only (reconcile --repair). Keeps `seededAt`."""
        await spend_counters_collection.update_one({"_id": scope}, {"$set": {"usd": usd, "updatedAt": now_ms()}})
