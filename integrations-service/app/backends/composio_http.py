"""Thin Composio REST client. Maps transport failures to domain errors; no business logic."""
from typing import Any, Dict, Optional

import httpx

from ..errors import ActionFailed, BackendUnavailable, RateLimited
from ..services.secret_store import SecretStore


class ComposioHttp:
    def __init__(self, secrets: SecretStore, base_url: str = "https://backend.composio.dev",
                 transport: Optional[httpx.AsyncBaseTransport] = None, timeout: float = 30.0):
        self._secrets = secrets
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    async def request(self, method: str, path: str, *, api_key: Optional[str] = None,
                      params: Optional[Dict[str, Any]] = None, json: Any = None) -> Dict[str, Any]:
        key = api_key or self._secrets.get("composio_api_key")
        if not key:
            raise BackendUnavailable("Composio API key is not configured")
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout,
                                         transport=self._transport) as client:
                resp = await client.request(method, path, params=params, json=json, headers={"x-api-key": key})
        except httpx.HTTPError as exc:
            raise BackendUnavailable(f"Composio unreachable: {type(exc).__name__}") from exc
        if resp.status_code == 429:
            raise RateLimited("Composio rate limit hit")
        if resp.status_code >= 500:
            raise BackendUnavailable(f"Composio error {resp.status_code}")
        if resp.status_code >= 400:
            raise ActionFailed(f"Composio rejected request ({resp.status_code}): {_safe_message(resp)}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise ActionFailed("Composio returned invalid JSON") from exc


def _safe_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return str(err.get("message") or err)[:200]
    except (ValueError, AttributeError):
        return ""
