from typing import List, Optional

from ..database import boards_collection
from ..models import new_id, now_ms


def new_chat() -> dict:
    return {"id": new_id(), "createdAt": now_ms(), "messages": []}


def text_message(role: str, text: str) -> dict:
    return {"id": new_id(), "role": role, "type": "text", "text": text}


async def save_chats(board_id: str, chats: List[dict], active_chat_id: Optional[str]) -> None:
    await boards_collection.update_one(
        {"_id": board_id},
        {"$set": {"chats": chats, "activeChatId": active_chat_id, "updatedAt": now_ms()}},
    )


async def get_or_create_active_chat(board: dict) -> dict:
    """Returns `board`'s active chat, creating and persisting one if none
    exists yet. The returned dict lives inside `board["chats"]`, so callers
    can mutate its `messages` in place and persist later with `save_chats`.
    """
    chats = board.setdefault("chats", [])
    chat = next((c for c in chats if c["id"] == board.get("activeChatId")), None)
    if chat is not None:
        return chat

    chat = new_chat()
    chats.append(chat)
    board["activeChatId"] = chat["id"]
    await save_chats(board["_id"], chats, chat["id"])
    return chat
