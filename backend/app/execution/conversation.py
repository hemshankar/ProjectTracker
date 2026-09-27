"""Shapes one task's chat history into the Anthropic Messages API format —
the seam between our stored chat schema (`{id, role, type, text, payload}`)
and what the model actually sees.
"""
from typing import List

from ..chat_service import build_board_context


def build_task_system_prompt(board: dict, task: dict) -> str:
    context = build_board_context(board)
    return (
        f'{context}\n\nFocus on this task: "{task.get("text", "")}". You can call tools to make '
        "progress. Read-only tools run immediately and their result is fed back to you. Any "
        "mutating tool call (sending an email, creating or editing a calendar event, or anything "
        "else with an effect outside this app) is never executed directly — it is proposed to the "
        "user as a pending approval instead, and you'll see the outcome once they decide. If a "
        "proposal is rejected, don't repeat it unmodified — explain what you'll do differently or "
        "ask a clarifying question."
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
        else:
            text = m.get("text") or ""
            if text:
                out.append({"role": m["role"], "content": text})
    return out
