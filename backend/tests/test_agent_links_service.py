import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import pytest
from fastapi import HTTPException

from app.database import agent_links_collection, agents_collection
from app.services import agent_links_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT_A = "test-agent-links-a"
AGENT_B = "test-agent-links-b"
ADMIN_USER = "test-user-links-admin"


async def _reset():
    await agent_links_collection.delete_many({"fromAgentId": {"$in": [AGENT_A, AGENT_B]}})
    await agents_collection.delete_many({"_id": {"$in": [AGENT_A, AGENT_B]}})
    await agents_collection.insert_many([
        {"_id": AGENT_A, "name": "Agent A"},
        {"_id": AGENT_B, "name": "Agent B"},
    ])


async def test_no_link_by_default():
    await _reset()
    try:
        assert await agent_links_service.has_link(AGENT_A, AGENT_B) is False
    finally:
        await _reset()


async def test_grant_link_makes_has_link_true():
    await _reset()
    try:
        link = await agent_links_service.grant_link(AGENT_A, AGENT_B, ADMIN_USER)
        assert link["fromAgentId"] == AGENT_A
        assert link["toAgentId"] == AGENT_B
        assert link["toAgentName"] == "Agent B"
        assert await agent_links_service.has_link(AGENT_A, AGENT_B) is True
        # The reverse direction is never implicitly granted.
        assert await agent_links_service.has_link(AGENT_B, AGENT_A) is False
    finally:
        await _reset()


async def test_granting_twice_is_idempotent():
    await _reset()
    try:
        await agent_links_service.grant_link(AGENT_A, AGENT_B, ADMIN_USER)
        await agent_links_service.grant_link(AGENT_A, AGENT_B, ADMIN_USER)
        count = await agent_links_collection.count_documents({"fromAgentId": AGENT_A, "toAgentId": AGENT_B})
        assert count == 1
    finally:
        await _reset()


async def test_cannot_grant_self_delegation():
    await _reset()
    try:
        with pytest.raises(HTTPException):
            await agent_links_service.grant_link(AGENT_A, AGENT_A, ADMIN_USER)
    finally:
        await _reset()


async def test_revoke_removes_link():
    await _reset()
    try:
        await agent_links_service.grant_link(AGENT_A, AGENT_B, ADMIN_USER)
        await agent_links_service.revoke_link(AGENT_A, AGENT_B, ADMIN_USER)
        assert await agent_links_service.has_link(AGENT_A, AGENT_B) is False
    finally:
        await _reset()


async def test_revoke_missing_link_raises():
    await _reset()
    try:
        with pytest.raises(HTTPException):
            await agent_links_service.revoke_link(AGENT_A, AGENT_B, ADMIN_USER)
    finally:
        await _reset()
