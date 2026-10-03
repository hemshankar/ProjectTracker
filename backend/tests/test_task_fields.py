import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest
from fastapi import HTTPException

from app.database import boards_collection, task_revisions_collection
from app.execution import completion_summary, task_field_tools
from app.services import task_fields_service as svc
from app.services import tasks_service
from app.task_fields import DESCRIPTION, SUMMARY, append_revision_note, removed_lines

BOARD_ID = "test-board-task-fields"
OTHER_BOARD_ID = "test-board-task-fields-2"
TASK_ID = "test-task-task-fields"


async def _reset():
    for bid in (BOARD_ID, OTHER_BOARD_ID):
        await boards_collection.delete_many({"_id": bid})
    await task_revisions_collection.delete_many({"taskId": TASK_ID})
    for bid in (BOARD_ID, OTHER_BOARD_ID):
        await boards_collection.insert_one({
            "_id": bid, "agentId": "test-agent-task-fields", "ownerId": "u", "title": "B",
            "tasks": [{"id": TASK_ID, "text": "write the report", "status": "idle"}] if bid == BOARD_ID else [],
            "chats": [], "activeChatId": None, "status": "idle", "stopRequested": False,
        })


# ---- pure rules ----

def test_removed_lines_ignores_additions_and_blank_lines():
    assert removed_lines("a\nb\n", "a\n\nb\nc\n") == []
    assert removed_lines("a\nb\nc", "a\nc") == ["b"]
    assert removed_lines("", "anything") == []


def test_append_revision_note_states_what_was_removed():
    out = append_revision_note("new text", "dropped the budget line, now out of scope")
    assert out.startswith("new text")
    assert "removed — dropped the budget line" in out


# ---- versioned service ----

@pytest.mark.asyncio(loop_scope="session")
async def test_missing_field_reads_as_empty_version_zero():
    await _reset()
    state = await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION)
    assert state["content"] == "" and state["version"] == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_write_bumps_version_and_records_revision():
    await _reset()
    r1 = await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "first", 0, "human", "u1")
    r2 = await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "second", 1, "agent", None)
    assert (r1["version"], r2["version"]) == (1, 2)
    history = await svc.list_revisions(TASK_ID, DESCRIPTION)
    assert [h["version"] for h in history] == [2, 1]
    assert history[0]["authorType"] == "agent" and history[1]["content"] == "first"


@pytest.mark.asyncio(loop_scope="session")
async def test_stale_write_is_rejected_with_current_content():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "mine", 0, "human", "u1")
    with pytest.raises(svc.VersionConflict) as exc_info:
        await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "stale", 0, "human", "u2")
    assert exc_info.value.current["content"] == "mine"
    assert exc_info.value.current["version"] == 1
    assert len(await svc.list_revisions(TASK_ID, DESCRIPTION)) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_write_to_unknown_task_raises_not_found():
    await _reset()
    with pytest.raises(svc.TaskNotFound):
        await svc.write_field(BOARD_ID, "nope", DESCRIPTION, "x", 0, "human", "u")


@pytest.mark.asyncio(loop_scope="session")
async def test_restore_creates_new_revision_and_keeps_history():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "v1 text", 0, "human", "u")
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "v2 text", 1, "human", "u")
    restored = await svc.restore_revision(BOARD_ID, TASK_ID, DESCRIPTION, 1, 2, "u")
    assert restored["version"] == 3 and restored["content"] == "v1 text"
    assert len(await svc.list_revisions(TASK_ID, DESCRIPTION)) == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_fields_are_versioned_independently():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "desc", 0, "human", "u")
    await svc.write_field(BOARD_ID, TASK_ID, SUMMARY, "sum", 0, "agent", None, status="done")
    assert (await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION))["version"] == 1
    summary = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert summary["version"] == 1 and summary["status"] == "done"


@pytest.mark.asyncio(loop_scope="session")
async def test_history_and_fields_follow_task_across_boards():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "carry me", 0, "human", "u")
    await tasks_service.move_task(BOARD_ID, TASK_ID, OTHER_BOARD_ID, "u")
    state = await svc.get_field(OTHER_BOARD_ID, TASK_ID, DESCRIPTION)
    assert state["content"] == "carry me"
    assert len(await svc.list_revisions(TASK_ID, DESCRIPTION)) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_add_task_seeds_description_from_integration():
    await _reset()
    created = await tasks_service.add_task(
        BOARD_ID, "seeded-task", "Reply to Priya", False, "u",
        description="Email body: please send the contract", description_source="integration",
    )
    assert created["description"] == "Email body: please send the contract"
    assert created["descriptionVersion"] == 1
    history = await svc.list_revisions("seeded-task", DESCRIPTION)
    assert history[0]["authorType"] == "integration"
    await task_revisions_collection.delete_many({"taskId": "seeded-task"})


@pytest.mark.asyncio(loop_scope="session")
async def test_add_task_rejects_oversized_description():
    await _reset()
    with pytest.raises(HTTPException) as exc_info:
        await tasks_service.add_task(BOARD_ID, "big", "x", False, "u", description="a" * 60_000)
    assert exc_info.value.status_code == 400


# ---- agent tools ----

@pytest.mark.asyncio(loop_scope="session")
async def test_agent_overwrite_that_drops_text_requires_acknowledgement():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "keep me\ndrop me", 0, "human", "u")
    text, is_error = await task_field_tools.run(
        "update_task_description", {"content": "keep me", "base_version": 1}, BOARD_ID, TASK_ID
    )
    assert is_error and "removed_summary" in text
    assert (await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION))["version"] == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_overwrite_with_acknowledgement_appends_note():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "keep me\ndrop me", 0, "human", "u")
    text, is_error = await task_field_tools.run(
        "update_task_description",
        {"content": "keep me", "base_version": 1, "removed_summary": "dropped an obsolete line"},
        BOARD_ID, TASK_ID,
    )
    assert not is_error
    state = await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION)
    assert state["version"] == 2 and "dropped an obsolete line" in state["content"]
    assert state["updatedBy"]["type"] == "agent"


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_pure_addition_needs_no_acknowledgement():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "line one", 0, "human", "u")
    _, is_error = await task_field_tools.run(
        "update_task_description", {"content": "line one\nline two", "base_version": 1}, BOARD_ID, TASK_ID
    )
    assert not is_error
    assert "Revision note" not in (await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION))["content"]


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_stale_write_gets_current_text_back_not_overwritten():
    await _reset()
    await svc.write_field(BOARD_ID, TASK_ID, DESCRIPTION, "user edit", 0, "human", "u")
    text, is_error = await task_field_tools.run(
        "update_task_description", {"content": "agent view", "base_version": 0}, BOARD_ID, TASK_ID
    )
    assert is_error and "user edit" in text and "base_version=1" in text
    assert (await svc.get_field(BOARD_ID, TASK_ID, DESCRIPTION))["content"] == "user edit"


@pytest.mark.asyncio(loop_scope="session")
async def test_set_execution_summary_rejects_empty():
    await _reset()
    _, is_error = await task_field_tools.run("set_execution_summary", {"summary": "  "}, BOARD_ID, TASK_ID)
    assert is_error


# ---- execution summary safety net ----

@pytest.mark.asyncio(loop_scope="session")
async def test_finalize_writes_fallback_when_agent_wrote_none():
    await _reset()
    await completion_summary.finalize(BOARD_ID, TASK_ID, "failed", "tool exploded")
    state = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert state["status"] == "failed" and "tool exploded" in state["content"]
    assert state["updatedBy"]["type"] == "agent"


@pytest.mark.asyncio(loop_scope="session")
async def test_finalize_keeps_agent_written_summary_and_stamps_status():
    await _reset()
    await task_field_tools.run("set_execution_summary", {"summary": "I did the thing."}, BOARD_ID, TASK_ID)
    await completion_summary.finalize(BOARD_ID, TASK_ID, "done")
    state = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert state["content"] == "I did the thing." and state["status"] == "done" and state["version"] == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_later_ending_does_not_reuse_stale_manual_summary():
    await _reset()
    await completion_summary.finalize(BOARD_ID, TASK_ID, "manual")
    await completion_summary.finalize(BOARD_ID, TASK_ID, "done")
    state = await svc.get_field(BOARD_ID, TASK_ID, SUMMARY)
    assert state["version"] == 2 and state["status"] == "done"
    assert "Completed" in state["content"]
