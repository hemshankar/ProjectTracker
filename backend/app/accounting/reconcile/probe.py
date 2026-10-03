"""Core's read-only view of the accounting ledger, for reconcile. Raises AccountingUnavailable if it is down."""
from typing import List, Optional, Protocol

from ..query_client import UsageQueryClient

EXISTS_PAGE = 1000  # the service rejects more ids than this per request


class LedgerProbe(Protocol):
    async def missing(self, call_ids: List[str]) -> List[str]: ...
    async def total(self, scope: str, scope_id: Optional[str], since_ms: int) -> float: ...


class HttpLedgerProbe:
    def __init__(self, client: UsageQueryClient):
        self._client = client

    async def missing(self, call_ids: List[str]) -> List[str]:
        out: List[str] = []
        for i in range(0, len(call_ids), EXISTS_PAGE):
            body = await self._client.post("/events/exists", {"callIds": call_ids[i:i + EXISTS_PAGE]})
            out.extend(body["missing"])
        return out

    async def total(self, scope: str, scope_id: Optional[str], since_ms: int) -> float:
        body = await self._client.get("/ledger/total", {"scope": scope, "id": scope_id, "since": since_ms})
        return float(body["usd"])
