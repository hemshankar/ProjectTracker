from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..container import get_container
from ..models.queries import LedgerFilter, RowsPage
from ..security import require_internal_key
from .params import ledger_filter

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])


@router.get("/rows", response_model=RowsPage)
async def rows(limit: int = Query(100, ge=1), cursor: Optional[str] = None,
               f: LedgerFilter = Depends(ledger_filter)) -> RowsPage:
    return await get_container().rows.rows(f, limit, cursor)
