"""Agent-wide concurrency cap (Phase 6): `agent_settings.concurrency.maxConcurrentTasks`
bounds how many of an Agent's task_runs may be `running` at once, across all
of its boards — independent of, and checked before, budget/rate-limit/lock
enforcement. Best-effort (a plain count, not a compare-and-swap): a stale
read just means two of an Agent's board runners momentarily squeeze one
extra task through together, which is fine for a cost/DB-load guard that
isn't meant to be a correctness boundary.
"""
import asyncio
from typing import Optional

from .. import config
from ..database import agent_settings_collection, boards_collection, task_runs_collection


async def _cap_for(agent_id: str) -> Optional[int]:
    settings = await agent_settings_collection.find_one({"_id": agent_id}, {"concurrency": 1})
    return ((settings or {}).get("concurrency") or {}).get("maxConcurrentTasks")


async def has_capacity(agent_id: str) -> bool:
    cap = await _cap_for(agent_id)
    if cap is None:
        return True
    running = await task_runs_collection.count_documents({"agentId": agent_id, "status": "running"})
    return running < cap


async def wait_for_capacity(agent_id: str, board_id: str) -> bool:
    """Polls until a concurrency slot opens up, or the board's Stop flag is
    set. Returns False if abandoned via Stop — the caller leaves the not-yet-
    claimed task idle, same as any task on a board that never got started."""
    while not await has_capacity(agent_id):
        board = await boards_collection.find_one({"_id": board_id}, {"stopRequested": 1})
        if board and board.get("stopRequested"):
            return False
        await asyncio.sleep(config.RATE_LIMIT_POLL_SECONDS)
    return True
