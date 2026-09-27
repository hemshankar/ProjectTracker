import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..chat_service import stream_reply
from ..database import boards_collection
from ..dependencies import get_current_user, require_board_access
from ..execution import approval
from ..models import ChatMessageIn
from ..services import audit_service, chats_service

router = APIRouter(
    prefix="/api/boards/{board_id}/chats",
    tags=["chats"],
    dependencies=[Depends(require_board_access("viewer"))],
)


class ActiveChatIn(BaseModel):
    chatId: str


async def _get_board(board_id: str) -> dict:
    doc = await boards_collection.find_one({"_id": board_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Board not found")
    return doc


@router.get("")
async def list_chats(board_id: str):
    board = await _get_board(board_id)
    return {"chats": board.get("chats", []), "activeChatId": board.get("activeChatId")}


@router.post("")
async def create_chat(board_id: str, user: dict = Depends(get_current_user)):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    chat = chats_service.new_chat()
    chats.append(chat)
    await chats_service.save_chats(board_id, chats, chat["id"])
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        entity_type="chat",
        action="create",
        actor_type="human",
        actor_id=user["_id"],
        before=None,
        after=chat,
    )
    return chat


@router.patch("/active")
async def set_active_chat(board_id: str, payload: ActiveChatIn):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    if not any(c["id"] == payload.chatId for c in chats):
        raise HTTPException(status_code=404, detail="Chat not found")
    await chats_service.save_chats(board_id, chats, payload.chatId)
    return {"ok": True}


@router.post("/{chat_id}/messages")
async def send_message(
    board_id: str, chat_id: str, payload: ChatMessageIn, user: dict = Depends(get_current_user)
):
    board = await _get_board(board_id)
    chats = board.get("chats", [])
    chat = next((c for c in chats if c["id"] == chat_id), None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_message = chats_service.text_message("user", payload.text)
    chat["messages"].append(user_message)
    history = [dict(m) for m in chat["messages"]]
    await chats_service.save_chats(board_id, chats, board.get("activeChatId") or chat_id)
    await audit_service.write_audit(
        agent_id=board.get("agentId"),
        board_id=board_id,
        entity_type="chat_message",
        action="create",
        actor_type="human",
        actor_id=user["_id"],
        before=None,
        after=user_message,
    )

    async def event_stream():
        assistant_text = ""
        try:
            async for delta in stream_reply(board, history):
                assistant_text += delta
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        finally:
            assistant_message = chats_service.text_message("assistant", assistant_text)
            chat["messages"].append(assistant_message)
            await chats_service.save_chats(board_id, chats, board.get("activeChatId") or chat_id)
            await audit_service.write_audit(
                agent_id=board.get("agentId"),
                board_id=board_id,
                entity_type="chat_message",
                action="create",
                actor_type="agent",
                actor_id=None,
                before=None,
                after=assistant_message,
            )
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _resolve_action(board_id: str, chat_id: str, message_id: str, approved: bool, user: dict) -> dict:
    board = await _get_board(board_id)
    chat = next((c for c in board.get("chats", []) if c["id"] == chat_id), None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    message = next((m for m in chat["messages"] if m.get("id") == message_id), None)
    if message is None or message.get("type") != "action_request":
        raise HTTPException(status_code=404, detail="Action request not found")

    try:
        outcome = await approval.resolve(board_id, chat_id, message_id, approved, user["_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if outcome.deferred:
        asyncio.create_task(approval.resolve_deferred(board_id, chat_id, message_id, user["_id"]))
    return outcome.board


@router.post("/{chat_id}/messages/{message_id}/approve")
async def approve_action(
    board_id: str, chat_id: str, message_id: str,
    user: dict = Depends(require_board_access("editor")),
):
    return await _resolve_action(board_id, chat_id, message_id, True, user)


@router.post("/{chat_id}/messages/{message_id}/reject")
async def reject_action(
    board_id: str, chat_id: str, message_id: str,
    user: dict = Depends(require_board_access("editor")),
):
    return await _resolve_action(board_id, chat_id, message_id, False, user)
