"""CRUD for `agent_links` — an explicit, Agent-Admin-granted permission for
one Agent to delegate work to another (Phase 6). Entity/permission checks
only; the actual delegated-task creation lives in `execution/delegation.py`.
"""
from fastapi import HTTPException

from ..database import agent_links_collection, agents_collection
from ..models import new_id, now_ms
from ..models_identity import agent_link_to_json
from . import audit_service


async def has_link(from_agent_id: str, to_agent_id: str) -> bool:
    doc = await agent_links_collection.find_one({"fromAgentId": from_agent_id, "toAgentId": to_agent_id})
    return doc is not None


async def grant_link(from_agent_id: str, to_agent_id: str, granted_by: str) -> dict:
    if to_agent_id == from_agent_id:
        raise HTTPException(status_code=400, detail="An Agent cannot delegate to itself")
    target = await agents_collection.find_one({"_id": to_agent_id})
    if not target:
        raise HTTPException(status_code=404, detail="Target Agent not found")

    existing = await agent_links_collection.find_one({"fromAgentId": from_agent_id, "toAgentId": to_agent_id})
    if existing:
        return agent_link_to_json(existing, target)

    doc = {
        "_id": new_id(),
        "fromAgentId": from_agent_id,
        "toAgentId": to_agent_id,
        "grantedBy": granted_by,
        "createdAt": now_ms(),
    }
    await agent_links_collection.insert_one(doc)
    await audit_service.write_audit(
        agent_id=from_agent_id,
        board_id=None,
        entity_type="agent_link",
        action="create",
        actor_type="human",
        actor_id=granted_by,
        before=None,
        after=doc,
    )
    return agent_link_to_json(doc, target)


async def revoke_link(from_agent_id: str, to_agent_id: str, actor_id: str) -> None:
    before = await agent_links_collection.find_one({"fromAgentId": from_agent_id, "toAgentId": to_agent_id})
    if not before:
        raise HTTPException(status_code=404, detail="Delegation link not found")
    await agent_links_collection.delete_one({"fromAgentId": from_agent_id, "toAgentId": to_agent_id})
    await audit_service.write_audit(
        agent_id=from_agent_id,
        board_id=None,
        entity_type="agent_link",
        action="delete",
        actor_type="human",
        actor_id=actor_id,
        before=before,
        after=None,
    )


async def list_links_from(from_agent_id: str) -> list:
    links = [doc async for doc in agent_links_collection.find({"fromAgentId": from_agent_id})]
    if not links:
        return []
    targets = {}
    async for a in agents_collection.find({"_id": {"$in": [l["toAgentId"] for l in links]}}):
        targets[a["_id"]] = a
    return [agent_link_to_json(l, targets.get(l["toAgentId"])) for l in links]
