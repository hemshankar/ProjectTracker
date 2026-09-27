"""Checks whether a board's run is actually finished — every task resolved,
not just none left idle to pick up. A task can be sitting in
`awaiting_approval` (or `awaiting_reply`) with no idle task behind it; the
board must keep its "running" (processing) status until that's resolved
too, so the glow stays accurate. A task marked `manual` is the same case —
still pending on an external reply, not a clean finish.
"""
from ..database import boards_collection
from .. import task_state
from .events import events

_PENDING_TASK_STATUSES = {
    "idle", "queued", "running", "awaiting_reply", "awaiting_approval", "awaiting_clarification", "manual",
}


async def try_complete_board(board_id: str) -> None:
    board = await boards_collection.find_one({"_id": board_id})
    if board is None:
        return
    tasks = board.get("tasks", [])
    if any(t.get("status") in _PENDING_TASK_STATUSES for t in tasks):
        return
    # A failed task isn't "pending", but it isn't a clean finish either — land
    # the board on "failed" (still restartable) rather than masking it as "done".
    final_status = "failed" if any(t.get("status") == "failed" for t in tasks) else "done"
    completed = await task_state.transition_board_status(board_id, ["queued", "running"], final_status)
    if completed is not None:
        await events.publish(board_id, {"boardId": board_id, "status": final_status})
