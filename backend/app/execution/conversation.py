"""Shapes one task's chat history into the Anthropic Messages API format —
the seam between our stored chat schema (`{id, role, type, text, payload}`)
and what the model actually sees.
"""
from typing import Any, List, Optional, Tuple

from ..chat_service import build_board_context
from ..services import agent_links_service


def split_response(response: Any) -> Tuple[str, Optional[Any]]:
    """Splits one model response into its plain text and (at most one) tool
    call — shared by the top-level task loop and the scoped sub-agent loop."""
    text_parts: List[str] = []
    tool_use = None
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use" and tool_use is None:
            tool_use = block
    return "\n".join(p for p in text_parts if p), tool_use


def assistant_turn(response: Any, tool_use: Any) -> dict:
    """The assistant-side request-params turn for a tool call just made —
    only text/tool_use blocks round-trip cleanly as input; any other
    parallel tool_use in the same turn is dropped too, since only one
    `tool_use` is ever actually executed (see `split_response`)."""
    kept = [b.model_dump() for b in response.content if b.type == "text" or b is tool_use]
    return {"role": "assistant", "content": kept}


def tool_result_turn(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    turn = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}]}
    if is_error:
        turn["content"][0]["is_error"] = True
    return turn


def _describe_link(link: dict) -> str:
    name = link.get("toAgentName") or "(unnamed Agent)"
    description = link.get("toAgentDescription") or ""
    detail = f" — {description}" if description else " — no capability description set; ask if unsure it fits"
    return f'- targetAgentId "{link["toAgentId"]}", "{name}"{detail}'


async def _delegation_targets_note(agent_id: Optional[str]) -> str:
    """Lists the Agents `agent_id` actually has a granted `agent_links` entry
    for — without this, `delegate_to_agent` names a target the model could
    only ever guess at, since nothing else in its context names a peer
    Agent or what it's for."""
    if not agent_id:
        return ""
    links = await agent_links_service.list_links_from(agent_id)
    if not links:
        return ""
    listing = "\n".join(_describe_link(l) for l in links)
    return (
        "\n\nAgents you're allowed to delegate to via delegate_to_agent (delegate_to_agent refuses "
        f"any targetAgentId not on this list):\n{listing}"
    )


def _board_chat_note(board: dict, task: dict) -> str:
    """Recent plain-text messages from the board's own free-form chats
    (never this task's dedicated chat, which is the conversation the model
    is already in) — folded in as read-only awareness, not something to
    reply to, since merging it into the actual message list would risk
    breaking the tool_use/tool_result pairing the rest of this conversation
    relies on."""
    texts = []
    for chat in board.get("chats", []):
        if chat.get("taskId"):
            continue
        for m in chat.get("messages", []):
            if m.get("type", "text") == "text" and m.get("text"):
                texts.append(f'{m.get("role", "user")}: {m["text"]}')
    if not texts:
        return ""
    recent = texts[-15:]
    listing = "\n".join(f"- {t}" for t in recent)
    return (
        "\n\nRecent general discussion on this board's own chat (context only — not directed at "
        f"this task specifically, and you can't reply to it from here):\n{listing}"
    )


def _description_note(task: dict) -> str:
    version = task.get("descriptionVersion") or 0
    description = (task.get("description") or "").strip()
    shown = description if description else "(empty — nothing has been written yet)"
    return (
        f"\n\nTask description (current version: {version} — pass this as base_version to "
        f"update_task_description):\n{shown}\n\n"
        "The description is this task's detailed context. As the task gets clearer — requirements "
        "pinned down, decisions made, facts learned — keep it current with update_task_description "
        "(send the full new text; if you remove anything, say what and why in removed_summary). "
        "Before you finish the task, or stop because it failed or is waiting on someone outside this "
        "system, call set_execution_summary with what was done, the outcome, and anything the user "
        "should follow up on."
    )


async def build_task_system_prompt(board: dict, task: dict, is_first_turn: bool = True) -> str:
    context = build_board_context(board)
    delegation_note = await _delegation_targets_note(board.get("agentId"))
    board_chat_note = _board_chat_note(board, task)
    # Only nudged on this task's very first turn — repeating it on every
    # resumption (a delegation reply landing, an approval decision coming
    # back) would invite the model to re-litigate ambiguity at moments where
    # it should just be picking a resumed conversation back up.
    ambiguity_check_note = (
        "This task's text is short — before doing anything else, judge whether it's actually clear enough to act on correctly. "
        "If it's ambiguous or missing something you'd need to guess (who, what, which one, etc.), "
        "call ask_user with your question instead of assuming.\n\n"
    ) if is_first_turn else ""
    return (
        f'{context}\n\nFocus on this task: "{task.get("text", "")}".{_description_note(task)}\n\n'
        f"{ambiguity_check_note}"
        "You can call ask_user any time — at the start, or later mid-task if you get stuck and need "
        "more information — rather than guessing; this pauses the task until the user replies in "
        "this task's own chat.\n\n"
        "If you've done everything you can on your end but the task can't actually finish until "
        "someone outside this system does something — replies to an email you sent, signs a "
        "document, gets back to you after a reminder — call mark_manual with a short note on what "
        "you're waiting on and from whom. Don't leave the task open-ended without calling it, and "
        "don't guess at or assume an outcome that hasn't happened yet.\n\n"
        "You can call tools to make progress. Read-only tools run immediately and their result is "
        "fed back to you. Any mutating tool call (sending an email, creating or editing a calendar "
        "event, or anything else with an effect outside this app) is never executed directly — it "
        "is proposed to the user as a pending approval instead, and you'll see the outcome once "
        "they decide. If a proposal is rejected, don't repeat it unmodified — explain what you'll "
        "do differently or ask a clarifying question.\n\n"
        "If a piece of this task is complex enough to decompose, call delegate_subtask to run a "
        "scoped sub-agent, with a restricted set of tools, on just that piece — it has no budget "
        "or approval flow of its own, and a mutating action it proposes still surfaces as a normal "
        "approval card here. If this task needs a specialization this Agent doesn't have, call "
        "delegate_to_agent to hand it to one of the Agents listed below (if any) — this only works "
        "if an Agent Admin has already granted that delegation link; if not, or if none are listed, "
        "you'll get a clear refusal back, and you should tell the user rather than retry silently. A "
        "successful delegation spends the target Agent's own budget, never this one's, and this task "
        f"waits for its reply.{delegation_note}{board_chat_note}"
    )


def to_anthropic_messages(messages: List[dict]) -> List[dict]:
    """Converts stored chat messages into Anthropic message params.

    A resolved `action_request` becomes the `tool_use`/`tool_result` pair the
    model expects to see for a call it made; a still-`pending` one is left
    out entirely — the model is never shown a dangling tool call it hasn't
    gotten a result for yet.
    """
    out: List[dict] = []
    for m in messages:
        if m.get("type") == "action_request":
            payload = m.get("payload", {})
            status = payload.get("status")
            if status == "pending":
                continue
            out.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": payload["toolUseId"],
                    "name": payload["tool"],
                    "input": payload.get("params", {}),
                }],
            })
            if status == "approved":
                result_content = payload.get("result") or "Action completed."
                is_error = False
            else:
                result_content = (
                    "The user rejected this action. Do not repeat it unmodified — "
                    "explain or propose an alternative."
                )
                is_error = True
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": payload["toolUseId"],
                    "content": result_content,
                    "is_error": is_error,
                }],
            })
        elif m.get("type") == "clarification_request":
            payload = m.get("payload", {})
            if payload.get("status") != "answered":
                continue
            out.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": payload["toolUseId"],
                    "name": "ask_user",
                    "input": {"question": payload.get("question", "")},
                }],
            })
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": payload["toolUseId"],
                    "content": payload.get("answer") or "(no answer given)",
                }],
            })
        elif m.get("type") == "manual_hold":
            payload = m.get("payload", {})
            if payload.get("status") != "resolved":
                continue
            out.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": payload["toolUseId"],
                    "name": "mark_manual",
                    "input": {"note": payload.get("note", "")},
                }],
            })
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": payload["toolUseId"],
                    "content": payload.get("resolution") or "(resolved, no details given)",
                }],
            })
        else:
            text = m.get("text") or ""
            if text:
                out.append({"role": m["role"], "content": text})
    return out
