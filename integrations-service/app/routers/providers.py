from typing import List

from fastapi import APIRouter, Depends

from ..container import Container, get_container
from ..models import ProviderOut
from ..security import require_internal_key

router = APIRouter(dependencies=[Depends(require_internal_key)])


@router.get("/providers", response_model=List[ProviderOut])
async def list_providers(c: Container = Depends(get_container)) -> List[ProviderOut]:
    return [ProviderOut(toolType=p.tool_type, displayName=p.display_name, backend=p.backend,
                        backendSlug=p.backend_slug, authMode=p.auth_mode, enabled=p.enabled)
            for p in await c.providers.list()]
