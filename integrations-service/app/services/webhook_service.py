import time
from typing import Mapping

from pymongo.errors import DuplicateKeyError

from ..backends.base import CONNECTED, EXPIRED, NOT_CONNECTED, ConnectionInfo
from .connection_service import ConnectionService
from .provider_service import ProviderService

_KIND_TO_STATUS = {"connected": CONNECTED, "expired": EXPIRED, "removed": NOT_CONNECTED}


class WebhookService:
    def __init__(self, db, providers: ProviderService, connections: ConnectionService, clock=time.time):
        self._events = db["webhook_events"]
        self._col = db["connections"]
        self._providers = providers
        self._connections = connections
        self._clock = clock

    async def handle(self, backend_name: str, headers: Mapping[str, str], body: bytes) -> str:
        """Verify first (inside parse_webhook), then process idempotently."""
        provider_for_backend = next((p for p in await self._providers.list() if p.backend == backend_name), None)
        if provider_for_backend is None:
            return "ignored"
        backend = self._providers.backend_for(provider_for_backend)
        event = backend.parse_webhook(headers, body)
        if event is None:
            return "ignored"
        try:
            await self._events.insert_one({"eventId": event.event_id, "receivedAt": _utcnow(self._clock())})
        except DuplicateKeyError:
            return "duplicate"
        existing = await self._col.find_one({"backendConnectionId": event.backend_connection_id})
        agent_id = (existing or {}).get("agentId") or event.user_id
        tool_type = (existing or {}).get("toolType") or await self._tool_type_for(event.toolkit_slug)
        if not agent_id or not tool_type:
            return "unmatched"
        info = ConnectionInfo(_KIND_TO_STATUS[event.kind], event.backend_connection_id)
        await self._connections.record_state(agent_id, tool_type, backend_name, info)
        self._connections.invalidate(agent_id, tool_type)
        return "processed"

    async def _tool_type_for(self, slug):
        for p in await self._providers.list():
            if p.backend_slug == slug:
                return p.tool_type
        return None


def _utcnow(ts: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc)
