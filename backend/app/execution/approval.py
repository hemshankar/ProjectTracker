"""Approve/reject resolution for a pending action-request chat message.

A rejection, or an approval whose rate limit and resource lock are both
immediately available, resolves inline and the HTTP endpoint returns the
final board state. When enforcement can't proceed right away, the task is
parked in `queued` (same status a rate-limit wait uses elsewhere) and the
actual execution continues in the background via `resolve_deferred` —
mirroring how `AgentRunner` runs a board's automatic steps outside the
request/response cycle.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple

from .. import task_state
from ..database import boards_collection
from ..models import board_to_json
from ..models_tools import ConnectedTokens
from ..services import audit_service, chats_service, lock_service, rate_limit_service, tool_connections_service
from . import completion, delegation, stopping, tools
from .context import finish_task_run
from .enforcement import wait_for_lock, wait_for_rate_limit
from .events import events
from .resume import TERMINAL_STATUSES, resume_task


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
        result = await tools.execute_tool(spec, params, tokens) if spec else "Action completed."
    finally:
        if spec is not None and spec.tool_type is not None and spec.resource_key:
            await lock_service.release(spec.resource_key(params), run_id)

    # `_resume_conversation` re-fetches the board fresh (it may run long
    # after this point) — persist the approval decision atomically now, or
    # it's lost and the model never learns the action actually ran. This
    # also has to land before that re-fetch for a *different* reason: two
    # tasks in the same board can resolve concurrently since Phase 6 (see
    # `execution.loop`), so a whole-chats-array overwrite here could lose a
    # sibling task's own concurrent update.
    await chats_service.update_message_payload(board_id, chat_id, message_id, {"status": "approved", "result": result})

    return await _resume_conversation(board_id, chat_id, message_id, "done", actor_id)


async def _resume_conversation(
    board_id: str, chat_id: str, message_id: str, fallback_status: str, actor_id: str
) -> dict:
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    task_id = task["id"]

    # Reachable with the task in `awaiting_approval` (fast path: never left
    # that state), `queued` (deferred path whose first bare enforcement
    # attempt already succeeded, so `_wait_parked` never ran to unpark it),
    # or `running` (deferred path that did go through `_wait_parked`, which
    # moves it queued -> running before handing back here).
    prior_statuses = ["awaiting_approval", "queued", "running"]

    board_json = await resume_task(board_id, chat_id, task_id, fallback_status, prior_statuses)

    await audit_service.write_audit(
        agent_id=board.get("agentId"), board_id=board_id, task_id=task_id,
        entity_type="chat_message", action="update", actor_type="human", actor_id=actor_id,
        before={"id": message_id, "status": "pending"},
        after={"id": message_id, "status": message["payload"]["status"]},
    )

    after_board = await _get_board(board_id)
    after_task = next(t for t in after_board.get("tasks", []) if t["id"] == task_id)
    if after_task.get("status") in TERMINAL_STATUSES:
        await delegation.on_task_resolved(
            after_task, delegation.extract_result_text(after_board, after_task, after_task["status"])
        )
    return board_json


async def resolve(board_id: str, chat_id: str, message_id: str, approved: bool, actor_id: str) -> Outcome:
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    payload = message["payload"]
    if payload.get("status") != "pending":
        raise ValueError("Action already resolved")
    if task.get("status") != "awaiting_approval":
        raise ValueError("Task is not awaiting approval")

    if not approved:
        await chats_service.update_message_payload(board_id, chat_id, message_id, {"status": "rejected"})
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
    uses (parking as `queued`, polling, honoring Stop), then executes.

    Registered in `stopping.task_registry` the same way `AgentRunner._run_task`
    is — this is the one other place a task's progress continues outside a
    live HTTP request, so a Stop needs to be able to cancel it too.
    """
    board = await _get_board(board_id)
    _, message, task = _locate(board, chat_id, message_id)
    payload = message["payload"]
    spec = tools.TOOLS.get(payload["tool"])
    params = payload.get("params", {})
    task_id = task["id"]
    run_id = task.get("currentRunId")
    agent_id = board.get("agentId")
    lock_key = spec.resource_key(params) if spec is not None and spec.tool_type is not None and spec.resource_key else None
    lock_held = False

    current = asyncio.current_task()
    if current is not None:
        stopping.task_registry.register(task_id, current)
    try:
        if spec is not None and spec.tool_type is not None:
            if not await wait_for_rate_limit(agent_id, board_id, task_id, spec.tool_type):
                await _finalize_abandoned(board_id, task, run_id)
                return
            if lock_key is not None:
                if not await wait_for_lock(board_id, task_id, lock_key, run_id or task_id):
                    await _finalize_abandoned(board_id, task, run_id)
                    return
                lock_held = True

        await _execute_and_resume(board_id, chat_id, message_id, actor_id)
    except asyncio.CancelledError:
        if lock_held and lock_key is not None:
            # Narrow window: the lock was acquired but `_execute_and_resume`
            # (whose own `finally` normally releases it) never got to start.
            # A harmless no-op if it actually did get that far first.
            await lock_service.release(lock_key, run_id or task_id)
        await stopping.mark_stopped(board_id, task_id, run_id, agent_id)
    finally:
        if current is not None:
            stopping.task_registry.unregister(task_id, current)


async def _finalize_abandoned(board_id: str, task: dict, run_id: Optional[str]) -> None:
    """`wait_for_rate_limit`/`wait_for_lock` already moved the task itself to
    `stopped` (see `enforcement._wait_parked`) — this just closes out the
    run record and re-checks board completion."""
    if run_id:
        await finish_task_run(run_id, "stopped", "stopped while waiting for a rate limit or resource lock")
    await completion.try_complete_board(board_id)
    await delegation.on_task_resolved(
        {**task, "status": "stopped"},
        "Stopped while waiting for a rate limit or resource lock to free up.",
    )
