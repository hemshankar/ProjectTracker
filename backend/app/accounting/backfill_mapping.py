"""Pure mapping from a legacy `llm_calls` row to a usage event (no I/O)."""
from typing import Optional

from .. import config

UNKNOWN_MODEL = "unknown"


def flat_rates() -> dict:
    """The flat per-MTok rates old rows were actually charged at."""
    return {
        "input": config.ANTHROPIC_INPUT_COST_PER_MTOK,
        "output": config.ANTHROPIC_OUTPUT_COST_PER_MTOK,
        "cacheRead": 0.0,
        "cacheWrite": 0.0,
        "webSearch": 0.0,
    }


def map_llm_call(row: dict, names: Optional[dict] = None) -> dict:
    """`usd` is copied verbatim: it is the number caps were enforced against."""
    names = names or {}
    has_snapshot = bool(row.get("model")) and bool(row.get("rates"))
    return {
        "callId": row["_id"],
        "ts": row.get("ts") or 0,
        "agentId": row.get("agentId") or "unknown",
        "boardId": row.get("boardId"),
        "taskId": row.get("taskId"),
        "runId": row.get("runId"),
        "parentRunId": row.get("parentRunId"),
        "callKind": row.get("callKind") or ("subagent" if row.get("parentRunId") else "task_run"),
        "userId": row.get("userId"),
        "agentName": names.get("agentName"),
        "boardTitle": names.get("boardTitle"),
        "taskTitle": names.get("taskTitle"),
        "model": row.get("model") or UNKNOWN_MODEL,
        "inputTokens": row.get("inputTokens") or 0,
        "outputTokens": row.get("outputTokens") or 0,
        "cacheReadTokens": row.get("cacheReadTokens") or 0,
        "cacheCreationTokens": row.get("cacheCreationTokens") or 0,
        "webSearchCount": row.get("webSearchCount") or 0,
        "rates": row.get("rates") or flat_rates(),
        "usd": row.get("usd") or 0.0,
        "pricedByFallback": bool(row.get("pricedByFallback", False)),
        "latencyMs": row.get("latencyMs"),
        "outcome": row.get("outcome") or "success",
        "anthropicRequestId": row.get("anthropicRequestId"),
        "source": "backfill",
        "estimated": not has_snapshot,
        "llmCallRef": row["_id"],
    }
