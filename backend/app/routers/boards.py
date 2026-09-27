import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import config, task_state
from ..database import boards_collection
from ..dependencies import get_agent_membership, get_board_role, get_current_user, require_agent_member, require_board_access
from ..execution import clarification, manual, stopping
from ..execution.events import events
from ..execution.loop import AgentRunner
from ..execution.registry import registry
from ..models import (
    BoardCreate,
    BoardUpdate,
    ChatMessageIn,
    ImportPayload,
    TaskIn,
    TaskMoveIn,
    TaskUpdate,
    board_export_shape,
    board_to_json,
    new_id,
    now_ms,
    sanitize_import_board,
    sanitize_task,
)
from ..models_identity import BOARD_ROLE_RANK
from ..models_tools import BoardBudgetUpdate
from ..pdf_export import build_pdf
from ..services import audit_service, chats_service, labels_service, observability, task_activity_service, tasks_service

BOARD_STARTABLE_STATUSES = ("idle", "stopped", "failed", "blocked", "done")

router = APIRouter(prefix="/api/boards", tags=["boards"])


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


async def _next_z(agent_id: str) -> int:
    doc = await boards_collection.find_one({"agentId": agent_id}, sort=[("z", -1)])
    return (doc["z"] + 1) if doc else 1


@router.post("")
async def create_board(payload: BoardCreate, user: dict = Depends(get_current_user)):
    if not await get_agent_membership(payload.agentId, user["_id"]):
        raise HTTPException(status_code=403, detail="Agent membership required")
    label = None
    if payload.labelId:
        label = await labels_service.get_label(payload.labelId)
        if label is None:
            raise HTTPException(status_code=400, detail="Unknown label")

    z = await _next_z(payload.agentId)
    tasks = [t for t in (sanitize_task(t) for t in (payload.tasks or [])) if t]
    doc = {
        "_id": payload.id or new_id(),
        "agentId": payload.agentId,
        "ownerId": user["_id"],
        "title": payload.title or "New board",
        "description": payload.description or "",
        # A labeled board's color is locked to its label — see `update_board`.
        "color": label["color"] if label else (
            payload.color if payload.color in config.HUES else config.HUES[(z - 1) % len(config.HUES)]
        ),
        "labelId": payload.labelId or None,
        "completed": bool(payload.completed),
        "x": payload.x or 0,
        "y": payload.y or 0,
        "w": payload.w or 290,
        "h": payload.h or 260,
        "z": payload.z if payload.z is not None else z,
        "tasks": tasks,
        "chats": [],
        "activeChatId": None,
        "status": "idle",
        "stopRequested": False,
        "statusReason": None,
        "budgetCapUsd": None,
        "glow": "none",
        "createdAt": now_ms(),
        "updatedAt": now_ms(),
    }
    await boards_collection.insert_one(doc)
    await audit_service.write_audit(
        agent_id=doc["agentId"],
        board_id=doc["_id"],
        entity_type="board",
        action="create",
        actor_type="human",
        actor_id=user["_id"],
        before=None,
        after=doc,
    )
    out = board_to_json(doc)
    out["myRole"] = "editor"
    return out


@router.get("/{board_id}")
async def get_board(board_id: str, user: dict = Depends(require_board_access("viewer"))):
    doc = await _get_board(board_id)
    out = board_to_json(doc)
    # Derived the same way `list_boards_for_agent` does — not just the
    # ownerId check, since an inbound-delegation board (Phase 6) has no
    # owner but still grants any of its Agent's members editor access.
    role, _ = await get_board_role(board_id, user["_id"])
    out["myRole"] = role or "viewer"
    return out


@router.patch("/{board_id}")
async def update_board(board_id: str, payload: BoardUpdate, user: dict = Depends(require_board_access("editor"))):
    before = await _get_board(board_id)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return board_to_json(before)

    if "labelId" in updates:
        if updates["labelId"] == "":
            updates["labelId"] = None
        else:
            label = await labels_service.get_label(updates["labelId"])
            if label is None:
                raise HTTPException(status_code=400, detail="Unknown label")
            # Locked to the label — overrides any color sent in this same request.
            updates["color"] = label["color"]
    elif "color" in updates and before.get("labelId"):
        raise HTTPException(
            status_code=400,
            detail="This board's color is locked to its label — remove the label to change color",
        )
    updates["updatedAt"] = now_ms()
    await boards_collection.update_one({"_id": board_id}, {"$set": updates})
    after = await _get_board(board_id)
    await audit_service.write_audit(
        agent_id=after.get("agentId"),
        board_id=board_id,
        entity_type="board",
        action="update",
        actor_type="human",
        actor_id=user["_id"],
        before=before,
        after=after,
    )
    return board_to_json(after)


@router.patch("/{board_id}/budget")
async def update_board_budget(
    board_id: str, payload: BoardBudgetUpdate, user: dict = Depends(require_board_access("editor"))
):
    before = await _get_board(board_id)
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"budgetCapUsd": payload.capUsd, "updatedAt": now_ms()}}
    )
    after = await _get_board(board_id)
    await audit_service.write_audit(
        agent_id=after.get("agentId"),
        board_id=board_id,
        entity_type="board",
        action="update",
        actor_type="human",
        actor_id=user["_id"],
        before=before,
        after=after,
    )
    return board_to_json(after)


@router.delete("/{board_id}")
async def delete_board(board_id: str, user: dict = Depends(require_board_access("editor"))):
    before = await _get_board(board_id)
    await boards_collection.delete_one({"_id": board_id})
    await audit_service.write_audit(
        agent_id=before.get("agentId"),
        board_id=board_id,
        entity_type="board",
        action="delete",
        actor_type="human",
        actor_id=user["_id"],
        before=before,
        after=None,
    )
    return {"ok": True}


@router.post("/reset")
async def reset_boards(agent_id: str, user: dict = Depends(require_agent_member())):
    removed = [d async for d in boards_collection.find({"agentId": agent_id})]
    await boards_collection.delete_many({"agentId": agent_id})
    for d in removed:
        await audit_service.write_audit(
            agent_id=agent_id,
            board_id=d["_id"],
            entity_type="board",
            action="delete",
            actor_type="human",
            actor_id=user["_id"],
            before=d,
            after=None,
        )
    return []


@router.post("/clear")
async def clear_boards(agent_id: str, user: dict = Depends(require_agent_member())):
    removed = [d async for d in boards_collection.find({"agentId": agent_id})]
    await boards_collection.delete_many({"agentId": agent_id})
    for d in removed:
        await audit_service.write_audit(
            agent_id=agent_id,
            board_id=d["_id"],
            entity_type="board",
            action="delete",
            actor_type="human",
            actor_id=user["_id"],
            before=d,
            after=None,
        )
    return []


@router.post("/import")
async def import_boards(
    agent_id: str, payload: ImportPayload, user: dict = Depends(require_agent_member())
):
    await boards_collection.delete_many({"agentId": agent_id})
    sanitized = [sanitize_import_board(b, i, i + 1) for i, b in enumerate(payload.boards)]
    for b in sanitized:
        b["agentId"] = agent_id
        b["ownerId"] = user["_id"]
    if sanitized:
        await boards_collection.insert_many(sanitized)
    for b in sanitized:
        await audit_service.write_audit(
            agent_id=agent_id,
            board_id=b["_id"],
            entity_type="board",
            action="create",
            actor_type="human",
            actor_id=user["_id"],
            before=None,
            after=b,
        )
    return [board_to_json(b) for b in sanitized]


@router.get("/export")
async def export_boards_json(agent_id: str, _user: dict = Depends(require_agent_member())):
    cursor = boards_collection.find({"agentId": agent_id}).sort("z", 1)
    docs = [d async for d in cursor]
    return {
        "app": "scatterboard",
        "version": 1,
        "exportedAt": now_ms(),
        "boards": [board_export_shape(d) for d in docs],
    }


@router.get("/export/pdf")
async def export_boards_pdf(agent_id: str, _user: dict = Depends(require_agent_member())):
    cursor = boards_collection.find({"agentId": agent_id}).sort("z", 1)
    docs = [d async for d in cursor]
    pdf_bytes = build_pdf(docs)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=scatterboard-summary.pdf"},
    )


# ---------------- tasks ----------------


@router.post("/{board_id}/tasks")
async def add_task(board_id: str, payload: TaskIn, user: dict = Depends(require_board_access("editor"))):
    return await tasks_service.add_task(
        board_id, payload.id, payload.text, bool(payload.done), user["_id"]
    )


@router.patch("/{board_id}/tasks/{task_id}")
async def update_task(
    board_id: str, task_id: str, payload: TaskUpdate, user: dict = Depends(require_board_access("editor"))
):
    return await tasks_service.update_task(board_id, task_id, payload, user["_id"])


@router.delete("/{board_id}/tasks/{task_id}")
async def delete_task(board_id: str, task_id: str, user: dict = Depends(require_board_access("editor"))):
    await tasks_service.delete_task(board_id, task_id, user["_id"])
    return {"ok": True}


@router.post("/{board_id}/tasks/{task_id}/move")
async def move_task(
    board_id: str, task_id: str, payload: TaskMoveIn, user: dict = Depends(require_board_access("editor")),
):
    target_role, target_board = await get_board_role(payload.targetBoardId, user["_id"])
    if target_board is None:
        raise HTTPException(status_code=404, detail="Target board not found")
    if target_role is None or BOARD_ROLE_RANK[target_role] < BOARD_ROLE_RANK["editor"]:
        raise HTTPException(status_code=403, detail="Insufficient access to target board")
    await tasks_service.move_task(board_id, task_id, payload.targetBoardId, user["_id"])
    return {"ok": True}


@router.post("/{board_id}/tasks/clear-completed")
async def clear_completed_tasks(board_id: str, user: dict = Depends(require_board_access("editor"))):
    await tasks_service.clear_completed_tasks(board_id, user["_id"])
    return {"ok": True}


@router.get("/{board_id}/tasks/{task_id}/messages")
async def get_task_messages(board_id: str, task_id: str, user: dict = Depends(require_board_access("viewer"))):
    doc = await _get_board(board_id)
    messages = [
        m
        for chat in doc.get("chats", [])
        for m in chat.get("messages", [])
        if m.get("taskId") == task_id
    ]
    return {"taskId": task_id, "messages": messages}


@router.get("/{board_id}/tasks/{task_id}/activity")
async def get_task_activity(board_id: str, task_id: str, user: dict = Depends(require_board_access("viewer"))):
    return await task_activity_service.get_task_activity(board_id, task_id, user["_id"])


@router.get("/{board_id}/audit")
async def get_board_audit(board_id: str, _user: dict = Depends(require_board_access("viewer"))):
    """The lighter, board-scoped Activity view (Phase 8) — any board
    viewer/editor, not just an Agent Admin; no raw prompts, no cross-board
    visibility. See `services.observability.list_board_audit`."""
    return await observability.list_board_audit(board_id)


def _find_task(board: dict, task_id: str) -> dict:
    task = next((t for t in board.get("tasks", []) if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{board_id}/tasks/{task_id}/chat")
async def get_task_chat(board_id: str, task_id: str, user: dict = Depends(require_board_access("viewer"))):
    board = await _get_board(board_id)
    task = _find_task(board, task_id)
    chat = await chats_service.get_or_create_task_chat(board, task)
    return {"chatId": chat["id"], "messages": chat["messages"]}


@router.post("/{board_id}/tasks/{task_id}/chat/messages")
async def send_task_chat_message(
    board_id: str, task_id: str, payload: ChatMessageIn, user: dict = Depends(require_board_access("editor")),
):
    board = await _get_board(board_id)
    task = _find_task(board, task_id)

    if task.get("status") == "awaiting_clarification":
        try:
            return await clarification.answer(board_id, task_id, payload.text, user["_id"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    if task.get("status") == "manual":
        try:
            return await manual.resolve(board_id, task_id, payload.text, user["_id"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    chat = await chats_service.get_or_create_task_chat(board, task)
    message = chats_service.text_message("user", payload.text)
    message["taskId"] = task_id
    await chats_service.append_messages(board_id, chat["id"], [message])
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        task_id=task_id,
        entity_type="chat_message",
        action="create",
        actor_type="human",
        actor_id=user["_id"],
        before=None,
        after=message,
    )
    return board_to_json(await _get_board(board_id))


@router.post("/{board_id}/tasks/{task_id}/run")
async def run_single_task(
    board_id: str, task_id: str, user: dict = Depends(require_board_access("editor")),
):
    """Runs just this one task, independent of the board's own Start/Stop —
    skips dispatch grouping and the board-level status gate entirely. Safe
    to call even while the board's own automatic loop is active: every claim
    goes through the same compare-and-swap `transition_task_status` call, so
    whichever side claims the task first wins and the other no-ops.
    """
    reset = await tasks_service.prepare_task_for_run(board_id, task_id, user["_id"])
    runner = AgentRunner(board_id=board_id, agent_id=reset.get("agentId"))
    asyncio.create_task(runner.run_task_by_id(task_id))
    return board_to_json(reset)


@router.post("/{board_id}/tasks/{task_id}/stop")
async def stop_single_task(
    board_id: str, task_id: str, user: dict = Depends(require_board_access("editor")),
):
    """Stops just this one task, right now — cancels its in-flight run if
    it's actually mid-call (see `execution.stopping`), or resolves it
    straight to `stopped` if it was only suspended waiting on a human.
    """
    try:
        await stopping.stop_task(board_id, task_id, user["_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return board_to_json(await _get_board(board_id))


# ---------------- execution (start/stop/live status) ----------------


@router.post("/{board_id}/start")
async def start_board(board_id: str, user: dict = Depends(require_board_access("editor"))):
    before = await _get_board(board_id)

    queued = await task_state.transition_board_status(
        board_id, BOARD_STARTABLE_STATUSES, "queued", stopRequested=False
    )
    if queued is None:
        raise HTTPException(status_code=409, detail="Board is already running")
    await events.publish(board_id, {"boardId": board_id, "status": "queued"})

    # A prior run may have left tasks "failed" — the runner only ever picks up
    # "idle" tasks, so without this a restart would never retry them.
    for t in queued.get("tasks", []):
        if t.get("status") == "failed":
            reset = await task_state.transition_task_status(
                board_id, t["id"], ["failed"], "idle", statusReason=None
            )
            if reset is not None:
                await events.publish(board_id, {"taskId": t["id"], "status": "idle"})

    running = await task_state.transition_board_status(board_id, ["queued"], "running")
    await events.publish(board_id, {"boardId": board_id, "status": "running"})

    await audit_service.write_audit(
        agent_id=running.get("agentId"),
        board_id=board_id,
        entity_type="board",
        action="update",
        actor_type="human",
        actor_id=user["_id"],
        before=before,
        after=running,
    )

    runner = AgentRunner(board_id=board_id, agent_id=running.get("agentId"))
    registry.register(board_id, asyncio.create_task(runner.run()))

    return board_to_json(running)


@router.post("/{board_id}/stop")
async def stop_board(board_id: str, user: dict = Depends(require_board_access("editor"))):
    before = await _get_board(board_id)
    if before.get("status") not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Board is not running")

    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"stopRequested": True, "updatedAt": now_ms()}}
    )
    # Abrupt: cancel every task actually in flight right now, rather than
    # just preventing the next stage from starting. `stopRequested` above is
    # still set too — `AgentRunner.run()`'s own loop notices it and finalizes
    # the board to `stopped` once these cancellations let it move past the
    # `asyncio.gather(...)` it was waiting on (see `execution.stopping`).
    for t in before.get("tasks", []):
        if t.get("status") in stopping.STOPPABLE_STATUSES:
            stopping.task_registry.cancel(t["id"])

    after = await _get_board(board_id)
    await audit_service.write_audit(
        agent_id=after.get("agentId"),
        board_id=board_id,
        entity_type="board",
        action="update",
        actor_type="human",
        actor_id=user["_id"],
        before=before,
        after=after,
    )
    return {"ok": True}
