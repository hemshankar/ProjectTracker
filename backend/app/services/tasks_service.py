from fastapi import HTTPException

from .. import task_state
from ..database import boards_collection
from ..execution import concurrency, glow
from ..execution.events import events
from ..models import TaskUpdate, now_ms, sanitize_task, task_to_json
from . import audit_service

# A board sitting in one of these reflects a run that has nothing left to do.
# Reopening a task (or adding a new one) puts idle work back on the board, so
# its status — and the "done" glow the frontend renders from it — needs to
# catch up immediately rather than waiting for the next full run to cycle it.
_TERMINAL_BOARD_STATUSES = ("done", "failed", "stopped", "blocked")

# The statuses a task can be manually (re)started from — mirrors
# `routers/boards.py`'s `BOARD_STARTABLE_STATUSES` minus "done" (re-running a
# completed task isn't what this action is for; un-check it first).
TASK_RUNNABLE_STATUSES = ("idle", "failed", "stopped", "blocked")


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


async def reopen_board_if_terminal(board_id: str, board: dict) -> None:
    if board.get("status") not in _TERMINAL_BOARD_STATUSES:
        return
    reopened = await task_state.transition_board_status(board_id, _TERMINAL_BOARD_STATUSES, "idle")
    if reopened is not None:
        await events.publish(board_id, {"boardId": board_id, "status": "idle"})


def _find_task(board: dict, task_id: str) -> dict:
    task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def add_task(board_id: str, task_id: str, text: str, done: bool, actor_id: str) -> dict:
    board = await _get_board(board_id)
    task = sanitize_task({"id": task_id, "text": text, "done": done})
    if not task:
        raise HTTPException(status_code=400, detail="Task text is required")
    tasks = board.get("tasks", []) + [task]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    if task["status"] == "idle":
        await reopen_board_if_terminal(board_id, board)
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        task_id=task["id"],
        entity_type="task",
        action="create",
        actor_type="human",
        actor_id=actor_id,
        before=None,
        after=task,
    )
    return task_to_json(task)


async def update_task(board_id: str, task_id: str, payload: TaskUpdate, actor_id: str) -> dict:
    board = await _get_board(board_id)
    before = dict(_find_task(board, task_id))

    if payload.text is not None:
        result = await boards_collection.update_one(
            {"_id": board_id, "tasks.id": task_id},
            {"$set": {"tasks.$.text": payload.text, "updatedAt": now_ms()}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Task not found")

    if payload.done is not None:
        new_status = "done" if payload.done else "idle"
        updated_board = await task_state.transition_task_status(board_id, task_id, None, new_status)
        if updated_board is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if new_status == "idle":
            await reopen_board_if_terminal(board_id, board)

    board = await _get_board(board_id)
    after = _find_task(board, task_id)
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        task_id=task_id,
        entity_type="task",
        action="update",
        actor_type="human",
        actor_id=actor_id,
        before=before,
        after=after,
    )
    return {"ok": True}


async def delete_task(board_id: str, task_id: str, actor_id: str) -> None:
    board = await _get_board(board_id)
    before = _find_task(board, task_id)
    tasks = [t for t in board.get("tasks", []) if t["id"] != task_id]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    await glow.refresh_glow(board_id)
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        task_id=task_id,
        entity_type="task",
        action="delete",
        actor_type="human",
        actor_id=actor_id,
        before=before,
        after=None,
    )


async def prepare_task_for_run(board_id: str, task_id: str, actor_id: str) -> dict:
    """Validates and resets one task to `idle` for a standalone run (see
    `routers/boards.py`'s `POST /tasks/{id}/run`) — independent of the
    board's own Start/Stop. The caller kicks off the actual execution once
    this returns cleanly; raises HTTPException (409) if the task isn't in a
    runnable status or the Agent is at its concurrency cap.
    """
    board = await _get_board(board_id)
    task = _find_task(board, task_id)

    if task.get("status") not in TASK_RUNNABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Task can't be run from status '{task.get('status')}'"
        )

    agent_id = board.get("agentId")
    if agent_id is not None and not await concurrency.has_capacity(agent_id):
        raise HTTPException(status_code=409, detail="Agent is at its concurrency limit")

    reset = await task_state.transition_task_status(
        board_id, task_id, TASK_RUNNABLE_STATUSES, "idle", statusReason=None, currentRunId=None,
    )
    if reset is None:
        raise HTTPException(status_code=409, detail="Task changed status before it could be run")
    await events.publish(board_id, {"taskId": task_id, "status": "idle"})
    await audit_service.write_audit(
        agent_id=agent_id,
        board_id=board_id,
        task_id=task_id,
        entity_type="task",
        action="update",
        actor_type="human",
        actor_id=actor_id,
        before=task,
        after=_find_task(reset, task_id),
    )
    return reset


async def clear_completed_tasks(board_id: str, actor_id: str) -> None:
    board = await _get_board(board_id)
    tasks = board.get("tasks", [])
    removed = [t for t in tasks if t.get("status") == "done"]
    if not removed:
        return
    remaining = [t for t in tasks if t.get("status") != "done"]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": remaining, "updatedAt": now_ms()}}
    )
    await glow.refresh_glow(board_id)
    for t in removed:
        await audit_service.write_audit(
            agent_id=board.get("agentId"),
            board_id=board_id,
            task_id=t["id"],
            entity_type="task",
            action="delete",
            actor_type="human",
            actor_id=actor_id,
            before=t,
            after=None,
        )
