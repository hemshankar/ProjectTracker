from typing import Literal, Optional

from pydantic import BaseModel

AgentRole = Literal["admin", "member"]
MemberStatus = Literal["requested", "active"]
BoardRole = Literal["viewer", "editor"]

BOARD_ROLE_RANK = {"viewer": 0, "editor": 1}


class AgentCreate(BaseModel):
    name: str


class MemberInvite(BaseModel):
    email: str
    role: Optional[AgentRole] = "member"


class MemberUpdate(BaseModel):
    role: Optional[AgentRole] = None
    status: Optional[MemberStatus] = None


class ShareCreate(BaseModel):
    email: str
    role: BoardRole = "viewer"


def user_to_json(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "email": doc.get("email"),
        "name": doc.get("name"),
        "pictureUrl": doc.get("pictureUrl"),
    }


def agent_to_json(doc: dict, my_role: Optional[str] = None) -> dict:
    out = {
        "id": doc["_id"],
        "name": doc.get("name"),
        "createdBy": doc.get("createdBy"),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
    }
    if my_role is not None:
        out["myRole"] = my_role
    return out


def member_to_json(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "agentId": doc.get("agentId"),
        "userId": doc.get("userId"),
        "role": doc.get("role"),
        "status": doc.get("status"),
        "invitedBy": doc.get("invitedBy"),
        "createdAt": doc.get("createdAt"),
    }


def share_to_json(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "boardId": doc.get("boardId"),
        "userId": doc.get("userId"),
        "role": doc.get("role"),
        "invitedBy": doc.get("invitedBy"),
        "createdAt": doc.get("createdAt"),
    }
