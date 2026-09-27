"""Approve/reject resolution for a pending action-request chat message.

A rejection, or an approval whose rate limit and resource lock are both
immediately available, resolves inline and the HTTP endpoint returns the
final board state. When enforcement can't proceed right away, the task is
parked in `queued` (same status a rate-limit wait uses elsewhere) and the
actual execution continues in the background via `resolve_deferred` —
mirroring how `AgentRunner` runs a board's automatic steps outside the
request/response cycle.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from .. import task_state
from ..database import boards_collection
from ..models import board_to_json
from ..models_tools import ConnectedTokens
from ..services import audit_service, chats_service, lock_service, rate_limit_service, tool_connections_service
from . import agent_service, completion, tools
from .context import finish_task_run
from .enforcement import BudgetExceededError, halt_board, wait_for_lock, wait_for_rate_limit
from .events import events


@dataclass
class Outcome:
    board: dict
    deferred: bool


async def _get_board(board_id: str) -> dict:
    return await boards_collection.find_one({"_id": board_id})


def _locate(board: dict, chat_id: str, message_id: str) -> Tuple[dict, dict, dict]:
    chat = next(c for c in board.get("chats", []) if c["id"] == chat_id)
    message = next(m for m in chat["messages"] if m.get("id") == message_id)
    task = next(t for t in board.get("tasks", []) if t["id"] == message["payload"]["taskId"])
    return chat, message, task


async def _try_enforce_once(board_id: str, task_id: str, agent_id: Optional[str], spec, params: dict, run_id: str) -> bool:
    if spec is None or spec.tool_type is None:
        return True
    if not await rate_limit_service.try_consume(agent_id, spec.tool_type):
        return False
    if spec.resource_key and not await lock_service.try_acquire(spec.resource_key(params), run_id):
        return False
    return True


async def _execute_and_resume(board_id: str, chat_id: str, message_id: str, actor_id: str) -> dict:
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    payload = message["payload"]
    spec = tools.TOOLS.get(payload["tool"])
    params = payload.get("params", {})
    task_id = task["id"]
    run_id = task.get("currentRunId") or task_id
    agent_id = board.get("agentId")

    tokens: Optional[ConnectedTokens] = None
    if spec is not None and spec.tool_type is not None:
        tokens = await tool_connections_service.get_valid_tokens(agent_id, spec.tool_type)
    try:
        payload["status"] = "approved"
        payload["result"] = await tools.execute_tool(spec, params, tokens) if spec else "Action completed."
    finally:
        if spec is not None and spec.tool_type is not None and spec.resource_key:
            await lock_service.release(spec.resource_key(params), run_id)

    # `_resume_conversation` re-fetches the board fresh (it may run long
    # after this point) — persist the approval decision now, or it's lost
    # and the model never learns the action actually ran.
    await chats_service.save_chats(board_id, board["chats"], board.get("activeChatId"))

    return await _resume_conversation(board_id, chat_id, message_id, "done", actor_id)


async def _resume_conversation(
    board_id: str, chat_id: str, message_id: str, fallback_status: str, actor_id: str
) -> dict:
    board = await _get_board(board_id)
    chat, message, task = _locate(board, chat_id, message_id)
    task_id = task["id"]
    run_id = task.get("currentRunId")
    before_msg_count = len(chat["messages"])

    # Reachable with the task in `awaiting_approval` (fast path: never left
    # that state), `queued` (deferred path whose first bare enforcement
    # attempt already succeeded, so `_wait_parked` never ran to unpark it),
    # or `running` (deferred path that did go through `_wait_parked`, which
    # moves it queued -> running before handing back here).
    prior_statuses = ["awaiting_approval", "queued", "running"]

    try:
        new_status = await agent_service.run_task_step(board_id, board, task, chat, fallback_status=fallback_status)
    except BudgetExceededError as exc:
        await chats_service.save_chats(board_id, board["chats"], board.get("activeChatId"))
        await task_state.transition_task_status(
            board_id, task_id, prior_statuses, "stopped", currentRunId=None, statusReason=exc.reason,
        )
        if run_id:
            await finish_task_run(run_id, "stopped", None)
        await events.publish(board_id, {"taskId": task_id, "status": "stopped", "statusReason": exc.reason})
        await halt_board(board_id, "stopped", exc.reason)
        return board_to_json(await _get_board(board_id))

    await chats_service.save_chats(board_id, board["chats"], board.get("activeChatId"))
    await task_state.transition_task_status(
        board_id, task_id, prior_statuses, new_status,
        currentRunId=(run_id if new_status == "awaiting_approval" else None),
    )
    if new_status != "awaiting_approval" and run_id:
        await finish_task_run(run_id, new_status, None)
    await events.publish(board_id, {"taskId": task_id, "status": new_status})

    for m in chat["messages"][before_msg_count:]:
        await audit_service.write_audit(
            agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
            entity_type="chat_message", action="create", actor_type="agent", actor_id=None,
            before=None, after=m,
        )
    await audit_service.write_audit(
        agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
        entity_type="chat_message", action="update", actor_type="human", actor_id=actor_id,
        before={"id": message_id, "status": "pending"},
        after={"id": message_id, "status": message["payload"]["status"]},
    )

    await completion.try_complete_board(board_id)
    return board_to_json(await _get_board(board_id))


async def resolve(board_id: str, chat_id: str, message_id: str, approved: bool, actor_id: str) -> Outcome:
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    payload = message["payload"]
    if payload.get("status") != "pending":
        raise ValueError("Action already resolved")
    if task.get("status") != "awaiting_approval":
        raise ValueError("Task is not awaiting approval")

    if not approved:
        payload["status"] = "rejected"
        board_json = await _resume_conversation(board_id, chat_id, message_id, "blocked", actor_id)
        return Outcome(board=board_json, deferred=False)

    spec = tools.TOOLS.get(payload["tool"])
    params = payload.get("params", {})
    task_id = task["id"]
    run_id = task.get("currentRunId") or task_id
    ready = await _try_enforce_once(board_id, task_id, board.get("agentId"), spec, params, run_id)
    if not ready:
        await task_state.transition_task_status(board_id, task_id, ["awaiting_approval"], "queued")
        await events.publish(board_id, {"taskId": task_id, "status": "queued"})
        return Outcome(board=board_to_json(await _get_board(board_id)), deferred=True)

    board_json = await _execute_and_resume(board_id, chat_id, message_id, actor_id)
    return Outcome(board=board_json, deferred=False)


async def resolve_deferred(board_id: str, chat_id: str, message_id: str, actor_id: str) -> None:
    """Background continuation for an approval that couldn't proceed
    immediately: waits on the same enforcement helpers the automatic loop
    uses (parking as `queued`, polling, honoring Stop), then executes."""
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    payload = message["payload"]
    spec = tools.TOOLS.get(payload["tool"])
    params = payload.get("params", {})
    task_id = task["id"]
    run_id = task.get("currentRunId")
    agent_id = board.get("agentId")

    if spec is not None and spec.tool_type is not None:
        if not await wait_for_rate_limit(agent_id, board_id, task_id, spec.tool_type):
            await _finalize_abandoned(board_id, run_id)
            return
        if spec.resource_key and not await wait_for_lock(board_id, task_id, spec.resource_key(params), run_id or task_id):
            await _finalize_abandoned(board_id, run_id)
            return

    await _execute_and_resume(board_id, chat_id, message_id, actor_id)


async def _finalize_abandoned(board_id: str, run_id: Optional[str]) -> None:
    """`wait_for_rate_limit`/`wait_for_lock` already moved the task itself to
    `stopped` (see `enforcement._wait_parked`) — this just closes out the
    run record and re-checks board completion."""
    if run_id:
        await finish_task_run(run_id, "stopped", "stopped while waiting for a rate limit or resource lock")
    await completion.try_complete_board(board_id)
