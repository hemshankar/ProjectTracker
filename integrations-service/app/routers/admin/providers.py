from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...container import Container, get_container
from .deps import ACTOR, require_admin, require_csrf

router = APIRouter(prefix="/providers")


class ProviderPatch(BaseModel):
    backend: Optional[str] = None
    backendSlug: Optional[str] = None
    enabled: Optional[bool] = None
    confirm: bool = False


@router.get("", dependencies=[Depends(require_admin)])
async def list_providers(c: Container = Depends(get_container)) -> List[dict]:
    return await c.provider_admin.list()


@router.patch("/{tool_type}", dependencies=[Depends(require_csrf)])
async def patch_provider(tool_type: str, patch: ProviderPatch, c: Container = Depends(get_container)) -> dict:
    return await c.provider_admin.update(tool_type, ACTOR, patch.backend, patch.backendSlug, patch.enabled, patch.confirm)
