import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

from types import SimpleNamespace as NS

import pytest

from app import pricing
from app.accounting.context import UsageContextResolver, _TtlCache
from app.accounting.recorder import UsageRecorder
from app.database import agents_collection, boards_collection, llm_calls_collection, task_runs_collection
from app.execution import tracing

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT, BOARD, TASK, RUN, SUB = "ur-agent", "ur-board", "ur-task", "ur-run", "ur-sub"
PARENT = "ur-parent"


def response(model="claude-haiku-4-5", **usage):
    base = dict(input_tokens=1000, output_tokens=500, cache_read_input_tokens=200,
                cache_creation_input_tokens=100, server_tool_use=NS(web_search_requests=1))
    return NS(model=model, content=[NS(type="text", text="ok")], usage=NS(**{**base, **usage}))


async def clean():
    await llm_calls_collection.delete_many({"boardId": BOARD})
    await boards_collection.delete_one({"_id": BOARD})
    await agents_collection.delete_one({"_id": AGENT})
    await task_runs_collection.delete_many({"_id": {"$in": [RUN, PARENT]}})


async def seed():
    await agents_collection.insert_one({"_id": AGENT, "name": "Ops Workspace"})
    await boards_collection.insert_one({"_id": BOARD, "agentId": AGENT, "title": "Launch", "status": "running",
                                        "tasks": [{"id": TASK, "text": "Write the plan"}]})
    await task_runs_collection.insert_one({"_id": RUN, "startedBy": "user-1", "boardId": BOARD})


async def record(recorder, **kw):
    args = dict(agent_id=AGENT, board_id=BOARD, task_id=TASK, run_id=RUN, response=response(),
                system_prompt="s", request_messages=[], tool_call=None, latency_ms=5.0, response_text="ok")
    return await recorder.record(**{**args, **kw})


async def test_row_has_new_fields_and_priced_per_model(monkeypatch):
    table = {"claude-haiku-4-5": pricing.PriceRates(1.0, 5.0, 0.1, 1.25, 0.01)}
    monkeypatch.setattr(pricing, "_TABLE", table)
    await clean()
    try:
        await seed()
        doc = await record(UsageRecorder())
        row = await llm_calls_collection.find_one({"_id": doc["_id"]})
        assert row["model"] == "claude-haiku-4-5" and row["callKind"] == "task_run"
        assert (row["cacheReadTokens"], row["cacheCreationTokens"], row["webSearchCount"]) == (200, 100, 1)
        expected = (1000 * 1.0 + 500 * 5.0 + 200 * 0.1 + 100 * 1.25) / 1e6 + 0.01
        assert row["usd"] == pytest.approx(expected)
        assert row["rates"]["cacheWrite"] == 1.25 and row["pricedByFallback"] is False
        assert row["userId"] == "user-1"
    finally:
        await clean()


async def test_unknown_model_flagged_and_subagent_kind_inherits_user(monkeypatch):
    monkeypatch.setattr(pricing, "_TABLE", {})
    await clean()
    try:
        await seed()
        await task_runs_collection.insert_one({"_id": PARENT, "startedBy": "user-9", "boardId": BOARD})
        doc = await record(UsageRecorder(), run_id=SUB, parent_run_id=PARENT, response=response(model="brand-new"))
        row = await llm_calls_collection.find_one({"_id": doc["_id"]})
        assert row["pricedByFallback"] is True and row["callKind"] == "subagent" and row["userId"] == "user-9"
    finally:
        await clean()


async def test_failures_in_context_or_event_never_raise_and_row_is_written():
    class Boom:
        async def resolve(self, **_):
            raise RuntimeError("db hiccup")

    class BadBuilder:
        def build(self, *a, **k):
            raise RuntimeError("bad event")

    await clean()
    try:
        doc = await record(UsageRecorder(resolver=Boom(), builder=BadBuilder()))
        assert await llm_calls_collection.find_one({"_id": doc["_id"]}) is not None
    finally:
        await clean()


async def test_context_snapshots_names_and_caches():
    await clean()
    try:
        await seed()
        resolver = UsageContextResolver(_TtlCache())
        ctx = await resolver.resolve(agent_id=AGENT, board_id=BOARD, task_id=TASK, run_id=RUN,
                                     parent_run_id=None, call_kind="task_run")
        assert (ctx.agent_name, ctx.board_title, ctx.task_title, ctx.user_id) == (
            "Ops Workspace", "Launch", "Write the plan", "user-1")
        await boards_collection.delete_one({"_id": BOARD})  # cached: still resolves within the TTL
        assert (await resolver.resolve(agent_id=AGENT, board_id=BOARD, task_id=TASK, run_id=RUN,
                                       parent_run_id=None, call_kind="task_run")).board_title == "Launch"
    finally:
        await clean()


async def test_deleted_board_yields_nulls():
    ctx = await UsageContextResolver(_TtlCache()).resolve(
        agent_id="gone", board_id="gone-board", task_id="t", run_id=None, parent_run_id=None, call_kind="chat")
    assert ctx.board_title is None and ctx.task_title is None and ctx.agent_name is None and ctx.user_id is None


async def test_ttl_cache_expires():
    now = [0.0]
    cache, calls = _TtlCache(ttl=10, clock=lambda: now[0]), []

    async def load():
        calls.append(1)
        return len(calls)
    assert await cache.get("k", load) == 1 and await cache.get("k", load) == 1
    now[0] = 11
    assert await cache.get("k", load) == 2


async def test_summary_has_usage_fields_and_old_rows_render():
    await clean()
    try:
        await seed()
        await tracing.record_call(agent_id=AGENT, board_id=BOARD, task_id=TASK, run_id=RUN, response=response(),
                                  system_prompt="s", request_messages=[], tool_call=None, latency_ms=1.0)
        from app.services import observability
        await llm_calls_collection.insert_one({"_id": "old-row", "agentId": AGENT, "boardId": BOARD,
                                               "taskId": TASK, "usd": 0.5, "ts": 1})
        calls = await observability.list_llm_calls(AGENT, board_id=BOARD)
        assert {c["id"] for c in calls} >= {"old-row"} and len(calls) == 2
        assert (await observability.get_llm_call(AGENT, "old-row"))["usd"] == 0.5
        assert [c for c in calls if c["id"] != "old-row"][0]["model"] == "claude-haiku-4-5"
    finally:
        await clean()
