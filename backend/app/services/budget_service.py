"""Board/Agent/global spend enforcement, all tracked in one normalized unit
(USD) inside `llm_calls` — the same log Phase 8 extends with full call
detail. Checked cheapest/most-specific first, short-circuiting.
"""
from typing import Optional

from .. import config
from ..database import agent_settings_collection, boards_collection, global_settings_collection, llm_calls_collection
from ..models import new_id, now_ms


def usd_for_usage(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * config.ANTHROPIC_INPUT_COST_PER_MTOK
        + output_tokens / 1_000_000 * config.ANTHROPIC_OUTPUT_COST_PER_MTOK
    )


async def _sum_usd(match: dict) -> float:
    total = 0.0
    async for doc in llm_calls_collection.find(match, {"usd": 1}):
        total += doc.get("usd", 0.0)
    return total


async def record_spend(agent_id: Optional[str], board_id: str, task_id: str, run_id: str, usd: float) -> None:
    if usd <= 0:
        return
    await llm_calls_collection.insert_one({
        "_id": new_id(),
        "agentId": agent_id,
        "boardId": board_id,
        "taskId": task_id,
        "runId": run_id,
        "usd": usd,
        "ts": now_ms(),
    })


async def check_exceeded(agent_id: Optional[str], board_id: str) -> Optional[str]:
    """Returns "budget_exceeded" if any cap (board, then Agent, then global)
    is already at or over its limit, else None. Cheapest check first."""
    board = await boards_collection.find_one({"_id": board_id}, {"budgetCapUsd": 1})
    board_cap = (board or {}).get("budgetCapUsd")
    if board_cap is not None and await _sum_usd({"boardId": board_id}) >= board_cap:
        return "budget_exceeded"

    if agent_id is not None:
        agent_settings = await agent_settings_collection.find_one({"_id": agent_id}, {"budget": 1})
        agent_cap = (agent_settings or {}).get("budget", {}).get("capUsd")
        if agent_cap is not None and await _sum_usd({"agentId": agent_id}) >= agent_cap:
            return "budget_exceeded"

    global_doc = await global_settings_collection.find_one({"_id": "global"}, {"budgetCapUsd": 1})
    global_cap = (global_doc or {}).get("budgetCapUsd", config.GLOBAL_BUDGET_CAP_USD)
    if global_cap is not None and await _sum_usd({}) >= global_cap:
        return "budget_exceeded"

    return None
