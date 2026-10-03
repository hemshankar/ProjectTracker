"""Versioned reads/writes for a task's Description and Execution Summary.

Every write is a compare-and-swap on the field's version (the same pattern
`task_state.transition_task_status` uses for status): the caller says which
version it was based on, and a stale base is rejected with the current
content so the caller can merge instead of silently clobbering someone
else's edit. Each accepted write appends an immutable row to
`task_revisions`, keyed by task id alone so history follows a task when it
moves between boards.
"""
from typing import List, Optional

from pymongo import ReturnDocument

from ..database import boards_collection, task_revisions_collection
from ..execution.events import events
from ..models import new_id, now_ms
from ..task_fields import AUTHOR_TYPES, MAX_CONTENT_CHARS, FieldSpec
from . import audit_service


class TaskNotFound(Exception):
    pass


class FieldValidationError(ValueError):
    pass


class VersionConflict(Exception):
    """The caller's base version is stale. Carries what's current so the
    caller can show or merge it."""

    def __init__(self, current: dict) -> None:
        super().__init__("Version conflict")
        self.current = current


def _find_task(board: Optional[dict], task_id: str) -> Optional[dict]:
    if board is None:
        return None
    return next((t for t in board.get("tasks", []) if t["id"] == task_id), None)


def field_state(task: dict, spec: FieldSpec) -> dict:
    """The field's current value in API shape — a missing field reads as
    empty at version 0, so tasks created before this feature need no
    migration."""
    return {
        "content": task.get(spec.attr) or "",
        "version": task.get(spec.version_key()) or 0,
        "updatedAt": task.get(spec.updated_at_key()),
        "updatedBy": task.get(spec.updated_by_key()),
        "status": task.get(spec.status_key()),
    }


async def get_field(board_id: str, task_id: str, spec: FieldSpec) -> dict:
    task = _find_task(await boards_collection.find_one({"_id": board_id}), task_id)
    if task is None:
        raise TaskNotFound(task_id)
    return field_state(task, spec)


def _version_match(spec: FieldSpec, expected_version: int) -> dict:
    if expected_version == 0:
        return {"$or": [{spec.version_key(): 0}, {spec.version_key(): {"$exists": False}}]}
    return {spec.version_key(): expected_version}


async def write_field(
    board_id: str,
    task_id: str,
    spec: FieldSpec,
    content: str,
    expected_version: int,
    author_type: str,
    author_id: Optional[str],
    *,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Raises `VersionConflict` on a stale `expected_version`, `TaskNotFound`
    if the task isn't on the board, `FieldValidationError` on bad input."""
    if author_type not in AUTHOR_TYPES:
        raise FieldValidationError(f"Unknown author type: {author_type}")
    if len(content) > MAX_CONTENT_CHARS:
        raise FieldValidationError(f"Content exceeds {MAX_CONTENT_CHARS} characters")

    new_version = expected_version + 1
    ts = now_ms()
    author = {"type": author_type, "id": author_id}
    task_set: dict = {
        f"tasks.$.{spec.attr}": content,
        f"tasks.$.{spec.version_key()}": new_version,
        f"tasks.$.{spec.updated_at_key()}": ts,
        f"tasks.$.{spec.updated_by_key()}": author,
        "updatedAt": ts,
    }
    if status is not None:
        task_set[f"tasks.$.{spec.status_key()}"] = status

    before_board = await boards_collection.find_one_and_update(
        {"_id": board_id, "tasks": {"$elemMatch": {"id": task_id, **_version_match(spec, expected_version)}}},
        {"$set": task_set},
        return_document=ReturnDocument.BEFORE,
    )
    if before_board is None:
        task = _find_task(await boards_collection.find_one({"_id": board_id}), task_id)
        if task is None:
            raise TaskNotFound(task_id)
        raise VersionConflict(field_state(task, spec))

    before_task = _find_task(before_board, task_id)
    await task_revisions_collection.insert_one({
        "_id": new_id(), "taskId": task_id, "field": spec.key, "version": new_version,
        "content": content, "authorType": author_type, "authorId": author_id,
        "status": status, "note": note, "ts": ts,
    })
    await events.publish(
        board_id, {"taskId": task_id, "type": "task_field_updated", "field": spec.key, "version": new_version}
    )
    await audit_service.write_audit(
        agent_id=before_board.get("agentId"), board_id=board_id, task_id=task_id,
        entity_type="task_field", action="update",
        actor_type="agent" if author_type == "agent" else "human", actor_id=author_id,
        before={"field": spec.key, "version": expected_version, "content": (before_task or {}).get(spec.attr) or ""},
        after={"field": spec.key, "version": new_version, "content": content},
    )
    return {**field_state({
        spec.attr: content, spec.version_key(): new_version, spec.updated_at_key(): ts,
        spec.updated_by_key(): author, spec.status_key(): status,
    }, spec)}


def _revision_json(r: dict) -> dict:
    return {
        "version": r["version"], "content": r.get("content", ""), "authorType": r.get("authorType"),
        "authorId": r.get("authorId"), "status": r.get("status"), "note": r.get("note"), "ts": r.get("ts"),
    }


async def list_revisions(task_id: str, spec: FieldSpec, limit: int = 100) -> List[dict]:
    cursor = task_revisions_collection.find({"taskId": task_id, "field": spec.key}).sort("version", -1).limit(limit)
    return [_revision_json(r) async for r in cursor]


async def restore_revision(
    board_id: str, task_id: str, spec: FieldSpec, version: int, expected_version: int, author_id: Optional[str]
) -> dict:
    """Restoring writes the old content as a brand-new revision (never
    rewinds history), so nothing is ever lost by restoring."""
    revision = await task_revisions_collection.find_one({"taskId": task_id, "field": spec.key, "version": version})
    if revision is None:
        raise TaskNotFound(f"revision {version}")
    return await write_field(
        board_id, task_id, spec, revision.get("content", ""), expected_version, "human", author_id,
        status=revision.get("status"), note=f"Restored from v{version}",
    )
