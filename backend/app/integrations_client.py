from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

import httpx

from . import config


class IntegrationsError(Exception):
    """Gateway call failed; `status` is the HTTP status (503 when unreachable)."""

    def __init__(self, status: int, message: str, code: str = "gateway_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass(frozen=True)
class GatewayResult:
    ok: bool
    result: Any = None
    error: Optional[str] = None


class IntegrationsClient(Protocol):
    """What the monolith needs from the integrations service (injectable for tests)."""

    async def ping(self) -> bool: ...
    async def create_session(self, agent_id: str, tool_type: str, callback_url: str) -> str: ...
    async def list_connections(self, agent_id: str) -> List[dict]: ...
    async def disconnect(self, agent_id: str, tool_type: str) -> None: ...
    async def execute(self, agent_id: str, tool_type: str, action: str, args: dict) -> GatewayResult: ...


class HttpIntegrationsClient:
    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self._base_url = (base_url or config.INTEGRATIONS_SERVICE_URL).rstrip("/")
        self._service_key = service_key if service_key is not None else config.INTERNAL_SERVICE_KEY

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, f"{self._base_url}{path}",
                                            headers={"X-Internal-Key": self._service_key}, **kwargs)
        except httpx.HTTPError as exc:
            raise IntegrationsError(503, "Integrations service is unreachable") from exc
        if resp.status_code >= 400:
            try:
                err = resp.json()["error"]
                message, code = err["message"], err.get("code", "gateway_error")
            except (ValueError, KeyError, TypeError):
                message, code = f"Integrations service error ({resp.status_code})", "gateway_error"
            raise IntegrationsError(resp.status_code, message, code)
        return resp.json()

    async def ping(self) -> bool:
        try:
            return (await self._request("POST", "/internal/ping")).get("ok") is True
        except IntegrationsError:
            return False

    async def create_session(self, agent_id: str, tool_type: str, callback_url: str) -> str:
        data = await self._request("POST", "/connections/session", json={
            "agentId": agent_id, "toolType": tool_type, "callbackUrl": callback_url})
        return data["url"]

    async def list_connections(self, agent_id: str) -> List[dict]:
        return await self._request("GET", f"/connections/{agent_id}")

    async def disconnect(self, agent_id: str, tool_type: str) -> None:
        await self._request("DELETE", f"/connections/{agent_id}/{tool_type}")

    async def execute(self, agent_id: str, tool_type: str, action: str, args: dict) -> GatewayResult:
        data = await self._request("POST", "/execute", json={
            "agentId": agent_id, "toolType": tool_type, "action": action, "args": args, "caller": "monolith"})
        return GatewayResult(ok=data.get("ok", False), result=data.get("result"), error=data.get("error"))


def get_integrations_client() -> IntegrationsClient:
    return HttpIntegrationsClient()
