"""The agent's tool catalogue.

Each mutating tool declares its `tool_type` (which connector and budget/rate
limit bucket it belongs to) and how to derive a resource lock key from its
params. Real execution goes through `execute_tool`, which uses the Agent's
connected `ToolConnector` when available and falls back to a simulated
result otherwise — so the approval workflow (Phase 4) and this phase's
enforcement can both be exercised without live credentials.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..models_tools import ConnectedTokens
from .connectors import get_connector


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    mutating: bool
    simulate: Callable[[Dict[str, Any]], str]
    tool_type: Optional[str] = None  # None for internal, non-connector tools
    resource_key: Optional[Callable[[Dict[str, Any]], str]] = None


def _send_email(params: Dict[str, Any]) -> str:
    to = params.get("to", "the recipient")
    subject = params.get("subject", "")
    return f'Email sent to {to} — subject "{subject}".'


def _create_calendar_event(params: Dict[str, Any]) -> str:
    title = params.get("title", "Untitled event")
    start = params.get("start", "the requested time")
    return f'Calendar event "{title}" created for {start}.'


def _send_slack_message(params: Dict[str, Any]) -> str:
    return f'Message sent to {params.get("channel", "the channel")}.'


def _search_notes(params: Dict[str, Any]) -> str:
    query = params.get("query", "")
    return f'Searched existing notes for "{query}" — nothing relevant on file yet.'


TOOLS: Dict[str, ToolSpec] = {
    "send_email": ToolSpec(
        name="send_email",
        description="Send an email on the user's behalf.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        mutating=True,
        simulate=_send_email,
        tool_type="gmail",
        resource_key=lambda p: f"gmail:{p.get('to', '')}",
    ),
    "create_calendar_event": ToolSpec(
        name="create_calendar_event",
        description="Create a calendar event.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "Start time, plain language or ISO 8601"},
                "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "start"],
        },
        mutating=True,
        simulate=_create_calendar_event,
        tool_type="calendar",
        resource_key=lambda p: f"calendar:{p.get('title', '')}|{p.get('start', '')}",
    ),
    "send_slack_message": ToolSpec(
        name="send_slack_message",
        description="Post a message to a Slack channel.",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name, e.g. #general"},
                "text": {"type": "string"},
            },
            "required": ["channel", "text"],
        },
        mutating=True,
        simulate=_send_slack_message,
        tool_type="slack",
        resource_key=lambda p: f"slack:{p.get('channel', '')}",
    ),
    "search_notes": ToolSpec(
        name="search_notes",
        description="Search this board's existing notes and history. Read-only.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        mutating=False,
        simulate=_search_notes,
    ),
}


# Dynamic-filtering web search needs Opus 5/4.8/4.7/4.6 or Sonnet 5/4.6; other
# models fall back to the older, basic variant.
_WEB_SEARCH_DYNAMIC_MODELS = {"claude-opus-5", "claude-sonnet-5"}


def _web_search_tool_def(model: str) -> dict:
    tool_type = "web_search_20260209" if model in _WEB_SEARCH_DYNAMIC_MODELS else "web_search_20250305"
    return {"type": tool_type, "name": "web_search"}


def anthropic_tool_defs(model: str, web_search_enabled: bool = False) -> List[dict]:
    defs = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS.values()
    ]
    if web_search_enabled:
        defs.append(_web_search_tool_def(model))
    return defs


def describe_action(spec: ToolSpec, params: Dict[str, Any]) -> str:
    if spec.name == "send_email":
        return f'Send an email to {params.get("to", "(unknown recipient)")} — subject "{params.get("subject", "")}"'
    if spec.name == "create_calendar_event":
        return f'Create calendar event "{params.get("title", "Untitled event")}" for {params.get("start", "(unspecified time)")}'
    if spec.name == "send_slack_message":
        return f'Post to {params.get("channel", "(unknown channel)")}: "{params.get("text", "")}"'
    return f"Run {spec.name} with {params}"


async def execute_tool(spec: ToolSpec, params: Dict[str, Any], tokens: Optional[ConnectedTokens]) -> str:
    """Runs the real connector when the Agent has a connection for this
    tool's type; otherwise falls back to the canned simulated result."""
    if spec.tool_type is None:
        return spec.simulate(params)
    connector = get_connector(spec.tool_type)
    return await connector.execute(spec.name, params, tokens)
