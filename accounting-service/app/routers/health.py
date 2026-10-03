from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..container import get_container
from ..services.readiness import check_ready

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/health/ready")
async def ready():
    result = await check_ready(get_container().db)
    return JSONResponse(result, status_code=200 if result["ready"] else 503)
