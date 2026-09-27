import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import boards_collection
from app.execution import agent_service, clarification

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ID = "test-board-clarification"
TASK_ID = "test-task-clarification"
CHAT_ID = "test-chat-clarification"
MESSAGE_ID = "test-msg-clarification"


async def _reset():
    await boards_collection.delete_many({"_id": BOARD_ID})
    await boards_collection.insert_one({
        "_id": BOARD_ID,
        "agentId": "test-agent-clarification",
        "ownerId": "test-owner",
        "title": "Board",
        "tasks": [{
            "id": TASK_ID, "text": "fix login", "status": "awaiting_clarification",
            "statusReason": None, "currentRunId": "test-run-clarification",
        }],
        "chats": [{
            "id": CHAT_ID,
            "createdAt": 0,
            "taskId": TASK_ID,
            "messages": [{
                "id": MESSAGE_ID,
                "role": "assistant",
                "type": "clarification_request",
                "text": "Which login flow — email or SSO?",
                "payload": {
                    "taskId": TASK_ID,
                    "question": "Which login flow — email or SSO?",
                    "toolUseId": "toolu_test",
                    "status": "pending",
                },
            }],
        }],
        "activeChatId": None,
        "status": "running",
        "stopRequested": False,
    })


async def test_answer_rejects_task_not_awaiting_clarification():
    await _reset()
    try:
        await boards_collection.update_one(
            {"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.status": "idle"}}
        )
        with pytest.raises(ValueError):
            await clarification.answer(BOARD_ID, TASK_ID, "SSO", "test-user")
    finally:
        await _reset()


async def test_answer_marks_question_answered_and_resumes_task(monkeypatch):
    await _reset()
    try:
        # Forces `run_task_step`'s "not configured" fallback path so this
        # resolves deterministically instead of depending on how a real
        # model happens to respond to "SSO" — enough to prove the resume
        # itself actually happened.
        monkeypatch.setattr(agent_service, "get_client", lambda: None)
        await clarification.answer(BOARD_ID, TASK_ID, "SSO", "test-user")

        board = await boards_collection.find_one({"_id": BOARD_ID})
        task = next(t for t in board["tasks"] if t["id"] == TASK_ID)
        assert task["status"] == "done"
        assert task["currentRunId"] is None

        chat = next(c for c in board["chats"] if c["id"] == CHAT_ID)
        answered = next(m for m in chat["messages"] if m["id"] == MESSAGE_ID)
        assert answered["payload"]["status"] == "answered"
        assert answered["payload"]["answer"] == "SSO"
    finally:
        await _reset()
