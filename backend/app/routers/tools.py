import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from .. import config
from ..dependencies import require_agent_admin
from ..execution.connectors import get_connector
from ..models_settings import TOOL_TYPES
from ..security import sign_state, verify_state
from ..services import tool_connections_service

router = APIRouter(tags=["tools"])


@router.get("/api/agents/{agent_id}/tools")
async def list_tool_connections(agent_id: str, _admin: dict = Depends(require_agent_admin())):
    return await tool_connections_service.list_statuses(agent_id)


@router.get("/api/agents/{agent_id}/tools/{tool_type}/connect")
async def connect_tool(agent_id: str, tool_type: str, _admin: dict = Depends(require_agent_admin())):
    if tool_type not in TOOL_TYPES:
        raise HTTPException(status_code=404, detail="Unknown tool")
    connector = get_connector(tool_type)
    if not connector.configured():
        raise HTTPException(
            status_code=503,
            detail=f"{tool_type} isn't configured on the server yet — see .env.example for the required credentials.",
        )
    state = sign_state(json.dumps({"agentId": agent_id, "toolType": tool_type}))
    return RedirectResponse(connector.build_authorize_url(state))


@router.delete("/api/agents/{agent_id}/tools/{tool_type}")
async def disconnect_tool(agent_id: str, tool_type: str, _admin: dict = Depends(require_agent_admin())):
    if tool_type not in TOOL_TYPES:
        raise HTTPException(status_code=404, detail="Unknown tool")
    await tool_connections_service.disconnect(agent_id, tool_type)
    return {"ok": True}


async def _handle_callback(expected_tool_type: str, code: str, state: str) -> RedirectResponse:
    decoded = verify_state(state) if state else None
    if not code or not decoded:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    parsed = json.loads(decoded)
    agent_id, tool_type = parsed["agentId"], parsed["toolType"]
    if tool_type != expected_tool_type:
        raise HTTPException(status_code=400, detail="Tool type mismatch")

    connector = get_connector(tool_type)
    tokens = await connector.exchange_code(code)
    await tool_connections_service.save_connection(agent_id, tool_type, tokens)
    return RedirectResponse(config.FRONTEND_ORIGIN)


@router.get("/api/tools/google/callback")
async def google_tools_callback(code: str = "", state: str = ""):
    # Google's callback URL is shared by gmail and calendar; the real tool
    # type travels inside the signed `state`, not the query string.
    decoded = verify_state(state) if state else None
    if not decoded:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    tool_type = json.loads(decoded)["toolType"]
    return await _handle_callback(tool_type, code, state)


@router.get("/api/tools/slack/callback")
async def slack_tools_callback(code: str = "", state: str = ""):
    return await _handle_callback("slack", code, state)
