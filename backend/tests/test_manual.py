import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.execution import agent_service, manual

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-manual"
TASK_ID = "test-task-manual"
CHAT_ID = "test-chat-manual"
MESSAGE_ID = "test-msg-manual"


async def _reset():
    await boards_collection.delete_many({"_id": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": "test-agent-manual",
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [{
            "id": TASK_ID, "text": "chase signature", "status": "manual",
            "statusReason": None, "currentRunId": "test-run-manual",
        }],
        "chats": [{
            "id": CHAT_ID,
            "createdAt": 0,
            "taskId": TASK_ID,
            "messages": [{
                "id": MESSAGE_ID,
                "role": "assistant",
                "type": "manual_hold",
                "text": "Sent a reminder to priya@x.com — waiting on her reply.",
                "payload": {
                    "taskId": TASK_ID,
                    "note": "Sent a reminder to priya@x.com — waiting on her reply.",
                    "toolUseId": "toolu_test",
                    "status": "pending",
                },
            }],
        }],
        "activeChatId": None,
        "status": "running",
        "stopRequested": False,
    })


async def test_resolve_rejects_task_not_manual():
    await _reset()
    try:
        await boards_collection.update_one(
            {"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.status": "idle"}}
        )
        with pytest.raises(ValueError):
            await manual.resolve(BOARD_ID, TASK_ID, "She signed it", "test-user")
    finally:
        await _reset()


async def test_resolve_marks_hold_resolved_and_resumes_task(monkeypatch):
    await _reset()
    try:
        # Same "not configured" fallback trick as test_clarification.py: makes
        # the resume land deterministically on the fallback status instead of
        # depending on a real model's response.
        monkeypatch.setattr(agent_service, "get_client", lambda: None)
        await manual.resolve(BOARD_ID, TASK_ID, "She signed it", "test-user")

        board = await boards_collection.find_one({"_id": BOARD_ID})
        task = next(t for t in board["tasks"] if t["id"] == TASK_ID)
        assert task["status"] == "done"
        assert task["currentRunId"] is None

        chat = next(c for c in board["chats"] if c["id"] == CHAT_ID)
        resolved = next(m for m in chat["messages"] if m["id"] == MESSAGE_ID)
        assert resolved["payload"]["status"] == "resolved"
        assert resolved["payload"]["resolution"] == "She signed it"
    finally:
        await _reset()
