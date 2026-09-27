from fastapi import HTTPException

from .. import task_state
from ..database import boards_collection
from ..execution.events import events
from ..models import TaskUpdate, now_ms, sanitize_task, task_to_json
from . import audit_service

# A board sitting in one of these reflects a run that has nothing left to do.
# Reopening a task (or adding a new one) puts idle work back on the board, so
# its status — and the "done" glow the frontend renders from it — needs to
# catch up immediately rather than waiting for the next full run to cycle it.
_TERMINAL_BOARD_STATUSES = ("done", "failed", "stopped", "blocked")


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


async def _reopen_board_if_terminal(board_id: str, board: dict) -> None:
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
        await _reopen_board_if_terminal(board_id, board)
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
            await _reopen_board_if_terminal(board_id, board)

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
