import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest
from fastapi import HTTPException

from app.database import agent_settings_collection, boards_collection, task_runs_collection
from app.services import tasks_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-run-single-task"
BOARD_ID = "test-board-run-single-task"
TASK_ID = "test-task-run-single-task"


async def _reset(task_status="idle", status_reason=None):
    await boards_collection.delete_many({"_id": BOARD_ID})
    await agent_settings_collection.delete_one({"_id": AGENT_ID})
    await task_runs_collection.delete_many({"agentId": AGENT_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": AGENT_ID,
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [{
            "id": TASK_ID, "text": "do a thing", "status": task_status,
            "statusReason": status_reason, "currentRunId": "stale-run-id" if task_status != "idle" else None,
        }],
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
    })


async def test_prepare_task_for_run_refuses_non_runnable_status():
    await _reset(task_status="running")
    try:
        with pytest.raises(HTTPException) as exc_info:
            await tasks_service.prepare_task_for_run(BOARD_ID, TASK_ID, "test-user")
        assert exc_info.value.status_code == 409
    finally:
        await _reset()


async def test_prepare_task_for_run_refuses_at_concurrency_cap():
    await _reset(task_status="idle")
    try:
        await agent_settings_collection.insert_one(
            {"_id": AGENT_ID, "concurrency": {"maxConcurrentTasks": 1}}
        )
        await task_runs_collection.insert_one(
            {"_id": "other-run", "agentId": AGENT_ID, "status": "running"}
        )
        with pytest.raises(HTTPException) as exc_info:
            await tasks_service.prepare_task_for_run(BOARD_ID, TASK_ID, "test-user")
        assert exc_info.value.status_code == 409

        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["status"] == "idle"
    finally:
        await _reset()


async def test_prepare_task_for_run_resets_a_failed_task_to_idle():
    await _reset(task_status="failed", status_reason="boom")
    try:
        reset = await tasks_service.prepare_task_for_run(BOARD_ID, TASK_ID, "test-user")
        task = next(t for t in reset["tasks"] if t["id"] == TASK_ID)
        assert task["status"] == "idle"
        assert task["statusReason"] is None
        assert task["currentRunId"] is None
    finally:
        await _reset()
