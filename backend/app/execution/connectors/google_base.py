"""Shared Google OAuth mechanics for the Gmail and Calendar connectors.

Both reuse the Phase 1 Google OAuth app (GOOGLE_CLIENT_ID/SECRET) but request
different scopes and hit a separate, fixed callback URL from the login flow
so tool-connection consent is independent of user sign-in.
"""
from typing import ClassVar
from urllib.parse import urlencode

import httpx

from ... import config
from ...models import now_ms
from ...models_tools import ConnectedTokens
from .base import ToolConnector

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleConnectorBase(ToolConnector):
    scope: ClassVar[str] = ""

    def configured(self) -> bool:
        return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)

    def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": config.GOOGLE_CLIENT_ID,
            "redirect_uri": config.GOOGLE_TOOLS_REDIRECT_URI,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> ConnectedTokens:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": config.GOOGLE_TOOLS_REDIRECT_URI,
                },
            )
            token_resp.raise_for_status()
            payload = token_resp.json()

            # Best-effort only: a missing/denied userinfo scope shouldn't
            # fail the whole connection, just leave it unlabeled.
            email = ""
            try:
                userinfo_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {payload['access_token']}"},
                )
                userinfo_resp.raise_for_status()
                email = userinfo_resp.json().get("email", "")
            except httpx.HTTPStatusError:
                pass

        return ConnectedTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=now_ms() + int(payload.get("expires_in", 3600)) * 1000,
            identity_label=email,
        )

    async def refresh(self, tokens: ConnectedTokens) -> ConnectedTokens:
        if not tokens.refresh_token:
            return tokens
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                    "refresh_token": tokens.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        return ConnectedTokens(
            access_token=payload["access_token"],
            refresh_token=tokens.refresh_token,
            expires_at=now_ms() + int(payload.get("expires_in", 3600)) * 1000,
            identity_label=tokens.identity_label,
        )
