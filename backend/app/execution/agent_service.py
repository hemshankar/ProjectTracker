"""The tool-use-aware agent loop for one task's automatic run.

Builds on `chat_service`'s Anthropic client, but — unlike the human-facing
chat, which just streams plain text — this declares tools and knows how to
suspend a task at a mutating tool call until a human approves or rejects it
(Phase 4's approval workflow), then resume the same conversation from
exactly that point. Phase 6 adds two more ways a task can suspend: a
sub-agent it spun up (`delegate_subtask`) proposing a mutating action, and a
peer Agent it handed work to (`delegate_to_agent`) not having replied yet.
`mark_manual` is a further one: the agent has already done everything it
can and the rest depends on someone outside this system entirely, so the
task waits on a human to say what that person did, rather than on any
in-system reply.
"""
import time
from typing import Any, List, Tuple

from .. import config
from ..chat_service import get_client
from ..database import agents_collection, boards_collection
from ..models_settings import default_model_config
from ..services import settings_service
from ..services.chats_service import text_message
from . import subagent, tools, tracing
from .conversation import assistant_turn, build_task_system_prompt, split_response, to_anthropic_messages, tool_result_turn
from .enforcement import check_budget
from .events import events
from .pending_messages import (
    action_request_message as _action_request_message,
    clarification_request_message as _clarification_request_message,
    delegation_request_message as _delegation_request_message,
    manual_hold_message as _manual_hold_message,
)

DEFAULT_MAX_TOOL_ROUNDS = config.TASK_MAX_TOOL_ROUNDS


async def _ingest_live_input(board_id: str, chat_id: str, seen_ids: set, anthropic_messages: List[dict]) -> None:
    """Picks up any human chat message sent mid-run through the normal chat
    endpoint, so the next model call actually sees it — not just whatever
    was there when this task started. Only feeds `anthropic_messages` (the
    model-facing view); `chat["messages"]` is left untouched so the caller
    can tell exactly which messages this run newly authored (see
    `execution.loop`).
    """
    fresh = await boards_collection.find_one({"_id": board_id}, {"chats": 1})
    if not fresh:
        return
    fresh_chat = next((c for c in fresh.get("chats", []) if c["id"] == chat_id), None)
    if not fresh_chat:
        return
    new_msgs = [
        m for m in fresh_chat["messages"]
        if m.get("id") and m.get("id") not in seen_ids and m.get("role") == "user"
    ]
    if not new_msgs:
        return
    seen_ids.update(m["id"] for m in new_msgs)
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


async def _handle_delegate_to_agent(board: dict, task: dict, chat: dict, tool_use: Any, lead_text: str) -> Tuple[str, str]:
    """Returns `("suspended", "")` when the delegation was accepted (the
    caller should return `awaiting_reply` immediately), or `("refused",
    detail)` when there's no granted link — fed back to the model as an
    error tool_result so it can tell the user, rather than retrying blindly.
    """
    from . import delegation  # local import: delegation imports this module

    from_agent_id = board.get("agentId")
    target_agent_id = tool_use.input.get("targetAgentId", "")
    request_text = tool_use.input.get("request", "")

    from_agent = await agents_collection.find_one({"_id": from_agent_id}) if from_agent_id else None
    target_agent = await agents_collection.find_one({"_id": target_agent_id})
    from_agent_name = (from_agent or {}).get("name") or "another Agent"
    target_agent_name = (target_agent or {}).get("name") or target_agent_id

    try:
        await delegation.request_delegation(
            from_agent_id, from_agent_name, target_agent_id,
            board["_id"], task["id"], task.get("currentRunId"), request_text,
        )
    except delegation.DelegationRefused as exc:
        return "refused", str(exc)

    chat["messages"].append(
        _delegation_request_message(task["id"], target_agent_id, target_agent_name, request_text, lead_text)
    )
    return "suspended", ""


async def run_task_step(
    board_id: str, board: dict, task: dict, chat: dict, fallback_status: str = "done"
) -> str:
    """Advances `task`'s conversation until it finishes or suspends — on a
    proposed mutating action (this task's own, or a sub-agent's), or on a
    peer-Agent delegation awaiting reply. Appends any new assistant/
    action-request/delegation-request entries to `chat["messages"]` in
    place; the caller persists and audits them.

    Safe to call to start a task, to resume it after an approve/reject
    decision on the last `action_request`, or to resume it after a
    delegated task's reply — every case rebuilds the model-facing history
    fresh from `chat["messages"]`, so the model only ever sees a fully
    resolved history, never a dangling tool call.
    """
    client = get_client()
    if client is None:
        chat["messages"].append(
            text_message("assistant", "Agent isn't configured — missing ANTHROPIC_API_KEY.")
        )
        return fallback_status

    # Each task has its own dedicated chat (`chats_service.get_or_create_task_chat`),
    # so an empty history really does mean this is the task's first turn ever —
    # not just the first turn of this particular call.
    system_prompt = await build_task_system_prompt(board, task, is_first_turn=not chat["messages"])
    anthropic_messages = to_anthropic_messages(chat["messages"])
    # The Anthropic API requires the conversation to end on a user turn. An
    # empty history (first task ever) and a shared board chat that already
    # ends on an assistant turn (this task starting right after a prior one
    # finished, in the same chat) both need the same nudge appended.
    if not anthropic_messages or anthropic_messages[-1]["role"] != "user":
        anthropic_messages.append({"role": "user", "content": "Make progress on this task."})

    agent_id = board.get("agentId")
    run_id = task.get("currentRunId")
    agent_settings = await settings_service.get_settings(agent_id) if agent_id else None
    model_config = agent_settings["modelConfig"] if agent_settings else default_model_config()
    max_tool_rounds = agent_settings["execution"]["maxToolRounds"] if agent_settings else DEFAULT_MAX_TOOL_ROUNDS
    seen_ids = {m.get("id") for m in chat["messages"]}

    for _ in range(max_tool_rounds):
        await _ingest_live_input(board_id, chat["id"], seen_ids, anthropic_messages)
        await check_budget(agent_id, board_id)
        call_started = time.monotonic()
        # Streamed rather than a plain `create()` call: a maxTokens this large
        # is enough to risk an HTTP timeout on a buffered response. The
        # text_stream is also re-published live (see `events`) so an open
        # Task Chat tab can type the reply out token-by-token instead of
        # only seeing it once this round finishes and persists.
        await events.publish(board_id, {"taskId": task["id"], "type": "chat_stream_start"})
        async with client.messages.stream(
            model=model_config["model"],
            max_tokens=model_config["maxTokens"],
            system=system_prompt,
            messages=anthropic_messages,
            tools=tools.anthropic_tool_defs(model_config["model"], model_config["webSearchEnabled"]),
        ) as stream:
            async for delta in stream.text_stream:
                await events.publish(board_id, {"taskId": task["id"], "type": "chat_delta", "delta": delta})
            response = await stream.get_final_message()
        await events.publish(board_id, {"taskId": task["id"], "type": "chat_stream_end"})
        latency_ms = (time.monotonic() - call_started) * 1000
        text, tool_use = split_response(response)

        async def _record(tool_call: Any) -> None:
            await tracing.record_call(
                agent_id=agent_id, board_id=board_id, task_id=task["id"], run_id=run_id,
                response=response, system_prompt=system_prompt, request_messages=anthropic_messages,
                tool_call=tool_call, latency_ms=latency_ms,
            )

        if tool_use is None:
            await _record(None)
            chat["messages"].append(
                text_message("assistant", text or "Task completed with no additional output.")
            )
            return fallback_status

        if tool_use.name == "ask_user":
            question = tool_use.input.get("question", "")
            await _record({"name": "ask_user", "params": tool_use.input, "status": "awaiting_reply"})
            chat["messages"].append(
                _clarification_request_message(task["id"], question, tool_use.id, text)
            )
            return "awaiting_clarification"

        if tool_use.name == "mark_manual":
            note = tool_use.input.get("note", "")
            await _record({"name": "mark_manual", "params": tool_use.input, "status": "manual"})
            chat["messages"].append(
                _manual_hold_message(task["id"], note, tool_use.id, text)
            )
            return "manual"

        if tool_use.name == "delegate_to_agent":
            outcome, detail = await _handle_delegate_to_agent(board, task, chat, tool_use, text)
            await _record({
                "name": "delegate_to_agent", "params": tool_use.input,
                "result": detail if outcome == "refused" else None, "status": outcome,
            })
            if outcome == "suspended":
                return "awaiting_reply"
            anthropic_messages.append(assistant_turn(response, tool_use))
            anthropic_messages.append(tool_result_turn(tool_use.id, detail, is_error=True))
            continue

        if tool_use.name == "delegate_subtask":
            result_text, pending_action = await subagent.run_subtask(
                board, task, run_id, model_config,
                tool_use.input.get("instructions", ""), tool_use.input.get("allowedTools"),
            )
            await _record({
                "name": "delegate_subtask", "params": tool_use.input,
                "result": result_text if pending_action is None else None,
                "status": "awaiting_approval" if pending_action is not None else "done",
            })
            if pending_action is not None:
                chat["messages"].append(_action_request_message(
                    task["id"], pending_action["description"], pending_action["tool"],
                    pending_action["params"], pending_action["toolUseId"], text,
                ))
                return "awaiting_approval"
            anthropic_messages.append(assistant_turn(response, tool_use))
            anthropic_messages.append(tool_result_turn(tool_use.id, result_text))
            continue

        spec = tools.TOOLS.get(tool_use.name)
        if spec is not None and spec.mutating:
            await _record({"name": tool_use.name, "params": tool_use.input, "status": "awaiting_approval"})
            chat["messages"].append(_action_request_message(
                task["id"], tools.describe_action(spec, tool_use.input), tool_use.name,
                tool_use.input, tool_use.id, text,
            ))
            return "awaiting_approval"

        result_text = (
            await tools.execute_tool(spec, tool_use.input, None) if spec else f"Unknown tool '{tool_use.name}'."
        )
        await _record({"name": tool_use.name, "params": tool_use.input, "result": result_text, "status": "done"})
        anthropic_messages.append(assistant_turn(response, tool_use))
        anthropic_messages.append(tool_result_turn(tool_use.id, result_text))

    chat["messages"].append(
        text_message("assistant", "I wasn't able to finish this within the allotted tool-call rounds.")
    )
    return "failed"
