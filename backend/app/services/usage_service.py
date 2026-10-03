"""Member-visible usage: totals only (task, board, batches). Service total + undelivered outbox delta;
falls back to local counters when the accounting service is unreachable."""
from typing import Dict, List, Optional

from ..accounting.counters import SpendCounters, board_scope
from ..accounting.pending import PendingUsage
from ..accounting.query_client import AccountingUnavailable, UsageQueryClient
from ..accounting.ttl_cache import TtlCache
from ..database import agent_settings_collection
from ..models_settings import usage_display_json
from ..models_usage import BoardUsage, TaskUsage, UsageBatch
from . import agents_service

MAX_BATCH_IDS = 500


class UsageService:
    def __init__(self, client: UsageQueryClient, pending: Optional[PendingUsage] = None,
                 counters: Optional[SpendCounters] = None, cache: Optional[TtlCache] = None):
        self._client = client
        self._pending = pending or PendingUsage()
        self._counters = counters or SpendCounters()
        self._cache = cache or TtlCache(5.0)

    async def board_usage(self, board: dict) -> BoardUsage:
        if not await self._display_flag(board["agentId"], "showBoardCosts"):
            return BoardUsage(usd=None, enabled=False)
        try:
            totals = await self._client.get("/summary", {"agentId": board["agentId"], "boardId": board["_id"]})
        except AccountingUnavailable:
            return BoardUsage(usd=await self._counters.get(board_scope(board["_id"])), stale=True)
        delta = (await self._pending.by_scope("boardId", [board["_id"]])).get(board["_id"], 0.0)
        return BoardUsage(usd=totals["usd"] + delta, calls=totals["calls"])

    async def task_usage(self, board: dict, task_id: str) -> TaskUsage:
        try:
            totals = await self._client.get("/summary", {"agentId": board["agentId"], "taskId": task_id})
        except AccountingUnavailable:
            return TaskUsage(usd=None, stale=True)  # no local per-task source
        delta = (await self._pending.by_scope("taskId", [task_id])).get(task_id, 0.0)
        return TaskUsage(usd=totals["usd"] + delta, calls=totals["calls"],
                         inputTokens=totals["inputTokens"], outputTokens=totals["outputTokens"])

    async def boards_batch(self, agent_id: str, user_id: str) -> UsageBatch:
        """Totals for the boards this caller can see; never any other board."""
        if not await self._display_flag(agent_id, "showBoardCosts"):
            return UsageBatch(totals={}, enabled=False)
        visible = [b["id"] for b in await agents_service.list_boards_for_agent(agent_id, user_id)]
        ids = visible[:MAX_BATCH_IDS]
        key = ("boards", agent_id, tuple(sorted(ids)))
        if (hit := self._cache.get(key)) is not None:
            return hit
        result = await self._batch(agent_id, "boardIds", "boardId", ids)
        if not result.stale:
            self._cache.put(key, result)
        elif ids:
            result = UsageBatch(totals={i: await self._counters.get(board_scope(i)) for i in ids}, stale=True)
        return result

    async def tasks_batch(self, board: dict) -> UsageBatch:
        """Per-task totals for card pills; empty unless the workspace admin enabled the display."""
        if not await self._display_flag(board["agentId"], "showTaskCosts"):
            return UsageBatch(totals={}, enabled=False)
        ids = [t["id"] for t in board.get("tasks", [])][:MAX_BATCH_IDS]
        key = ("tasks", board["agentId"], board["_id"], tuple(sorted(ids)))
        if (hit := self._cache.get(key)) is not None:
            return hit
        result = await self._batch(board["agentId"], "taskIds", "taskId", ids)
        if not result.stale:
            self._cache.put(key, result)
        return result

    async def _display_flag(self, agent_id: str, flag: str) -> bool:
        doc = await agent_settings_collection.find_one({"_id": agent_id}, {"usageDisplay": 1})
        return usage_display_json(doc or {})[flag]

    async def _batch(self, agent_id: str, param: str, field: str, ids: List[str]) -> UsageBatch:
        if not ids:
            return UsageBatch(totals={})
        try:
            raw: Dict[str, dict] = await self._client.get("/summary/batch", {"agentId": agent_id, param: ",".join(ids)})
        except AccountingUnavailable:
            return UsageBatch(totals={i: None for i in ids}, stale=True)
        pending = await self._pending.by_scope(field, ids)
        return UsageBatch(totals={i: raw.get(i, {}).get("usd", 0.0) + pending.get(i, 0.0) for i in ids})
