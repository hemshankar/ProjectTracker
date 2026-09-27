import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest

from app.database import audit_log_collection, boards_collection, undo_pointers_collection
from app.services import audit_service, undo_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_ID = "test-agent-undo"
USER_ID = "test-user-undo"
BOARD_ID = "test-board-undo"
TASK_ID = "test-task-undo"


def _task(text, status="idle"):
    return {"id": TASK_ID, "text": text, "status": status, "statusReason": None, "currentRunId": None}


async def _cleanup():
    await boards_collection.delete_many({"_id": BOARD_ID})
    await audit_log_collection.delete_many({"agentId": AGENT_ID})
    await undo_pointers_collection.delete_many({"_id": f"{AGENT_ID}:{USER_ID}"})


async def _seed_board(**fields):
    doc = {
        "_id": BOARD_ID,
        "agentId": AGENT_ID,
        "ownerId": USER_ID,
        "title": "Original title",
        "description": "",
        "color": "blue",
        "labelId": None,
        "completed": False,
        "x": 0, "y": 0, "w": 290, "h": 260, "z": 1,
        "tasks": [],
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
        "glow": "none",
        "budgetCapUsd": None,
    }
    doc.update(fields)
    await boards_collection.insert_one(doc)
    return doc


async def test_undo_redo_task_text_update():
    await _cleanup()
    try:
        await _seed_board(tasks=[_task("before text")])
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="update", actor_type="human", actor_id=USER_ID,
            before=_task("before text"), after=_task("after text"),
        )
        await boards_collection.update_one({"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.text": "after text"}})

        result = await undo_service.undo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["text"] == "before text"

        result = await undo_service.redo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["text"] == "after text"
    finally:
        await _cleanup()


async def test_undo_skips_agent_authored_changes():
    """The core Phase 7 guarantee: an agent's own edit sitting between two
    human edits is never touched by undo — it isn't even in the timeline."""
    await _cleanup()
    try:
        await _seed_board(tasks=[_task("human v1")])

        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="update", actor_type="human", actor_id=USER_ID,
            before=_task("human v1"), after=_task("human v2"),
        )
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="update", actor_type="agent", actor_id=None,
            before=_task("human v2"), after=_task("agent touched this"),
        )
        await boards_collection.update_one(
            {"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.text": "agent touched this"}}
        )

        result = await undo_service.undo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        # Undo reverts straight to "human v1" (the only human entry), not to
        # "human v2" — the agent's entry in between is invisible to it.
        assert board["tasks"][0]["text"] == "human v1"
    finally:
        await _cleanup()


async def test_undo_board_update_restores_metadata_not_tasks():
    await _cleanup()
    try:
        before_doc = await _seed_board(title="Original title", tasks=[_task("untouched")])
        after_doc = dict(before_doc)
        after_doc["title"] = "Renamed"
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID,
            entity_type="board", action="update", actor_type="human", actor_id=USER_ID,
            before=before_doc, after=after_doc,
        )
        await boards_collection.update_one({"_id": BOARD_ID}, {"$set": {"title": "Renamed"}})
        # Simulate the agent independently changing a task after the rename —
        # undo of the title change must leave this alone.
        await boards_collection.update_one(
            {"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.status": "done"}}
        )

        result = await undo_service.undo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["title"] == "Original title"
        assert board["tasks"][0]["status"] == "done"
    finally:
        await _cleanup()


async def test_undo_task_delete_restores_it_and_redo_removes_it_again():
    await _cleanup()
    try:
        await _seed_board(tasks=[])
        snapshot = _task("deleted task")
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="delete", actor_type="human", actor_id=USER_ID,
            before=snapshot, after=None,
        )

        result = await undo_service.undo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert any(t["id"] == TASK_ID for t in board["tasks"])

        result = await undo_service.redo(AGENT_ID, USER_ID)
        assert result["ok"] is True
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert not any(t["id"] == TASK_ID for t in board["tasks"])
    finally:
        await _cleanup()


async def test_undo_with_nothing_to_undo_is_a_no_op():
    await _cleanup()
    try:
        await _seed_board(tasks=[_task("x")])
        result = await undo_service.undo(AGENT_ID, USER_ID)
        assert result["ok"] is False
    finally:
        await _cleanup()


async def test_new_edit_after_undo_clears_the_redo_history():
    await _cleanup()
    try:
        await _seed_board(tasks=[_task("v1")])
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="update", actor_type="human", actor_id=USER_ID,
            before=_task("v1"), after=_task("v2"),
        )
        await boards_collection.update_one({"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.text": "v2"}})

        # Undo v2 -> v1 (one entry now sits "redo-able").
        await undo_service.undo(AGENT_ID, USER_ID)

        # A brand new human edit lands (as if the user typed something new).
        await audit_service.write_audit(
            agent_id=AGENT_ID, board_id=BOARD_ID, task_id=TASK_ID,
            entity_type="task", action="update", actor_type="human", actor_id=USER_ID,
            before=_task("v1"), after=_task("v3"),
        )
        await boards_collection.update_one({"_id": BOARD_ID, "tasks.id": TASK_ID}, {"$set": {"tasks.$.text": "v3"}})

        # Redo must not be able to jump forward to "v2" — that branch is dead.
        result = await undo_service.redo(AGENT_ID, USER_ID)
        assert result["ok"] is False
        board = await boards_collection.find_one({"_id": BOARD_ID})
        assert board["tasks"][0]["text"] == "v3"
    finally:
        await _cleanup()
