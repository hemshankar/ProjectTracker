"""The only Backend that knows Composio's API."""
from typing import Any, Mapping, Optional

from ..actions.composio_map import get_tool
from ..errors import ActionFailed, NotConnected
from . import composio_events
from .base import (CONNECTED, EXPIRED, NOT_CONNECTED, ActionResult, BackendEvent, Capabilities,
                   ConnectionInfo, ConnectSession, ProviderConfig)
from ..services.secret_store import SecretStore
from .composio_http import ComposioHttp

_V3 = "/api/v3"


class ComposioBackend:
    def __init__(self, http: ComposioHttp, secrets: SecretStore):
        self._http = http
        self._secrets = secrets
        self._auth_config_ids: dict = {}

    def capabilities(self) -> Capabilities:
        return Capabilities(named_actions=True, proxy=True, triggers=False)

    # --- connect -----------------------------------------------------------
    async def _auth_config_id(self, slug: str) -> str:
        if slug in self._auth_config_ids:
            return self._auth_config_ids[slug]
        found = await self._http.request("GET", f"{_V3}/auth_configs", params={"toolkit_slug": slug})
        items = found.get("items") or []
        if items:
            auth_id = items[0]["id"]
        else:
            created = await self._http.request("POST", f"{_V3}/auth_configs", json={
                "toolkit": {"slug": slug}, "auth_config": {"type": "use_composio_managed_auth"}})
            auth_id = (created.get("auth_config") or {}).get("id") or created.get("id")
            if not auth_id:
                raise ActionFailed(f"could not create Composio auth config for {slug}")
        self._auth_config_ids[slug] = auth_id
        return auth_id

    async def create_connect_session(self, user_id: str, provider: ProviderConfig, callback_url: str) -> ConnectSession:
        auth_id = await self._auth_config_id(provider.backend_slug)
        data = await self._http.request("POST", f"{_V3}/connected_accounts/link", json={
            "auth_config_id": auth_id, "user_id": user_id, "callback_url": callback_url})
        url = data.get("redirect_url")
        if not url:
            raise ActionFailed("Composio returned no connect link")
        return ConnectSession(url=url, backend_connection_id=data.get("connected_account_id"))

    async def _accounts(self, user_id: str, slug: str) -> list:
        data = await self._http.request("GET", f"{_V3}/connected_accounts", params={
            "user_ids": user_id, "toolkit_slugs": slug, "order_by": "updated_at"})
        return data.get("items") or []

    async def get_connection(self, user_id: str, provider: ProviderConfig) -> ConnectionInfo:
        accounts = await self._accounts(user_id, provider.backend_slug)
        for acct in accounts:
            if str(acct.get("status", "")).upper() == "ACTIVE":
                return ConnectionInfo(CONNECTED, acct.get("id"), None)
        for acct in accounts:
            if str(acct.get("status", "")).upper() in ("EXPIRED", "FAILED"):
                return ConnectionInfo(EXPIRED, acct.get("id"))
        return ConnectionInfo(NOT_CONNECTED)

    async def disconnect(self, user_id: str, provider: ProviderConfig) -> None:
        for acct in await self._accounts(user_id, provider.backend_slug):
            await self._http.request("DELETE", f"{_V3}/connected_accounts/{acct['id']}")

    # --- actions -----------------------------------------------------------
    async def _active_id(self, user_id: str, provider: ProviderConfig) -> str:
        info = await self.get_connection(user_id, provider)
        if info.status != CONNECTED or not info.backend_connection_id:
            raise NotConnected(provider.tool_type)
        return info.backend_connection_id

    async def execute_action(self, user_id: str, provider: ProviderConfig, action: str, args: Mapping[str, Any]) -> ActionResult:
        tool = get_tool(action)
        conn_id = await self._active_id(user_id, provider)
        data = await self._http.request("POST", f"{_V3}/tools/execute/{tool.slug}", json={
            "user_id": user_id, "connected_account_id": conn_id, "arguments": tool.translate(args)})
        if data.get("successful") is False:
            return ActionResult(ok=False, error=str(data.get("error") or "action failed")[:300])
        return ActionResult(ok=True, data=data.get("data"))

    async def proxy(self, user_id: str, provider: ProviderConfig, method: str, endpoint: str,
                    params: Optional[Mapping[str, Any]], body: Any) -> ActionResult:
        conn_id = await self._active_id(user_id, provider)
        payload = {"endpoint": endpoint, "method": method.upper(), "connected_account_id": conn_id,
                   "parameters": [{"in": "query", "name": k, "value": str(v)} for k, v in (params or {}).items()]}
        if body is not None:
            payload["body"] = body
        data = await self._http.request("POST", f"{_V3}/tools/execute/proxy", api_key=self._secrets.get("composio_proxy_api_key")
                                        or self._secrets.get("composio_api_key"), json=payload)
        return ActionResult(ok=True, data=data.get("data", data))

    # --- events ------------------------------------------------------------
    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> Optional[BackendEvent]:
        return composio_events.parse(headers, body, self._secrets.get("composio_webhook_secret"))
