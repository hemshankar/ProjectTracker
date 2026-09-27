import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import rate_limits_collection
from app.models import now_ms
from app.services import rate_limit_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-rate-limit"
DOC_ID = f"{AGENT_ID}:gmail"


async def _reset():
    await rate_limits_collection.delete_one({"_id": DOC_ID})


async def test_bucket_starts_at_capacity_minus_one():
    await _reset()
    try:
        # capacity_for falls back to the config default (50/day) with no
        # agent_settings override in place.
        assert await rate_limit_service.try_consume(AGENT_ID, "gmail") is True
        doc = await rate_limits_collection.find_one({"_id": DOC_ID})
        assert doc["tokens"] == pytest.approx(49, abs=0.001)
    finally:
        await _reset()


async def test_bucket_blocks_once_drained():
    await _reset()
    try:
        await rate_limits_collection.insert_one({"_id": DOC_ID, "tokens": 0.0, "lastRefill": now_ms()})
        assert await rate_limit_service.try_consume(AGENT_ID, "gmail") is False
    finally:
        await _reset()
