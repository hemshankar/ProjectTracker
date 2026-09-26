from fastapi import APIRouter, HTTPException, Response

from .. import config
from ..database import boards_collection
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
from ..pdf_export import build_pdf
from ..seed import default_boards

router = APIRouter(prefix="/api/boards", tags=["boards"])


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


async def _next_z() -> int:
    doc = await boards_collection.find_one(sort=[("z", -1)])
    return (doc["z"] + 1) if doc else 1


@router.get("")
async def list_boards():
    cursor = boards_collection.find().sort("z", 1)
    docs = [board_to_json(d) async for d in cursor]
    return docs


@router.post("")
async def create_board(payload: BoardCreate):
    z = await _next_z()
    tasks = [t for t in (sanitize_task(t) for t in (payload.tasks or [])) if t]
    doc = {
        "_id": payload.id or new_id(),
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
        "createdAt": now_ms(),
        "updatedAt": now_ms(),
    }
    await boards_collection.insert_one(doc)
    return board_to_json(doc)


@router.patch("/{board_id}")
async def update_board(board_id: str, payload: BoardUpdate):
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return board_to_json(await _get_board(board_id))
    updates["updatedAt"] = now_ms()
    result = await boards_collection.update_one({"_id": board_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Board not found")
    return board_to_json(await _get_board(board_id))


@router.delete("/{board_id}")
async def delete_board(board_id: str):
    result = await boards_collection.delete_one({"_id": board_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"ok": True}


@router.post("/reset")
async def reset_boards():
    await boards_collection.delete_many({})
    boards = default_boards()
    if boards:
        await boards_collection.insert_many(boards)
    return [board_to_json(b) for b in boards]


@router.post("/clear")
async def clear_boards():
    await boards_collection.delete_many({})
    return []


@router.post("/import")
async def import_boards(payload: ImportPayload):
    await boards_collection.delete_many({})
    sanitized = [
        sanitize_import_board(b, i, i + 1) for i, b in enumerate(payload.boards)
    ]
    if sanitized:
        await boards_collection.insert_many(sanitized)
    return [board_to_json(b) for b in sanitized]


@router.get("/export")
async def export_boards_json():
    cursor = boards_collection.find().sort("z", 1)
    docs = [d async for d in cursor]
    return {
        "app": "scatterboard",
        "version": 1,
        "exportedAt": now_ms(),
        "boards": [board_export_shape(d) for d in docs],
    }


@router.get("/export/pdf")
async def export_boards_pdf():
    cursor = boards_collection.find().sort("z", 1)
    docs = [d async for d in cursor]
    pdf_bytes = build_pdf(docs)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=scatterboard-summary.pdf"},
    )


# ---------------- tasks ----------------


@router.post("/{board_id}/tasks")
async def add_task(board_id: str, payload: TaskIn):
    board = await _get_board(board_id)
    task = sanitize_task({"id": payload.id, "text": payload.text, "done": payload.done})
    if not task:
        raise HTTPException(status_code=400, detail="Task text is required")
    tasks = board.get("tasks", []) + [task]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    return task


@router.patch("/{board_id}/tasks/{task_id}")
async def update_task(board_id: str, task_id: str, payload: TaskUpdate):
    board = await _get_board(board_id)
    tasks = board.get("tasks", [])
    found = False
    for t in tasks:
        if t["id"] == task_id:
            found = True
            if payload.text is not None:
                t["text"] = payload.text
            if payload.done is not None:
                t["done"] = payload.done
            break
    if not found:
        raise HTTPException(status_code=404, detail="Task not found")
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    return {"ok": True}


@router.delete("/{board_id}/tasks/{task_id}")
async def delete_task(board_id: str, task_id: str):
    board = await _get_board(board_id)
    tasks = [t for t in board.get("tasks", []) if t["id"] != task_id]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    return {"ok": True}


@router.post("/{board_id}/tasks/clear-completed")
async def clear_completed_tasks(board_id: str):
    board = await _get_board(board_id)
    tasks = [t for t in board.get("tasks", []) if not t.get("done")]
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"tasks": tasks, "updatedAt": now_ms()}}
    )
    return {"ok": True}
