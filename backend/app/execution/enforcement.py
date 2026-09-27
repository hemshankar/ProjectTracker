"""Wires the three enforcement checks from Phase 5's design into the agent
loop, in order, before a tool call actually runs:

1. Rate limit — an empty bucket parks the task in `queued` and polls rather
   than failing it.
2. Budget — raises `BudgetExceededError`; the caller lets the in-flight step
   finish, then halts before the next one (see `loop.py`).
3. Resource lock (mutating calls only) — held elsewhere parks the task in
   `queued` and polls, same as a rate limit wait.

Both polling waits bail out early if the board's Stop flag is set, so a
human Stop still takes effect while a task is parked waiting.
"""
import asyncio
from typing import Optional

from .. import config, task_state
from ..database import boards_collection
from ..services import budget_service, lock_service, rate_limit_service
from .events import events


class BudgetExceededError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def check_budget(agent_id: Optional[str], board_id: str) -> None:
    reason = await budget_service.check_exceeded(agent_id, board_id)
    if reason:
        raise BudgetExceededError(reason)


async def halt_board(board_id: str, status: str, reason: Optional[str] = None) -> None:
    await task_state.transition_board_status(
        board_id, ["queued", "running"], status, stopRequested=False, statusReason=reason
    )
    await events.publish(board_id, {"boardId": board_id, "status": status, "statusReason": reason})


async def _board_stop_requested(board_id: str) -> bool:
    board = await boards_collection.find_one({"_id": board_id}, {"stopRequested": 1})
    return bool(board and board.get("stopRequested"))


async def _wait_parked(board_id: str, task_id: str, condition) -> bool:
    """Parks the task in `queued` and polls `condition` until it returns
    True, or the board is stopped. Returns False if the wait was abandoned —
    the task is left in `stopped` in that case, never dangling in `queued`
    or `running` with nothing left watching it."""
    parked = await task_state.transition_task_status(board_id, task_id, ["running"], "queued")
    if parked is not None:
        await events.publish(board_id, {"taskId": task_id, "status": "queued"})

    while not await condition():
        if await _board_stop_requested(board_id):
            await task_state.transition_task_status(
                board_id, task_id, ["queued"], "stopped", statusReason="user"
            )
            await events.publish(board_id, {"taskId": task_id, "status": "stopped", "statusReason": "user"})
            return False
        await asyncio.sleep(config.RATE_LIMIT_POLL_SECONDS)

    resumed = await task_state.transition_task_status(board_id, task_id, ["queued"], "running")
    if resumed is not None:
        await events.publish(board_id, {"taskId": task_id, "status": "running"})
    return True


async def wait_for_rate_limit(agent_id: str, board_id: str, task_id: str, tool_type: Optional[str]) -> bool:
    if tool_type is None:
        return True
    if await rate_limit_service.try_consume(agent_id, tool_type):
        return True
    return await _wait_parked(board_id, task_id, lambda: rate_limit_service.try_consume(agent_id, tool_type))


async def wait_for_lock(board_id: str, task_id: str, resource_key: str, run_id: str) -> bool:
    if await lock_service.try_acquire(resource_key, run_id):
        return True
    return await _wait_parked(board_id, task_id, lambda: lock_service.try_acquire(resource_key, run_id))
