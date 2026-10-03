import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...actions.catalog import CATALOG
from ...container import Container, get_container
from ...errors import GatewayError
from .deps import require_csrf

router = APIRouter(prefix="/providers/{tool_type}", dependencies=[Depends(require_csrf)])
TEST_USER = "admin-test"


class TestConnect(BaseModel):
    callbackUrl: str = "http://localhost:8101"


@router.post("/test-connect")
async def test_connect(tool_type: str, body: TestConnect, c: Container = Depends(get_container)) -> dict:
    session = await c.connections.create_session(TEST_USER, tool_type, body.callbackUrl)
    return {"url": session.url}


@router.post("/test-action")
async def test_action(tool_type: str, c: Container = Depends(get_container)) -> dict:
    """Runs one read-only action as the test user. Returns status and latency, never the body."""
    action = next((a.name for a in CATALOG.values() if a.tool_type == tool_type and not a.mutating), None)
    if not action:
        return {"ok": False, "error": "no read-only action for this provider", "latencyMs": 0}
    started = time.monotonic()
    try:
        result = await c.actions.execute(TEST_USER, tool_type, action, {}, caller="admin")
        outcome = {"ok": result.ok, "error": result.error}
    except GatewayError as exc:
        outcome = {"ok": False, "error": f"{exc.code}: {exc.message}"}
    return {**outcome, "action": action, "latencyMs": int((time.monotonic() - started) * 1000)}
