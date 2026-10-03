from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from .. import config
from ..dependencies import require_agent_admin
from ..integrations_client import IntegrationsClient, IntegrationsError, get_integrations_client
from ..models_settings import TOOL_TYPES

router = APIRouter(tags=["tools"])


def _gateway_http_error(exc: IntegrationsError) -> HTTPException:
    return HTTPException(status_code=exc.status if exc.status in (404, 409, 503) else 502, detail=exc.message)


@router.get("/api/agents/{agent_id}/tools")
async def list_tool_connections(
    agent_id: str,
    _admin: dict = Depends(require_agent_admin()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    try:
        return await client.list_connections(agent_id)
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)


@router.get("/api/agents/{agent_id}/tools/{tool_type}/connect")
async def connect_tool(
    agent_id: str,
    tool_type: str,
    _admin: dict = Depends(require_agent_admin()),
    client: IntegrationsClient = Depends(get_integrations_client),
):
    if tool_type not in TOOL_TYPES:
        raise HTTPException(status_code=404, detail="Unknown tool")
    try:
        url = await client.create_session(agent_id, tool_type, config.FRONTEND_ORIGIN)
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
    if tool_type not in TOOL_TYPES:
        raise HTTPException(status_code=404, detail="Unknown tool")
    try:
        await client.disconnect(agent_id, tool_type)
    except IntegrationsError as exc:
        raise _gateway_http_error(exc)
    return {"ok": True}
