from typing import Literal, Optional

from pydantic import BaseModel

AgentRole = Literal["admin", "member"]
MemberStatus = Literal["requested", "active"]
BoardRole = Literal["viewer", "editor"]

BOARD_ROLE_RANK = {"viewer": 0, "editor": 1}


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class MemberInvite(BaseModel):
    email: str
    role: Optional[AgentRole] = "member"


class MemberUpdate(BaseModel):
    role: Optional[AgentRole] = None
    status: Optional[MemberStatus] = None


class ShareCreate(BaseModel):
    email: str
    role: BoardRole = "viewer"


class AgentLinkCreate(BaseModel):
    toAgentId: str


class LabelCreate(BaseModel):
    name: str
    color: str


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
        "description": doc.get("description") or "",
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


def label_to_json(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "name": doc.get("name"),
        "color": doc.get("color"),
        "createdBy": doc.get("createdBy"),
        "createdAt": doc.get("createdAt"),
    }


def agent_link_to_json(doc: dict, to_agent: Optional[dict] = None) -> dict:
    return {
        "id": doc["_id"],
        "fromAgentId": doc.get("fromAgentId"),
        "toAgentId": doc.get("toAgentId"),
        "toAgentName": (to_agent or {}).get("name"),
        "toAgentDescription": (to_agent or {}).get("description") or "",
        "grantedBy": doc.get("grantedBy"),
        "createdAt": doc.get("createdAt"),
    }
