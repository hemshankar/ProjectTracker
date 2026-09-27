import asyncio
import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.task_state import transition_task_status

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-race"
TASK_ID = "test-task-race"


async def _reset_board():
    await boards_collection.delete_one({"_id": BOARD_ID})
    await boards_collection.insert_one(
        {
            "_id": BOARD_ID,
            "agentId": "test-agent",
            "tasks": [
                {
                    "id": TASK_ID,
                    "text": "race me",
                    "status": "idle",
                    "statusReason": None,
                    "currentRunId": None,
                }
            ],
        }
    )


async def test_transition_task_status():
    await _reset_board()
    try:
        # A filter miss (task not in one of the expected statuses) is a no-op.
        miss = await transition_task_status(BOARD_ID, TASK_ID, ["running"], "done")
        assert miss is None
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["status"] == "idle"

        # Two concurrent transitions racing on the same idle->running move:
        # exactly one wins, the atomic compare-and-swap is the double-run guard.
        results = await asyncio.gather(
            *[
                transition_task_status(BOARD_ID, TASK_ID, ["idle", "queued"], "running")
                for _ in range(5)
            ]
        )
        successes = [r for r in results if r is not None]
        assert len(successes) == 1

        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["status"] == "running"
    finally:
        await boards_collection.delete_one({"_id": BOARD_ID})
