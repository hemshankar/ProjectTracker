"""Named actions callers use. Backend-agnostic; adding one is a catalog entry + a map entry."""
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from ..errors import UnknownAction


@dataclass(frozen=True)
class ActionDef:
    name: str
    tool_type: str
    mutating: bool
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


def _schema(props: Dict[str, Any], required: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """JSON Schema for an action's arguments. No agent id field: callers can never name another agent."""
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


_STR = {"type": "string"}
_ACTIONS: Tuple[ActionDef, ...] = (
    ActionDef("gmail.send_email", "gmail", True, "Send an email",
              _schema({"to": _STR, "subject": _STR, "body": _STR}, ("to", "subject", "body"))),
    ActionDef("gmail.list_messages", "gmail", False, "List recent Gmail messages, optionally filtered by a Gmail search query",
              _schema({"query": {"type": "string", "description": "Gmail search query"},
                       "maxResults": {"type": "integer", "minimum": 1, "maximum": 50}})),
    ActionDef("calendar.create_event", "calendar", True, "Create a calendar event",
              _schema({"title": _STR, "start": _STR, "end": _STR, "attendees": {"type": "array", "items": _STR}},
                      ("title", "start"))),
    ActionDef("calendar.list_events", "calendar", False, "List calendar events in a time range",
              _schema({"timeMin": {"type": "string", "description": "RFC3339 start"},
                       "timeMax": {"type": "string", "description": "RFC3339 end"}})),
    ActionDef("slack.post_message", "slack", True, "Post a Slack message",
              _schema({"channel": _STR, "text": _STR}, ("channel", "text"))),
    ActionDef("slack.list_channels", "slack", False, "List Slack channels", _schema({})),
)
CATALOG: Dict[str, ActionDef] = {a.name: a for a in _ACTIONS}


def get_action(name: str) -> ActionDef:
    action = CATALOG.get(name)
    if not action:
        raise UnknownAction(name)
    return action
