import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.execution import glow
from app import task_state

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-glow"
TASK_ID = "test-task-glow"


def _task(status):
    return {"id": TASK_ID, "text": "t", "status": status, "statusReason": None, "currentRunId": None}


async def _reset(board_status, task_status):
    await boards_collection.delete_many({"_id": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": "test-agent-glow",
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [_task(task_status)],
        "chats": [],
        "activeChatId": None,
        "status": board_status,
        "stopRequested": False,
        "glow": "none",
    })


@pytest.mark.parametrize(
    "board_status,task_status,expected",
    [
        ("running", "running", "processing"),
        ("running", "awaiting_approval", "needs_approval"),
        ("running", "awaiting_reply", "needs_reply"),
        ("running", "awaiting_clarification", "needs_reply"),
        ("running", "manual", "needs_reply"),
        ("done", "done", "done"),
        ("idle", "idle", "none"),
        # Approval outranks a board that's already stopped — the task is
        # still the most actionable thing on the board.
        ("stopped", "awaiting_approval", "needs_approval"),
    ],
)
async def test_compute_glow_precedence(board_status, task_status, expected):
    await _reset(board_status, task_status)
    try:
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert glow.compute_glow(board) == expected
    finally:
        await boards_collection.delete_many({"_id": BOARD_ID})


async def test_transition_task_status_persists_and_publishes_glow():
    await _reset("running", "running")
    try:
        updated = await task_state.transition_task_status(
            BOARD_ID, TASK_ID, ["running"], "awaiting_approval"
        )
        assert updated["glow"] == "needs_approval"

        persisted = await boards_collection.find_one({"_id": BOARD_ID})
        assert persisted["glow"] == "needs_approval"
    finally:
        await boards_collection.delete_many({"_id": BOARD_ID})


async def test_migrate_board_glow_backfills_missing_field():
    await boards_collection.delete_many({"_id": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": "test-agent-glow",
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [_task("done")],
        "chats": [],
        "activeChatId": None,
        "status": "done",
        "stopRequested": False,
        # no "glow" field — simulates a pre-Phase-7 board.
    })
    try:
        migrated = await glow.migrate_board_glow()
        assert migrated >= 1
        persisted = await boards_collection.find_one({"_id": BOARD_ID})
        assert persisted["glow"] == "done"
    finally:
        await boards_collection.delete_many({"_id": BOARD_ID})
