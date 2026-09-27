from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..models_identity import LabelCreate
from ..services import labels_service

router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.post("")
async def create_label(payload: LabelCreate, user: dict = Depends(get_current_user)):
    return await labels_service.create_label(user, payload.name, payload.color)


@router.get("")
async def list_labels(_user: dict = Depends(get_current_user)):
    return await labels_service.list_labels()
