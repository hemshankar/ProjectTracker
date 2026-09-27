import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

from types import SimpleNamespace

import pytest

from app.database import llm_calls_collection
from app.execution import tracing
from app.execution.events import events

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-tracing"
BOARD_ID = "test-board-tracing"
TASK_ID = "test-task-tracing"
RUN_ID = "test-run-tracing"


def _fake_response(text="Done.", usage_tokens=(10, 5)):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=usage_tokens[0], output_tokens=usage_tokens[1]) if usage_tokens else None,
    )


async def test_record_call_inserts_full_detail_and_computes_usd():
    await llm_calls_collection.delete_many({"boardId": BOARD_ID})
    try:
        await tracing.record_call(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID, run_id=RUN_ID,
            response=_fake_response(), system_prompt="You are an agent.",
            request_messages=[{"role": "user", "content": "go"}],
            tool_call={"name": "search_notes", "params": {"query": "x"}, "result": "ok", "status": "done"},
            latency_ms=123.4,
        )
        doc = await llm_calls_collection.find_one({"boardId": BOARD_ID})
        assert doc["agentId"] == AGENT_ID
        assert doc["taskId"] == TASK_ID
        assert doc["runId"] == RUN_ID
        assert doc["systemPrompt"] == "You are an agent."
        assert doc["response"] == "Done."
        assert doc["toolCalls"] == [{"name": "search_notes", "params": {"query": "x"}, "result": "ok", "status": "done"}]
        assert doc["inputTokens"] == 10
        assert doc["outputTokens"] == 5
        assert doc["usd"] > 0
        assert doc["latencyMs"] == 123.4
        assert doc["expiresAt"] > doc["ts"]
    finally:
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})


async def test_record_call_publishes_live_tail_summary():
    await llm_calls_collection.delete_many({"boardId": BOARD_ID})
    queue = events.subscribe(BOARD_ID)
    try:
        await tracing.record_call(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID, run_id=RUN_ID,
            response=_fake_response(), system_prompt="sys", request_messages=[],
            tool_call=None, latency_ms=5.0,
        )
        event = await queue.get()
        assert event["boardId"] == BOARD_ID
        assert event["llmCall"]["taskId"] == TASK_ID
        assert event["llmCall"]["status"] == "done"
        assert event["llmCall"]["tool"] is None
    finally:
        events.unsubscribe(BOARD_ID, queue)
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})


async def test_record_call_handles_missing_usage():
    await llm_calls_collection.delete_many({"boardId": BOARD_ID})
    try:
        await tracing.record_call(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID, run_id=RUN_ID,
            response=_fake_response(usage_tokens=None), system_prompt="sys",
            request_messages=[], tool_call=None, latency_ms=1.0,
        )
        doc = await llm_calls_collection.find_one({"boardId": BOARD_ID})
        assert doc["usd"] == 0.0
        assert doc["inputTokens"] == 0
        assert doc["outputTokens"] == 0
    finally:
        await llm_calls_collection.delete_many({"boardId": BOARD_ID})
