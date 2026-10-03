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
        store = self._connections.store
        info = ConnectionInfo(_KIND_TO_STATUS[event.kind], event.backend_connection_id)
        record = await store.find_by_backend_connection(event.backend_connection_id)
        if record is None and event.user_id:
            tool_type = await self._tool_type_for(event.toolkit_slug)
            record = await store.find_by_backend(event.user_id, tool_type) if tool_type else None
            if record is None and tool_type and ":" not in event.user_id:
                await self._connections.ensure_legacy(event.user_id, tool_type, backend_name, info)
                return "processed"
        if record is None:
            return "unmatched"
        await self._connections.record_state(record, backend_name, info)
        return "processed"

    async def _tool_type_for(self, slug):
        for p in await self._providers.list():
            if p.backend_slug == slug:
                return p.tool_type
        return None


def _utcnow(ts: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc)
