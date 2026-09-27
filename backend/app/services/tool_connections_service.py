from typing import Optional

from .. import crypto
from ..database import tool_connections_collection
from ..execution.connectors import get_connector
from ..models import now_ms
from ..models_settings import TOOL_TYPES
from ..models_tools import ConnectedTokens, connection_status_json


def _encode(tokens: ConnectedTokens) -> dict:
    return {
        "accessToken": crypto.encrypt(tokens.access_token),
        "refreshToken": crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else None,
        "expiresAt": tokens.expires_at,
        "label": tokens.identity_label,
    }


def _decode(doc: dict) -> ConnectedTokens:
    return ConnectedTokens(
        access_token=crypto.decrypt(doc["accessToken"]),
        refresh_token=crypto.decrypt(doc["refreshToken"]) if doc.get("refreshToken") else None,
        expires_at=doc.get("expiresAt"),
        identity_label=doc.get("label", ""),
    )


async def list_statuses(agent_id: str) -> list:
    docs = {d["toolType"]: d async for d in tool_connections_collection.find({"agentId": agent_id})}
    return [connection_status_json(t, docs.get(t)) for t in TOOL_TYPES]


async def save_connection(agent_id: str, tool_type: str, tokens: ConnectedTokens) -> None:
    await tool_connections_collection.update_one(
        {"agentId": agent_id, "toolType": tool_type},
        {"$set": {**_encode(tokens), "agentId": agent_id, "toolType": tool_type},
         "$setOnInsert": {"createdAt": now_ms()}},
        upsert=True,
    )


async def disconnect(agent_id: str, tool_type: str) -> None:
    await tool_connections_collection.delete_one({"agentId": agent_id, "toolType": tool_type})


async def get_valid_tokens(agent_id: str, tool_type: str) -> Optional[ConnectedTokens]:
    """Returns usable tokens for this Agent's tool connection, refreshing
    them first if they're near expiry. None means "not connected" — callers
    fall back to the simulated tool result."""
    doc = await tool_connections_collection.find_one({"agentId": agent_id, "toolType": tool_type})
    if not doc:
        return None
    tokens = _decode(doc)

    if tokens.expires_at is not None and tokens.expires_at - now_ms() < 60_000:
        connector = get_connector(tool_type)
        tokens = await connector.refresh(tokens)
        await save_connection(agent_id, tool_type, tokens)

    return tokens
