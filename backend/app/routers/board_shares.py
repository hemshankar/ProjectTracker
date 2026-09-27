from fastapi import APIRouter, Depends

from ..database import boards_collection
from ..dependencies import require_board_access
from ..models_identity import ShareCreate
from ..services import sharing_service

router = APIRouter(prefix="/api/boards/{board_id}/shares", tags=["board_shares"])


@router.get("")
async def list_shares(board_id: str, _user: dict = Depends(require_board_access("editor"))):
    return await sharing_service.list_shares(board_id)


@router.post("")
async def create_share(
    board_id: str, payload: ShareCreate, user: dict = Depends(require_board_access("editor"))
):
    board = await boards_collection.find_one({"_id": board_id})
    return await sharing_service.share_board(board, user, payload)


@router.delete("/{user_id}")
async def delete_share(board_id: str, user_id: str, _user: dict = Depends(require_board_access("editor"))):
    await sharing_service.remove_share(board_id, user_id)
    return {"ok": True}
