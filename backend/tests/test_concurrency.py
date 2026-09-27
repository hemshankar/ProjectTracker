import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import agent_settings_collection, task_runs_collection
from app.execution import concurrency

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-concurrency"


async def _reset(cap):
    await agent_settings_collection.delete_one({"_id": AGENT_ID})
    await task_runs_collection.delete_many({"agentId": AGENT_ID})
    await agent_settings_collection.insert_one({"_id": AGENT_ID, "concurrency": {"maxConcurrentTasks": cap}})


async def test_no_cap_means_unlimited():
    await _reset(cap=None)
    try:
        for i in range(5):
            await task_runs_collection.insert_one({"_id": f"run-{i}", "agentId": AGENT_ID, "status": "running"})
        assert await concurrency.has_capacity(AGENT_ID) is True
    finally:
        await _reset(cap=None)


async def test_capacity_is_available_under_cap():
    await _reset(cap=2)
    try:
        await task_runs_collection.insert_one({"_id": "run-a", "agentId": AGENT_ID, "status": "running"})
        assert await concurrency.has_capacity(AGENT_ID) is True
    finally:
        await _reset(cap=None)


async def test_capacity_exhausted_at_cap():
    await _reset(cap=2)
    try:
        await task_runs_collection.insert_many([
            {"_id": "run-a", "agentId": AGENT_ID, "status": "running"},
            {"_id": "run-b", "agentId": AGENT_ID, "status": "running"},
        ])
        assert await concurrency.has_capacity(AGENT_ID) is False
    finally:
        await _reset(cap=None)


async def test_finished_runs_dont_count_against_the_cap():
    await _reset(cap=1)
    try:
        await task_runs_collection.insert_many([
            {"_id": "run-a", "agentId": AGENT_ID, "status": "done"},
            {"_id": "run-b", "agentId": AGENT_ID, "status": "failed"},
        ])
        assert await concurrency.has_capacity(AGENT_ID) is True
    finally:
        await _reset(cap=None)
