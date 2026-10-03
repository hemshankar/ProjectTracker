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

from .. import integrations_client
from ..integrations_client import IntegrationsClient, IntegrationsError


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
    "delegate_subtask": ToolSpec(
        name="delegate_subtask",
        description=(
            "Spin up a scoped sub-agent, with a restricted set of tools, to work on one specific "
            "piece of this task. Use this to decompose complex work rather than doing everything "
            "yourself in one pass. The sub-agent has no budget or approval flow of its own — a "
            "mutating action it proposes still surfaces as a normal approval card on this task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "instructions": {"type": "string", "description": "What the sub-agent should accomplish"},
                "allowedTools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names the sub-agent may use; omit to allow all non-orchestration tools",
                },
            },
            "required": ["instructions"],
        },
        mutating=False,
        simulate=lambda p: "Sub-agent dispatched.",
    ),
    "delegate_to_agent": ToolSpec(
        name="delegate_to_agent",
        description=(
            "Hand part of this task to a different Agent this one has an explicit delegation link "
            "to. Only works if an Agent Admin already granted that link — otherwise it's refused. "
            "The delegated work spends the target Agent's own budget and tools, never this one's, "
            "and this task waits for its reply."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "targetAgentId": {"type": "string", "description": "The Agent id to delegate to"},
                "request": {"type": "string", "description": "What you want the target Agent to do"},
            },
            "required": ["targetAgentId", "request"],
        },
        mutating=False,
        simulate=lambda p: "Delegated.",
    ),
    "ask_user": ToolSpec(
        name="ask_user",
        description=(
            "Ask the user a clarifying question when this task's short text isn't enough to act on "
            "correctly, or when you get stuck mid-task and need more information. This pauses the "
            "task until they reply in this task's chat — use it instead of guessing."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user"},
            },
            "required": ["question"],
        },
        mutating=False,
        simulate=lambda p: "Question asked.",
    ),
    "mark_manual": ToolSpec(
        name="mark_manual",
        description=(
            "Mark this task as needing manual follow-up when you've already done everything you can "
            "and what happens next depends on someone outside this system — e.g. you sent a reminder "
            "email and the task can't move forward until that person replies or acts. This pauses the "
            "task until a human resolves it with what happened; use it instead of leaving the task "
            "hanging or guessing at an outcome that hasn't happened yet."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "What you're waiting on and from whom, e.g. 'Sent a reminder to priya@x.com about the signed contract — waiting on her reply.'",
                },
            },
            "required": ["note"],
        },
        mutating=False,
        simulate=lambda p: "Marked for manual follow-up.",
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


class ToolExecutionError(Exception):
    """The gateway could not run the action (rate limited, outage, provider error)."""


# One table maps a model-facing tool to a gateway action; a new tool type is an entry here.
TOOL_TO_ACTION: Dict[str, str] = {
    "send_email": "gmail.send_email",
    "create_calendar_event": "calendar.create_event",
    "send_slack_message": "slack.post_message",
}


async def execute_tool(
    spec: ToolSpec, params: Dict[str, Any], agent_id: Optional[str], client: Optional[IntegrationsClient] = None
) -> str:
    """Runs the action through the integrations gateway. Falls back to the
    canned simulated result for internal tools, calls with no Agent, tools
    with no gateway action, and Agents that haven't connected the tool."""
    action = TOOL_TO_ACTION.get(spec.name)
    if spec.tool_type is None or agent_id is None or action is None:
        return spec.simulate(params)
    client = client or integrations_client.get_integrations_client()
    try:
        result = await client.execute(agent_id, spec.tool_type, action, params)
    except IntegrationsError as exc:
        if exc.code == "not_connected":
            return spec.simulate(params)
        raise ToolExecutionError(exc.message) from exc
    if not result.ok:
        raise ToolExecutionError(result.error or "The action failed")
    return spec.simulate(params)
