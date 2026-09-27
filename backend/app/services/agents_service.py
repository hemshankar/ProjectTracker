from fastapi import HTTPException

from ..database import (
    agent_members_collection,
    agents_collection,
    board_shares_collection,
    boards_collection,
    users_collection,
)
from ..models import new_id, now_ms, board_to_json
from ..models_identity import MemberInvite, MemberUpdate, agent_to_json, member_to_json


async def create_agent(user: dict, name: str) -> dict:
    agent_id = new_id()
    now = now_ms()
    doc = {"_id": agent_id, "name": name.strip() or "Untitled Agent", "createdBy": user["_id"], "createdAt": now, "updatedAt": now}
    await agents_collection.insert_one(doc)
    await agent_members_collection.insert_one(
        {
            "_id": new_id(),
            "agentId": agent_id,
            "userId": user["_id"],
            "role": "admin",
            "status": "active",
            "invitedBy": user["_id"],
            "createdAt": now,
        }
    )
    return agent_to_json(doc, my_role="admin")


async def list_agents_for_user(user: dict) -> list:
    cursor = agent_members_collection.find({"userId": user["_id"], "status": "active"})
    memberships = [m async for m in cursor]
    if not memberships:
        return []
    agent_ids = [m["agentId"] for m in memberships]
    role_by_agent = {m["agentId"]: m["role"] for m in memberships}
    agents_cursor = agents_collection.find({"_id": {"$in": agent_ids}})
    return [agent_to_json(a, my_role=role_by_agent.get(a["_id"])) async for a in agents_cursor]


async def _resolve_target_user_id(payload: MemberInvite) -> str:
    target = await users_collection.find_one({"email": payload.email})
    if not target:
        raise HTTPException(status_code=404, detail="No user has signed in with that email yet")
    return target["_id"]


async def invite_or_request_member(agent_id: str, requester: dict, payload: MemberInvite) -> dict:
    target_user_id = await _resolve_target_user_id(payload)
    requester_membership = await agent_members_collection.find_one(
        {"agentId": agent_id, "userId": requester["_id"], "status": "active"}
    )
    is_admin = bool(requester_membership and requester_membership.get("role") == "admin")

    if target_user_id != requester["_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Only an Agent Admin can invite other users")

    existing = await agent_members_collection.find_one({"agentId": agent_id, "userId": target_user_id})
    if existing:
        raise HTTPException(status_code=409, detail="That user is already a member or has a pending request")

    status = "active" if is_admin else "requested"
    role = payload.role if is_admin else "member"
    doc = {
        "_id": new_id(),
        "agentId": agent_id,
        "userId": target_user_id,
        "role": role,
        "status": status,
        "invitedBy": requester["_id"],
        "createdAt": now_ms(),
    }
    await agent_members_collection.insert_one(doc)
    return member_to_json(doc)


async def update_member(agent_id: str, user_id: str, payload: MemberUpdate) -> dict:
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        member = await agent_members_collection.find_one({"agentId": agent_id, "userId": user_id})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        return member_to_json(member)
    result = await agent_members_collection.update_one(
        {"agentId": agent_id, "userId": user_id}, {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    member = await agent_members_collection.find_one({"agentId": agent_id, "userId": user_id})
    return member_to_json(member)


async def remove_member(agent_id: str, user_id: str) -> None:
    result = await agent_members_collection.delete_one({"agentId": agent_id, "userId": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")


async def list_members(agent_id: str) -> list:
    cursor = agent_members_collection.find({"agentId": agent_id})
    members = [member_to_json(m) async for m in cursor]
    user_ids = [m["userId"] for m in members]
    users_by_id = {}
    if user_ids:
        async for u in users_collection.find({"_id": {"$in": user_ids}}):
            users_by_id[u["_id"]] = {"email": u.get("email"), "name": u.get("name")}
    for m in members:
        m["user"] = users_by_id.get(m["userId"])
    return members


async def list_boards_for_agent(agent_id: str, user_id: str) -> list:
    owned_cursor = boards_collection.find({"agentId": agent_id, "ownerId": user_id})
    owned = [b async for b in owned_cursor]

    shares_cursor = board_shares_collection.find({"userId": user_id})
    shared_board_ids = [s["boardId"] async for s in shares_cursor]
    shared = []
    if shared_board_ids:
        shared_cursor = boards_collection.find(
            {"agentId": agent_id, "_id": {"$in": shared_board_ids}, "ownerId": {"$ne": user_id}}
        )
        shared = [b async for b in shared_cursor]

    role_by_board = {s["boardId"]: s.get("role") for s in await board_shares_collection.find(
        {"userId": user_id}
    ).to_list(length=None)}

    docs = owned + shared
    docs.sort(key=lambda d: d.get("z", 0))
    out = []
    for d in docs:
        board = board_to_json(d)
        board["myRole"] = "editor" if d.get("ownerId") == user_id else role_by_board.get(d["_id"], "viewer")
        out.append(board)
    return out
