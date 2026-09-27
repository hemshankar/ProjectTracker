import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .. import config
from ..dependencies import get_current_user
from ..models_identity import user_to_json
from ..security import sign_session, sign_state, verify_state
from ..services.auth_service import (
    build_google_authorize_url,
    exchange_code_for_userinfo,
    run_legacy_migration_if_needed,
    upsert_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE_NAME = "scatterboard_oauth_state"


@router.get("/google/login")
async def google_login():
    state = secrets.token_urlsafe(16)
    url = build_google_authorize_url(state)
    resp = RedirectResponse(url)
    resp.set_cookie(
        STATE_COOKIE_NAME,
        sign_state(state),
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = ""):
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    verified = verify_state(cookie_state) if cookie_state else None
    if not code or not verified or verified != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    userinfo = await exchange_code_for_userinfo(code)
    user = await upsert_user(userinfo)
    await run_legacy_migration_if_needed(user)

    resp = RedirectResponse(config.FRONTEND_ORIGIN)
    resp.delete_cookie(STATE_COOKIE_NAME)
    resp.set_cookie(
        config.SESSION_COOKIE_NAME,
        sign_session(user["_id"]),
        max_age=config.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    return resp


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(config.SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user_to_json(user)
