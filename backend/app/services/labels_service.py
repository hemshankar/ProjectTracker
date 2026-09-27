"""Board labels: a small, global, shared-across-every-board set (not scoped
per agent) — matching how board colors are a fixed global list rather than
per-agent. Any authenticated user can create one, same as creating an Agent
requires nothing beyond being logged in; there's no admin gate here because
there's no per-agent (or higher) resource being changed.

A label carries its own color, born from whatever board it was first created
on. Assigning a label to a board locks that board's color to the label's —
see `routers/boards.py` — though different labels are free to share the same
color; only a board's own color is tied to its label, not the reverse.
"""
from typing import Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from .. import config
from ..database import labels_collection
from ..models import new_id, now_ms
from ..models_identity import label_to_json


async def create_label(user: dict, name: str, color: str) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Label name is required")
    if await labels_collection.find_one({"name": name}):
        raise HTTPException(status_code=409, detail="A label with that name already exists")
    doc = {
        "_id": new_id(),
        "name": name,
        "color": color if color in config.HUES else config.HUES[0],
        "createdBy": user["_id"],
        "createdAt": now_ms(),
    }
    try:
        await labels_collection.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A label with that name already exists")
    return label_to_json(doc)


async def list_labels() -> list:
    cursor = labels_collection.find().sort("name", 1)
    return [label_to_json(doc) async for doc in cursor]


async def get_label(label_id: str) -> Optional[dict]:
    doc = await labels_collection.find_one({"_id": label_id})
    return label_to_json(doc) if doc else None


async def label_exists(label_id: str) -> bool:
    return await labels_collection.find_one({"_id": label_id}) is not None
