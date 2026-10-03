from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import config
from ..container import get_container
from ..security import require_internal_key

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])


class ExistsRequest(BaseModel):
    callIds: List[str]


class ExistsResponse(BaseModel):
    missing: List[str]


@router.get("/stats")
async def stats() -> dict:
    return await get_container().stats.stats()


@router.get("/ledger/total")
async def ledger_total(scope: Literal["global", "agent", "board"], id: Optional[str] = None,
                       since: Optional[int] = Query(None, ge=0)) -> dict:
    if scope != "global" and not id:
        raise HTTPException(status_code=422, detail="id is required for agent and board scopes")
    return await get_container().stats.ledger_total(scope, id, since)


@router.post("/events/exists", response_model=ExistsResponse)
async def events_exists(body: ExistsRequest) -> ExistsResponse:
    if len(body.callIds) > config.MAX_EXISTS_IDS:
        raise HTTPException(status_code=413, detail=f"at most {config.MAX_EXISTS_IDS} ids per request")
    return ExistsResponse(missing=await get_container().stats.missing(body.callIds))
