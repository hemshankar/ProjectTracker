import logging
from typing import List

from ..repositories.ledger_repository import LedgerRepository
from ..repositories.rollup_repository import RollupRepository
from .rollup_keys import DAY_MS, RollupAccumulator, day_string

log = logging.getLogger(__name__)
_REBUILD_CHUNK = 1000


class RollupService:
    def __init__(self, ledger: LedgerRepository, rollups: RollupRepository):
        self._ledger, self._rollups = ledger, rollups

    async def apply(self, inserted_ledger_docs: List[dict]) -> None:
        """Called only with rows newly inserted into the ledger, so redelivery cannot double-count."""
        await self._rollups.apply(RollupAccumulator().add_all(inserted_ledger_docs).docs())

    async def rebuild(self, from_ms: int, to_ms: int) -> int:
        """Recompute rollups for [from_ms, to_ms) from the ledger. Returns rollup docs written."""
        acc = RollupAccumulator()
        async for chunk in self._ledger.iter_chunks({"ts": {"$gte": from_ms, "$lt": to_ms}}, _REBUILD_CHUNK):
            acc.add_all(chunk)
        docs = acc.docs()
        await self._rollups.replace_range(_day_floor(from_ms), _day_ceil(to_ms), docs)
        return len(docs)

    async def verify(self, from_ms: int, to_ms: int) -> List[dict]:
        """Per-day ledger-vs-rollup comparison; returns only days that disagree."""
        expected = {}
        async for chunk in self._ledger.iter_chunks({"ts": {"$gte": from_ms, "$lt": to_ms}}, _REBUILD_CHUNK):
            for d in chunk:
                e = expected.setdefault(day_string(d["ts"]), {"usd": 0.0, "calls": 0})
                e["usd"] += d.get("usd") or 0
                e["calls"] += 1
        pipeline = [{"$match": {"dayTs": {"$gte": _day_floor(from_ms), "$lt": _day_ceil(to_ms)}}},
                    {"$group": {"_id": "$day", "usd": {"$sum": "$usd"}, "calls": {"$sum": "$calls"}}}]
        actual = {r["_id"]: r for r in await self._rollups.aggregate(pipeline)}
        mismatches = []
        for day in sorted(set(expected) | set(actual)):
            led = expected.get(day, {"usd": 0.0, "calls": 0})
            roll = actual.get(day, {"usd": 0.0, "calls": 0})
            if round(led["usd"] - roll["usd"], 9) != 0 or led["calls"] != roll["calls"]:
                mismatches.append({"day": day, "ledgerUsd": round(led["usd"], 6), "rollupUsd": round(roll["usd"], 6),
                                   "delta": round(roll["usd"] - led["usd"], 6),
                                   "ledgerCalls": led["calls"], "rollupCalls": roll["calls"]})
        return mismatches


def _day_floor(ms: int) -> int:
    return ms - ms % DAY_MS


def _day_ceil(ms: int) -> int:
    return -(-ms // DAY_MS) * DAY_MS
