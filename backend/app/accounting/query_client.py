"""Core -> accounting-service reads. 3s timeout, no retries; failures become AccountingUnavailable."""
from typing import AsyncIterator, Dict, List, Optional, Protocol, Tuple

import httpx

from .. import config


class AccountingUnavailable(Exception):
    """The accounting service could not answer. Never propagates into runs or board loading."""


class UsageQueryClient(Protocol):
    async def get(self, path: str, params: dict) -> object: ...
    async def post(self, path: str, body: dict) -> object: ...
    async def stream(self, path: str, params: dict) -> Tuple[Dict[str, str], AsyncIterator[bytes]]: ...
    async def ping(self) -> bool: ...


class HttpUsageQueryClient:
    def __init__(self, base_url: Optional[str] = None, service_key: Optional[str] = None, timeout: float = 3):
        self._base_url = (base_url or config.ACCOUNTING_SERVICE_URL).rstrip("/")
        self._key = service_key if service_key is not None else config.ACCOUNTING_SERVICE_KEY
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base_url}/internal{path}"

    async def get(self, path: str, params: dict) -> object:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(self._url(path), params=_clean(params), headers={"X-Internal-Key": self._key})
        except httpx.HTTPError as exc:
            raise AccountingUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            raise AccountingUnavailable(f"accounting service returned {resp.status_code}")
        return resp.json()

    async def post(self, path: str, body: dict) -> object:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url(path), json=body, headers={"X-Internal-Key": self._key})
        except httpx.HTTPError as exc:
            raise AccountingUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            raise AccountingUnavailable(f"accounting service returned {resp.status_code}")
        return resp.json()

    async def stream(self, path: str, params: dict) -> Tuple[Dict[str, str], AsyncIterator[bytes]]:
        # No overall read timeout: exports can legitimately run long.
        client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, read=None))
        try:
            req = client.build_request("GET", self._url(path), params=_clean(params),
                                       headers={"X-Internal-Key": self._key})
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise AccountingUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            await resp.aclose()
            await client.aclose()
            raise AccountingUnavailable(f"accounting service returned {resp.status_code}")

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return dict(resp.headers), body()

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return (await client.get(f"{self._base_url}/health")).status_code == 200
        except httpx.HTTPError:
            return False


def _clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}
