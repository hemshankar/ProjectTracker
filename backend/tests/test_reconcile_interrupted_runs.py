import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection, task_runs_collection
from app.task_state import reconcile_interrupted_runs

pytestmark = pytest.mark.asyncio(loop_scope="session")

ZOMBIE_BOARD_ID = "test-board-zombie-running"
PARKED_BOARD_ID = "test-board-zombie-queued"
AWAITING_APPROVAL_BOARD_ID = "test-board-awaiting-approval"
RUN_ID = "test-run-zombie"


async def _cleanup():
    await boards_collection.delete_many(
        {"_id": {"$in": [ZOMBIE_BOARD_ID, PARKED_BOARD_ID, AWAITING_APPROVAL_BOARD_ID]}}
    )
    await task_runs_collection.delete_one({"_id": RUN_ID})


async def test_reconcile_fails_board_with_zombie_running_task():
    await _cleanup()
    await boards_collection.insert_one(
        {
            "_id": ZOMBIE_BOARD_ID,
            "agentId": "test-agent",
            "status": "running",
            "stopRequested": False,
            "tasks": [
                {
                    "id": "t1",
                    "status": "running",
                    "statusReason": None,
                    "currentRunId": RUN_ID,
                }
            ],
        }
    )
    await task_runs_collection.insert_one(
        {"_id": RUN_ID, "boardId": ZOMBIE_BOARD_ID, "taskId": "t1", "status": "running", "endedAt": None}
    )
    try:
        count = await reconcile_interrupted_runs()
        assert count == 1

        board = await boards_collection.find_one({"_id": ZOMBIE_BOARD_ID})
        assert board["status"] == "failed"
        assert board["stopRequested"] is False
        task = board["tasks"][0]
        assert task["status"] == "failed"
        assert task["currentRunId"] is None

        run = await task_runs_collection.find_one({"_id": RUN_ID})
        assert run["status"] == "failed"
        assert run["endedAt"] is not None
    finally:
        await _cleanup()


async def test_reconcile_fails_board_stuck_queued_with_no_tasks():
    await _cleanup()
    await boards_collection.insert_one(
        {
            "_id": PARKED_BOARD_ID,
            "agentId": "test-agent",
            "status": "queued",
            "stopRequested": False,
            "tasks": [],
        }
    )
    try:
        count = await reconcile_interrupted_runs()
        assert count == 1
        board = await boards_collection.find_one({"_id": PARKED_BOARD_ID})
        assert board["status"] == "failed"
    finally:
        await _cleanup()


async def test_reconcile_leaves_board_waiting_on_human_alone():
    await _cleanup()
    await boards_collection.insert_one(
        {
            "_id": AWAITING_APPROVAL_BOARD_ID,
            "agentId": "test-agent",
            "status": "running",
            "stopRequested": False,
            "tasks": [
                {
                    "id": "t1",
                    "status": "awaiting_approval",
                    "statusReason": None,
                    "currentRunId": RUN_ID,
                }
            ],
        }
    )
    try:
        count = await reconcile_interrupted_runs()
        assert count == 0
        board = await boards_collection.find_one({"_id": AWAITING_APPROVAL_BOARD_ID})
        assert board["status"] == "running"
        assert board["tasks"][0]["status"] == "awaiting_approval"
    finally:
        await _cleanup()
