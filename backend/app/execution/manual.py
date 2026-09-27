"""Resolution for a pending `mark_manual` hold: a human records what actually
happened with whoever the agent was waiting on outside the system (mirroring
`clarification.py`'s answer-recording, on the same `manual_hold` message
rather than as a separate chat message), and the task's conversation resumes
from `manual`.
"""
from typing import Optional

from ..database import boards_collection
from ..services import audit_service, chats_service
from . import delegation
from .resume import TERMINAL_STATUSES, resume_task


async def _get_board(board_id: str) -> dict:
    return await boards_collection.find_one({"_id": board_id})


def _find_pending_hold(chat: dict, task_id: str) -> Optional[dict]:
    for m in reversed(chat.get("messages", [])):
        payload = m.get("payload", {})
        if m.get("type") == "manual_hold" and payload.get("taskId") == task_id and payload.get("status") == "pending":
            return m
    return None


async def resolve(board_id: str, task_id: str, resolution_text: str, actor_id: str) -> dict:
    """Raises ValueError (→ 409 at the router) if the task isn't actually
    marked manual, or has no pending hold — mirrors `clarification.answer`'s
    guards."""
    board = await _get_board(board_id)
    task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        raise ValueError("Task not found")
    if task.get("status") != "manual":
        raise ValueError("Task is not awaiting manual resolution")

    chat = await chats_service.get_or_create_task_chat(board, task)
    pending = _find_pending_hold(chat, task_id)
    if pending is None:
        raise ValueError("No pending manual hold for this task")

    await chats_service.update_message_payload(
        board_id, chat["id"], pending["id"], {"status": "resolved", "resolution": resolution_text}
    )

    board_json = await resume_task(board_id, chat["id"], task_id, "done", ["manual"])

    await audit_service.write_audit(
        agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
        entity_type="chat_message", action="update", actor_type="human", actor_id=actor_id,
        before={"id": pending["id"], "status": "pending"},
        after={"id": pending["id"], "status": "resolved"},
    )

    after_board = await _get_board(board_id)
    after_task = next(t for t in after_board.get("tasks", []) if t["id"] == task_id)
    if after_task.get("status") in TERMINAL_STATUSES:
        await delegation.on_task_resolved(
            after_task, delegation.extract_result_text(after_board, after_task, after_task["status"])
        )
    return board_json
