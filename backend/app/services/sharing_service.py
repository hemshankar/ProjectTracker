from fastapi import HTTPException

from ..database import agent_members_collection, board_shares_collection, users_collection
from ..models import new_id, now_ms
from ..models_identity import ShareCreate, share_to_json


async def share_board(board: dict, requester: dict, payload: ShareCreate) -> dict:
    target = await users_collection.find_one({"email": payload.email})
    if not target:
        raise HTTPException(status_code=404, detail="No user has signed in with that email yet")
    target_user_id = target["_id"]

    if target_user_id == board.get("ownerId"):
        raise HTTPException(status_code=409, detail="That user already owns this board")

    existing = await board_shares_collection.find_one(
        {"boardId": board["_id"], "userId": target_user_id}
    )
    now = now_ms()
    if existing:
        await board_shares_collection.update_one(
            {"_id": existing["_id"]}, {"$set": {"role": payload.role}}
        )
        existing["role"] = payload.role
        doc = existing
    else:
        doc = {
            "_id": new_id(),
            "boardId": board["_id"],
            "userId": target_user_id,
            "role": payload.role,
            "invitedBy": requester["_id"],
            "createdAt": now,
        }
        await board_shares_collection.insert_one(doc)

    # Board access implies Agent access — auto-create membership if missing.
    agent_id = board.get("agentId")
    existing_member = await agent_members_collection.find_one(
        {"agentId": agent_id, "userId": target_user_id}
    )
    if not existing_member:
        await agent_members_collection.insert_one(
            {
                "_id": new_id(),
                "agentId": agent_id,
                "userId": target_user_id,
                "role": "member",
                "status": "active",
                "invitedBy": requester["_id"],
                "createdAt": now,
            }
        )

    return share_to_json(doc)


async def list_shares(board_id: str) -> list:
    shares = [share_to_json(s) async for s in board_shares_collection.find({"boardId": board_id})]
    user_ids = [s["userId"] for s in shares]
    users_by_id = {}
    if user_ids:
        async for u in users_collection.find({"_id": {"$in": user_ids}}):
            users_by_id[u["_id"]] = {"email": u.get("email"), "name": u.get("name")}
    for s in shares:
        s["user"] = users_by_id.get(s["userId"])
    return shares


async def remove_share(board_id: str, user_id: str) -> None:
    result = await board_shares_collection.delete_one({"boardId": board_id, "userId": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Share not found")
