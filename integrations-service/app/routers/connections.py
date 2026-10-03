from typing import List

from fastapi import APIRouter, Depends

from ..container import Container, get_container
from ..models import SessionRequest, SessionResponse
from ..security import require_internal_key

router = APIRouter(prefix="/connections", dependencies=[Depends(require_internal_key)])


@router.post("/session", response_model=SessionResponse)
async def create_session(req: SessionRequest, c: Container = Depends(get_container)) -> SessionResponse:
    session = await c.connections.create_session(req.agentId, req.toolType, req.callbackUrl)
    return SessionResponse(url=session.url)


@router.get("/{agent_id}")
async def list_connections(agent_id: str, c: Container = Depends(get_container)) -> List[dict]:
    return await c.connections.status_all(agent_id)


@router.get("/{agent_id}/{tool_type}")
async def get_connection(agent_id: str, tool_type: str, c: Container = Depends(get_container)) -> dict:
    return await c.connections.status(agent_id, tool_type)


@router.delete("/{agent_id}/{tool_type}")
async def disconnect(agent_id: str, tool_type: str, c: Container = Depends(get_container)) -> dict:
    await c.connections.disconnect(agent_id, tool_type)
    return {"ok": True}
