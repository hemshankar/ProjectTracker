import time
from typing import Dict, List, Optional, Tuple

from ..backends.base import CONNECTED, ConnectionInfo, ConnectSession
from ..errors import BackendUnavailable
from .audit_service import AuditService
from .provider_service import ProviderService


class ConnectionService:
    def __init__(self, db, providers: ProviderService, audit: AuditService, ttl_seconds: int = 15, clock=time.time):
        self._col = db["connections"]
        self._providers = providers
        self._audit = audit
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: Dict[Tuple[str, str], Tuple[float, dict]] = {}

    async def create_session(self, agent_id: str, tool_type: str, callback_url: str) -> ConnectSession:
        provider = await self._providers.get(tool_type)
        session = await self._providers.backend_for(provider).create_connect_session(agent_id, provider, callback_url)
        await self._audit.record("monolith", "connect_session", f"{agent_id}/{tool_type}")
        return session

    async def status(self, agent_id: str, tool_type: str) -> dict:
        key = (agent_id, tool_type)
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        provider = await self._providers.get(tool_type, require_enabled=False)
        if not provider.enabled:
            return {"toolType": tool_type, "connected": False, "status": "disabled", "label": None,
                    "expiresAt": None, "stale": False}
        try:
            info = await self._providers.backend_for(provider).get_connection(agent_id, provider)
        except BackendUnavailable:
            stored = await self._col.find_one({"agentId": agent_id, "toolType": tool_type})
            return self._json(tool_type, provider.display_name, _info_from_doc(stored), stale=True)
        await self.record_state(agent_id, tool_type, provider.backend, info)
        result = self._json(tool_type, provider.display_name, info)
        self._cache[key] = (self._clock(), result)
        return result

    async def status_all(self, agent_id: str) -> List[dict]:
        return [await self.status(agent_id, p.tool_type) for p in await self._providers.list()]

    async def disconnect(self, agent_id: str, tool_type: str) -> None:
        provider = await self._providers.get(tool_type, require_enabled=False)
        await self._providers.backend_for(provider).disconnect(agent_id, provider)
        await self._col.delete_one({"agentId": agent_id, "toolType": tool_type})
        self.invalidate(agent_id, tool_type)
        await self._audit.record("monolith", "disconnect", f"{agent_id}/{tool_type}")

    async def record_state(self, agent_id: str, tool_type: str, backend: str, info: ConnectionInfo) -> None:
        await self._col.update_one(
            {"agentId": agent_id, "toolType": tool_type},
            {"$set": {"backend": backend, "backendConnectionId": info.backend_connection_id,
                      "status": info.status, "label": info.label, "updatedAt": int(self._clock() * 1000)}},
            upsert=True)

    def invalidate(self, agent_id: str, tool_type: str) -> None:
        self._cache.pop((agent_id, tool_type), None)

    def invalidate_tool(self, tool_type: str) -> None:
        for key in [k for k in self._cache if k[1] == tool_type]:
            self._cache.pop(key, None)

    @staticmethod
    def _json(tool_type: str, display_name: str, info: ConnectionInfo, stale: bool = False) -> dict:
        connected = info.status == CONNECTED
        return {"toolType": tool_type, "connected": connected, "status": info.status,
                "label": (info.label or display_name) if connected else None, "expiresAt": None, "stale": stale}


def _info_from_doc(doc: Optional[dict]) -> ConnectionInfo:
    if not doc:
        return ConnectionInfo("not_connected")
    return ConnectionInfo(doc.get("status", "not_connected"), doc.get("backendConnectionId"), doc.get("label"))
