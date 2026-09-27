import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import audit_log_collection, llm_calls_collection
from app.services import observability

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-observability"
OTHER_AGENT_ID = "test-agent-observability-other"
BOARD_ID = "test-board-observability"
OTHER_BOARD_ID = "test-board-observability-other"


async def _reset():
    await audit_log_collection.delete_many({"agentId": {"$in": [AGENT_ID, OTHER_AGENT_ID]}})
    await llm_calls_collection.delete_many({"agentId": {"$in": [AGENT_ID, OTHER_AGENT_ID]}})


async def _seed_audit():
    await audit_log_collection.insert_many([
        {
            "_id": "audit-1", "agentId": AGENT_ID, "boardId": BOARD_ID, "taskId": "t1",
            "entityType": "task", "action": "update", "actorType": "human", "actorId": "u1",
            "before": {"status": "idle"}, "after": {"status": "running"}, "undoRedo": False, "ts": 100,
        },
        {
            "_id": "audit-2", "agentId": AGENT_ID, "boardId": OTHER_BOARD_ID, "taskId": "t2",
            "entityType": "task", "action": "update", "actorType": "agent", "actorId": None,
            "before": {}, "after": {}, "undoRedo": False, "ts": 200,
        },
        {
            "_id": "audit-3", "agentId": OTHER_AGENT_ID, "boardId": "unrelated-board", "taskId": "t3",
            "entityType": "board", "action": "create", "actorType": "human", "actorId": "u2",
            "before": None, "after": {}, "undoRedo": False, "ts": 300,
        },
    ])


async def _seed_llm_calls():
    await llm_calls_collection.insert_many([
        {
            "_id": "call-1", "agentId": AGENT_ID, "boardId": BOARD_ID, "taskId": "t1",
            "runId": "run-1", "parentRunId": None, "systemPrompt": "sys", "messages": [],
            "response": "hi", "toolCalls": [{"name": "search_notes", "params": {}, "status": "done"}],
            "usd": 0.01, "inputTokens": 10, "outputTokens": 5, "latencyMs": 42.0, "ts": 100,
        },
        {
            "_id": "call-2", "agentId": AGENT_ID, "boardId": OTHER_BOARD_ID, "taskId": "t2",
            "runId": "run-2", "parentRunId": "run-1", "systemPrompt": "sys2", "messages": [],
            "response": "", "toolCalls": [], "usd": 0.02, "inputTokens": 20, "outputTokens": 10,
            "latencyMs": 10.0, "ts": 200,
        },
        {
            "_id": "call-3", "agentId": OTHER_AGENT_ID, "boardId": "unrelated-board", "taskId": "t3",
            "runId": "run-3", "parentRunId": None, "systemPrompt": "", "messages": [],
            "response": "", "toolCalls": [], "usd": 0.0, "inputTokens": 0, "outputTokens": 0,
            "latencyMs": 1.0, "ts": 300,
        },
    ])


async def test_list_audit_scopes_to_agent_and_filters_by_board():
    await _reset()
    await _seed_audit()
    try:
        rows = await observability.list_audit(AGENT_ID)
        assert {r["id"] for r in rows} == {"audit-1", "audit-2"}
        assert rows[0]["ts"] >= rows[-1]["ts"]  # newest first

        scoped = await observability.list_audit(AGENT_ID, board_id=BOARD_ID)
        assert [r["id"] for r in scoped] == ["audit-1"]

        by_actor = await observability.list_audit(AGENT_ID, actor_type="agent")
        assert [r["id"] for r in by_actor] == ["audit-2"]
    finally:
        await _reset()


async def test_list_board_audit_is_board_scoped_regardless_of_agent():
    await _reset()
    await _seed_audit()
    try:
        rows = await observability.list_board_audit(BOARD_ID)
        assert [r["id"] for r in rows] == ["audit-1"]
    finally:
        await _reset()


async def test_list_llm_calls_returns_summaries_scoped_to_agent():
    await _reset()
    await _seed_llm_calls()
    try:
        rows = await observability.list_llm_calls(AGENT_ID)
        assert [r["id"] for r in rows] == ["call-1", "call-2"]  # oldest first
        assert rows[0]["tool"] == "search_notes"
        assert rows[0]["status"] == "done"
        assert rows[1]["tool"] is None
        assert "systemPrompt" not in rows[0]  # summary omits full-detail fields

        by_board = await observability.list_llm_calls(AGENT_ID, board_id=OTHER_BOARD_ID)
        assert [r["id"] for r in by_board] == ["call-2"]
        assert by_board[0]["parentRunId"] == "run-1"
    finally:
        await _reset()


async def test_get_llm_call_returns_full_detail_scoped_to_agent():
    await _reset()
    await _seed_llm_calls()
    try:
        call = await observability.get_llm_call(AGENT_ID, "call-1")
        assert call["systemPrompt"] == "sys"
        assert call["toolCalls"][0]["name"] == "search_notes"

        # Scoped to the right Agent — another Agent's own call id is a 404,
        # not a cross-Agent leak.
        assert await observability.get_llm_call(OTHER_AGENT_ID, "call-1") is None
    finally:
        await _reset()
