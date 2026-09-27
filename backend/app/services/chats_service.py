from typing import List, Optional

from pymongo import ReturnDocument

from ..database import boards_collection
from ..models import new_id, now_ms


def new_chat(task_id: Optional[str] = None) -> dict:
    chat = {"id": new_id(), "createdAt": now_ms(), "messages": []}
    if task_id is not None:
        chat["taskId"] = task_id
    return chat


def text_message(role: str, text: str) -> dict:
    return {"id": new_id(), "role": role, "type": "text", "text": text}


async def save_chats(board_id: str, chats: List[dict], active_chat_id: Optional[str]) -> None:
    await boards_collection.update_one(
        {"_id": board_id},
        {"$set": {"chats": chats, "activeChatId": active_chat_id, "updatedAt": now_ms()}},
    )


async def append_messages(board_id: str, chat_id: str, messages: List[dict]) -> None:
    """Atomically appends to one chat's message array via `$push`. Unlike
    `save_chats`' whole-array overwrite, this is safe when two of a board's
    tasks finish at nearly the same moment (Phase 6's within-board task
    parallelism) — each contributes its own messages without racing to
    replace the other's."""
    if not messages:
        return
    await boards_collection.update_one(
        {"_id": board_id, "chats.id": chat_id},
        {"$push": {"chats.$[c].messages": {"$each": messages}}, "$set": {"updatedAt": now_ms()}},
        array_filters=[{"c.id": chat_id}],
    )


async def update_message_payload(board_id: str, chat_id: str, message_id: str, payload_updates: dict) -> None:
    """Atomically patches one message's `payload` fields (e.g. an
    action-request's approved/rejected status and result) via array filters —
    same concurrent-safety rationale as `append_messages`."""
    sets = {f"chats.$[c].messages.$[m].payload.{k}": v for k, v in payload_updates.items()}
    sets["updatedAt"] = now_ms()
    await boards_collection.update_one(
        {"_id": board_id},
        {"$set": sets},
        array_filters=[{"c.id": chat_id}, {"m.id": message_id}],
    )


async def get_or_create_active_chat(board: dict) -> dict:
    """Returns `board`'s active chat, creating and persisting one if none
    exists yet. The returned dict lives inside `board["chats"]`, so callers
    can mutate its `messages` in place and persist new ones later with
    `append_messages`.

    The creation step is a conditional update (only when the board still has
    no active chat), not a blind `save_chats` — with Phase 6's within-board
    task parallelism, two tasks can both hit "no chat yet" on a brand-new
    board at nearly the same moment, and a bare whole-array overwrite would
    let the second one silently erase the first one's freshly created chat.
    """
    chats = board.setdefault("chats", [])
    chat = next((c for c in chats if c["id"] == board.get("activeChatId")), None)
    if chat is not None:
        return chat

    chat = new_chat()
    updated = await boards_collection.find_one_and_update(
        {"_id": board["_id"], "activeChatId": board.get("activeChatId")},
        {"$push": {"chats": chat}, "$set": {"activeChatId": chat["id"], "updatedAt": now_ms()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        # Lost the race — a concurrent task already created one; use theirs.
        fresh = await boards_collection.find_one({"_id": board["_id"]})
        chats[:] = fresh.get("chats", [])
        board["activeChatId"] = fresh.get("activeChatId")
        return next(c for c in chats if c["id"] == board["activeChatId"])

    chats.append(chat)
    board["activeChatId"] = chat["id"]
    return chat


async def get_or_create_task_chat(board: dict, task: dict) -> dict:
    """Returns `task`'s own persistent chat, creating and persisting one if
    none exists yet — every run of this task (first run, or a resume after
    an approval/clarification) shares this one chat, so its history is
    never split across an unrelated board-level chat. Same conditional-
    creation race-safety rationale as `get_or_create_active_chat`: two
    tasks' runs can start at nearly the same moment, but never for the
    *same* task, so racing here only ever means "someone else already
    created this exact task's chat."
    """
    task_id = task["id"]
    chats = board.setdefault("chats", [])
    chat = next((c for c in chats if c.get("taskId") == task_id), None)
    if chat is not None:
        return chat

    chat = new_chat(task_id=task_id)
    updated = await boards_collection.find_one_and_update(
        {"_id": board["_id"], "chats": {"$not": {"$elemMatch": {"taskId": task_id}}}},
        {"$push": {"chats": chat}, "$set": {"updatedAt": now_ms()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        fresh = await boards_collection.find_one({"_id": board["_id"]})
        chats[:] = fresh.get("chats", [])
        return next(c for c in chats if c.get("taskId") == task_id)

    chats.append(chat)
    return chat
