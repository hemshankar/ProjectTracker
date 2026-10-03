from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from .. import config, dependencies
from ..dependencies import get_current_user, require_agent_admin, require_agent_member
from ..integrations_client import IntegrationsClient, IntegrationsError, get_integrations_client
from ..models_settings import TOOL_TYPES

router = APIRouter(tags=["tools"])


def _gateway_http_error(exc: IntegrationsError) -> HTTPException:
    return HTTPException(status_code=exc.status if exc.status in (403, 404, 409, 503) else 502, detail=exc.message)


def _known_tool(tool_type: str) -> None:
    if tool_type not in TOOL_TYPES:
        raise HTTPException(status_code=404, detail="Unknown tool")


async def _require_admin(agent_id: str, user: dict) -> None:
    member = await dependencies.get_agent_membership(agent_id, user["_id"])
    if not member or member.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Agent admin access required")


@router.get("/api/agents/{agent_id}/tools")
async def list_tool_connections(
    agent_id: str,
    user: dict = Depends(require_agent_member()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    """Every connection this user may see: shared ones plus their own personal ones."""
    try:
        return await client.list_connections(agent_id, acting_user=user["_id"])
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)


@router.get("/api/agents/{agent_id}/tools/{tool_type}/connect")
async def connect_tool(
    agent_id: str,
    tool_type: str,
    personal: bool = False,
    label: Optional[str] = None,
    user: dict = Depends(require_agent_member()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    _known_tool(tool_type)
    if not personal:
        await _require_admin(agent_id, user)  # shared connections belong to the whole agent
    extra = {}
    if personal:
        extra["owner_user_id"] = user["_id"]
    if label:
        extra["label"] = label
    try:
        url = await client.create_session(agent_id, tool_type, config.FRONTEND_ORIGIN, **extra)
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)
    return RedirectResponse(url)


@router.delete("/api/agents/{agent_id}/tools/{tool_type}")
async def disconnect_tool(
    agent_id: str,
    tool_type: str,
    _admin: dict = Depends(require_agent_admin()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    _known_tool(tool_type)
    try:
        await client.disconnect(agent_id, tool_type)
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)
    return {"ok": True}


async def _find_connection(client: IntegrationsClient, agent_id: str, user_id: str, connection_id: str) -> dict:
    connections = await client.list_connections(agent_id, acting_user=user_id)
    found = next((c for c in connections if c.get("connectionId") == connection_id), None)
    if not found:
        raise HTTPException(status_code=404, detail="Connection not found")
    return found


@router.delete("/api/agents/{agent_id}/tools/by-id/{connection_id}")
async def disconnect_connection(
    agent_id: str,
    connection_id: str,
    user: dict = Depends(require_agent_member()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    """Owners remove their personal connection; shared ones need an agent admin."""
    try:
        conn = await _find_connection(client, agent_id, user["_id"], connection_id)
        if conn.get("ownerUserId") != user["_id"]:
            await _require_admin(agent_id, user)
        await client.disconnect_connection(agent_id, connection_id, acting_user=user["_id"])
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)
    return {"ok": True}


@router.post("/api/agents/{agent_id}/tools/by-id/{connection_id}/default")
async def make_default_connection(
    agent_id: str,
    connection_id: str,
    user: dict = Depends(get_current_user),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    await _require_admin(agent_id, user)
    try:
        await client.set_default(agent_id, connection_id, acting_user=user["_id"])
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)
    return {"ok": True}
