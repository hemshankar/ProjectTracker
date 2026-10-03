import time
import uuid
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from ..backends.base import CONNECTED, NOT_CONNECTED, ConnectionInfo
from ..errors import BackendUnavailable, Forbidden, InvalidInput, NotConnected
from ..models.connection import PENDING, ConnectionRecord, SessionResult
from .audit_service import AuditService
from .connection_store import ConnectionStore
from .provider_service import ProviderService

_PENDING_TTL_MS = 24 * 3600 * 1000


class ConnectionService:
    """Connection lifecycle and status. Which connection a call uses is the resolver's job."""

    def __init__(self, db, providers: ProviderService, audit: AuditService, ttl_seconds: int = 15, clock=time.time):
        self.store = ConnectionStore(db, clock)
        self._providers = providers
        self._audit = audit
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: Dict[Tuple[str, str], Tuple[float, ConnectionRecord]] = {}

    # --- connect -----------------------------------------------------------
    async def create_session(self, agent_id: str, tool_type: str, callback_url: str,
                             owner_user_id: Optional[str] = None, label: Optional[str] = None) -> SessionResult:
        provider = await self._providers.get(tool_type)
        connection_id = f"conn_{uuid.uuid4().hex[:16]}"
        record = ConnectionRecord(connection_id, agent_id, tool_type, provider.backend,
                                  backend_user_id=f"{agent_id}:{connection_id}", label=(label or "").strip() or None,
                                  owner_user_id=owner_user_id, created_at=self.store.now_ms())
        session = await self._providers.backend_for(provider).create_connect_session(
            record.backend_user_id, provider, callback_url)
        await self.store.insert(replace(record, backend_connection_id=session.backend_connection_id))
        await self._audit.record("monolith", "connect_session", f"{agent_id}/{tool_type}/{connection_id}")
        return SessionResult(session.url, connection_id)

    # --- status ------------------------------------------------------------
    async def refresh(self, record: ConnectionRecord) -> Tuple[ConnectionRecord, bool]:
        """Asks the backend for the live state. Returns (record, stale)."""
        key = (record.agent_id, record.connection_id)
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1], False
        provider = await self._providers.get(record.tool_type, require_enabled=False)
        try:
            info = await self._providers.backend_for(provider).get_connection(record.backend_user_id, provider)
        except BackendUnavailable:
            return record, True
        keep_pending = record.status == PENDING and info.status == NOT_CONNECTED
        label = record.label or info.label
        await self.store.update_state(record.connection_id, provider.backend, info, keep_pending, label)
        fresh = replace(record, status=PENDING if keep_pending else info.status,
                        label=label, backend=provider.backend,
                        backend_connection_id=info.backend_connection_id or record.backend_connection_id)
        fresh = await self._ensure_default(fresh)
        self._cache[key] = (self._clock(), fresh)
        return fresh, False

    async def status(self, agent_id: str, tool_type: str, caller_user: Optional[str] = None) -> dict:
        provider = await self._providers.get(tool_type, require_enabled=False)
        if not provider.enabled:
            return self._placeholder(tool_type, "disabled")
        entries = await self._entries(agent_id, tool_type, provider.display_name, caller_user)
        entries.sort(key=lambda e: (not e["isDefault"], not e["connected"]))
        return entries[0] if entries else self._placeholder(tool_type, NOT_CONNECTED)

    async def status_all(self, agent_id: str, caller_user: Optional[str] = None) -> List[dict]:
        """Every visible connection; a tool with none gets one not-connected placeholder (legacy shape)."""
        await self.store.purge_pending(agent_id, self.store.now_ms() - _PENDING_TTL_MS)
        out: List[dict] = []
        for provider in await self._providers.list():
            if not provider.enabled:
                out.append(self._placeholder(provider.tool_type, "disabled"))
                continue
            entries = await self._entries(agent_id, provider.tool_type, provider.display_name, caller_user)
            out.extend(entries or [self._placeholder(provider.tool_type, NOT_CONNECTED)])
        return out

    async def _entries(self, agent_id: str, tool_type: str, display_name: str, caller_user: Optional[str]) -> List[dict]:
        entries = []
        for record in await self.store.list(agent_id, tool_type):
            if not record.visible_to(caller_user):
                continue
            fresh, stale = await self.refresh(record)
            if fresh.status != PENDING:  # an unfinished connect is not shown
                entries.append(self._json(fresh, display_name, stale))
        return entries

    # --- disconnect / default ---------------------------------------------
    async def disconnect(self, agent_id: str, tool_type: str, caller_user: Optional[str] = None) -> None:
        records = [r for r in await self.store.list(agent_id, tool_type) if r.visible_to(caller_user)]
        target = next((r for r in records if r.is_default), records[0] if records else None)
        if target:
            await self.disconnect_by_id(agent_id, target.connection_id, caller_user)

    async def disconnect_by_id(self, agent_id: str, connection_id: str, caller_user: Optional[str] = None) -> None:
        record = await self.store.get(agent_id, connection_id)
        if record is None:
            return
        if not record.visible_to(caller_user):
            raise Forbidden("connection belongs to another user")
        provider = await self._providers.get(record.tool_type, require_enabled=False)
        await self._providers.backend_for(provider).disconnect(record.backend_user_id, provider)
        await self.store.delete(connection_id)
        self.invalidate(agent_id, record.tool_type)
        if record.is_default:
            await self._promote_default(agent_id, record.tool_type)
        await self._audit.record("monolith", "disconnect", f"{agent_id}/{record.tool_type}/{connection_id}")

    async def set_default(self, agent_id: str, connection_id: str, caller_user: Optional[str] = None) -> None:
        record = await self.store.get(agent_id, connection_id)
        if record is None:
            raise NotConnected(connection_id)
        if not record.visible_to(caller_user):
            raise Forbidden("connection belongs to another user")
        if record.owner_user_id:
            raise InvalidInput("only shared connections can be the default")
        fresh, _ = await self.refresh(record)
        if fresh.status != CONNECTED:
            raise NotConnected(record.tool_type)
        await self.store.set_default(agent_id, record.tool_type, connection_id)
        self.invalidate(agent_id, record.tool_type)
        await self._audit.record("monolith", "set_default", f"{agent_id}/{record.tool_type}/{connection_id}")

    # --- state written by webhooks ----------------------------------------
    async def record_state(self, record: ConnectionRecord, backend: str, info: ConnectionInfo) -> None:
        await self.store.update_state(record.connection_id, backend, info, label=record.label or info.label)
        await self._ensure_default(replace(record, status=info.status))
        self.invalidate(record.agent_id, record.tool_type)

    async def ensure_legacy(self, agent_id: str, tool_type: str, backend: str, info: ConnectionInfo) -> None:
        """A connect that predates multi-connection support: user_id is the agent id itself."""
        record = ConnectionRecord(f"conn_{uuid.uuid4().hex[:16]}", agent_id, tool_type, backend, agent_id,
                                  info.status, None, None, False, info.backend_connection_id, self.store.now_ms())
        await self.store.insert(await self._ensure_default(record))

    def invalidate(self, agent_id: str, tool_type: str) -> None:
        for key in [k for k, (_, r) in self._cache.items() if k[0] == agent_id and r.tool_type == tool_type]:
            self._cache.pop(key, None)

    def invalidate_tool(self, tool_type: str) -> None:
        for key in [k for k, (_, r) in self._cache.items() if r.tool_type == tool_type]:
            self._cache.pop(key, None)

    # --- helpers -----------------------------------------------------------
    async def _ensure_default(self, record: ConnectionRecord) -> ConnectionRecord:
        """First connected shared connection of a tool becomes its default."""
        if record.status != CONNECTED or record.owner_user_id or record.is_default:
            return record
        if await self.store.has_default(record.agent_id, record.tool_type):
            return record
        await self.store.set_default(record.agent_id, record.tool_type, record.connection_id)
        return replace(record, is_default=True)

    async def _promote_default(self, agent_id: str, tool_type: str) -> None:
        for record in await self.store.list(agent_id, tool_type):
            if not record.owner_user_id and record.status == CONNECTED:
                await self.store.set_default(agent_id, tool_type, record.connection_id)
                return

    @staticmethod
    def _placeholder(tool_type: str, status: str) -> dict:
        return {"toolType": tool_type, "connected": False, "status": status, "label": None, "expiresAt": None,
                "stale": False, "connectionId": None, "ownerUserId": None, "visibility": "agent", "isDefault": False}

    @staticmethod
    def _json(r: ConnectionRecord, display_name: str, stale: bool = False) -> dict:
        connected = r.status == CONNECTED
        return {"toolType": r.tool_type, "connected": connected, "status": r.status,
                "label": (r.label or display_name) if connected else None, "expiresAt": None, "stale": stale,
                "connectionId": r.connection_id, "ownerUserId": r.owner_user_id, "visibility": r.visibility,
                "isDefault": r.is_default}
