from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...container import Container, get_container
from .deps import ACTOR, require_admin, require_csrf

router = APIRouter(prefix="/actions")


class ActionPatch(BaseModel):
    maxAttempts: Optional[int] = None
    baseDelayMs: Optional[int] = None


@router.get("", dependencies=[Depends(require_admin)])
async def list_actions(c: Container = Depends(get_container)) -> List[dict]:
    return await c.action_settings.list()


@router.patch("/{action}", dependencies=[Depends(require_csrf)])
async def patch_action(action: str, patch: ActionPatch, c: Container = Depends(get_container)) -> dict:
    return await c.action_settings.update(action, ACTOR, patch.maxAttempts, patch.baseDelayMs)
