"""Core -> accounting-service delivery. Call sites never depend on this directly (see UsageRecorder, Phase 3+)."""
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

import httpx

from .. import config

SCHEMA_VERSION = 1


class SinkError(Exception):
    """Delivery failed. `retryable` is True for 5xx/connection errors, False for 4xx."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class SinkResult:
    accepted: int = 0
    duplicates: int = 0
    rejected: List[dict] = field(default_factory=list)


class UsageSink(Protocol):
    """Narrow interface: deliver one batch of usage events."""

    async def send(self, events: List[dict]) -> SinkResult: ...


class HttpUsageClient:
    def __init__(self, base_url: Optional[str] = None, service_key: Optional[str] = None, timeout: float = 30):
        self._base_url = (base_url or config.ACCOUNTING_SERVICE_URL).rstrip("/")
        self._service_key = service_key if service_key is not None else config.ACCOUNTING_SERVICE_KEY
        self._timeout = timeout

    async def send(self, events: List[dict]) -> SinkResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/events",
                    headers={"X-Internal-Key": self._service_key},
                    json={"schemaVersion": SCHEMA_VERSION, "events": events},
                )
        except httpx.HTTPError as exc:
            raise SinkError("Accounting service is unreachable") from exc
        if resp.status_code >= 500:
            raise SinkError(f"Accounting service error ({resp.status_code})")
        if resp.status_code >= 400:
            raise SinkError(f"Accounting service rejected the request ({resp.status_code})", retryable=False)
        body = resp.json()
        return SinkResult(body.get("accepted", 0), body.get("duplicates", 0), body.get("rejected", []))
