from fastapi import APIRouter, Depends

from ..dependencies import require_agent_admin
from ..models_settings import AgentSettingsUpdate
from ..services import settings_service

router = APIRouter(prefix="/api/agents/{agent_id}/settings", tags=["settings"])


@router.get("")
async def get_settings(agent_id: str, _admin: dict = Depends(require_agent_admin())):
    return await settings_service.get_settings(agent_id)


@router.patch("")
async def update_settings(
    agent_id: str, payload: AgentSettingsUpdate, admin: dict = Depends(require_agent_admin())
):
    return await settings_service.update_settings(agent_id, payload, admin["_id"])
