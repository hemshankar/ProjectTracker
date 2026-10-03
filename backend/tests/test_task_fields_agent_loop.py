import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection, task_revisions_collection, task_runs_collection
from app.execution import agent_service
from app.execution.loop import AgentRunner
from app.services import task_fields_service as svc
from app.task_fields import DESCRIPTION, SUMMARY

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-fields-loop"
TASK_ID = "test-task-fields-loop"
AGENT_ID = "test-agent-fields-loop"


class _Block:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items()}


class _Response:
    def __init__(self, *blocks):
        self.content = list(blocks)


def _tool(name, tool_id, **params):
    return _Response(_Block("tool_use", id=tool_id, name=name, input=params))


def _text(text):
    return _Response(_Block("text", text=text))


class _ScriptedStream:
    def __init__(self, response, seen):
        self._response, self._seen = response, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def empty():
            return
            yield ""  # pragma: no cover
        return empty()

    async def get_final_message(self):
        return self._response


class _ScriptedClient:
    """Plays back canned model turns and records each call's system prompt."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.system_prompts = []
        self.messages = self

    def stream(self, **kwargs):
        self.system_prompts.append(kwargs["system"])
        return _ScriptedStream(self._responses.pop(0), self)


async def _reset(description=None):
    await boards_collection.delete_many({"_id": BOARD_ID})
    await task_runs_collection.delete_many({"boardId": BOARD_ID})
    await task_revisions_collection.delete_many({"taskId": TASK_ID})
    task = {"id": TASK_ID, "text": "plan the offsite", "status": "idle", "statusReason": None, "currentRunId": None}
    await boards_collection.insert_one({
        "_id": BOARD_ID, "agentId": AGENT_ID, "ownerId": "u", "title": "Board", "tasks": [task],
        "chats": [], "activeChatId": None, "status": "idle", "stopRequested": False,
    })
    if description:
        await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, description, 0, "human", "u")


async def _run(monkeypatch, responses):
    client = _ScriptedClient(responses)
    monkeypatch.setattr(agent_service, "get_client", lambda: client)
    await AgentRunner(board_id=BOARD_ID, agent_id=AGENT_ID).run_task_by_id(TASK_ID)
    board = await boards_collection.find_one({"_id": BOARD_ID})
    return client, next(t for t in board["tasks"] if t["id"] == TASK_ID)


async def test_agent_updates_description_and_writes_its_own_summary(monkeypatch):
    await _reset(description="Venue: TBD")
    client, task = await _run(monkeypatch, [
        _tool("update_task_description", "tu1", content="Venue: TBD\nBudget: $5k", base_version=1),
        _tool("set_execution_summary", "tu2", summary="Planned the offsite; budget set to $5k."),
        _text("All done."),
    ])
    assert task["status"] == "done"
    desc = await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION)
    assert desc["version"] == 2 and "Budget: $5k" in desc["content"]
    summary = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert summary["content"] == "Planned the offsite; budget set to $5k."
    assert summary["status"] == "done"
    assert summary["version"] == 1  # the agent's own text stood; no fallback overwrote it
    assert "Venue: TBD" in client.system_prompts[0] and "current version: 1" in client.system_prompts[0]


async def test_run_without_agent_summary_gets_fallback_summary(monkeypatch):
    await _reset()
    _, task = await _run(monkeypatch, [_text("Finished everything you asked.")])
    assert task["status"] == "done"
    summary = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert summary["status"] == "done"
    assert "Finished everything you asked." in summary["content"]


async def test_refused_overwrite_is_fed_back_to_the_model_not_applied(monkeypatch):
    await _reset(description="keep this line\nand this one")
    _, task = await _run(monkeypatch, [
        _tool("update_task_description", "tu1", content="only this", base_version=1),
        _text("Understood, leaving it."),
    ])
    assert task["status"] == "done"
    desc = await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION)
    assert desc["version"] == 1 and "keep this line" in desc["content"]


async def test_failed_run_gets_a_failed_summary(monkeypatch):
    await _reset()
    client = _ScriptedClient([])  # an exhausted script makes the model call raise -> the task fails
    monkeypatch.setattr(agent_service, "get_client", lambda: client)
    await AgentRunner(board_id=BOARD_ID, agent_id=AGENT_ID).run_task_by_id(TASK_ID)
    board = await boards_collection.find_one({"_id": BOARD_ID})
    task = next(t for t in board["tasks"] if t["id"] == TASK_ID)
    assert task["status"] == "failed"
    summary = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert summary["status"] == "failed" and summary["version"] == 1
