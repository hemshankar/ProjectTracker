import asyncio
import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.task_state import transition_board_status

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-start-race"


async def _reset_board():
    await boards_collection.delete_one({"_id": BOARD_ID})
    await boards_collection.insert_one(
        {
            "_id": BOARD_ID,
            "agentId": "test-agent",
            "status": "idle",
            "stopRequested": False,
            "tasks": [],
        }
    )


async def test_transition_board_status():
    await _reset_board()
    try:
        # A filter miss (board not in one of the expected statuses) is a no-op.
        miss = await transition_board_status(BOARD_ID, ["running"], "done")
        assert miss is None
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["status"] == "idle"

        # Two concurrent Start clicks racing on the same idle->queued move:
        # exactly one wins — the same compare-and-swap guard as tasks, at the
        # board level, so a board can never end up double-running.
        results = await asyncio.gather(
            *[
                transition_board_status(BOARD_ID, ["idle", "stopped", "failed", "blocked"], "queued")
                for _ in range(5)
            ]
        )
        successes = [r for r in results if r is not None]
        assert len(successes) == 1

        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["status"] == "queued"
    finally:
        await boards_collection.delete_one({"_id": BOARD_ID})
