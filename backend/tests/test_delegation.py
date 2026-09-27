import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import agent_links_collection, agents_collection, audit_log_collection, boards_collection
from app.execution import agent_service, delegation
from app.services import agent_links_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_A = "test-agent-delegation-a"
AGENT_B = "test-agent-delegation-b"
ADMIN_USER = "test-user-delegation-admin"
BOARD_A_ID = "test-board-delegation-a"
TASK_A_ID = "test-task-delegation-a"


async def _reset():
    await agent_links_collection.delete_many({"fromAgentId": {"$in": [AGENT_A, AGENT_B]}})
    await agents_collection.delete_many({"_id": {"$in": [AGENT_A, AGENT_B]}})
    await agents_collection.insert_many([
        {"_id": AGENT_A, "name": "Agent A"},
        {"_id": AGENT_B, "name": "Agent B"},
    ])
    await boards_collection.delete_many({"agentId": {"$in": [AGENT_A, AGENT_B]}})
    await audit_log_collection.delete_many({"agentId": {"$in": [AGENT_A, AGENT_B]}})
    await boards_collection.insert_one({
        "_id": BOARD_A_ID,
        "agentId": AGENT_A,
        "ownerId": "test-owner",
        "title": "Board A",
        "tasks": [{
            "id": TASK_A_ID, "text": "Needs Agent B's specialty", "status": "awaiting_reply",
            "statusReason": None, "currentRunId": "test-run-a",
        }],
        "chats": [],
        "activeChatId": None,
        "status": "running",
        "stopRequested": False,
    })


async def test_delegation_refused_without_granted_link():
    await _reset()
    try:
        with pytest.raises(delegation.DelegationRefused):
            await delegation.request_delegation(
                AGENT_A, "Agent A", AGENT_B, BOARD_A_ID, TASK_A_ID, "test-run-a", "please help",
            )
    finally:
        await _reset()


async def test_delegation_refused_to_self():
    await _reset()
    try:
        with pytest.raises(delegation.DelegationRefused):
            await delegation.request_delegation(
                AGENT_A, "Agent A", AGENT_A, BOARD_A_ID, TASK_A_ID, "test-run-a", "please help",
            )
    finally:
        await _reset()


async def test_delegation_with_granted_link_creates_task_on_targets_own_board():
    await _reset()
    try:
        await agent_links_service.grant_link(AGENT_A, AGENT_B, ADMIN_USER)
        result = await delegation.request_delegation(
            AGENT_A, "Agent A", AGENT_B, BOARD_A_ID, TASK_A_ID, "test-run-a", "please help",
        )
        target_board = await boards_collection.find_one({"_id": result["targetBoardId"]})
        # The delegated task lives on Agent B's own board, under Agent B's
        # own agentId — every budget/spend check in this codebase keys off
        # `board.agentId`, so this placement alone is what keeps a
        # delegated task's spend landing against B, never A.
        assert target_board["agentId"] == AGENT_B
        assert target_board["inboundDelegation"] is True

        target_task = next(t for t in target_board["tasks"] if t["id"] == result["targetTaskId"])
        assert target_task["status"] == "idle"
        assert target_task["delegatedFromAgentId"] == AGENT_A
        assert target_task["delegatedFromTaskId"] == TASK_A_ID
        assert "Agent A" in target_task["text"]
        assert "please help" in target_task["text"]
    finally:
        await _reset()
        await boards_collection.delete_many({"inboundDelegation": True, "agentId": AGENT_B})


async def test_on_task_resolved_is_noop_for_non_delegated_task():
    await _reset()
    try:
        # No delegatedFromTaskId — must not touch anything or raise.
        await delegation.on_task_resolved({"id": "some-task", "status": "done"}, "result")
    finally:
        await _reset()


async def test_on_task_resolved_resumes_origin_task(monkeypatch):
    await _reset()
    try:
        # Forces `run_task_step`'s "not configured" fallback path so this
        # resolves deterministically regardless of whether a real
        # ANTHROPIC_API_KEY happens to be set in the environment running
        # these tests — otherwise a real model can (reasonably) decide to
        # call the new `ask_user` tool on a terse "Here's what I found."
        # reply, which is a valid model choice but makes this assertion
        # about the resume plumbing itself flaky.
        monkeypatch.setattr(agent_service, "get_client", lambda: None)
        delegated_task = {
            "id": "test-delegated-task",
            "status": "done",
            "delegatedFromAgentId": AGENT_A,
            "delegatedFromBoardId": BOARD_A_ID,
            "delegatedFromTaskId": TASK_A_ID,
            "delegatedFromRunId": "test-run-a",
        }
        await delegation.on_task_resolved(delegated_task, "Here's what I found.")

        board = await boards_collection.find_one({"_id": BOARD_A_ID})
        origin_task = next(t for t in board["tasks"] if t["id"] == TASK_A_ID)
        # No ANTHROPIC_API_KEY in the test environment, so `run_task_step`
        # takes its "not configured" fallback path and resolves immediately
        # — enough to prove the resume actually happened.
        assert origin_task["status"] == "done"
        assert origin_task["currentRunId"] is None

        chat = board["chats"][0]
        texts = [m.get("text", "") for m in chat["messages"]]
        assert any("Here's what I found." in t for t in texts)
    finally:
        await _reset()
