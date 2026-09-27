"""Derives the one `boards.glow` field the frontend renders from, per the
Phase 7 design: `none` | `processing` | `done` | `needs_reply` |
`needs_approval`, recomputed after any write that could change it (a task's
status, the board's own status, or the population of tasks) rather than left
for the frontend to infer from raw statuses.

Precedence when tasks disagree — the most actionable state wins:
`needs_approval` > `needs_reply` > `processing` > `done` > `none`.
"""
from typing import Optional

from ..database import boards_collection
from .events import events

# `awaiting_reply` is the PRD's own name; `awaiting_clarification` and
# `manual` (added in later phases for ask_user / mark_manual holds) are the
# same shape of wait — the agent needs a human's text reply in chat — so all
# three bubble up to the same `needs_reply` glow.
_NEEDS_REPLY_STATUSES = {"awaiting_reply", "awaiting_clarification", "manual"}
_PROCESSING_BOARD_STATUSES = {"queued", "running"}

GLOW_VALUES = ("none", "processing", "done", "needs_reply", "needs_approval")


def compute_glow(board: dict) -> str:
    statuses = {t.get("status") for t in board.get("tasks", [])}
    if "awaiting_approval" in statuses:
        return "needs_approval"
    if statuses & _NEEDS_REPLY_STATUSES:
        return "needs_reply"
    if board.get("status") in _PROCESSING_BOARD_STATUSES:
        return "processing"
    if board.get("status") == "done":
        return "done"
    return "none"


async def refresh_glow_for(board: dict) -> str:
    """Same as `refresh_glow`, for a caller that already has the fresh board
    doc in hand (e.g. straight out of a `find_one_and_update`) — skips the
    extra round trip a plain `refresh_glow(board_id)` would otherwise need.
    """
    board_id = board["_id"]
    glow = compute_glow(board)
    if board.get("glow") != glow:
        await boards_collection.update_one({"_id": board_id}, {"$set": {"glow": glow}})
        await events.publish(board_id, {"boardId": board_id, "glow": glow})
    return glow


async def refresh_glow(board_id: str) -> Optional[str]:
    """Recomputes and persists `board_id`'s glow, publishing an SSE delta
    when it actually changed. Safe to call unconditionally after any task or
    board write — a no-op query miss (board deleted concurrently) just
    returns None.
    """
    board = await boards_collection.find_one({"_id": board_id})
    if board is None:
        return None
    return await refresh_glow_for(board)


async def migrate_board_glow() -> int:
    """One-off, idempotent startup migration: backfills `glow` on any board
    that predates this field. Safe to call on every startup."""
    migrated = 0
    async for board in boards_collection.find({"glow": {"$exists": False}}):
        await boards_collection.update_one(
            {"_id": board["_id"]}, {"$set": {"glow": compute_glow(board)}}
        )
        migrated += 1
    return migrated
