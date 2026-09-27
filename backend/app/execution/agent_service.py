"""The tool-use-aware agent loop for one task's automatic run.

Builds on `chat_service`'s Anthropic client, but — unlike the human-facing
chat, which just streams plain text — this declares tools and knows how to
suspend a task at a mutating tool call until a human approves or rejects it
(Phase 4's approval workflow), then resume the same conversation from
exactly that point.
"""
from typing import Any, List, Optional, Tuple

from ..chat_service import get_client
from ..database import boards_collection
from ..models import new_id
from ..models_settings import default_model_config
from ..services import budget_service, settings_service
from ..services.chats_service import text_message
from . import tools
from .conversation import build_task_system_prompt, to_anthropic_messages
from .enforcement import check_budget

MAX_TOOL_ROUNDS = 4


def _split_response(response: Any) -> Tuple[str, Optional[Any]]:
    text_parts: List[str] = []
    tool_use = None
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use" and tool_use is None:
            tool_use = block
    return "\n".join(p for p in text_parts if p), tool_use


def _action_request_message(task_id: str, spec: tools.ToolSpec, tool_use: Any, lead_text: str) -> dict:
    return {
        "id": new_id(),
        "role": "assistant",
        "type": "action_request",
        "text": lead_text,
        "payload": {
            "taskId": task_id,
            "description": tools.describe_action(spec, tool_use.input),
            "tool": tool_use.name,
            "params": tool_use.input,
            "toolUseId": tool_use.id,
            "status": "pending",
        },
    }


async def _ingest_live_input(board_id: str, chat: dict, anthropic_messages: List[dict]) -> None:
    """Picks up any human chat message sent mid-run through the normal chat
    endpoint, so the next model call actually sees it — not just whatever
    was there when this task started.
    """
    fresh = await boards_collection.find_one({"_id": board_id}, {"chats": 1})
    if not fresh:
        return
    fresh_chat = next((c for c in fresh.get("chats", []) if c["id"] == chat["id"]), None)
    if not fresh_chat:
        return
    known_ids = {m.get("id") for m in chat["messages"]}
    new_msgs = [
        m for m in fresh_chat["messages"]
        if m.get("id") and m.get("id") not in known_ids and m.get("role") == "user"
    ]
    if not new_msgs:
        return
    chat["messages"].extend(new_msgs)
    combined = "\n".join(m.get("text", "") for m in new_msgs if m.get("text"))
    if not combined:
        return
    if anthropic_messages and anthropic_messages[-1]["role"] == "user":
        content = anthropic_messages[-1]["content"]
        if isinstance(content, str):
            anthropic_messages[-1]["content"] = [
                {"type": "text", "text": content}, {"type": "text", "text": combined}
            ]
        else:
            content.append({"type": "text", "text": combined})
    else:
        anthropic_messages.append({"role": "user", "content": combined})


async def run_task_step(
    board_id: str, board: dict, task: dict, chat: dict, fallback_status: str = "done"
) -> str:
    """Advances `task`'s conversation until it finishes or proposes a new
    mutating action. Appends any new assistant/action-request entries to
    `chat["messages"]` in place; the caller persists and audits them.

    Safe to call both to start a task and to resume it after an
    approve/reject decision has just been recorded on the last
    `action_request` message — either way the model only ever sees a fully
    resolved history, never a dangling tool call.
    """
    client = get_client()
    if client is None:
        chat["messages"].append(
            text_message("assistant", "Agent isn't configured — missing ANTHROPIC_API_KEY.")
        )
        return fallback_status

    system_prompt = build_task_system_prompt(board, task)
    anthropic_messages = to_anthropic_messages(chat["messages"])
    # The Anthropic API requires the conversation to end on a user turn. An
    # empty history (first task ever) and a shared board chat that already
    # ends on an assistant turn (this task starting right after a prior one
    # finished, in the same chat) both need the same nudge appended.
    if not anthropic_messages or anthropic_messages[-1]["role"] != "user":
        anthropic_messages.append({"role": "user", "content": "Make progress on this task."})

    agent_id = board.get("agentId")
    run_id = task.get("currentRunId")
    model_config = (
        (await settings_service.get_settings(agent_id))["modelConfig"] if agent_id else default_model_config()
    )

    for _ in range(MAX_TOOL_ROUNDS):
        await _ingest_live_input(board_id, chat, anthropic_messages)
        await check_budget(agent_id, board_id)
        # Streamed rather than a plain `create()` call: a maxTokens this large
        # is enough to risk an HTTP timeout on a buffered response.
        async with client.messages.stream(
            model=model_config["model"],
            max_tokens=model_config["maxTokens"],
            system=system_prompt,
            messages=anthropic_messages,
            tools=tools.anthropic_tool_defs(model_config["model"], model_config["webSearchEnabled"]),
        ) as stream:
            response = await stream.get_final_message()
        usage = getattr(response, "usage", None)
        if usage is not None:
            usd = budget_service.usd_for_usage(usage.input_tokens, usage.output_tokens)
            await budget_service.record_spend(agent_id, board_id, task["id"], run_id, usd)
        text, tool_use = _split_response(response)

        if tool_use is None:
            chat["messages"].append(
                text_message("assistant", text or "Task completed with no additional output.")
            )
            return fallback_status

        spec = tools.TOOLS.get(tool_use.name)
        if spec is not None and spec.mutating:
            chat["messages"].append(_action_request_message(task["id"], spec, tool_use, text))
            return "awaiting_approval"

        result_text = (
            await tools.execute_tool(spec, tool_use.input, None) if spec else f"Unknown tool '{tool_use.name}'."
        )
        # Only text/tool_use round-trip cleanly as request input; extended-thinking
        # blocks the model may have emitted alongside them do not. And since we
        # only ever execute the one `tool_use` picked above, any other tool_use
        # blocks from a parallel-tool-call turn must be dropped here too — each
        # kept tool_use needs its matching tool_result right after, and we only
        # produce one.
        kept_blocks = [b.model_dump() for b in response.content if b.type == "text" or b is tool_use]
        anthropic_messages.append({"role": "assistant", "content": kept_blocks})
        anthropic_messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": result_text}],
        })

    chat["messages"].append(
        text_message("assistant", "I wasn't able to finish this within the allotted tool-call rounds.")
    )
    return "failed"
