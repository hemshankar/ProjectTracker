"""Abrupt per-task Stop: cancels whatever `asyncio.Task` is currently
driving a task's progress (the automatic loop's stage task, a standalone
single-task run, or a deferred approval's background wait/execute) rather
than waiting for it to finish on its own.

`TaskRunRegistry` is the per-task counterpart to `execution/registry.py`'s
board-level `RunnerRegistry` — every place that actually drives a task
forward registers `asyncio.current_task()` under that task's id for the
duration, so a Stop action anywhere can find and cancel exactly that
coroutine, without disturbing sibling tasks or the board's own loop.
"""
import asyncio
from typing import Dict, Optional

from .. import task_state
from ..database import boards_collection
from ..services import audit_service
from . import completion, delegation
from .context import finish_task_run
from .events import events

STOPPABLE_STATUSES = ("running", "queued")
_SUSPENDED_STATUSES = ("awaiting_approval", "awaiting_reply", "awaiting_clarification", "manual")


class TaskRunRegistry:
    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}

    def register(self, task_id: str, task: asyncio.Task) -> None:
        self._tasks[task_id] = task

    def unregister(self, task_id: str, task: asyncio.Task) -> None:
        # Only clear if this call still owns the slot — a fresh run may
        # already have registered its own task under the same id by the
        # time this one's `finally` runs.
        if self._tasks.get(task_id) is task:
            self._tasks.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True


task_registry = TaskRunRegistry()


async def mark_stopped(board_id: str, task_id: str, run_id: Optional[str], agent_id: Optional[str]) -> None:
    """Shared cleanup once a task's in-flight work has actually been
    interrupted — same bookkeeping shape every other terminal-status path
    already uses (`resume.py`'s `resume_task`, `enforcement.py`'s
    `_finalize_abandoned`). The compare-and-swap means a cancellation that
    lands after the task already reached its true terminal status harmlessly
    no-ops instead of clobbering it — a narrow, acceptable race.
    """
    after = await task_state.transition_task_status(
        board_id, task_id, STOPPABLE_STATUSES, "stopped", statusReason="user", currentRunId=None,
    )
    if after is None:
        return
    if run_id:
        await finish_task_run(run_id, "stopped", "Stopped by user")
    await events.publish(board_id, {"taskId": task_id, "status": "stopped", "statusReason": "user"})
    task = next((t for t in after.get("tasks", []) if t["id"] == task_id), None)
    if task is not None:
        await audit_service.write_audit(
            agent_id=agent_id, board_id=board_id, task_id=task_id,
            entity_type="task", action="update", actor_type="human", actor_id=None,
            before=None, after=task,
        )
        await delegation.on_task_resolved(task, "Stopped by user.")
    await completion.try_complete_board(board_id)


async def stop_task(board_id: str, task_id: str, actor_id: str) -> str:
    """Stops one task right now. Raises `ValueError` (→ 409 at the router)
    if the task isn't in a stoppable state at all."""
    board = await boards_collection.find_one({"_id": board_id})
    if board is None:
        raise ValueError("Board not found")
    task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        raise ValueError("Task not found")
    status = task.get("status")

    if status in STOPPABLE_STATUSES:
        if not task_registry.cancel(task_id):
            # Nothing tracked — e.g. a race with the run finishing right as
            # Stop was clicked. Fall back to a direct transition so the task
            # doesn't dangle.
            await mark_stopped(board_id, task_id, task.get("currentRunId"), board.get("agentId"))
        return "stopped"

    if status in _SUSPENDED_STATUSES:
        # No live coroutine to cancel — just sitting in the DB waiting on a
        # human. Resolve it straight to `stopped`.
        after = await task_state.transition_task_status(
            board_id, task_id, [status], "stopped", statusReason="user", currentRunId=None,
        )
        if after is None:
            raise ValueError("Task changed status before it could be stopped")
        await events.publish(board_id, {"taskId": task_id, "status": "stopped", "statusReason": "user"})
        after_task = next(t for t in after.get("tasks", []) if t["id"] == task_id)
        await audit_service.write_audit(
            agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
            entity_type="task", action="update", actor_type="human", actor_id=actor_id,
            before=task, after=after_task,
        )
        await delegation.on_task_resolved(after_task, "Stopped by user.")
        await completion.try_complete_board(board_id)
        return "stopped"

    raise ValueError(f"Task can't be stopped from status '{status}'")
