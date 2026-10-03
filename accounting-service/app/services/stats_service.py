"""Operational read-outs: ledger stats, exact ledger totals for reconcile, readiness."""
import time
from typing import Callable, List, Optional

from ..repositories.ledger_repository import LedgerRepository
from ..repositories.rollup_repository import RollupRepository
from .rollup_keys import DAY_MS

_HOUR_MS = 3_600_000
SCOPE_FIELDS = {"global": None, "agent": "agentId", "board": "boardId"}


class StatsService:
    def __init__(self, ledger: LedgerRepository, rollups: RollupRepository, rejected_total: Callable[[], int],
                 verify_result: Callable[[], Optional[dict]] = lambda: None,
                 clock: Callable[[], float] = time.time):
        self._ledger, self._rollups, self._rejected, self._clock = ledger, rollups, rejected_total, clock
        self._verify = verify_result

    async def stats(self) -> dict:
        now = int(self._clock() * 1000)
        led = await self._ledger.stats({})
        recent = await self._ledger.count({"ingestedAt": {"$gte": now - _HOUR_MS}})
        newest = await self._rollups.aggregate([{"$group": {"_id": None, "max": {"$max": "$dayTs"}}}])
        rollup_day = newest[0]["max"] if newest else None
        lag_days = None
        if led["maxTs"] is not None:
            ledger_day = led["maxTs"] - led["maxTs"] % DAY_MS
            lag_days = max(0, (ledger_day - rollup_day) // DAY_MS) if rollup_day is not None else None
        return {"ledgerCount": led["count"], "latestTs": led["maxTs"], "ingestedLastHour": recent,
                "rejectedSinceStart": self._rejected(), "rollupLagDays": lag_days,
                "rollupVerify": self._verify()}

    async def ledger_total(self, scope: str, scope_id: Optional[str], since_ms: Optional[int]) -> dict:
        """Exact (millisecond) ledger sum for a counter scope, from `since_ms` on. Used by core reconcile."""
        query: dict = {}
        field = SCOPE_FIELDS[scope]
        if field:
            query[field] = scope_id
        if since_ms is not None:
            query["ts"] = {"$gte": since_ms}
        led = await self._ledger.stats(query)
        return {"usd": round(led["usd"], 6), "calls": led["count"]}

    async def missing(self, ids: List[str]) -> List[str]:
        return await self._ledger.missing_ids(ids)
