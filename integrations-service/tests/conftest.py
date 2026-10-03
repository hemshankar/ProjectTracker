import pytest
from mongomock_motor import AsyncMongoMockClient

from app.backends.fake_backend import FakeBackend
from app.container import build_container
from app.database import ensure_indexes


@pytest.fixture
def fake():
    return FakeBackend()


@pytest.fixture
async def container(fake):
    c = build_container(AsyncMongoMockClient()["test"], {"composio": fake})
    await ensure_indexes(c.db)
    await c.providers.seed()
    return c
