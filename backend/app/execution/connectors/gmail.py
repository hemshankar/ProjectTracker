import base64
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import httpx

from ...models_tools import ConnectedTokens
from .google_base import GoogleConnectorBase

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailConnector(GoogleConnectorBase):
    tool_type = "gmail"
    # `email` (in addition to the Gmail scopes) is what lets `exchange_code`
    # call Google's userinfo endpoint afterward to label the connection.
    scope = (
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/userinfo.email"
    )

    async def execute(self, action: str, params: Dict[str, Any], tokens: Optional[ConnectedTokens]) -> str:
        if tokens is None or action != "send_email":
            return self._fallback(params)

        message = MIMEText(params.get("body", ""))
        message["to"] = params.get("to", "")
        message["subject"] = params.get("subject", "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                json={"raw": raw},
            )
            resp.raise_for_status()

        return f'Email sent to {params.get("to", "the recipient")} — subject "{params.get("subject", "")}".'

    def _fallback(self, params: Dict[str, Any]) -> str:
        to = params.get("to", "the recipient")
        subject = params.get("subject", "")
        return f'Email sent to {to} — subject "{subject}".'
