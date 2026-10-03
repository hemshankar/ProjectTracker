"""Records the full-detail row Phase 8 keeps in `llm_calls` for every model
call the task loop and sub-agent loop make, and pushes a lightweight
summary onto the board's SSE channel so an open Traces tab can live-tail a
still-`running` board. One insert covers both Phase 5's spend accounting
(`usd`) and Phase 8's drillable detail (system prompt, request messages,
response, the one tool call this turn made, if any).
"""
from typing import Any, Optional

from ..accounting.recorder import get_recorder
from .events import events


def _summary(doc: dict) -> dict:
    tool_calls = doc.get("toolCalls") or []
    tool_call = tool_calls[0] if tool_calls else None
    return {
        "id": doc["_id"],
        "boardId": doc.get("boardId"),
        "taskId": doc.get("taskId"),
        "runId": doc.get("runId"),
        "parentRunId": doc.get("parentRunId"),
        "tool": tool_call.get("name") if tool_call else None,
        "status": tool_call.get("status") if tool_call else "done",
        "usd": doc.get("usd", 0.0),
        "model": doc.get("model"),
        "inputTokens": doc.get("inputTokens", 0),
        "outputTokens": doc.get("outputTokens", 0),
        "latencyMs": doc.get("latencyMs"),
        "ts": doc.get("ts"),
    }


async def record_call(
    *,
    agent_id: Optional[str],
    board_id: str,
    task_id: Optional[str],
    run_id: Optional[str],
    response: Any,
    system_prompt: str,
    request_messages: list,
    tool_call: Optional[dict],
    latency_ms: float,
    parent_run_id: Optional[str] = None,
) -> None:
    response_text = "\n".join(b.text for b in response.content if b.type == "text")
    doc = await get_recorder().record(
        agent_id=agent_id, board_id=board_id, task_id=task_id, run_id=run_id, response=response,
        system_prompt=system_prompt, request_messages=list(request_messages), tool_call=tool_call,
        latency_ms=latency_ms, response_text=response_text, parent_run_id=parent_run_id,
    )
    await events.publish(board_id, {"boardId": board_id, "llmCall": _summary(doc)})
