import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.services import chats_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-task-chats"
TASK_A_ID = "test-task-chat-a"
TASK_B_ID = "test-task-chat-b"


async def _reset():
    await boards_collection.delete_many({"_id": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": "test-agent-task-chats",
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [
            {"id": TASK_A_ID, "text": "task a", "status": "idle", "statusReason": None, "currentRunId": None},
            {"id": TASK_B_ID, "text": "task b", "status": "idle", "statusReason": None, "currentRunId": None},
        ],
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
    })


async def test_get_or_create_task_chat_creates_one_chat_per_task():
    await _reset()
    try:
        board = await boards_collection.find_one({"_id": BOARD_ID})
        task_a = next(t for t in board["tasks"] if t["id"] == TASK_A_ID)
        task_b = next(t for t in board["tasks"] if t["id"] == TASK_B_ID)

        chat_a = await chats_service.get_or_create_task_chat(board, task_a)
        chat_b = await chats_service.get_or_create_task_chat(board, task_b)
        assert chat_a["id"] != chat_b["id"]
        assert chat_a["taskId"] == TASK_A_ID
        assert chat_b["taskId"] == TASK_B_ID

        persisted = await boards_collection.find_one({"_id": BOARD_ID})
        assert len(persisted["chats"]) == 2
    finally:
        await _reset()


async def test_get_or_create_task_chat_is_idempotent_and_isolates_messages():
    await _reset()
    try:
        board = await boards_collection.find_one({"_id": BOARD_ID})
        task_a = next(t for t in board["tasks"] if t["id"] == TASK_A_ID)

        chat_a_first = await chats_service.get_or_create_task_chat(board, task_a)
        await chats_service.append_messages(
            BOARD_ID, chat_a_first["id"], [chats_service.text_message("assistant", "hello from task a")]
        )

        fresh_board = await boards_collection.find_one({"_id": BOARD_ID})
        task_a_fresh = next(t for t in fresh_board["tasks"] if t["id"] == TASK_A_ID)
        chat_a_second = await chats_service.get_or_create_task_chat(fresh_board, task_a_fresh)

        assert chat_a_second["id"] == chat_a_first["id"]
        assert len(fresh_board["chats"]) == 1

        task_b_fresh = next(t for t in fresh_board["tasks"] if t["id"] == TASK_B_ID)
        chat_b = await chats_service.get_or_create_task_chat(fresh_board, task_b_fresh)
        assert chat_b["messages"] == []
    finally:
        await _reset()
