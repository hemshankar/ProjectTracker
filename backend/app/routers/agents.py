import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from .. import config
from ..database import users_collection
from ..dependencies import get_agent_membership, get_current_user, require_agent_admin, require_agent_member
from ..execution.events import events
from ..models_identity import AgentCreate, AgentLinkCreate, AgentUpdate, MemberInvite, MemberUpdate
from ..security import verify_session
from ..services import agent_links_service, agents_service, observability, undo_service

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("")
async def create_agent(payload: AgentCreate, user: dict = Depends(get_current_user)):
    return await agents_service.create_agent(user, payload.name, payload.description or "")


@router.get("")
async def list_agents(user: dict = Depends(get_current_user)):
    return await agents_service.list_agents_for_user(user)


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, payload: AgentUpdate, admin: dict = Depends(require_agent_admin())):
    return await agents_service.update_agent(agent_id, payload, admin["_id"])


@router.get("/{agent_id}/boards")
async def list_agent_boards(agent_id: str, user: dict = Depends(require_agent_member())):
    return await agents_service.list_boards_for_agent(agent_id, user["_id"])


@router.websocket("/{agent_id}/ws")
async def agent_board_events(websocket: WebSocket, agent_id: str):
    """One connection per agent, multiplexing every visible board's status/
    task/glow events — replaces what used to be one SSE connection per
    board, which was exhausting the browser's per-origin connection limit
    once an agent had more than a handful of boards open at once.

    Dependency injection doesn't run for WebSocket routes the way it does
    for HTTP ones, so auth is done by hand here rather than reusing
    `get_current_user`/`require_agent_member`.
    """
    token = websocket.cookies.get(config.SESSION_COOKIE_NAME)
    user_id = verify_session(token) if token else None
    user = await users_collection.find_one({"_id": user_id}) if user_id else None
    if not user or not await get_agent_membership(agent_id, user_id):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    subscribed_ids: set = set()

    async def resync():
        boards = await agents_service.list_boards_for_agent(agent_id, user_id)
        board_ids = {b["id"] for b in boards}
        added = board_ids - subscribed_ids
        removed = subscribed_ids - board_ids
        if added:
            events.subscribe_many(added, queue)
            subscribed_ids.update(added)
        if removed:
            events.unsubscribe_many(removed, queue)
            subscribed_ids.difference_update(removed)

    await resync()

    async def sender():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=config.BOARD_EVENTS_POLL_SECONDS)
            except asyncio.TimeoutError:
                await resync()
                continue
            await websocket.send_json(event)

    async def receiver():
        # The client never sends anything meaningful — this is just what
        # notices a closed socket, since `sender` only ever calls `send`.
        while True:
            await websocket.receive_text()

    sender_task = asyncio.create_task(sender())
    receiver_task = asyncio.create_task(receiver())
    try:
        done, pending = await asyncio.wait({sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        events.unsubscribe_many(subscribed_ids, queue)


@router.post("/{agent_id}/undo")
async def undo(agent_id: str, user: dict = Depends(require_agent_member())):
    """Undoes this user's own most recent board/task edit within this Agent
    — see `services.undo_service` for scope and semantics."""
    return await undo_service.undo(agent_id, user["_id"])


@router.post("/{agent_id}/redo")
async def redo(agent_id: str, user: dict = Depends(require_agent_member())):
    return await undo_service.redo(agent_id, user["_id"])


@router.get("/{agent_id}/members")
async def list_members(agent_id: str, user: dict = Depends(require_agent_member())):
    return await agents_service.list_members(agent_id)


@router.post("/{agent_id}/members")
async def invite_member(agent_id: str, payload: MemberInvite, user: dict = Depends(get_current_user)):
    return await agents_service.invite_or_request_member(agent_id, user, payload)


@router.patch("/{agent_id}/members/{user_id}")
async def update_member(
    agent_id: str, user_id: str, payload: MemberUpdate, _admin: dict = Depends(require_agent_admin())
):
    return await agents_service.update_member(agent_id, user_id, payload)


@router.delete("/{agent_id}/members/{user_id}")
async def remove_member(agent_id: str, user_id: str, _admin: dict = Depends(require_agent_admin())):
    await agents_service.remove_member(agent_id, user_id)
    return {"ok": True}


# ---------------- delegation links (Phase 6) ----------------


@router.get("/{agent_id}/links")
async def list_links(agent_id: str, _user: dict = Depends(require_agent_member())):
    return await agent_links_service.list_links_from(agent_id)


@router.post("/{agent_id}/links")
async def create_link(agent_id: str, payload: AgentLinkCreate, admin: dict = Depends(require_agent_admin())):
    return await agent_links_service.grant_link(agent_id, payload.toAgentId, admin["_id"])


@router.delete("/{agent_id}/links/{to_agent_id}")
async def delete_link(agent_id: str, to_agent_id: str, admin: dict = Depends(require_agent_admin())):
    await agent_links_service.revoke_link(agent_id, to_agent_id, admin["_id"])
    return {"ok": True}


# ---------------- Agent Admin Console: Activity/Traces (Phase 8) ----------------


@router.get("/{agent_id}/audit")
async def get_agent_audit(
    agent_id: str,
    boardId: Optional[str] = None,
    taskId: Optional[str] = None,
    actorType: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    _admin: dict = Depends(require_agent_admin()),
):
    return await observability.list_audit(
        agent_id, board_id=boardId, task_id=taskId, actor_type=actorType, since=since, until=until
    )


@router.get("/{agent_id}/llm-calls")
async def get_agent_llm_calls(
    agent_id: str,
    boardId: Optional[str] = None,
    taskId: Optional[str] = None,
    runId: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    _admin: dict = Depends(require_agent_admin()),
):
    return await observability.list_llm_calls(
        agent_id, board_id=boardId, task_id=taskId, run_id=runId, since=since, until=until
    )


@router.get("/{agent_id}/llm-calls/{call_id}")
async def get_agent_llm_call_detail(agent_id: str, call_id: str, _admin: dict = Depends(require_agent_admin())):
    call = await observability.get_llm_call(agent_id, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="LLM call not found")
    return call
