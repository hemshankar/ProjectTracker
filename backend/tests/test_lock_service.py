import asyncio
import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import resource_locks_collection
from app.services import lock_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

RESOURCE_KEY = "calendar:test-event|2026-01-05T09:00"


async def _reset():
    await resource_locks_collection.delete_one({"_id": RESOURCE_KEY})


async def test_only_one_racing_run_acquires_the_lock():
    await _reset()
    try:
        results = await asyncio.gather(
            *[lock_service.try_acquire(RESOURCE_KEY, f"run-{i}") for i in range(5)]
        )
        assert sum(1 for r in results if r) == 1
    finally:
        await _reset()


async def test_release_then_reacquire():
    await _reset()
    try:
        assert await lock_service.try_acquire(RESOURCE_KEY, "run-a") is True
        assert await lock_service.try_acquire(RESOURCE_KEY, "run-b") is False

        await lock_service.release(RESOURCE_KEY, "run-a")
        assert await lock_service.try_acquire(RESOURCE_KEY, "run-b") is True
    finally:
        await _reset()


async def test_expired_lock_can_be_taken_over():
    await _reset()
    try:
        assert await lock_service.try_acquire(RESOURCE_KEY, "run-a", ttl_ms=-1) is True
        # Already expired (negative TTL), so a new run can immediately take it.
        assert await lock_service.try_acquire(RESOURCE_KEY, "run-b") is True
    finally:
        await _reset()
