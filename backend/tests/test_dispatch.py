import json
import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.execution import dispatch
from app.execution.dispatch import LLMDispatchStrategy, SequentialDispatchStrategy

pytestmark = pytest.mark.asyncio(loop_scope="session")

TASKS = [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}, {"id": "c", "text": "three"}]


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeStream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self._response


class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def stream(self, **kwargs):
        return _FakeStream(_FakeResponse(self._text))


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


async def test_sequential_strategy_gives_one_stage_per_task():
    stages, held = await SequentialDispatchStrategy().group(TASKS, TASKS)
    assert stages == [[TASKS[0]], [TASKS[1]], [TASKS[2]]]
    assert held == []


async def test_llm_strategy_single_task_skips_the_model_call():
    stages, held = await LLMDispatchStrategy().group(TASKS[:1], TASKS[:1])
    assert stages == [[TASKS[0]]]
    assert held == []


async def test_llm_strategy_falls_back_without_a_configured_client():
    # No ANTHROPIC_API_KEY in the test environment, so `get_client()` is
    # None — the strategy must degrade to one stage per task, never raise.
    stages, held = await LLMDispatchStrategy().group(TASKS, TASKS)
    assert sum(len(stage) for stage in stages) == len(TASKS)
    assert {t["id"] for stage in stages for t in stage} == {"a", "b", "c"}
    assert held == []


async def test_llm_strategy_holds_back_a_task_dependent_on_a_paused_one(monkeypatch):
    reply = json.dumps({"stages": [["a"], ["b"]], "held": ["c"]})
    monkeypatch.setattr(dispatch, "get_client", lambda: _FakeClient(reply))

    paused_task = {"id": "z", "text": "blocked prerequisite", "status": "awaiting_clarification"}
    stages, held = await LLMDispatchStrategy().group(TASKS, TASKS + [paused_task])

    staged_ids = {t["id"] for stage in stages for t in stage}
    assert staged_ids == {"a", "b"}
    assert held == ["c"]


async def test_llm_strategy_treats_unlisted_ready_task_as_a_safety_net_stage(monkeypatch):
    # The model forgot to place "c" anywhere (not staged, not held) — it must
    # still run, since an incomplete response is different from an explicit hold.
    reply = json.dumps({"stages": [["a"], ["b"]]})
    monkeypatch.setattr(dispatch, "get_client", lambda: _FakeClient(reply))

    stages, held = await LLMDispatchStrategy().group(TASKS, TASKS)
    staged_ids = {t["id"] for stage in stages for t in stage}
    assert staged_ids == {"a", "b", "c"}
    assert held == []
