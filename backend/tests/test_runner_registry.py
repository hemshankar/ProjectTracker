import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import asyncio

import pytest

from app.execution.registry import RunnerRegistry

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_board_ids_lists_registered_boards():
    registry = RunnerRegistry()

    async def forever():
        await asyncio.Event().wait()

    task = asyncio.create_task(forever())
    registry.register("board-1", task)

    assert registry.board_ids() == ["board-1"]
    assert registry.is_running("board-1") is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_all_cancels_and_awaits_tracked_tasks():
    registry = RunnerRegistry()
    cancelled = asyncio.Event()

    async def forever():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(forever())
    registry.register("board-1", task)
    await asyncio.sleep(0)  # let the task actually start before cancelling it

    await registry.cancel_all(timeout=1.0)

    assert cancelled.is_set()
    assert task.cancelled()


async def test_cancel_all_is_a_noop_with_no_tracked_tasks():
    registry = RunnerRegistry()
    await registry.cancel_all(timeout=1.0)
