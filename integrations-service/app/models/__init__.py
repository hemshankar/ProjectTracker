from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    callbackUrl: str = Field(min_length=1)


class SessionResponse(BaseModel):
    url: str


class ExecuteRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    action: str = Field(min_length=1)
    args: Dict[str, Any] = {}
    caller: str = "monolith"


class ProxyRequest(BaseModel):
    agentId: str = Field(min_length=1)
    toolType: str = Field(min_length=1)
    method: str = "GET"
    endpoint: str = Field(min_length=1)
    params: Optional[Dict[str, Any]] = None
    body: Any = None


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
