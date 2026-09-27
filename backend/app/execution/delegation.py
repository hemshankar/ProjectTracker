"""Peer-Agent delegation (Phase 6): `delegate_to_agent` lets the owning
Agent hand a piece of a task to a different top-level Agent it has an
explicit `agent_links` grant for. The delegated task runs under the target
Agent's own scatterboard, tools and budget; its result comes back to the
requesting task as a reply once resolved (`on_task_resolved`), which the
board runner and the approval flow both call whenever a task reaches a
terminal status.
"""
from typing import Optional, Tuple

from ..database import boards_collection
from ..models import new_id, now_ms
from ..services import agent_links_service, audit_service, chats_service
from .events import events
from .resume import TERMINAL_STATUSES, resume_task

INBOUND_BOARD_TITLE = "Inbound Delegations"


class DelegationRefused(Exception):
    pass


async def _get_or_create_inbound_board(target_agent_id: str) -> dict:
    board = await boards_collection.find_one({"agentId": target_agent_id, "inboundDelegation": True})
    if board:
        return board
    doc = {
        "_id": new_id(),
        "agentId": target_agent_id,
        "ownerId": None,
        "title": INBOUND_BOARD_TITLE,
        "description": "Tasks delegated here by other Agents this one has a granted link to.",
        "color": "slate",
        "completed": False,
        "x": 0, "y": 0, "w": 320, "h": 280, "z": 0,
        "tasks": [],
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
        "statusReason": None,
        "budgetCapUsd": None,
        "inboundDelegation": True,
        "createdAt": now_ms(),
        "updatedAt": now_ms(),
    }
    await boards_collection.insert_one(doc)
    return doc


async def request_delegation(
    from_agent_id: Optional[str],
    from_agent_name: str,
    to_agent_id: str,
    from_board_id: str,
    from_task_id: str,
    from_run_id: Optional[str],
    request_text: str,
) -> dict:
    """Creates the delegated task on the target Agent's inbound board.
    Raises `DelegationRefused` if there's no granted `agent_links` entry —
    never silently, per the PRD's "clear refusal, not a silent failure"."""
    if not from_agent_id or to_agent_id == from_agent_id:
        raise DelegationRefused("An Agent cannot delegate to itself.")
    if not await agent_links_service.has_link(from_agent_id, to_agent_id):
        raise DelegationRefused(
            f"No delegation link is granted from this Agent to '{to_agent_id}'. "
            "An Agent Admin must grant one first, in Settings."
        )

    board = await _get_or_create_inbound_board(to_agent_id)
    task = {
        "id": new_id(),
        "text": f"[Delegated by {from_agent_name}] {request_text}",
        "status": "idle",
        "statusReason": None,
        "currentRunId": None,
        "delegatedFromAgentId": from_agent_id,
        "delegatedFromBoardId": from_board_id,
        "delegatedFromTaskId": from_task_id,
        "delegatedFromRunId": from_run_id,
    }
    tasks = board.get("tasks", []) + [task]
    await boards_collection.update_one({"_id": board["_id"]}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}})
    await audit_service.write_audit(
        agent_id=to_agent_id, board_id=board["_id"], task_id=task["id"],
        entity_type="task", action="create", actor_type="agent", actor_id=None,
        before=None, after=task,
    )
    await events.publish(board["_id"], {"taskId": task["id"], "status": "idle"})
    return {"targetBoardId": board["_id"], "targetTaskId": task["id"]}


def _delegation_origin(task: dict) -> Optional[Tuple[Optional[str], str, str, Optional[str]]]:
    if not task.get("delegatedFromTaskId"):
        return None
    return (
        task.get("delegatedFromAgentId"),
        task["delegatedFromBoardId"],
        task["delegatedFromTaskId"],
        task.get("delegatedFromRunId"),
    )


def extract_result_text(board: dict, task: dict, status: str, error: Optional[str] = None) -> str:
    """A short summary of a delegated task's outcome, for the reply that
    goes back to the Agent that requested it."""
    if status == "failed":
        return f"Failed: {error or 'unknown error'}"
    if status == "blocked":
        return "Blocked — a proposed action was rejected."
    if status == "stopped":
        return f"Stopped ({task.get('statusReason') or 'user'})."
    chat = next((c for c in board.get("chats", []) if c.get("taskId") == task["id"]), None)
    if chat:
        for m in reversed(chat["messages"]):
            if m.get("role") == "assistant" and m.get("type") not in ("action_request", "clarification_request"):
                return m.get("text") or "Done."
    return "Done."


async def on_task_resolved(task: dict, result_text: str) -> None:
    """Hooked in wherever a task reaches a terminal status — if `task` was
    created by `request_delegation`, delivers its result back to the
    originating task and resumes that task's conversation from
    `awaiting_reply`. A no-op for any ordinary, non-delegated task."""
    origin = _delegation_origin(task)
    if origin is None:
        return
    _from_agent_id, from_board_id, from_task_id, _from_run_id = origin

    from_board = await boards_collection.find_one({"_id": from_board_id})
    if from_board is None:
        return
    from_task = next((t for t in from_board.get("tasks", []) if t["id"] == from_task_id), None)
    if from_task is None or from_task.get("status") != "awaiting_reply":
        return

    chat = await chats_service.get_or_create_task_chat(from_board, from_task)
    pending = next(
        (m for m in chat["messages"] if m.get("type") == "delegation_request"
         and m.get("payload", {}).get("taskId") == from_task_id
         and m["payload"].get("status") == "pending"),
        None,
    )
    if pending is not None:
        await chats_service.update_message_payload(
            from_board_id, chat["id"], pending["id"], {"status": "resolved", "result": result_text}
        )

    reply = chats_service.text_message("user", f"[Delegated task result — {task.get('status')}] {result_text}")
    reply["taskId"] = from_task_id
    await chats_service.append_messages(from_board_id, chat["id"], [reply])

    await resume_task(from_board_id, chat["id"], from_task_id, "done", ["awaiting_reply"])

    after_board = await boards_collection.find_one({"_id": from_board_id})
    after_task = next(t for t in after_board.get("tasks", []) if t["id"] == from_task_id)
    if after_task.get("status") in TERMINAL_STATUSES:
        await on_task_resolved(after_task, extract_result_text(after_board, after_task, after_task["status"]))
