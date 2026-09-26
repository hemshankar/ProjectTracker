import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..chat_service import stream_reply
from ..database import boards_collection
from ..models import ChatMessageIn, new_id, now_ms

router = APIRouter(prefix="/api/boards/{board_id}/chats", tags=["chats"])


class ActiveChatIn(BaseModel):
    chatId: str


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


def _new_chat() -> dict:
    return {"id": new_id(), "createdAt": now_ms(), "messages": []}


async def _save_board_chats(board_id: str, chats: list, active_chat_id: str):
    await boards_collection.update_one(
        {"_id": board_id},
        {"$set": {"chats": chats, "activeChatId": active_chat_id, "updatedAt": now_ms()}},
    )


@router.get("")
async def list_chats(board_id: str):
    board = await _get_board(board_id)
    return {"chats": board.get("chats", []), "activeChatId": board.get("activeChatId")}


@router.post("")
async def create_chat(board_id: str):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    chat = _new_chat()
    chats.append(chat)
    await _save_board_chats(board_id, chats, chat["id"])
    return chat


@router.patch("/active")
async def set_active_chat(board_id: str, payload: ActiveChatIn):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    if not any(c["id"] == payload.chatId for c in chats):
        raise HTTPException(status_code=404, detail="Chat not found")
    await boards_collection.update_one(
        {"_id": board_id}, {"$set": {"activeChatId": payload.chatId, "updatedAt": now_ms()}}
    )
    return {"ok": True}


@router.post("/{chat_id}/messages")
async def send_message(board_id: str, chat_id: str, payload: ChatMessageIn):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    chat = next((c for c in chats if c["id"] == chat_id), None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_message = {"role": "user", "text": payload.text}
    chat["messages"].append(user_message)
    history = [dict(m) for m in chat["messages"]]
    await _save_board_chats(board_id, chats, board.get("activeChatId") or chat_id)

    async def event_stream():
        assistant_text = ""
        try:
            async for delta in stream_reply(board, history):
                assistant_text += delta
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        finally:
            chat["messages"].append({"role": "assistant", "text": assistant_text})
            await _save_board_chats(board_id, chats, board.get("activeChatId") or chat_id)
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
