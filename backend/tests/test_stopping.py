import asyncio
import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection, task_runs_collection
from app.execution import agent_service, stopping
from app.execution.loop import AgentRunner

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-stopping"
TASK_ID = "test-task-stopping"
AGENT_ID = "test-agent-stopping"


class _HangingStream:
    """Never actually returns a response — proves cancellation interrupts
    the in-flight model call rather than waiting for it to finish."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        await asyncio.Event().wait()


class _HangingMessages:
    def stream(self, **kwargs):
        return _HangingStream()


class _HangingClient:
    def __init__(self):
        self.messages = _HangingMessages()


async def _reset(task_status="idle", run_id=None):
    await boards_collection.delete_many({"_id": BOARD_ID})
    await task_runs_collection.delete_many({"boardId": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": AGENT_ID,
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [{
            "id": TASK_ID, "text": "do a thing", "status": task_status,
            "statusReason": None, "currentRunId": run_id,
        }],
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
    })


async def _get_task():
    board = await boards_collection.find_one({"_id": BOARD_ID})
    return next(t for t in board["tasks"] if t["id"] == TASK_ID)


async def test_stop_task_raises_for_a_non_stoppable_status():
    await _reset(task_status="idle")
    try:
        with pytest.raises(ValueError):
            await stopping.stop_task(BOARD_ID, TASK_ID, "test-user")
    finally:
        await _reset()


async def test_stop_task_resolves_a_suspended_task_directly():
    await _reset(task_status="awaiting_clarification", run_id="test-run-suspended")
    try:
        await task_runs_collection.insert_one(
            {"_id": "test-run-suspended", "boardId": BOARD_ID, "taskId": TASK_ID, "status": "running", "endedAt": None}
        )
        status = await stopping.stop_task(BOARD_ID, TASK_ID, "test-user")
        assert status == "stopped"

        task = await _get_task()
        assert task["status"] == "stopped"
        assert task["currentRunId"] is None
    finally:
        await _reset()


async def test_stop_task_cancels_a_genuinely_in_flight_task(monkeypatch):
    await _reset()
    try:
        monkeypatch.setattr(agent_service, "get_client", lambda: _HangingClient())
        runner = AgentRunner(BOARD_ID, AGENT_ID)
        bg = asyncio.create_task(runner.run_task_by_id(TASK_ID))
        try:
            task = None
            for _ in range(100):
                task = await _get_task()
                if task["status"] == "running":
                    break
                await asyncio.sleep(0.02)
            assert task is not None and task["status"] == "running"
            run_id = task["currentRunId"]
            assert run_id is not None

            status = await stopping.stop_task(BOARD_ID, TASK_ID, "test-user")
            assert status == "stopped"
            await asyncio.wait_for(bg, timeout=2.0)

            task = await _get_task()
            assert task["status"] == "stopped"
            assert task["currentRunId"] is None

            run = await task_runs_collection.find_one({"_id": run_id})
            assert run["status"] == "stopped"
        finally:
            if not bg.done():
                bg.cancel()
    finally:
        await _reset()
