"""Read-only query layer over `audit_log` and `llm_calls` for the Agent
Admin Console's Activity/Traces tabs (Phase 8), plus the lighter
board-scoped Activity view any board viewer/editor gets. Never writes
either collection — `audit_service.write_audit` and
`budget_service.record_llm_call` own that.
"""
from typing import Optional

from ..database import audit_log_collection, llm_calls_collection

_LIST_LIMIT = 200


def _time_range(since: Optional[int], until: Optional[int]) -> dict:
    rng: dict = {}
    if since is not None:
        rng["$gte"] = since
    if until is not None:
        rng["$lte"] = until
    return {"ts": rng} if rng else {}


def _audit_json(d: dict) -> dict:
    return {
        "id": d["_id"],
        "agentId": d.get("agentId"),
        "boardId": d.get("boardId"),
        "taskId": d.get("taskId"),
        "entityType": d.get("entityType"),
        "action": d.get("action"),
        "actorType": d.get("actorType"),
        "actorId": d.get("actorId"),
        "before": d.get("before"),
        "after": d.get("after"),
        "ts": d.get("ts"),
    }


async def list_audit(
    agent_id: str,
    *,
    board_id: Optional[str] = None,
    task_id: Optional[str] = None,
    actor_type: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
) -> list:
    match: dict = {"agentId": agent_id, **_time_range(since, until)}
    if board_id:
        match["boardId"] = board_id
    if task_id:
        match["taskId"] = task_id
    if actor_type:
        match["actorType"] = actor_type
    cursor = audit_log_collection.find(match).sort("ts", -1).limit(_LIST_LIMIT)
    return [_audit_json(d) async for d in cursor]


async def list_board_audit(board_id: str) -> list:
    """The lighter, board-scoped Activity view — the same query as
    `list_audit`, `boardId`-only, so any board viewer/editor can see just
    their board's slice without Agent-Admin access or cross-board reach.
    """
    cursor = audit_log_collection.find({"boardId": board_id}).sort("ts", -1).limit(_LIST_LIMIT)
    return [_audit_json(d) async for d in cursor]


def _call_summary_json(d: dict) -> dict:
    tool_calls = d.get("toolCalls") or []
    tool_call = tool_calls[0] if tool_calls else None
    return {
        "id": d["_id"],
        "boardId": d.get("boardId"),
        "taskId": d.get("taskId"),
        "runId": d.get("runId"),
        "parentRunId": d.get("parentRunId"),
        "tool": tool_call.get("name") if tool_call else None,
        "status": tool_call.get("status") if tool_call else "done",
        "usd": d.get("usd", 0.0),
        "model": d.get("model"),
        "callKind": d.get("callKind"),
        "outcome": d.get("outcome"),
        "latencyMs": d.get("latencyMs"),
        "ts": d.get("ts"),
    }


async def list_llm_calls(
    agent_id: str,
    *,
    board_id: Optional[str] = None,
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
    call_kind: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
) -> list:
    """Summaries only (no prompt/response bodies) — the Traces list view;
    `get_llm_call` fetches one row's full detail on demand.
    """
    match: dict = {"agentId": agent_id, **_time_range(since, until)}
    if board_id:
        match["boardId"] = board_id
    if task_id:
        match["taskId"] = task_id
    if run_id:
        match["runId"] = run_id
    if call_kind:
        match["callKind"] = call_kind
    cursor = llm_calls_collection.find(match).sort("ts", 1).limit(_LIST_LIMIT)
    return [_call_summary_json(d) async for d in cursor]


async def get_llm_call(agent_id: str, call_id: str) -> Optional[dict]:
    d = await llm_calls_collection.find_one({"_id": call_id, "agentId": agent_id})
    if not d:
        return None
    return {
        "id": d["_id"],
        "boardId": d.get("boardId"),
        "taskId": d.get("taskId"),
        "runId": d.get("runId"),
        "parentRunId": d.get("parentRunId"),
        "systemPrompt": d.get("systemPrompt"),
        "messages": d.get("messages"),
        "response": d.get("response"),
        "toolCalls": d.get("toolCalls") or [],
        "usd": d.get("usd", 0.0),
        "model": d.get("model"),
        "inputTokens": d.get("inputTokens"),
        "outputTokens": d.get("outputTokens"),
        "cacheReadTokens": d.get("cacheReadTokens"),
        "cacheCreationTokens": d.get("cacheCreationTokens"),
        "latencyMs": d.get("latencyMs"),
        "ts": d.get("ts"),
    }
