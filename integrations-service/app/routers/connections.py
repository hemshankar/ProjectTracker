from typing import List, Optional

from fastapi import APIRouter, Depends, Header

from ..container import Container, get_container
from ..models import SessionRequest, SessionResponse
from ..security import require_internal_key

router = APIRouter(prefix="/connections", dependencies=[Depends(require_internal_key)])


def acting_user(x_acting_user: Optional[str] = Header(default=None)) -> Optional[str]:
    """Trusted only because every route here already required the internal key."""
    return x_acting_user or None


@router.post("/session", response_model=SessionResponse)
async def create_session(req: SessionRequest, c: Container = Depends(get_container)) -> SessionResponse:
    session = await c.connections.create_session(req.agentId, req.toolType, req.callbackUrl, req.ownerUserId, req.label)
    return SessionResponse(url=session.url, connectionId=session.connection_id)


@router.get("/{agent_id}")
async def list_connections(agent_id: str, user: Optional[str] = Depends(acting_user),
                           c: Container = Depends(get_container)) -> List[dict]:
    return await c.connections.status_all(agent_id, user)


@router.delete("/{agent_id}/by-id/{connection_id}")
async def disconnect_by_id(agent_id: str, connection_id: str, user: Optional[str] = Depends(acting_user),
                           c: Container = Depends(get_container)) -> dict:
    await c.connections.disconnect_by_id(agent_id, connection_id, user)
    return {"ok": True}


@router.post("/{agent_id}/by-id/{connection_id}/default")
async def make_default(agent_id: str, connection_id: str, user: Optional[str] = Depends(acting_user),
                       c: Container = Depends(get_container)) -> dict:
    await c.connections.set_default(agent_id, connection_id, user)
    return {"ok": True}


@router.get("/{agent_id}/{tool_type}")
async def get_connection(agent_id: str, tool_type: str, user: Optional[str] = Depends(acting_user),
                         c: Container = Depends(get_container)) -> dict:
    return await c.connections.status(agent_id, tool_type, user)


@router.delete("/{agent_id}/{tool_type}")
async def disconnect(agent_id: str, tool_type: str, user: Optional[str] = Depends(acting_user),
                     c: Container = Depends(get_container)) -> dict:
    await c.connections.disconnect(agent_id, tool_type, user)
    return {"ok": True}
