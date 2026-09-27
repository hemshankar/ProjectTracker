import asyncio

import pytest

from app.execution.events import BoardEventBus

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_publish_stamps_board_id_even_when_event_omits_it():
    bus = BoardEventBus()
    queue = bus.subscribe("board-a")
    await bus.publish("board-a", {"taskId": "task-1", "status": "running"})
    event = queue.get_nowait()
    assert event == {"boardId": "board-a", "taskId": "task-1", "status": "running"}


async def test_subscribe_many_fans_multiple_boards_into_one_shared_queue():
    bus = BoardEventBus()
    queue = asyncio.Queue()
    bus.subscribe_many(["board-a", "board-b"], queue)

    await bus.publish("board-a", {"status": "queued"})
    await bus.publish("board-b", {"status": "running"})

    first = await queue.get()
    second = await queue.get()
    assert {first["boardId"], second["boardId"]} == {"board-a", "board-b"}


async def test_unsubscribe_many_stops_delivery_to_all_listed_boards():
    bus = BoardEventBus()
    queue = asyncio.Queue()
    bus.subscribe_many(["board-a", "board-b"], queue)
    bus.unsubscribe_many(["board-a", "board-b"], queue)

    await bus.publish("board-a", {"status": "queued"})
    await bus.publish("board-b", {"status": "running"})

    assert queue.empty()
