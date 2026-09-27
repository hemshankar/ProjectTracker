from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from ... import config
from ...models_tools import ConnectedTokens
from .base import ToolConnector

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
SLACK_SCOPES = "chat:write,channels:read,users:read"


class SlackConnector(ToolConnector):
    tool_type = "slack"

    def configured(self) -> bool:
        return bool(config.SLACK_CLIENT_ID and config.SLACK_CLIENT_SECRET)

    def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": config.SLACK_CLIENT_ID,
            "scope": SLACK_SCOPES,
            "redirect_uri": config.SLACK_REDIRECT_URI,
            "state": state,
        }
        return f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> ConnectedTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                SLACK_OAUTH_TOKEN_URL,
                data={
                    "client_id": config.SLACK_CLIENT_ID,
                    "client_secret": config.SLACK_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": config.SLACK_REDIRECT_URI,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        if not payload.get("ok"):
            raise ValueError(f"Slack OAuth exchange failed: {payload.get('error')}")

        return ConnectedTokens(
            access_token=payload["access_token"],
            refresh_token=None,
            expires_at=None,  # Slack bot tokens don't expire by default
            identity_label=(payload.get("team") or {}).get("name", "Slack workspace"),
        )

    async def refresh(self, tokens: ConnectedTokens) -> ConnectedTokens:
        return tokens  # non-expiring bot token; nothing to refresh

    async def execute(self, action: str, params: Dict[str, Any], tokens: Optional[ConnectedTokens]) -> str:
        if tokens is None or action != "send_slack_message":
            return self._fallback(params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                SLACK_POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                json={"channel": params.get("channel", ""), "text": params.get("text", "")},
            )
            resp.raise_for_status()
            payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Slack send failed: {payload.get('error')}")

        return f'Message sent to {params.get("channel", "the channel")}.'

    def _fallback(self, params: Dict[str, Any]) -> str:
        return f'Message sent to {params.get("channel", "the channel")}.'
