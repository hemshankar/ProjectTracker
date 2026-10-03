"""Seed spend counters from the authoritative sum of llm_calls (sets, never increments)."""
from typing import Dict

from ..database import llm_calls_collection
from .counters import GLOBAL_SCOPE, SpendCounters, agent_scope, board_scope


async def sum_llm_calls() -> Dict[str, float]:
    totals: Dict[str, float] = {GLOBAL_SCOPE: 0.0}
    async for row in llm_calls_collection.find({}, {"usd": 1, "boardId": 1, "agentId": 1}):
        usd = row.get("usd", 0.0)
        totals[GLOBAL_SCOPE] += usd
        for key, scope in (("boardId", board_scope), ("agentId", agent_scope)):
            if row.get(key):
                totals[scope(row[key])] = totals.get(scope(row[key]), 0.0) + usd
    return totals


async def seed_counters(counters: SpendCounters, dry_run: bool = False) -> Dict[str, float]:
    totals = await sum_llm_calls()
    if not dry_run:
        await counters.set_many(totals)
    return totals
