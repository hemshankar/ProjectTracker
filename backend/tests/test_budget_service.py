import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection, llm_calls_collection
from app.services import budget_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-budget"
AGENT_ID = "test-agent-budget"


async def _reset(board_cap):
    await boards_collection.delete_one({"_id": BOARD_ID})
    await llm_calls_collection.delete_many({"boardId": BOARD_ID})
    await boards_collection.insert_one(
        {"_id": BOARD_ID, "agentId": AGENT_ID, "status": "running", "tasks": [], "budgetCapUsd": board_cap}
    )


async def test_under_cap_is_not_exceeded():
    await _reset(board_cap=1.0)
    try:
        await budget_service.record_llm_call(AGENT_ID, BOARD_ID, "t1", "r1", 0.1)
        assert await budget_service.check_exceeded(AGENT_ID, BOARD_ID) is None
    finally:
        await boards_collection.delete_one({"_id": BOARD_ID})
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})


async def test_board_cap_exceeded_stops_gracefully():
    await _reset(board_cap=0.05)
    try:
        await budget_service.record_llm_call(AGENT_ID, BOARD_ID, "t1", "r1", 0.1)
        # The in-flight call that pushed spend over the cap already recorded —
        # the *next* check is what halts the board, never the one in progress.
        assert await budget_service.check_exceeded(AGENT_ID, BOARD_ID) == "budget_exceeded"
    finally:
        await boards_collection.delete_one({"_id": BOARD_ID})
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})


async def test_no_cap_means_unlimited():
    await _reset(board_cap=None)
    try:
        await budget_service.record_llm_call(AGENT_ID, BOARD_ID, "t1", "r1", 1000.0)
        assert await budget_service.check_exceeded(AGENT_ID, BOARD_ID) is None
    finally:
        await boards_collection.delete_one({"_id": BOARD_ID})
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})
