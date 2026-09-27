from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request

from . import config
from .database import agent_members_collection, board_shares_collection, boards_collection, users_collection
from .models_identity import BOARD_ROLE_RANK
from .security import verify_session


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    user_id = verify_session(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def get_agent_membership(agent_id: str, user_id: str) -> Optional[dict]:
    return await agent_members_collection.find_one(
        {"agentId": agent_id, "userId": user_id, "status": "active"}
    )


def require_agent_admin():
    async def dep(agent_id: str, user: dict = Depends(get_current_user)) -> dict:
        member = await get_agent_membership(agent_id, user["_id"])
        if not member or member.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Agent admin access required")
        return user

    return dep


def require_agent_member():
    async def dep(agent_id: str, user: dict = Depends(get_current_user)) -> dict:
        member = await get_agent_membership(agent_id, user["_id"])
        if not member:
            raise HTTPException(status_code=403, detail="Agent membership required")
        return user

    return dep


async def get_board_role(board_id: str, user_id: str) -> Tuple[Optional[str], Optional[dict]]:
    board = await boards_collection.find_one({"_id": board_id})
    if not board:
        return None, None
    if board.get("ownerId") == user_id:
        return "editor", board
    share = await board_shares_collection.find_one({"boardId": board_id, "userId": user_id})
    if share:
        return share["role"], board
    # An inbound-delegation board (Phase 6) has no owner or per-user shares —
    # it belongs to the Agent itself, so any of that Agent's members can
    # work the tasks other Agents delegated there.
    if board.get("inboundDelegation") and await get_agent_membership(board["agentId"], user_id):
        return "editor", board
    return None, board


def require_board_access(min_role: str = "viewer"):
    async def dep(board_id: str, user: dict = Depends(get_current_user)) -> dict:
        role, board = await get_board_role(board_id, user["_id"])
        if board is None:
            raise HTTPException(status_code=404, detail="Board not found")
        if role is None or BOARD_ROLE_RANK[role] < BOARD_ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail="Insufficient board access")
        return user

    return dep
