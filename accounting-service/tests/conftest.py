import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import config, container as container_module
from app.container import build_container
from app.database import ensure_indexes
from app.main import app

KEY = "test-key"


@pytest.fixture
async def container(monkeypatch):
    monkeypatch.setattr(config, "ACCOUNTING_SERVICE_KEY", KEY)
    c = build_container(AsyncMongoMockClient()["test"])
    await ensure_indexes(c.db)
    monkeypatch.setattr(container_module, "_container", c)
    return c


@pytest.fixture
async def client(container):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def auth():
    return {"X-Internal-Key": KEY}


def make_event(call_id="c1", **overrides) -> dict:
    base = {"callId": call_id, "ts": 1_700_000_000_000, "agentId": "a1", "callKind": "task_run",
            "boardId": "b1", "taskId": "t1", "model": "claude-sonnet-5",
            "inputTokens": 100, "outputTokens": 50, "usd": 0.001}
    return {**base, **overrides}
