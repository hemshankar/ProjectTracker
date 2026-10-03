from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..container import get_container
from ..models.queries import LedgerFilter
from ..security import require_internal_key
from .params import ledger_filter

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])


@router.get("/export")
async def export(format: str = Query("csv", pattern="^(csv|jsonl)$"),
                 f: LedgerFilter = Depends(ledger_filter)) -> StreamingResponse:
    media_type, filename, stream = get_container().export.prepare(f, format)
    return StreamingResponse(stream, media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
