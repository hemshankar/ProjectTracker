"""Persistence for the `connections` collection. Mapping only; no business rules."""
import time
from dataclasses import asdict
from typing import List, Optional

from ..backends.base import ConnectionInfo
from ..models.connection import PENDING, ConnectionRecord

_FIELDS = {
    "connection_id": "connectionId", "agent_id": "agentId", "tool_type": "toolType", "backend": "backend",
    "backend_user_id": "backendUserId", "status": "status", "label": "label", "owner_user_id": "ownerUserId",
    "is_default": "isDefault", "backend_connection_id": "backendConnectionId", "created_at": "createdAt",
}


def to_doc(r: ConnectionRecord) -> dict:
    doc = {_FIELDS[k]: v for k, v in asdict(r).items()}
    doc["visibility"] = r.visibility
    return doc


def from_doc(d: dict) -> ConnectionRecord:
    return ConnectionRecord(
        connection_id=d["connectionId"], agent_id=d["agentId"], tool_type=d["toolType"],
        backend=d.get("backend", ""), backend_user_id=d.get("backendUserId") or d["agentId"],
        status=d.get("status", PENDING), label=d.get("label"), owner_user_id=d.get("ownerUserId"),
        is_default=bool(d.get("isDefault")), backend_connection_id=d.get("backendConnectionId"),
        created_at=d.get("createdAt", 0))


class ConnectionStore:
    def __init__(self, db, clock=time.time):
        self._col = db["connections"]
        self._clock = clock

    def now_ms(self) -> int:
        return int(self._clock() * 1000)

    async def insert(self, record: ConnectionRecord) -> None:
        await self._col.insert_one(to_doc(record))

    async def get(self, agent_id: str, connection_id: str) -> Optional[ConnectionRecord]:
        doc = await self._col.find_one({"agentId": agent_id, "connectionId": connection_id})
        return from_doc(doc) if doc else None

    async def list(self, agent_id: str, tool_type: Optional[str] = None) -> List[ConnectionRecord]:
        query = {"agentId": agent_id, **({"toolType": tool_type} if tool_type else {})}
        return [from_doc(d) async for d in self._col.find(query).sort("createdAt", 1)]

    async def find_by_backend(self, backend_user_id: str, tool_type: str) -> Optional[ConnectionRecord]:
        doc = await self._col.find_one({"backendUserId": backend_user_id, "toolType": tool_type})
        return from_doc(doc) if doc else None

    async def find_by_backend_connection(self, backend_connection_id: str) -> Optional[ConnectionRecord]:
        doc = await self._col.find_one({"backendConnectionId": backend_connection_id})
        return from_doc(doc) if doc else None

    async def update_state(self, connection_id: str, backend: str, info: ConnectionInfo,
                           keep_pending: bool = False, label: Optional[str] = None) -> None:
        status = PENDING if keep_pending else info.status
        fields = {"backend": backend, "status": status, "updatedAt": self.now_ms()}
        if info.backend_connection_id or not keep_pending:
            fields["backendConnectionId"] = info.backend_connection_id
        if label:  # only filled in when the user gave none; a chosen label is never overwritten
            fields["label"] = label
        await self._col.update_one({"connectionId": connection_id}, {"$set": fields})

    async def set_default(self, agent_id: str, tool_type: str, connection_id: str) -> None:
        # Unset first: the partial unique index allows only one default per agent+tool.
        await self._col.update_many({"agentId": agent_id, "toolType": tool_type, "isDefault": True},
                                    {"$set": {"isDefault": False}})
        await self._col.update_one({"connectionId": connection_id}, {"$set": {"isDefault": True}})

    async def has_default(self, agent_id: str, tool_type: str) -> bool:
        return await self._col.count_documents({"agentId": agent_id, "toolType": tool_type, "isDefault": True}) > 0

    async def delete(self, connection_id: str) -> None:
        await self._col.delete_one({"connectionId": connection_id})

    async def purge_pending(self, agent_id: str, older_than_ms: int) -> None:
        await self._col.delete_many({"agentId": agent_id, "status": PENDING, "createdAt": {"$lt": older_than_ms}})
