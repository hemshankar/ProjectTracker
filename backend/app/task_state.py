from typing import Any, Iterable, Optional

from pymongo import ReturnDocument

from .database import boards_collection, task_runs_collection
from .execution.context import finish_task_run
from .models import now_ms

INTERRUPTED_REASON = "Interrupted by server restart"

TASK_STATUSES = (
    "idle",
    "queued",
    "running",
    "awaiting_reply",
    "awaiting_approval",
    "awaiting_clarification",
    "manual",
    "stopped",
    "failed",
    "blocked",
    "done",
)

BOARD_STATUSES = (
    "idle",
    "queued",
    "running",
    "manual",
    "stopped",
    "failed",
    "blocked",
    "done",
)


async def transition_task_status(
    board_id: str,
    task_id: str,
    expected_statuses: Optional[Iterable[str]],
    new_status: str,
    **fields: Any,
) -> Optional[dict]:
    """Atomically move one task inside a board's `tasks[]` to `new_status`,
    iff its current status is one of `expected_statuses` (or unconditionally
    when `expected_statuses` is None).

    A filter miss (task already moved on by a racing caller) returns None —
    that miss is the entire double-run guard, with no separate locking
    mechanism. Every status-changing code path must go through this
    function rather than a raw `update_one`.
    """
    if new_status not in TASK_STATUSES:
        raise ValueError(f"Unknown task status: {new_status}")

    task_match: dict = {"id": task_id}
    if expected_statuses is not None:
        task_match["status"] = {"$in": list(expected_statuses)}

    task_set = {"tasks.$.status": new_status}
    for key, value in fields.items():
        task_set[f"tasks.$.{key}"] = value
    task_set["updatedAt"] = now_ms()

    return await boards_collection.find_one_and_update(
        {"_id": board_id, "tasks": {"$elemMatch": task_match}},
        {"$set": task_set},
        return_document=ReturnDocument.AFTER,
    )


async def transition_board_status(
    board_id: str,
    expected_statuses: Optional[Iterable[str]],
    new_status: str,
    **fields: Any,
) -> Optional[dict]:
    """Same compare-and-swap pattern as `transition_task_status`, but for a
    board's own `status` field. A filter miss returns None.
    """
    if new_status not in BOARD_STATUSES:
        raise ValueError(f"Unknown board status: {new_status}")

    match: dict = {"_id": board_id}
    if expected_statuses is not None:
        match["status"] = {"$in": list(expected_statuses)}

    updates = {"status": new_status, "updatedAt": now_ms()}
    updates.update(fields)

    return await boards_collection.find_one_and_update(
        match,
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


async def migrate_legacy_board_statuses() -> int:
    """One-off, idempotent migration: any board missing `status`/`stopRequested`
    gets the idle defaults. Safe to call on every startup.
    """
    result = await boards_collection.update_many(
        {"status": {"$exists": False}},
        {"$set": {"status": "idle", "stopRequested": False}},
    )
    return result.modified_count


_ZOMBIE_TASK_STATUSES = ("running", "queued")
_HUMAN_WAIT_STATUSES = ("awaiting_approval", "awaiting_reply", "awaiting_clarification", "manual")


async def reconcile_interrupted_runs() -> int:
    """Startup recovery for boards left `running`/`queued` by a process that
    died mid-task (crash, redeploy, OOM-kill) — nothing else ever revisits
    them, since `RunnerRegistry` is a plain in-memory dict and there's no
    persistence for the asyncio.Task actually driving the board. Without
    this, such a board is stuck forever: /start 409s because "running"/
    "queued" aren't in BOARD_STARTABLE_STATUSES, and /stop is a silent no-op
    because nothing is left watching `stopRequested`.

    Any task actually mid-step (`running`) or parked on a rate limit/lock
    wait (`queued`) belongs to a coroutine that's gone, so it's reset to
    `failed` here, closing its dangling `task_runs` record the same way
    `finish_task_run` normally would. A task merely `awaiting_approval`,
    `awaiting_reply`, `awaiting_clarification`, or `manual` is untouched —
    that's a human-driven resume with no backing coroutine, so it's still
    resolvable after the restart.

    A board is then failed (restartable) unless the only thing left
    pending on it is one of those human-wait tasks, in which case it's
    legitimately still mid-run and left alone.

    A second pass below covers a task run standalone (outside any board's
    own `run()` loop) rather than as part of a whole-board run — the board's
    own `status` never changes for that, so the scan above never reaches it.
    """
    reconciled = 0
    async for board in boards_collection.find({"status": {"$in": ["queued", "running"]}}):
        board_id = board["_id"]
        had_zombie_task = False
        for task in board.get("tasks", []):
            if task.get("status") not in _ZOMBIE_TASK_STATUSES:
                continue
            had_zombie_task = True
            run_id = task.get("currentRunId")
            reset = await transition_task_status(
                board_id,
                task["id"],
                _ZOMBIE_TASK_STATUSES,
                "failed",
                statusReason=INTERRUPTED_REASON,
                currentRunId=None,
            )
            if reset is not None and run_id:
                await finish_task_run(run_id, "failed", INTERRUPTED_REASON)

        awaiting_human = any(t.get("status") in _HUMAN_WAIT_STATUSES for t in board.get("tasks", []))
        if awaiting_human and not had_zombie_task:
            continue

        failed = await transition_board_status(
            board_id,
            ["queued", "running"],
            "failed",
            stopRequested=False,
            statusReason=INTERRUPTED_REASON,
        )
        if failed is not None:
            reconciled += 1

    # A task can also be run standalone (see `AgentRunner.run_task_by_id`
    # called directly, outside `run()`'s own loop) without ever putting the
    # board itself into "queued"/"running" — the scan above never reaches
    # such a board, so a task left `running`/`queued` there by a process
    # that died mid-task would otherwise sit stuck forever. Same zombie-task
    # reset as above, just without any board-status transition (the board's
    # own status was never touched to begin with).
    async for board in boards_collection.find({
        "status": {"$nin": ["queued", "running"]},
        "tasks.status": {"$in": list(_ZOMBIE_TASK_STATUSES)},
    }):
        board_id = board["_id"]
        for task in board.get("tasks", []):
            if task.get("status") not in _ZOMBIE_TASK_STATUSES:
                continue
            run_id = task.get("currentRunId")
            reset = await transition_task_status(
                board_id,
                task["id"],
                _ZOMBIE_TASK_STATUSES,
                "failed",
                statusReason=INTERRUPTED_REASON,
                currentRunId=None,
            )
            if reset is not None:
                reconciled += 1
                if run_id:
                    await finish_task_run(run_id, "failed", INTERRUPTED_REASON)
    return reconciled


async def reconcile_orphaned_task_runs() -> int:
    """Sweeps any `task_runs` doc left `status: "running"` by a process that
    died mid-task. Complements `reconcile_interrupted_runs`, which only
    reaches a task's *primary* run (via `boards.tasks[].currentRunId`) — a
    sub-agent run (`kind: "subagent"`, linked by `parentRunId` instead) is
    invisible to that scan and would otherwise sit at `status: "running"`,
    `endedAt: null` forever, since nothing else ever revisits it either.
    Safe to run unconditionally on every startup: `task_runs` are only ever
    written by a coroutine driven by `RunnerRegistry`, which is wiped on
    every restart, so anything still "running" at startup is orphaned by
    definition.
    """
    result = await task_runs_collection.update_many(
        {"status": "running"},
        {"$set": {"status": "failed", "endedAt": now_ms(), "error": INTERRUPTED_REASON}},
    )
    return result.modified_count


async def migrate_legacy_task_statuses() -> int:
    """One-off, idempotent migration: any task missing `status` gets one
    derived from its old `done` flag. Safe to call on every startup.
    """
    migrated = 0
    async for board in boards_collection.find({"tasks.0": {"$exists": True}}):
        tasks = board.get("tasks", [])
        changed = False
        for t in tasks:
            if "status" not in t:
                t["status"] = "done" if t.get("done") else "idle"
                t.setdefault("statusReason", None)
                t.setdefault("currentRunId", None)
                changed = True
        if changed:
            await boards_collection.update_one({"_id": board["_id"]}, {"$set": {"tasks": tasks}})
            migrated += 1
    return migrated
