import time
import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from . import config


def new_id() -> str:
    return "id-" + uuid.uuid4().hex[:12]


def now_ms() -> int:
    return int(time.time() * 1000)


class TaskIn(BaseModel):
    text: str
    id: Optional[str] = None
    done: Optional[bool] = None


class TaskUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None


class TaskMoveIn(BaseModel):
    targetBoardId: str


class BoardCreate(BaseModel):
    agentId: str
    id: Optional[str] = None
    title: Optional[str] = "New board"
    description: Optional[str] = ""
    color: Optional[str] = None
    labelId: Optional[str] = None
    completed: Optional[bool] = False
    x: Optional[float] = 0
    y: Optional[float] = 0
    w: Optional[float] = 290
    h: Optional[float] = 260
    z: Optional[int] = None
    tasks: Optional[List[dict]] = None


class BoardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    labelId: Optional[str] = None
    completed: Optional[bool] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    z: Optional[int] = None


class ChatMessageIn(BaseModel):
    text: str


class ChatMessageEdit(BaseModel):
    text: Optional[str] = None
    payload: Optional[dict] = None


class ImportBoard(BaseModel):
    title: Optional[str] = "Untitled board"
    description: Optional[str] = ""
    color: Optional[str] = None
    completed: Optional[bool] = False
    x: Optional[float] = 0
    y: Optional[float] = 0
    w: Optional[float] = 290
    h: Optional[float] = 260
    tasks: Optional[List[dict]] = Field(default_factory=list)


class ImportPayload(BaseModel):
    boards: List[ImportBoard]


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def sanitize_task(raw: dict) -> Optional[dict]:
    text = str((raw or {}).get("text") or "").strip()
    if not text:
        return None
    return {
        "id": (raw or {}).get("id") or new_id(),
        "text": text,
        "status": "done" if bool((raw or {}).get("done")) else "idle",
        "statusReason": None,
        "currentRunId": None,
    }


def task_to_json(task: dict) -> dict:
    out = dict(task)
    out["done"] = out.get("status") == "done"
    return out


def sanitize_import_board(raw: ImportBoard, index: int, z: int) -> dict:
    color = raw.color if raw.color in config.HUES else config.HUES[index % len(config.HUES)]
    w = clamp(float(raw.w or 290), config.MIN_W, config.CANVAS_W)
    h = clamp(float(raw.h or 260), config.MIN_H, config.CANVAS_H)
    x = clamp(float(raw.x or 0), 0, config.CANVAS_W - w)
    y = clamp(float(raw.y or 0), 0, config.CANVAS_H - h)
    tasks = [t for t in (sanitize_task(t) for t in (raw.tasks or [])) if t]
    return {
        "_id": new_id(),
        "title": (raw.title or "Untitled board").strip() or "Untitled board",
        "description": (raw.description or "").strip(),
        "color": color,
        "completed": bool(raw.completed),
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "z": z,
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


def board_to_json(doc: dict) -> dict:
    out = dict(doc)
    out["id"] = out.pop("_id")
    out["tasks"] = [task_to_json(t) for t in out.get("tasks", [])]
    out.setdefault("chats", [])
    out.setdefault("status", "idle")
    out.setdefault("stopRequested", False)
    out.setdefault("statusReason", None)
    out.setdefault("budgetCapUsd", None)
    out.setdefault("labelId", None)
    out.setdefault("glow", "none")
    return out


def board_export_shape(doc: dict) -> dict:
    return {
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "color": doc.get("color", "blue"),
        "completed": bool(doc.get("completed", False)),
        "x": doc.get("x", 0),
        "y": doc.get("y", 0),
        "w": doc.get("w", 290),
        "h": doc.get("h", 260),
        "tasks": [
            {"text": t.get("text", ""), "done": t.get("status") == "done"}
            for t in doc.get("tasks", [])
        ],
    }
