"""Runs the agent's `update_task_description` / `set_execution_summary`
calls against the versioned store in `services.task_fields_service`.
Returns plain strings for the model (`is_error` tells the loop to flag it),
never raises for an expected rejection — a refusal is something the model
should read and react to, not a crash."""
from typing import Optional, Tuple

from ..services import task_fields_service as svc
from ..task_fields import DESCRIPTION, SUMMARY, append_revision_note, removed_lines
from .task_field_tool_specs import SET_SUMMARY, UPDATE_DESCRIPTION


async def run(tool_name: str, params: dict, board_id: str, task_id: str) -> Tuple[str, bool]:
    """Returns `(result_text, is_error)`."""
    try:
        if tool_name == UPDATE_DESCRIPTION:
            return await _update_description(params, board_id, task_id)
        if tool_name == SET_SUMMARY:
            return await _set_summary(params, board_id, task_id)
    except svc.TaskNotFound:
        return "This task no longer exists on the board.", True
    except svc.FieldValidationError as exc:
        return str(exc), True
    return f"Unknown tool '{tool_name}'.", True


def _conflict_message(base_version: int, current: dict) -> str:
    return (
        f"Refused: the description is now at version {current['version']}, not {base_version} — "
        "someone edited it since you read it. Merge their changes into your text and retry with "
        f"base_version={current['version']}.\n\nCurrent description:\n{current['content']}"
    )


async def _update_description(params: dict, board_id: str, task_id: str) -> Tuple[str, bool]:
    content = str(params.get("content") or "")
    base_version = params.get("base_version")
    if not isinstance(base_version, int) or base_version < 0:
        return "base_version must be the integer version shown with the current description.", True

    current = await svc.get_field(board_id, task_id, DESCRIPTION)
    if current["version"] != base_version:
        # Checked before the removal rule: against a newer text, "dropped lines"
        # would just be the other editor's work, not the agent's own deletion.
        return _conflict_message(base_version, current), True
    removed = removed_lines(current["content"], content)
    removed_summary = str(params.get("removed_summary") or "").strip()
    if removed and not removed_summary:
        preview = "; ".join(removed[:5]) + (" …" if len(removed) > 5 else "")
        return (
            "Refused: this overwrite drops existing text and `removed_summary` is empty. "
            f"Describe what you removed and why, or keep it. Dropped lines: {preview}", True,
        )
    if removed:
        content = append_revision_note(content, removed_summary)

    try:
        result = await svc.write_field(board_id, task_id, DESCRIPTION, content, base_version, "agent", None)
    except svc.VersionConflict as exc:
        return _conflict_message(base_version, exc.current), True
    return f"Description updated. It is now at version {result['version']}.", False


async def _set_summary(params: dict, board_id: str, task_id: str) -> Tuple[str, bool]:
    summary = str(params.get("summary") or "").strip()
    if not summary:
        return "summary must not be empty.", True
    await write_agent_summary(board_id, task_id, summary)
    return "Execution summary recorded.", False


async def write_agent_summary(board_id: str, task_id: str, summary: str, status: Optional[str] = None) -> dict:
    """Overwrites the summary as the agent. Sole-writer in practice, so a
    lost race with a human edit just retries once on the fresh version —
    the human's text stays in history either way."""
    for _ in range(2):
        current = await svc.get_field(board_id, task_id, SUMMARY)
        try:
            return await svc.write_field(
                board_id, task_id, SUMMARY, summary, current["version"], "agent", None, status=status
            )
        except svc.VersionConflict:
            continue
    raise svc.FieldValidationError("The summary was edited repeatedly while saving; try again.")
