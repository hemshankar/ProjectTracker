from typing import List

from fastapi import APIRouter, Depends, Query

from ...container import Container, get_container
from .deps import require_admin

router = APIRouter(prefix="/audit", dependencies=[Depends(require_admin)])


@router.get("")
async def list_audit(limit: int = Query(50, ge=1, le=200), skip: int = Query(0, ge=0),
                     c: Container = Depends(get_container)) -> List[dict]:
    return await c.audit.list(limit, skip)
