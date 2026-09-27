import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import task_runs_collection
from app.task_state import INTERRUPTED_REASON, reconcile_orphaned_task_runs

pytestmark = pytest.mark.asyncio(loop_scope="session")

SUBAGENT_RUN_ID = "test-run-orphaned-subagent"
PRIMARY_RUN_ID = "test-run-orphaned-primary"
DONE_RUN_ID = "test-run-already-done"


async def _cleanup():
    await task_runs_collection.delete_many(
        {"_id": {"$in": [SUBAGENT_RUN_ID, PRIMARY_RUN_ID, DONE_RUN_ID]}}
    )


async def test_reconcile_closes_orphaned_subagent_run():
    await _cleanup()
    await task_runs_collection.insert_one(
        {
            "_id": SUBAGENT_RUN_ID,
            "boardId": "test-board",
            "taskId": "t1",
            "status": "running",
            "endedAt": None,
            "parentRunId": PRIMARY_RUN_ID,
            "kind": "subagent",
        }
    )
    try:
        count = await reconcile_orphaned_task_runs()
        assert count == 1

        run = await task_runs_collection.find_one({"_id": SUBAGENT_RUN_ID})
        assert run["status"] == "failed"
        assert run["endedAt"] is not None
        assert run["error"] == INTERRUPTED_REASON
    finally:
        await _cleanup()


async def test_reconcile_leaves_finished_runs_untouched():
    await _cleanup()
    await task_runs_collection.insert_one(
        {
            "_id": DONE_RUN_ID,
            "boardId": "test-board",
            "taskId": "t1",
            "status": "done",
            "endedAt": 123,
            "parentRunId": None,
            "kind": "primary",
        }
    )
    try:
        await reconcile_orphaned_task_runs()
        run = await task_runs_collection.find_one({"_id": DONE_RUN_ID})
        assert run["status"] == "done"
        assert run["endedAt"] == 123
    finally:
        await _cleanup()
