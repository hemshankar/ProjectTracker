import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from .. import config, task_state
from ..database import boards_collection
from ..dependencies import get_agent_membership, get_current_user, require_agent_member, require_board_access
from ..execution.events import events
from ..execution.loop import AgentRunner
from ..execution.registry import registry
from ..models import (
    BoardCreate,
    BoardUpdate,
    ImportPayload,
    TaskIn,
    TaskUpdate,
    board_export_shape,
    board_to_json,
    new_id,
    now_ms,
    sanitize_import_board,
    sanitize_task,
)
from ..models_tools import BoardBudgetUpdate
from ..pdf_export import build_pdf
from ..services import audit_service, tasks_service

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

    z = await _next_z(payload.agentId)
    tasks = [t for t in (sanitize_task(t) for t in (payload.tasks or [])) if t]
    doc = {
        "_id": payload.id or new_id(),
        "agentId": payload.agentId,
        "ownerId": user["_id"],
        "title": payload.title or "New board",
        "description": payload.description or "",
        "color": payload.color if payload.color in config.HUES else config.HUES[(z - 1) % len(config.HUES)],
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
    out["myRole"] = "editor" if doc.get("ownerId") == user["_id"] else "viewer"
    return out


@router.patch("/{board_id}")
async def update_board(board_id: str, payload: BoardUpdate, user: dict = Depends(require_board_access("editor"))):
    before = await _get_board(board_id)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return board_to_json(before)
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


@router.get("/{board_id}/events")
async def board_events(board_id: str, _user: dict = Depends(require_board_access("viewer"))):
    board = await _get_board(board_id)

    async def event_stream():
        queue = events.subscribe(board_id)
        try:
            snapshot = {"boardId": board_id, "status": board.get("status", "idle")}
            yield f"data: {json.dumps(snapshot)}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            events.unsubscribe(board_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
