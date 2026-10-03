"""Makes sure a task ends its run with an Execution Summary.

The agent is asked to write one itself (`set_execution_summary`). This is
the safety net for when it doesn't — and it also stamps the final status
label (done / failed / manual / stopped) on whichever summary ends up
standing, so the Execution Summary tab can say what kind of ending it
describes. Called whenever a run finishes or parks a task on a manual hold;
never for the other suspensions (approval, clarification, peer reply), since
those aren't an ending.
"""
from typing import List, Optional

from ..database import boards_collection
from ..services import task_fields_service as svc
from ..task_fields import SUMMARY, SUMMARY_STATUSES
from . import task_field_tools

_STATUS_HEADINGS = {
    "done": "Completed",
    "failed": "Failed",
    "manual": "Waiting on a manual follow-up",
    "stopped": "Stopped",
    "blocked": "Blocked",
}


def _last_assistant_text(messages: List[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("type", "text") == "text" and m.get("text"):
            return m["text"]
    return ""


def _manual_note(messages: List[dict], task_id: str) -> str:
    for m in reversed(messages):
        payload = m.get("payload") or {}
        if m.get("type") == "manual_hold" and payload.get("taskId") == task_id:
            return payload.get("note", "")
    return ""


def build_fallback_summary(
    status: str, task_text: str, messages: List[dict], task_id: str, reason: Optional[str]
) -> str:
    """Deterministic, no model call: the status, the task, and the closest
    thing the run left behind to an outcome."""
    lines = [f"**{_STATUS_HEADINGS.get(status, status.title())}** — {task_text}", ""]
    if status == "manual":
        note = _manual_note(messages, task_id)
        lines.append(f"Waiting on: {note}" if note else "Waiting on someone outside this system.")
    elif status in ("failed", "stopped", "blocked") and reason:
        lines.append(f"Reason: {reason}")
    final_text = _last_assistant_text(messages)
    if final_text:
        lines += ["", final_text]
    return "\n".join(lines).rstrip() + "\n"


_FINAL_VERSION_KEY = "completionSummaryFinalVersion"


async def _mark_final(board_id: str, task_id: str, status: str, version: int) -> None:
    """Records which summary version was last finalized, so the next ending
    can tell "the agent wrote a new one since" from "this is the old one"."""
    await boards_collection.update_one(
        {"_id": board_id, "tasks.id": task_id},
        {"$set": {f"tasks.$.{SUMMARY.status_key()}": status, f"tasks.$.{_FINAL_VERSION_KEY}": version}},
    )


async def finalize(board_id: str, task_id: str, status: str, reason: Optional[str] = None) -> None:
    if status not in SUMMARY_STATUSES:
        return
    board = await boards_collection.find_one({"_id": board_id})
    task = next((t for t in (board or {}).get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        return

    current = svc.field_state(task, SUMMARY)
    written_since_last_ending = (
        current["version"] > (task.get(_FINAL_VERSION_KEY) or 0)
        and (current["updatedBy"] or {}).get("type") == "agent"
    )
    if written_since_last_ending:
        await _mark_final(board_id, task_id, status, current["version"])
        return

    chat = next((c for c in board.get("chats", []) if c.get("taskId") == task_id), None)
    text = build_fallback_summary(
        status, task.get("text", ""), (chat or {}).get("messages", []), task_id, reason or task.get("statusReason")
    )
    written = await task_field_tools.write_agent_summary(board_id, task_id, text, status=status)
    await _mark_final(board_id, task_id, status, written["version"])
