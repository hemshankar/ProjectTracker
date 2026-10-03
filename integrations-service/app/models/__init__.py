from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    callbackUrl: str = Field(min_length=1)
    ownerUserId: Optional[str] = None  # None = shared with the agent
    label: Optional[str] = Field(default=None, max_length=80)


class SessionResponse(BaseModel):
    url: str
    connectionId: Optional[str] = None


class ExecuteRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    action: str = Field(min_length=1)
    args: Dict[str, Any] = {}
    caller: str = "monolith"
    connectionId: Optional[str] = None  # None = the agent's default connection for this tool


class ProxyRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    method: str = "GET"
    endpoint: str = Field(min_length=1)
    params: Optional[Dict[str, Any]] = None
    body: Any = None
    connectionId: Optional[str] = None


class ExecuteResponse(BaseModel):
    ok: bool
    result: Any = None
    error: Optional[str] = None


class ProviderOut(BaseModel):
    toolType: str
    displayName: str
    backend: str
    backendSlug: str
    authMode: str
    enabled: bool
