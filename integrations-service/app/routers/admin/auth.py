from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ...container import Container, get_container
from ...errors import Unauthorized
from ...services.admin_auth_service import AdminSession
from .deps import COOKIE, require_admin, require_csrf

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response, c: Container = Depends(get_container)) -> dict:
    client = request.client.host if request.client else "unknown"
    result = c.admin_auth.login(client, req.password)
    if result is None:
        raise Unauthorized("Wrong password")
    cookie, csrf = result
    response.set_cookie(COOKIE, cookie, httponly=True, samesite="strict", path="/",
                        max_age=c.admin_session_ttl)
    return {"ok": True, "csrf": csrf}


@router.post("/logout")
async def logout(response: Response, _: AdminSession = Depends(require_csrf)) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(session: AdminSession = Depends(require_admin), c: Container = Depends(get_container)) -> dict:
    return {"authenticated": True, "csrf": c.admin_auth.csrf_for(session)}
