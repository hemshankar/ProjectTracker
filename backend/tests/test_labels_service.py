import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest
from fastapi import HTTPException

from app.database import labels_collection
from app.services import labels_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

USER = {"_id": "test-user-labels"}


async def _reset():
    await labels_collection.delete_many({"name": {"$in": ["Urgent", "Work", "  "]}})


async def test_create_label_returns_shape():
    await _reset()
    try:
        label = await labels_service.create_label(USER, "Urgent", "clay")
        assert label["name"] == "Urgent"
        assert label["color"] == "clay"
        assert label["createdBy"] == USER["_id"]
        assert await labels_service.label_exists(label["id"]) is True
    finally:
        await _reset()


async def test_create_label_falls_back_on_unknown_color():
    await _reset()
    try:
        label = await labels_service.create_label(USER, "Urgent", "not-a-real-hue")
        assert label["color"] in ["blue", "sage", "clay", "mauve", "ochre", "slate"]
    finally:
        await _reset()


async def test_create_label_rejects_blank_name():
    await _reset()
    try:
        with pytest.raises(HTTPException) as exc:
            await labels_service.create_label(USER, "   ", "blue")
        assert exc.value.status_code == 400
    finally:
        await _reset()


async def test_create_label_rejects_duplicate_name():
    await _reset()
    try:
        await labels_service.create_label(USER, "Work", "blue")
        with pytest.raises(HTTPException) as exc:
            await labels_service.create_label(USER, "Work", "sage")
        assert exc.value.status_code == 409
    finally:
        await _reset()


async def test_list_labels_sorted_by_name():
    await _reset()
    try:
        await labels_service.create_label(USER, "Work", "blue")
        await labels_service.create_label(USER, "Urgent", "clay")
        names = [l["name"] for l in await labels_service.list_labels()]
        assert names == sorted(names)
        assert set(["Work", "Urgent"]).issubset(set(names))
    finally:
        await _reset()


async def test_get_label_returns_none_for_unknown_id():
    assert await labels_service.get_label("no-such-label") is None


async def test_get_label_returns_full_shape():
    await _reset()
    try:
        created = await labels_service.create_label(USER, "Work", "mauve")
        fetched = await labels_service.get_label(created["id"])
        assert fetched == created
    finally:
        await _reset()


async def test_label_exists_false_for_unknown_id():
    assert await labels_service.label_exists("no-such-label") is False
