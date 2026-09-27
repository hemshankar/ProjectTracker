from fastapi import APIRouter, Depends

from ..dependencies import get_current_user, require_agent_admin, require_agent_member
from ..models_identity import AgentCreate, AgentLinkCreate, AgentUpdate, MemberInvite, MemberUpdate
from ..services import agent_links_service, agents_service

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("")
async def create_agent(payload: AgentCreate, user: dict = Depends(get_current_user)):
    return await agents_service.create_agent(user, payload.name, payload.description or "")


@router.get("")
async def list_agents(user: dict = Depends(get_current_user)):
    return await agents_service.list_agents_for_user(user)


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, payload: AgentUpdate, admin: dict = Depends(require_agent_admin())):
    return await agents_service.update_agent(agent_id, payload, admin["_id"])


@router.get("/{agent_id}/boards")
async def list_agent_boards(agent_id: str, user: dict = Depends(require_agent_member())):
    return await agents_service.list_boards_for_agent(agent_id, user["_id"])


@router.get("/{agent_id}/members")
async def list_members(agent_id: str, user: dict = Depends(require_agent_member())):
    return await agents_service.list_members(agent_id)


@router.post("/{agent_id}/members")
async def invite_member(agent_id: str, payload: MemberInvite, user: dict = Depends(get_current_user)):
    return await agents_service.invite_or_request_member(agent_id, user, payload)


@router.patch("/{agent_id}/members/{user_id}")
async def update_member(
    agent_id: str, user_id: str, payload: MemberUpdate, _admin: dict = Depends(require_agent_admin())
):
    return await agents_service.update_member(agent_id, user_id, payload)


@router.delete("/{agent_id}/members/{user_id}")
async def remove_member(agent_id: str, user_id: str, _admin: dict = Depends(require_agent_admin())):
    await agents_service.remove_member(agent_id, user_id)
    return {"ok": True}


# ---------------- delegation links (Phase 6) ----------------


@router.get("/{agent_id}/links")
async def list_links(agent_id: str, _user: dict = Depends(require_agent_member())):
    return await agent_links_service.list_links_from(agent_id)


@router.post("/{agent_id}/links")
async def create_link(agent_id: str, payload: AgentLinkCreate, admin: dict = Depends(require_agent_admin())):
    return await agent_links_service.grant_link(agent_id, payload.toAgentId, admin["_id"])


@router.delete("/{agent_id}/links/{to_agent_id}")
async def delete_link(agent_id: str, to_agent_id: str, admin: dict = Depends(require_agent_admin())):
    await agent_links_service.revoke_link(agent_id, to_agent_id, admin["_id"])
    return {"ok": True}
