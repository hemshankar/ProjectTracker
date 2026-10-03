import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from app import chat_service, pricing
from app.accounting import chat_usage
from app.accounting.attribution import DispatchAttribution, UsageAttribution
from app.database import boards_collection, llm_calls_collection
from app.execution import dispatch
from app.execution.dispatch import LLMDispatchStrategy, SequentialDispatchStrategy
from app.services import budget_service, observability

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT, BOARD = "cu-agent", "cu-board"
BOARD_DOC = {"_id": BOARD, "agentId": AGENT, "title": "B", "tasks": [], "status": "idle"}


def message(text="hello", model="claude-haiku-4-5", i=100, o=40):
    return NS(model=model, content=[NS(type="text", text=text)],
              usage=NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeStream:
    def __init__(self, chunks, final=None, snapshot=None, fail_after=None, error=None):
        self.chunks, self.final, self.snapshot, self.fail_after, self.error = chunks, final, snapshot, fail_after, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def current_message_snapshot(self):
        if self.snapshot is None:
            raise AssertionError("no snapshot yet")
        return self.snapshot

    @property
    def text_stream(self):
        async def gen():
            if self.error is not None:
                raise self.error
            for c in self.chunks:
                yield c
        return gen()

    async def get_final_message(self):
        return self.final


def install(monkeypatch, stream):
    client = NS(messages=NS(stream=lambda **kw: stream))
    monkeypatch.setattr(chat_service, "_client", client)
    monkeypatch.setattr(pricing, "_TABLE", {})


async def clean():
    await llm_calls_collection.delete_many({"boardId": BOARD})
    await boards_collection.delete_one({"_id": BOARD})
    await llm_calls_collection.delete_many({"agentId": None, "callKind": "dispatch"})


async def rows():
    return await llm_calls_collection.find({"boardId": BOARD}).to_list(None)


async def collect(gen):
    return "".join([c async for c in gen])


async def test_chat_success_records_one_row(monkeypatch):
    install(monkeypatch, FakeStream(["hel", "lo"], final=message()))
    await clean()
    try:
        out = await collect(chat_service.stream_reply(BOARD_DOC, [{"role": "user", "text": "hi"}],
                                                      UsageAttribution("u1", "task-9")))
        assert out == "hello"
        [row] = await rows()
        assert (row["callKind"], row["taskId"], row["runId"], row["userId"], row["outcome"]) == (
            "chat", "task-9", None, "u1", "success")
        assert row["model"] == "claude-haiku-4-5" and row["inputTokens"] == 100 and row["usd"] > 0
    finally:
        await clean()


async def test_chat_without_task_has_null_task(monkeypatch):
    install(monkeypatch, FakeStream(["x"], final=message()))
    await clean()
    try:
        await collect(chat_service.stream_reply(BOARD_DOC, [], UsageAttribution("u1")))
        [row] = await rows()
        assert row["taskId"] is None
    finally:
        await clean()


async def test_recording_failure_never_breaks_the_reply(monkeypatch):
    install(monkeypatch, FakeStream(["full ", "reply"], final=message()))

    class Boom:
        async def record(self, **_):
            raise RuntimeError("db down")
    monkeypatch.setattr(chat_usage, "get_recorder", lambda: Boom())
    assert await collect(chat_service.stream_reply(BOARD_DOC, [], None)) == "full reply"


async def test_cancelled_mid_stream_records_partial_usage(monkeypatch):
    install(monkeypatch, FakeStream(["a", "b", "c"], snapshot=message(i=50, o=7)))
    await clean()
    try:
        gen = chat_service.stream_reply(BOARD_DOC, [], UsageAttribution("u1"))
        assert await gen.__anext__() == "a"
        await gen.aclose()  # client disconnect
        [row] = await rows()
        assert row["outcome"] == "cancelled" and row["outputTokens"] == 7 and row["inputTokens"] == 50
    finally:
        await clean()


async def test_cancelled_without_snapshot_records_nothing(monkeypatch, caplog):
    install(monkeypatch, FakeStream(["a", "b"], snapshot=None))
    await clean()
    try:
        gen = chat_service.stream_reply(BOARD_DOC, [], None)
        await gen.__anext__()
        with caplog.at_level("WARNING"):
            await gen.aclose()
        assert await rows() == [] and "no usage available" in caplog.text
    finally:
        await clean()


async def test_api_error_records_nothing_and_keeps_message(monkeypatch):
    req = httpx.Request("POST", "http://x")
    err = anthropic.APIStatusError("boom", response=httpx.Response(500, request=req), body=None)
    install(monkeypatch, FakeStream([], error=err))
    await clean()
    try:
        out = await collect(chat_service.stream_reply(BOARD_DOC, [], None))
        assert out == "Something went wrong reaching the assistant (500)."
        assert await rows() == []
    finally:
        await clean()


async def test_chat_blocked_when_cap_exceeded(monkeypatch):
    install(monkeypatch, FakeStream(["never"], final=message()))
    await clean()
    try:
        await boards_collection.insert_one({**BOARD_DOC, "budgetCapUsd": 0.01})
        await budget_service.record_llm_call(AGENT, BOARD, None, None, 0.5)
        out = await collect(chat_service.stream_reply(BOARD_DOC, [], None))
        assert out == chat_service.BUDGET_BLOCKED_MESSAGE
        assert len(await rows()) == 1  # only the seeded spend, no new call
    finally:
        await clean()


async def test_chat_spend_counts_toward_board_cap(monkeypatch):
    monkeypatch.setattr(pricing, "_TABLE", {"claude-haiku-4-5": pricing.PriceRates(1000.0, 1000.0)})
    install(monkeypatch, FakeStream(["x"], final=message(i=1000, o=1000)))
    monkeypatch.setattr(pricing, "_TABLE", {"claude-haiku-4-5": pricing.PriceRates(1000.0, 1000.0)})
    await clean()
    try:
        await boards_collection.insert_one({**BOARD_DOC, "budgetCapUsd": 1.0})
        await collect(chat_service.stream_reply(BOARD_DOC, [], None))
        assert await budget_service.check_exceeded(AGENT, BOARD) == "budget_exceeded"
    finally:
        await clean()


class _Messages:
    def __init__(self, text, response=None):
        self.text, self.response = text, response

    def stream(self, **kw):
        self.kw = kw
        return FakeStream([], final=self.response or message(self.text))


async def test_dispatch_records_board_level_row(monkeypatch):
    monkeypatch.setattr(pricing, "_TABLE", {})
    msgs = _Messages(json.dumps({"stages": [["a"], ["b"]]}))
    monkeypatch.setattr(dispatch, "get_client", lambda: NS(messages=msgs))
    await clean()
    try:
        tasks = [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}]
        await LLMDispatchStrategy().group(tasks, tasks, DispatchAttribution(AGENT, BOARD, "u7"))
        [row] = await rows()
        assert (row["callKind"], row["taskId"], row["runId"], row["userId"], row["agentId"]) == (
            "dispatch", None, None, "u7", AGENT)
        assert row["model"] == "claude-haiku-4-5" and msgs.kw["model"] == dispatch.DISPATCH_MODEL
    finally:
        await clean()


async def test_dispatch_recording_failure_does_not_change_grouping(monkeypatch):
    monkeypatch.setattr(dispatch, "get_client", lambda: NS(messages=_Messages(json.dumps({"stages": [["a", "b"]]}))))

    class Boom:
        async def record(self, **_):
            raise RuntimeError("x")
    monkeypatch.setattr(dispatch, "get_recorder", lambda: Boom())
    tasks = [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}]
    stages, _ = await LLMDispatchStrategy().group(tasks, tasks, DispatchAttribution(AGENT, BOARD))
    assert len(stages) == 1 and len(stages[0]) == 2  # the model's grouping, not the sequential fallback


async def test_non_llm_planner_records_nothing():
    await clean()
    await SequentialDispatchStrategy().group([{"id": "a"}], [{"id": "a"}], DispatchAttribution(AGENT, BOARD))
    assert await rows() == []


async def test_traces_filter_by_call_kind_and_null_ids_render(monkeypatch):
    await clean()
    try:
        await llm_calls_collection.insert_many([
            {"_id": "k1", "agentId": AGENT, "boardId": BOARD, "taskId": None, "runId": None,
             "callKind": "chat", "usd": 0.1, "ts": 1},
            {"_id": "k2", "agentId": AGENT, "boardId": BOARD, "taskId": "t", "runId": "r",
             "callKind": "task_run", "usd": 0.2, "ts": 2}])
        chat_rows = await observability.list_llm_calls(AGENT, board_id=BOARD, call_kind="chat")
        assert [c["id"] for c in chat_rows] == ["k1"] and chat_rows[0]["taskId"] is None
        assert len(await observability.list_llm_calls(AGENT, board_id=BOARD)) == 2
    finally:
        await llm_calls_collection.delete_many({"_id": {"$in": ["k1", "k2"]}})
        await clean()
