from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..security import require_internal_key

router = APIRouter()


class PingResponse(BaseModel):
    ok: bool
    service: str


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/internal/ping", response_model=PingResponse, dependencies=[Depends(require_internal_key)])
async def ping() -> PingResponse:
    return PingResponse(ok=True, service="integrations-service")
