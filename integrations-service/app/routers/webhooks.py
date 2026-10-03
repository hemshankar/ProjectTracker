from fastapi import APIRouter, Depends, Request

from ..container import Container, get_container

router = APIRouter()


@router.post("/webhooks/{backend}")
async def receive(backend: str, request: Request, c: Container = Depends(get_container)) -> dict:
    # Public endpoint: authenticity is the backend's signature, checked before anything is parsed.
    body = await request.body()
    outcome = await c.webhooks.handle(backend, request.headers, body)
    return {"ok": True, "outcome": outcome}
