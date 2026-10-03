"""Decides which connection a call uses and whether the caller may use it."""
from typing import List, Optional

from ..errors import Forbidden, NotConnected
from ..models.connection import PENDING, ConnectionRecord, ConnectionRef
from .connection_service import ConnectionService


class ConnectionResolver:
    """Rules: explicit id; else the shared default; else the caller's own personal one; else NotConnected.

    Records created before multi-connection support are migrated, so the legacy fallback below only
    matters when the agent has no record at all: it addresses the backend by the bare agent id.
    """

    def __init__(self, connections: ConnectionService):
        self._connections = connections

    async def resolve(self, ref: ConnectionRef, caller_user: Optional[str] = None) -> ConnectionRecord:
        store = self._connections.store
        if ref.connection_id:
            record = await store.get(ref.agent_id, ref.connection_id)
            if record is None or record.tool_type != ref.tool_type:
                raise NotConnected(ref.tool_type)
            if not record.visible_to(caller_user):
                raise Forbidden("connection belongs to another user")
            return record
        all_records = await store.list(ref.agent_id, ref.tool_type)
        visible = [r for r in all_records if r.visible_to(caller_user)]
        picked = self._pick(visible, caller_user)
        if picked is None:  # a connect finished at the provider but nothing has refreshed it yet
            for pending in [r for r in visible if r.status == PENDING]:
                await self._connections.refresh(pending)
            picked = self._pick(await self._visible(ref, caller_user), caller_user)
        if picked:
            return picked
        if not all_records:
            return ConnectionRecord("legacy", ref.agent_id, ref.tool_type, "", ref.agent_id, status="unknown")
        raise NotConnected(ref.tool_type)

    async def _visible(self, ref: ConnectionRef, caller_user: Optional[str]) -> List[ConnectionRecord]:
        return [r for r in await self._connections.store.list(ref.agent_id, ref.tool_type) if r.visible_to(caller_user)]

    @staticmethod
    def _pick(records: List[ConnectionRecord], caller_user: Optional[str]) -> Optional[ConnectionRecord]:
        usable = [r for r in records if r.status != PENDING]
        shared_default = next((r for r in usable if r.is_default), None)
        if shared_default:
            return shared_default
        return next((r for r in usable if caller_user and r.owner_user_id == caller_user), None)
