from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...container import Container, get_container
from .deps import ACTOR, require_admin, require_csrf

router = APIRouter(prefix="/credentials")


class CredentialValue(BaseModel):
    value: str


@router.get("", dependencies=[Depends(require_admin)])
async def list_credentials(c: Container = Depends(get_container)) -> List[dict]:
    return c.credentials.list()  # names + status only; values are never returned


@router.put("/{name}", dependencies=[Depends(require_csrf)])
async def set_credential(name: str, body: CredentialValue, c: Container = Depends(get_container)) -> dict:
    await c.credentials.set(name, body.value, ACTOR)
    return {"ok": True}


@router.delete("/{name}", dependencies=[Depends(require_csrf)])
async def delete_credential(name: str, c: Container = Depends(get_container)) -> dict:
    await c.credentials.delete(name, ACTOR)
    return {"ok": True}
