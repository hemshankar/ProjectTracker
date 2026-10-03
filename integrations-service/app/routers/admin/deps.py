import hmac

from fastapi import Depends, Request

from ...container import Container, get_container
from ...errors import Forbidden, Unauthorized
from ...services.admin_auth_service import AdminSession

COOKIE = "admin_session"
ACTOR = "admin"


async def require_admin(request: Request, c: Container = Depends(get_container)) -> AdminSession:
    session = c.admin_auth.read(request.cookies.get(COOKIE))
    if not session:
        raise Unauthorized("Admin login required")
    return session


async def require_csrf(request: Request, session: AdminSession = Depends(require_admin),
                       c: Container = Depends(get_container)) -> AdminSession:
    sent = request.headers.get("x-admin-csrf", "")
    if not hmac.compare_digest(sent, c.admin_auth.csrf_for(session)):
        raise Forbidden("Missing or invalid CSRF token")
    return session
