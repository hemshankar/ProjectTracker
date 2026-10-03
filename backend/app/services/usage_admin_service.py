"""Admin-only usage: workspace totals, breakdown, history, ledger rows, export, health."""
import asyncio
from typing import AsyncIterator, Dict, List, Optional, Tuple

from fastapi import HTTPException

from .. import config
from ..accounting.outbox import OutboxRepository
from ..accounting.pending import PendingUsage
from ..accounting.query_client import UsageQueryClient
from ..database import boards_collection
from ..models_usage import AdminBreakdownRow, AdminRowsPage, AdminSeriesPoint, AdminTotals, UsageHealth

MAX_CONCURRENT_EXPORTS = 2


class UsageAdminService:
    def __init__(self, client: UsageQueryClient, pending: Optional[PendingUsage] = None,
                 outbox: Optional[OutboxRepository] = None):
        self._client = client
        self._pending = pending or PendingUsage()
        self._outbox = outbox or OutboxRepository()
        self._exports: Dict[str, int] = {}

    async def summary(self, agent_id: str, filters: dict) -> AdminTotals:
        raw = await self._client.get("/summary", {"agentId": agent_id, **filters})
        return AdminTotals(**raw, pendingUsd=await self._pending.for_agent(agent_id))

    async def timeseries(self, agent_id: str, params: dict) -> List[AdminSeriesPoint]:
        return [AdminSeriesPoint(**p) for p in await self._client.get("/timeseries", {"agentId": agent_id, **params})]

    async def breakdown(self, agent_id: str, params: dict) -> List[AdminBreakdownRow]:
        rows = [AdminBreakdownRow(**r) for r in await self._client.get("/breakdown", {"agentId": agent_id, **params})]
        gone = await self._missing(params.get("groupBy"), [r.key for r in rows if r.key])
        for r in rows:
            r.deleted = r.key in gone
        return rows

    async def rows(self, agent_id: str, params: dict) -> AdminRowsPage:
        page = await self._client.get("/rows", {"agentId": agent_id, **params})
        boards = await self._missing("board", [r["boardId"] for r in page["rows"] if r.get("boardId")])
        tasks = await self._missing("task", [r["taskId"] for r in page["rows"] if r.get("taskId")])
        for r in page["rows"]:
            r["boardDeleted"] = r.get("boardId") in boards
            r["taskDeleted"] = r.get("taskId") in tasks
        return AdminRowsPage(**page)

    async def health(self, agent_id: str) -> UsageHealth:
        return UsageHealth(serviceReachable=await self._client.ping(), outbox=await self._outbox.stats(),
                           delayThresholdSeconds=config.ALERT_OUTBOX_AGE_SECONDS)

    async def export(self, agent_id: str, params: dict) -> Tuple[Dict[str, str], AsyncIterator[bytes]]:
        if self._exports.get(agent_id, 0) >= MAX_CONCURRENT_EXPORTS:
            raise HTTPException(status_code=429, detail="Too many exports running for this workspace")
        self._exports[agent_id] = self._exports.get(agent_id, 0) + 1
        try:
            headers, body = await self._client.stream("/export", {"agentId": agent_id, **params})
        except BaseException:
            self._release(agent_id)
            raise

        async def guarded() -> AsyncIterator[bytes]:
            try:
                async for chunk in body:
                    yield chunk
            finally:
                self._release(agent_id)

        return headers, guarded()

    def _release(self, agent_id: str) -> None:
        self._exports[agent_id] = max(0, self._exports.get(agent_id, 1) - 1)

    async def _missing(self, dimension: Optional[str], ids: List[str]) -> set:
        """Ids of boards/tasks that no longer exist (so the UI can mark them 'deleted')."""
        ids = list(set(ids))
        if dimension == "board" and ids:
            found = {b["_id"] async for b in boards_collection.find({"_id": {"$in": ids}}, {"_id": 1})}
        elif dimension == "task" and ids:
            found = {t["id"] async for b in boards_collection.find({"tasks.id": {"$in": ids}}, {"tasks.id": 1})
                     for t in b.get("tasks", [])}
        else:
            return set()
        return set(ids) - found
