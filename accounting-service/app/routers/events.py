from fastapi import APIRouter, Depends

from ..container import get_container
from ..models.events import EventBatch, IngestResult
from ..security import require_internal_key

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])


@router.post("/events", response_model=IngestResult)
async def post_events(batch: EventBatch) -> IngestResult:
    result, _inserted = await get_container().ingest.ingest(batch)
    return result
