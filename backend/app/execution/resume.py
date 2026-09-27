"""Shared "resume a suspended task by re-running its conversation" shape.

Four places call a task's `agent_service.run_task_step` again after some
external event resolves whatever it was waiting on: `approval.py` (a human
approved/rejected an `action_request`), `clarification.py` (a human answered
an `ask_user` question), `manual.py` (a human resolved a `mark_manual` hold —
typically because whoever the agent was waiting on outside the system
responded), and `delegation.py` (a peer Agent's reply came back). All four
rebuild the model-facing history fresh from `chat["messages"]`
— the same fresh-rebuild property that makes `to_anthropic_messages` safe to
call repeatedly — then need the same persist/transition/publish/audit/
completion bookkeeping. This module is that shared bookkeeping; each caller
still does its own caller-specific work (e.g. approval's own audit record of
the human's approve/reject decision) before or after calling it.
"""
from typing import Iterable, Optional

from .. import task_state
from ..database import boards_collection
from ..models import board_to_json
from ..services import audit_service, chats_service
from . import agent_service, completion
from .context import finish_task_run
from .enforcement import BudgetExceededError, halt_board
from .events import events

TERMINAL_STATUSES = {"done", "failed", "blocked", "stopped"}
SUSPEND_STATUSES = ("awaiting_approval", "awaiting_reply", "awaiting_clarification", "manual")


async def resume_task(
    board_id: str, chat_id: str, task_id: str, fallback_status: str, prior_statuses: Iterable[str]
) -> dict:
    """Re-runs `task`'s conversation from `chat`, then persists whatever
    happened. Returns the board's fresh JSON. Callers still need to invoke
    `delegation.on_task_resolved` themselves once this reaches a terminal
    status (not done here, to avoid a circular import — `delegation.py`
    itself is one of this module's callers)."""
    board = await boards_collection.find_one({"_id": board_id})
    chat = next(c for c in board.get("chats", []) if c["id"] == chat_id)
    task = next(t for t in board.get("tasks", []) if t["id"] == task_id)
    run_id = task.get("currentRunId")
    before_msg_count = len(chat["messages"])

    try:
        new_status = await agent_service.run_task_step(board_id, board, task, chat, fallback_status=fallback_status)
    except BudgetExceededError as exc:
        await chats_service.append_messages(board_id, chat_id, chat["messages"][before_msg_count:])
        await task_state.transition_task_status(
            board_id, task_id, prior_statuses, "stopped", currentRunId=None, statusReason=exc.reason,
        )
        if run_id:
            await finish_task_run(run_id, "stopped", None)
        await events.publish(board_id, {"taskId": task_id, "status": "stopped", "statusReason": exc.reason})
        await halt_board(board_id, "stopped", exc.reason)
        return board_to_json(await boards_collection.find_one({"_id": board_id}))

    new_messages = chat["messages"][before_msg_count:]
    await chats_service.append_messages(board_id, chat_id, new_messages)
    await task_state.transition_task_status(
        board_id, task_id, prior_statuses, new_status,
        currentRunId=(run_id if new_status in SUSPEND_STATUSES else None),
    )
    if new_status not in SUSPEND_STATUSES and run_id:
        await finish_task_run(run_id, new_status, None)
    await events.publish(board_id, {"taskId": task_id, "status": new_status})

    for m in new_messages:
        await audit_service.write_audit(
            agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
            entity_type="chat_message", action="create", actor_type="agent", actor_id=None,
            before=None, after=m,
        )

    await completion.try_complete_board(board_id)
    return board_to_json(await boards_collection.find_one({"_id": board_id}))
