import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import agents_collection, board_shares_collection, boards_collection, task_runs_collection
from app.services import task_activity_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_A = "test-agent-activity-a"
AGENT_B = "test-agent-activity-b"
BOARD_A_ID = "test-board-activity-a"
BOARD_B_ID = "test-board-activity-b"
TASK_A_ID = "test-task-activity-a"
TASK_B_ID = "test-task-activity-b"
PRIMARY_RUN_ID = "test-run-activity-primary"
SUB_RUN_ID = "test-run-activity-sub"
VIEWER_USER = "test-user-activity-viewer"
OUTSIDER_USER = "test-user-activity-outsider"


async def _reset():
    await boards_collection.delete_many({"_id": {"$in": [BOARD_A_ID, BOARD_B_ID]}})
    await agents_collection.delete_many({"_id": {"$in": [AGENT_A, AGENT_B]}})
    await task_runs_collection.delete_many({"_id": {"$in": [PRIMARY_RUN_ID, SUB_RUN_ID]}})
    await board_shares_collection.delete_many({"boardId": {"$in": [BOARD_A_ID, BOARD_B_ID]}})
    await agents_collection.insert_many([{"_id": AGENT_A, "name": "Agent A"}, {"_id": AGENT_B, "name": "Agent B"}])
    await boards_collection.insert_one({
        "_id": BOARD_A_ID, "agentId": AGENT_A, "ownerId": VIEWER_USER, "title": "Board A",
        "tasks": [{"id": TASK_A_ID, "text": "Do the thing", "status": "done", "statusReason": None, "currentRunId": None}],
        "chats": [{"id": "chat-a", "createdAt": 0, "messages": [
            {"id": "m1", "role": "assistant", "type": "text", "text": "Working on it", "taskId": TASK_A_ID},
        ]}],
        "activeChatId": "chat-a", "status": "done", "stopRequested": False,
    })
    await boards_collection.insert_one({
        "_id": BOARD_B_ID, "agentId": AGENT_B, "ownerId": None, "title": "Inbound Delegations",
        "inboundDelegation": True,
        "tasks": [{
            "id": TASK_B_ID, "text": "[Delegated by Agent A] help", "status": "done",
            "statusReason": None, "currentRunId": None,
            "delegatedFromAgentId": AGENT_A, "delegatedFromBoardId": BOARD_A_ID,
            "delegatedFromTaskId": TASK_A_ID, "delegatedFromRunId": PRIMARY_RUN_ID,
        }],
        "chats": [{"id": "chat-b", "createdAt": 0, "messages": [
            {"id": "m2", "role": "assistant", "type": "text", "text": "Handled by B", "taskId": TASK_B_ID},
        ]}],
        "activeChatId": "chat-b", "status": "done", "stopRequested": False,
    })
    await task_runs_collection.insert_one({
        "_id": PRIMARY_RUN_ID, "boardId": BOARD_A_ID, "taskId": TASK_A_ID, "agentId": AGENT_A,
        "status": "done", "startedAt": 1, "endedAt": 2, "error": None, "parentRunId": None, "kind": "primary",
    })
    await task_runs_collection.insert_one({
        "_id": SUB_RUN_ID, "boardId": BOARD_A_ID, "taskId": TASK_A_ID, "agentId": AGENT_A,
        "status": "done", "startedAt": 1, "endedAt": 2, "error": None, "parentRunId": PRIMARY_RUN_ID,
        "kind": "subagent", "instructions": "Look up the number", "allowedTools": ["search_notes"],
        "transcript": [{"role": "user", "text": "Look up the number"}, {"role": "assistant", "text": "Found it: 42"}],
    })


async def test_counts_and_subagent_transcript_and_peer_delegation():
    await _reset()
    try:
        activity = await task_activity_service.get_task_activity(BOARD_A_ID, TASK_A_ID, VIEWER_USER)
        assert activity["counts"] == {"agents": 1, "subAgents": 1, "peerAgents": 1}
        assert len(activity["subAgentRuns"]) == 1
        assert activity["subAgentRuns"][0]["instructions"] == "Look up the number"
        assert activity["subAgentRuns"][0]["transcript"][-1]["text"] == "Found it: 42"

        assert len(activity["peerDelegations"]) == 1
        peer = activity["peerDelegations"][0]
        assert peer["toAgentId"] == AGENT_B
        assert peer["toAgentName"] == "Agent B"
        # VIEWER_USER owns board A but has no access to board B at all —
        # the peer conversation shows up as present but not readable.
        assert peer["accessible"] is False
        assert peer["messages"] == []
    finally:
        await _reset()


async def test_peer_delegation_messages_visible_with_board_access():
    await _reset()
    try:
        await board_shares_collection.insert_one(
            {"_id": "share-1", "boardId": BOARD_B_ID, "userId": OUTSIDER_USER, "role": "viewer"}
        )
        activity = await task_activity_service.get_task_activity(BOARD_A_ID, TASK_A_ID, OUTSIDER_USER)
        peer = activity["peerDelegations"][0]
        assert peer["accessible"] is True
        assert peer["messages"][0]["text"] == "Handled by B"
    finally:
        await _reset()


async def test_no_runs_means_zero_counts():
    await _reset()
    await task_runs_collection.delete_many({"_id": {"$in": [PRIMARY_RUN_ID, SUB_RUN_ID]}})
    try:
        activity = await task_activity_service.get_task_activity(BOARD_A_ID, TASK_A_ID, VIEWER_USER)
        assert activity["counts"]["agents"] == 0
        assert activity["counts"]["subAgents"] == 0
    finally:
        await _reset()
