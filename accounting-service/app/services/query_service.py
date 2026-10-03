from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models.queries import BreakdownRow, GroupBy, Granularity, SeriesPoint, Totals, UsageQuery
from ..repositories.ledger_repository import LedgerRepository
from ..repositories.rollup_repository import RollupRepository
from .ledger_filter import validate_range
from .rollup_keys import DAY_MS, SUM_FIELDS, day_start_ms

_SUMS = {"calls": {"$sum": "$calls"}, **{f: {"$sum": f"${f}"} for f in SUM_FIELDS}}
_NAME_FIELD = {"boardId": "boardTitle", "taskId": "taskTitle", "agentId": "agentName"}


def _totals(row: Optional[dict]) -> Totals:
    row = row or {}
    out = {k: row.get(k) or 0 for k in ("calls", *SUM_FIELDS)}
    out["usd"] = round(out["usd"], 6)
    return Totals(**out)


def _match(q: UsageQuery) -> dict:
    m: dict = {"agentId": q.agent_id}
    if q.board_id:
        m["boardId"] = q.board_id
    if q.task_id:
        m["taskId"] = q.task_id
    day = {}
    if q.since_ms is not None:
        day["$gte"] = day_start_ms(q.since_ms)
    if q.until_ms is not None:
        day["$lte"] = day_start_ms(q.until_ms)
    if day:
        m["dayTs"] = day
    return m


def bucket_start(day_ts: int, granularity: Granularity) -> int:
    """UTC bucket start: the day, the ISO week's Monday, or the 1st of the month."""
    if granularity is Granularity.DAY:
        return day_ts
    if granularity is Granularity.WEEK:
        return day_ts - ((day_ts // DAY_MS + 3) % 7) * DAY_MS  # epoch day 0 was a Thursday
    d = datetime.fromtimestamp(day_ts / 1000, tz=timezone.utc)
    return int(d.replace(day=1).timestamp() * 1000)


class QueryService:
    """Read-only totals, time series and breakdowns over the daily rollups."""

    def __init__(self, ledger: LedgerRepository, rollups: RollupRepository):
        self._ledger, self._rollups = ledger, rollups

    async def summary(self, q: UsageQuery) -> Totals:
        validate_range(q.since_ms, q.until_ms)
        rows = await self._rollups.aggregate([{"$match": _match(q)}, {"$group": {"_id": None, **_SUMS}}])
        return _totals(rows[0] if rows else None)

    async def summary_batch(self, agent_id: str, dimension: str, ids: List[str]) -> Dict[str, Totals]:
        """`dimension` is boardId or taskId. Ids with no spend come back as zero totals."""
        pipeline = [{"$match": {"agentId": agent_id, dimension: {"$in": ids}}},
                    {"$group": {"_id": f"${dimension}", **_SUMS}}]
        found = {r["_id"]: _totals(r) for r in await self._rollups.aggregate(pipeline)}
        return {i: found.get(i, Totals()) for i in ids}

    async def timeseries(self, q: UsageQuery, granularity: Granularity, group_by: GroupBy) -> List[SeriesPoint]:
        validate_range(q.since_ms, q.until_ms)
        field = group_by.field
        group_id = {"dayTs": "$dayTs", "key": f"${field}" if field else None}
        rows = await self._rollups.aggregate([{"$match": _match(q)}, {"$group": {"_id": group_id, **_SUMS}}])
        merged: Dict[tuple, dict] = {}
        for r in rows:
            start = bucket_start(r["_id"]["dayTs"], granularity)
            slot = merged.setdefault((start, r["_id"]["key"]), {k: 0 for k in ("calls", *SUM_FIELDS)})
            for k in slot:
                slot[k] += r.get(k) or 0
        points = []
        for (start, key), sums in sorted(merged.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            bucket = datetime.fromtimestamp(start / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            points.append(SeriesPoint(bucket=bucket, bucketTs=start, key=key, **_totals(sums).model_dump()))
        return points

    async def breakdown(self, q: UsageQuery, group_by: GroupBy, limit: int = 20) -> List[BreakdownRow]:
        validate_range(q.since_ms, q.until_ms)
        field = group_by.field or "agentId"
        pipeline = [{"$match": _match(q)}, {"$group": {"_id": f"${field}", **_SUMS}},
                    {"$sort": {"usd": -1}}, {"$limit": limit}]
        rows = await self._rollups.aggregate(pipeline)
        names = await self._names(q.agent_id, field, [r["_id"] for r in rows if r["_id"]])
        return [BreakdownRow(key=r["_id"], name=names.get(r["_id"]), **_totals(r).model_dump()) for r in rows]

    async def _names(self, agent_id: str, field: str, ids: List[str]) -> Dict[str, Optional[str]]:
        name_field = _NAME_FIELD.get(field)
        if not name_field or not ids:
            return {}
        return {r["_id"]: r.get("name") for r in await self._ledger.latest_by(field, ids, agent_id, name_field)}
