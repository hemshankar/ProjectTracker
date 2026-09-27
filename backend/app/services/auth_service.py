from urllib.parse import urlencode

import httpx

from .. import config
from ..database import agent_members_collection, agents_collection, boards_collection, users_collection
from ..models import new_id, now_ms

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def build_google_authorize_url(state: str) -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_userinfo(code: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_resp.raise_for_status()
        return userinfo_resp.json()


async def upsert_user(userinfo: dict) -> dict:
    user_id = userinfo["sub"]
    now = now_ms()
    existing = await users_collection.find_one({"_id": user_id})
    fields = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("email"),
        "pictureUrl": userinfo.get("picture"),
        "lastLoginAt": now,
    }
    if existing:
        await users_collection.update_one({"_id": user_id}, {"$set": fields})
        existing.update(fields)
        return existing
    doc = {"_id": user_id, "createdAt": now, **fields}
    await users_collection.insert_one(doc)
    return doc


async def run_legacy_migration_if_needed(user: dict) -> None:
    """One-off: the first user to ever sign in inherits every pre-auth board
    under a freshly created default Agent, so existing boards aren't orphaned."""
    if await agents_collection.count_documents({}) > 0:
        return
    orphaned = await boards_collection.count_documents({"agentId": {"$exists": False}})
    if orphaned == 0:
        return

    agent_id = new_id()
    now = now_ms()
    await agents_collection.insert_one(
        {"_id": agent_id, "name": "Default Agent", "createdBy": user["_id"], "createdAt": now, "updatedAt": now}
    )
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
    await boards_collection.update_many(
        {"agentId": {"$exists": False}},
        {"$set": {"agentId": agent_id, "ownerId": user["_id"]}},
    )
