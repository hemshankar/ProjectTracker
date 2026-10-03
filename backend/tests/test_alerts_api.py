import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import httpx
import pytest

from app import dependencies
from app.accounting.reconcile import alerts
from app.accounting.reconcile.alert_store import AlertStore
from app.accounting.reconcile.alerts import Alert
from app.database import system_alerts_collection
from app.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT, USER = "al-agent", "al-user"
BACKLOG = Alert(alerts.OUTBOX_BACKLOG, "error", "Backed up", "5 waiting")
PRICING = Alert(alerts.PRICING_FALLBACK, "warning", "Fallback", "stale table")


@pytest.fixture
async def api(monkeypatch):
    roles = {"admin": True}

    async def membership(agent_id, user_id):
        return {"role": "admin" if roles["admin"] else "member"} if agent_id == AGENT else None

    monkeypatch.setattr(dependencies, "get_agent_membership", membership)
    app.dependency_overrides[dependencies.get_current_user] = lambda: {"_id": USER}
    await system_alerts_collection.delete_many({})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, roles
    app.dependency_overrides.clear()
    await system_alerts_collection.delete_many({})


async def test_apply_opens_refreshes_resolves_and_reopens(api):
    store = AlertStore()
    await store.apply([BACKLOG, PRICING], [alerts.OUTBOX_BACKLOG, alerts.PRICING_FALLBACK])
    await store.apply([BACKLOG], [alerts.OUTBOX_BACKLOG, alerts.PRICING_FALLBACK])
    rows = {r["key"]: r for r in await store.list(include_resolved=True)}
    assert rows[alerts.OUTBOX_BACKLOG]["count"] == 2 and rows[alerts.OUTBOX_BACKLOG]["status"] == "open"
    assert rows[alerts.PRICING_FALLBACK]["status"] == "resolved" and rows[alerts.PRICING_FALLBACK]["resolvedAt"]
    assert [r["key"] for r in await store.list()] == [alerts.OUTBOX_BACKLOG]  # resolved hidden by default

    await store.apply([], [alerts.OUTBOX_BACKLOG])           # clears
    await store.apply([PRICING], [alerts.PRICING_FALLBACK])  # fires again -> fresh alert
    reopened = (await store.list())[0]
    assert reopened["key"] == alerts.PRICING_FALLBACK and reopened["count"] == 1 and reopened["acknowledgedAt"] is None


async def test_alerts_outside_managed_keys_are_untouched(api):
    store = AlertStore()
    await store.apply([BACKLOG], [alerts.OUTBOX_BACKLOG])
    await store.apply([], [alerts.COUNTER_DRIFT])  # another job's check says nothing about the backlog
    assert [r["key"] for r in await store.list()] == [alerts.OUTBOX_BACKLOG]


async def test_summary_ack_and_ordering(api):
    c, _ = api
    store = AlertStore()
    await store.apply([PRICING, BACKLOG], [])
    assert (await c.get(f"/api/agents/{AGENT}/alerts/summary")).json() == {"unacknowledged": 2, "severity": "error"}
    listed = (await c.get(f"/api/agents/{AGENT}/alerts")).json()
    assert [a["key"] for a in listed] == [alerts.OUTBOX_BACKLOG, alerts.PRICING_FALLBACK]  # errors first

    assert (await c.post(f"/api/agents/{AGENT}/alerts/{alerts.OUTBOX_BACKLOG}/acknowledge")).status_code == 204
    assert (await c.get(f"/api/agents/{AGENT}/alerts/summary")).json() == {"unacknowledged": 1, "severity": "warning"}
    ack = (await c.get(f"/api/agents/{AGENT}/alerts")).json()[0]
    assert ack["acknowledgedBy"] == USER  # acknowledged alerts stay listed until the condition clears
    assert (await c.post(f"/api/agents/{AGENT}/alerts/nope/acknowledge")).status_code == 404


async def test_admin_only(api):
    c, roles = api
    roles["admin"] = False
    for method, path in (("get", "alerts"), ("get", "alerts/summary"), ("post", f"alerts/{alerts.OUTBOX_BACKLOG}/acknowledge")):
        assert (await getattr(c, method)(f"/api/agents/{AGENT}/{path}")).status_code == 403, path
    assert (await c.get("/api/agents/someone-elses/alerts")).status_code == 403
