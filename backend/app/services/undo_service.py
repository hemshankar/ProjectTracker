"""Server-side undo/redo (Phase 7): a per-(agent, user) pointer into that
user's own `actorType="human"` audit-log entries — the audit log is the
server-side source of truth, never a client-only stack, so it survives a
page reload and stays consistent across that user's own tabs.

Scoped to the `board` and `task` entity types only: a pure, safe, local
snapshot to replay. `chat`/`chat_message` entries (approvals, clarification
answers, plain chat text) are deliberately excluded — reversing an
*approval* doesn't undo the real-world side effect it already triggered (an
email already sent can't be unsent), so undo only ever touches board/task
metadata. Agent-authored entries are excluded by construction (the query
filters `actorType="human"`), matching the PRD's "agent actions are never
undone this way."

Undo re-applies the pointed-at entry's `before` snapshot through the same
kind of write a human PATCH/POST/DELETE would make (never a raw whole-
document overwrite for a board `update` — see `_replay_board`); redo
replays `after`. Each replay is itself written back to the audit log
(tagged `undo_redo=True` so it's excluded from `_list_undoable` — otherwise
undoing would immediately become a fresh undo target) and moves the
pointer by one.
"""
from dataclasses import dataclass
from typing import Optional

from ..database import audit_log_collection, boards_collection, undo_pointers_collection
from ..execution import glow
from ..execution.completion import try_complete_board
from ..models import board_to_json, now_ms
from . import audit_service, tasks_service

_UNDOABLE_ENTITY_TYPES = ("board", "task")
_MAX_HISTORY = 200

_BOARD_METADATA_FIELDS = (
    "title", "description", "color", "labelId", "completed",
    "x", "y", "w", "h", "z", "budgetCapUsd",
)


@dataclass
class UndoResult:
    ok: bool
    boardId: Optional[str] = None
    board: Optional[dict] = None


async def _list_undoable(agent_id: str, user_id: str) -> list:
    cursor = audit_log_collection.find(
        {
            "agentId": agent_id,
            "actorId": user_id,
            "actorType": "human",
            "entityType": {"$in": _UNDOABLE_ENTITY_TYPES},
            "undoRedo": {"$ne": True},
        }
    ).sort("ts", -1).limit(_MAX_HISTORY)
    return [d async for d in cursor]


def _pointer_key(agent_id: str, user_id: str) -> str:
    return f"{agent_id}:{user_id}"


async def _load_pointer(agent_id: str, user_id: str, entries: list) -> int:
    """Reads the persisted pointer, resetting it to 0 if a genuinely new
    human edit (not one of our own replays) has landed since we last moved
    it — the same "a fresh edit clears the redo stack" rule an ordinary
    undo stack follows. Detected by comparing the newest undoable entry's id
    against the one we last saw: our own replay writes are tagged
    `undo_redo=True` and excluded from `entries`, so they never shift it —
    only a real edit elsewhere does.
    """
    top_id = entries[0]["_id"] if entries else None
    state = await undo_pointers_collection.find_one({"_id": _pointer_key(agent_id, user_id)})
    if state is None or state.get("lastSeenTopId") != top_id:
        return 0
    return state.get("pointer", 0)


async def _save_pointer(agent_id: str, user_id: str, pointer: int, entries: list) -> None:
    top_id = entries[0]["_id"] if entries else None
    await undo_pointers_collection.update_one(
        {"_id": _pointer_key(agent_id, user_id)},
        {"$set": {"pointer": pointer, "lastSeenTopId": top_id}},
        upsert=True,
    )


async def _replay_task(board_id: str, task_id: str, snapshot: Optional[dict]) -> None:
    board = await boards_collection.find_one({"_id": board_id})
    if board is None:
        return
    exists = any(t["id"] == task_id for t in board.get("tasks", []))

    if snapshot is None:
        if exists:
            await boards_collection.update_one({"_id": board_id}, {"$pull": {"tasks": {"id": task_id}}})
    elif exists:
        await boards_collection.update_one(
            {"_id": board_id, "tasks.id": task_id}, {"$set": {"tasks.$": dict(snapshot)}}
        )
    else:
        await boards_collection.update_one({"_id": board_id}, {"$push": {"tasks": dict(snapshot)}})

    await boards_collection.update_one({"_id": board_id}, {"$set": {"updatedAt": now_ms()}})
    await glow.refresh_glow(board_id)
    if snapshot is not None and snapshot.get("status") == "idle":
        fresh = await boards_collection.find_one({"_id": board_id})
        if fresh is not None:
            await tasks_service.reopen_board_if_terminal(board_id, fresh)
    await try_complete_board(board_id)


async def _replay_board(board_id: str, action: str, snapshot: Optional[dict], is_undo: bool) -> None:
    is_delete = (action == "create" and is_undo) or (action == "delete" and not is_undo)
    is_recreate = (action == "delete" and is_undo) or (action == "create" and not is_undo)

    if is_delete:
        await boards_collection.delete_one({"_id": board_id})
        return

    if is_recreate:
        if snapshot is not None and await boards_collection.find_one({"_id": board_id}) is None:
            await boards_collection.insert_one(dict(snapshot))
            await glow.refresh_glow(board_id)
        return

    # action == "update": both snapshots are full board documents (see
    # `routers/boards.py`'s update_board/update_board_budget), but only the
    # human-editable metadata fields are safe to restore — `tasks`/`chats`/
    # `status` may have moved on since, and clobbering them would be exactly
    # the "raw document overwrite" the design calls out to avoid.
    if snapshot is None:
        return
    updates = {k: snapshot[k] for k in _BOARD_METADATA_FIELDS if k in snapshot}
    updates["updatedAt"] = now_ms()
    result = await boards_collection.update_one({"_id": board_id}, {"$set": updates})
    if result.matched_count:
        await glow.refresh_glow(board_id)


async def _replay(entry: dict, is_undo: bool) -> None:
    snapshot = entry["before"] if is_undo else entry["after"]
    board_id = entry["boardId"]
    if entry["entityType"] == "task":
        await _replay_task(board_id, entry["taskId"], snapshot)
    else:
        await _replay_board(board_id, entry["action"], snapshot, is_undo)


async def _record_replay(entry: dict, user_id: str, is_undo: bool) -> None:
    before, after = (entry["after"], entry["before"]) if is_undo else (entry["before"], entry["after"])
    await audit_service.write_audit(
        agent_id=entry["agentId"],
        board_id=entry["boardId"],
        task_id=entry.get("taskId"),
        entity_type=entry["entityType"],
        action="update",
        actor_type="human",
        actor_id=user_id,
        before=before,
        after=after,
        undo_redo=True,
    )


async def _result_for(board_id: str) -> UndoResult:
    board = await boards_collection.find_one({"_id": board_id})
    return UndoResult(ok=True, boardId=board_id, board=board_to_json(board) if board else None)


async def _step(agent_id: str, user_id: str, is_undo: bool) -> UndoResult:
    entries = await _list_undoable(agent_id, user_id)
    pointer = await _load_pointer(agent_id, user_id, entries)

    target_index = pointer if is_undo else pointer - 1
    if target_index < 0 or target_index >= len(entries):
        await _save_pointer(agent_id, user_id, pointer, entries)
        return UndoResult(ok=False)

    entry = entries[target_index]
    await _replay(entry, is_undo)
    await _record_replay(entry, user_id, is_undo)
    await _save_pointer(agent_id, user_id, pointer + 1 if is_undo else pointer - 1, entries)
    return await _result_for(entry["boardId"])


async def undo(agent_id: str, user_id: str) -> dict:
    result = await _step(agent_id, user_id, is_undo=True)
    return result.__dict__


async def redo(agent_id: str, user_id: str) -> dict:
    result = await _step(agent_id, user_id, is_undo=False)
    return result.__dict__
