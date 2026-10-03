from typing import Dict, List

from fastapi import APIRouter, Depends, Query

from ..container import get_container
from ..models.queries import BreakdownRow, GroupBy, Granularity, SeriesPoint, Totals, UsageQuery
from ..security import require_internal_key
from .params import usage_query

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])


@router.get("/summary", response_model=Totals)
async def summary(q: UsageQuery = Depends(usage_query)) -> Totals:
    return await get_container().query.summary(q)


@router.get("/summary/batch", response_model=Dict[str, Totals])
async def summary_batch(agentId: str = Query(..., min_length=1), boardIds: str = "",
                        taskIds: str = "") -> Dict[str, Totals]:
    """Comma-separated `boardIds` or `taskIds` (one of them) -> totals per id."""
    dimension, raw = ("boardId", boardIds) if boardIds else ("taskId", taskIds)
    ids = [i for i in raw.split(",") if i][:500]
    return await get_container().query.summary_batch(agentId, dimension, ids)


@router.get("/timeseries", response_model=List[SeriesPoint])
async def timeseries(granularity: Granularity = Granularity.DAY, groupBy: GroupBy = GroupBy.NONE,
                     q: UsageQuery = Depends(usage_query)) -> List[SeriesPoint]:
    return await get_container().query.timeseries(q, granularity, groupBy)


@router.get("/breakdown", response_model=List[BreakdownRow])
async def breakdown(groupBy: GroupBy = GroupBy.BOARD, limit: int = Query(20, ge=1, le=100),
                    q: UsageQuery = Depends(usage_query)) -> List[BreakdownRow]:
    return await get_container().query.breakdown(q, groupBy, limit)
