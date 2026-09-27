from typing import AsyncGenerator, List, Optional

import anthropic

from . import config
from .models_settings import default_model_config
from .services import settings_service

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None


def get_client() -> Optional[anthropic.AsyncAnthropic]:
    return _client


def _pending_action_descriptions(board: dict) -> List[str]:
    descriptions = []
    for chat in board.get("chats", []):
        for m in chat.get("messages", []):
            if m.get("type") == "action_request" and m.get("payload", {}).get("status") == "pending":
                descriptions.append(m["payload"].get("description") or m["payload"].get("tool", "an action"))
    return descriptions


def build_board_context(board: dict, tools_available: bool = True) -> str:
    lines = [
        "You are a helpful assistant embedded in a project board app called Scatterboard. "
        "Only discuss the board described below.",
        f"Board title: {board.get('title') or 'Untitled board'}",
    ]
    if board.get("description"):
        lines.append(f"Board description: {board['description']}")

    tasks = board.get("tasks", [])
    open_tasks = [t for t in tasks if not t.get("done")]
    done_tasks = [t for t in tasks if t.get("done")]

    lines.append(f"Open tasks ({len(open_tasks)}):")
    if open_tasks:
        lines.extend(f"- {t.get('text', '')}" for t in open_tasks)
    else:
        lines.append("(none)")

    if done_tasks:
        lines.append(f"Completed tasks ({len(done_tasks)}):")
        lines.extend(f"- {t.get('text', '')}" for t in done_tasks)

    pending = _pending_action_descriptions(board)
    if pending:
        lines.append(
            "Pending action(s) already proposed, awaiting human approval (NOT yet executed):"
        )
        lines.extend(f"- {p}" for p in pending)
        lines.append(
            "None of these have happened yet, and you cannot approve or execute them yourself "
            "in this conversation. If the human says to 'proceed', 'send it', or similar, tell "
            "them to click Approve on that action's card — do not say it has been sent, created, "
            "or completed."
        )

    if tools_available:
        lines.append(
            "Answer questions, help prioritize, and help draft or think through this board's work. "
            "When working a task, you can call tools to make progress: read-only tools run "
            "immediately, and any mutating action (sending an email, creating or editing a calendar "
            "event, or anything else with an effect outside this app) is proposed to the user for "
            "approval before it runs."
        )
    else:
        lines.append(
            "This conversation has no tool access of its own — you can only discuss, draft, and "
            "advise here, never actually send an email, create a calendar event, or post to Slack. "
            "Real actions only happen through this board's task engine (a task's automatic run, or "
            "an approval card), never as a side effect of this chat. Never claim to have done "
            "something you cannot actually do here."
        )
    return "\n".join(lines)


async def stream_reply(board: dict, history: List[dict]) -> AsyncGenerator[str, None]:
    if _client is None:
        yield "Chat isn't configured — the server is missing an ANTHROPIC_API_KEY."
        return

    system_prompt = build_board_context(board, tools_available=False)
    messages = [
        {"role": m["role"], "content": m["text"]}
        for m in history
        if m.get("type", "text") == "text" and m.get("text")
    ]

    agent_id = board.get("agentId")
    model_config = (
        (await settings_service.get_settings(agent_id))["modelConfig"] if agent_id else default_model_config()
    )

    try:
        async with _client.messages.stream(
            model=model_config["model"],
            max_tokens=model_config["maxTokens"],
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except anthropic.APIStatusError as e:
        if e.status_code == 429:
            yield "You're sending messages a bit fast — please wait a moment and try again."
        else:
            yield f"Something went wrong reaching the assistant ({e.status_code})."
    except Exception:
        yield "Something went wrong reaching the assistant."
