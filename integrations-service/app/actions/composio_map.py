"""Named action -> Composio tool slug + argument translation.

VERIFY every slug and argument name against your Composio dashboard's tool list
(Toolkits -> <toolkit> -> Tools). They are the only place Composio naming leaks.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping

from .. import config
from ..errors import UnknownAction


@dataclass(frozen=True)
class ComposioTool:
    slug: str
    translate: Callable[[Mapping[str, Any]], Dict[str, Any]]


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _gmail_send(a: Mapping[str, Any]) -> Dict[str, Any]:
    return {"recipient_email": a.get("to"), "subject": a.get("subject", ""), "body": a.get("body", "")}


def _gmail_list(a: Mapping[str, Any]) -> Dict[str, Any]:
    return _drop_none({"query": a.get("query"), "max_results": a.get("maxResults", 10)})


def _cal_create(a: Mapping[str, Any]) -> Dict[str, Any]:
    return _drop_none({
        "summary": a.get("title"),
        "start_datetime": a.get("start"),
        "end_datetime": a.get("end"),
        "attendees": a.get("attendees"),
        # Naive datetimes (no offset) are read in this zone; without it Google treats them as UTC.
        "timezone": a.get("timezone") or config.DEFAULT_TIMEZONE,
    })


def _cal_list(a: Mapping[str, Any]) -> Dict[str, Any]:
    return _drop_none({"calendarId": "primary", "timeMin": a.get("timeMin"), "timeMax": a.get("timeMax")})


def _slack_post(a: Mapping[str, Any]) -> Dict[str, Any]:
    return {"channel": str(a.get("channel") or "").lstrip("#"), "text": a.get("text", "")}


COMPOSIO_TOOLS: Dict[str, ComposioTool] = {
    "gmail.send_email": ComposioTool("GMAIL_SEND_EMAIL", _gmail_send),
    "gmail.list_messages": ComposioTool("GMAIL_FETCH_EMAILS", _gmail_list),
    "calendar.create_event": ComposioTool("GOOGLECALENDAR_CREATE_EVENT", _cal_create),
    "calendar.list_events": ComposioTool("GOOGLECALENDAR_EVENTS_LIST", _cal_list),
    "slack.post_message": ComposioTool("SLACK_SEND_MESSAGE", _slack_post),
    "slack.list_channels": ComposioTool("SLACK_LIST_ALL_CHANNELS", lambda a: {}),
}


def get_tool(action: str) -> ComposioTool:
    tool = COMPOSIO_TOOLS.get(action)
    if not tool:
        raise UnknownAction(f"no Composio mapping for {action}")
    return tool
