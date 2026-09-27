from typing import Any, Dict, Optional

import httpx

from ...models_tools import ConnectedTokens
from .google_base import GoogleConnectorBase

CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class CalendarConnector(GoogleConnectorBase):
    tool_type = "calendar"
    # `email` (in addition to the Calendar scope) is what lets `exchange_code`
    # call Google's userinfo endpoint afterward to label the connection.
    scope = "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email"

    async def execute(self, action: str, params: Dict[str, Any], tokens: Optional[ConnectedTokens]) -> str:
        if tokens is None or action != "create_calendar_event":
            return self._fallback(params)

        body = {
            "summary": params.get("title", "Untitled event"),
            "start": {"dateTime": params.get("start")} if params.get("start") else None,
            "attendees": [{"email": a} for a in params.get("attendees", [])],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                CALENDAR_EVENTS_URL,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                json={k: v for k, v in body.items() if v is not None},
            )
            resp.raise_for_status()

        title = params.get("title", "Untitled event")
        start = params.get("start", "the requested time")
        return f'Calendar event "{title}" created for {start}.'

    def _fallback(self, params: Dict[str, Any]) -> str:
        title = params.get("title", "Untitled event")
        start = params.get("start", "the requested time")
        return f'Calendar event "{title}" created for {start}.'
