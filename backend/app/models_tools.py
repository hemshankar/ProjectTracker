from typing import Any, Dict, Optional

from pydantic import BaseModel


class ConnectedTokens(BaseModel):
    """Provider tokens for one tool connection. Stored encrypted at rest;
    this shape is the decrypted, in-memory form used by connectors."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None  # epoch ms
    identity_label: str = ""
    extra: Dict[str, Any] = {}


def connection_status_json(tool_type: str, doc: Optional[dict]) -> dict:
    if not doc:
        return {"toolType": tool_type, "connected": False, "label": None, "expiresAt": None}
    return {
        "toolType": tool_type,
        "connected": True,
        "label": doc.get("label"),
        "expiresAt": doc.get("expiresAt"),
        "connectedAt": doc.get("createdAt"),
    }


class BoardBudgetUpdate(BaseModel):
    capUsd: Optional[float] = None
