import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import httpx
import pytest

from app import dependencies
from app.accounting.counters import SpendCounters, board_scope
from app.accounting.query_client import AccountingUnavailable
from app.database import boards_collection, spend_counters_collection, usage_outbox_collection
from app.main import app
from app.routers import usage
from app.services import agents_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

AGENT, OTHER_AGENT, BOARD, TASK, USER = "ua-agent", "ua-other", "ua-board", "ua-task", "ua-user"
TOTALS = {"usd": 2.0, "calls": 4, "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 0,
          "cacheCreationTokens": 0, "webSearchCount": 0}


class FakeClient:
    def __init__(self):
        self.down, self.calls = False, []

    async def get(self, path, params):
        self.calls.append((path, params))
        if self.down:
            raise AccountingUnavailable("down")
        if path == "/summary/batch":
            return {i: {"usd": 1.0} for i in (params.get("boardIds") or params.get("taskIds")).split(",")}
        if path == "/breakdown":
            return [{**TOTALS, "key": BOARD, "name": "Old"}, {**TOTALS, "key": "ua-gone", "name": "Deleted board"}]
        if path == "/rows":
            return {"rows": [{"callId": "c1", "boardId": "ua-gone", "taskId": TASK, "model": "m"}], "nextCursor": None}
        if path == "/timeseries":
            return [{**TOTALS, "bucket": "2026-10-01", "bucketTs": 1, "key": None}]
        return TOTALS

    async def stream(self, path, params):
        self.calls.append((path, params))

        async def body():
            yield b"a,b\n"
            yield b"1,2\n"
        return {"content-disposition": 'attachment; filename="x.csv"', "content-type": "text/csv"}, body()

    async def ping(self):
        return not self.down


@pytest.fixture
async def api(monkeypatch):
    fake = FakeClient()
    roles = {"board": "viewer", "admin": False, "member": True}

    async def membership(agent_id, user_id):
        if agent_id != AGENT or not roles["member"]:
            return None
        return {"role": "admin" if roles["admin"] else "member"}

    async def board_role(board_id, user_id):
        board = await boards_collection.find_one({"_id": board_id})
        return (roles["board"], board) if board else (None, None)

    async def visible(agent_id, user_id):
        return [{"id": BOARD}]

    monkeypatch.setattr(dependencies, "get_agent_membership", membership)
    monkeypatch.setattr(dependencies, "get_board_role", board_role)
    monkeypatch.setattr(agents_service, "list_boards_for_agent", visible)
    for svc in (usage.member_usage, usage.admin_usage):
        monkeypatch.setattr(svc, "_client", fake)
    usage.member_usage._cache._items.clear()
    app.dependency_overrides[dependencies.get_current_user] = lambda: {"_id": USER}
    await boards_collection.delete_one({"_id": BOARD})
    await boards_collection.insert_one({"_id": BOARD, "agentId": AGENT, "title": "B", "tasks": [{"id": TASK, "text": "t"}]})
    await usage_outbox_collection.delete_many({"_id": {"$regex": "^ua-"}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, fake, roles
    app.dependency_overrides.clear()
    await boards_collection.delete_one({"_id": BOARD})
    await usage_outbox_collection.delete_many({"_id": {"$regex": "^ua-"}})
    await spend_counters_collection.delete_one({"_id": board_scope(BOARD)})


ADMIN_PATHS = ["summary", "timeseries", "breakdown", "rows", "export", "health"]


async def test_viewer_gets_totals_but_not_admin_endpoints(api):
    c, _, roles = api
    assert (await c.get(f"/api/boards/{BOARD}/usage")).json() == {"usd": 2.0, "stale": False, "calls": 4, "enabled": True}
    assert (await c.get(f"/api/boards/{BOARD}/tasks/{TASK}/usage")).status_code == 200
    for p in ADMIN_PATHS:
        assert (await c.get(f"/api/agents/{AGENT}/usage/{p}")).status_code == 403, p
    roles["admin"] = True
    for p in ADMIN_PATHS:
        assert (await c.get(f"/api/agents/{AGENT}/usage/{p}")).status_code == 200, p


async def test_non_member_is_rejected(api):
    c, _, roles = api
    roles["board"], roles["member"] = None, False
    assert (await c.get(f"/api/boards/{BOARD}/usage")).status_code == 403
    assert (await c.get(f"/api/agents/{AGENT}/usage/boards")).status_code == 403
    assert (await c.get(f"/api/agents/{OTHER_AGENT}/usage/summary")).status_code == 403


async def test_member_responses_have_no_breakdown_fields(api):
    c, _, _ = api
    for url in (f"/api/boards/{BOARD}/usage", f"/api/boards/{BOARD}/tasks/{TASK}/usage",
                f"/api/agents/{AGENT}/usage/boards", f"/api/boards/{BOARD}/usage/tasks"):
        body = (await c.get(url)).text
        for leaked in ("model", "userId", "callKind", "cacheRead", "webSearch"):
            assert leaked not in body, (url, leaked)


async def test_agent_id_is_path_derived_and_forged_param_ignored(api):
    c, fake, roles = api
    await c.get(f"/api/boards/{BOARD}/usage?agentId={OTHER_AGENT}")
    assert fake.calls[-1][1]["agentId"] == AGENT
    roles["admin"] = True
    await c.get(f"/api/agents/{AGENT}/usage/summary?agentId={OTHER_AGENT}")
    assert fake.calls[-1][1]["agentId"] == AGENT


async def test_task_costs_hidden_unless_admin_enabled(api):
    from app.database import agent_settings_collection
    c, _, _ = api
    await agent_settings_collection.delete_one({"_id": AGENT})
    off = (await c.get(f"/api/boards/{BOARD}/usage/tasks")).json()
    assert off["enabled"] is False and off["totals"] == {}
    await agent_settings_collection.insert_one({"_id": AGENT, "usageDisplay": {"showTaskCosts": True}})
    try:
        on = (await c.get(f"/api/boards/{BOARD}/usage/tasks")).json()
        assert on["enabled"] is True and on["totals"] == {TASK: 1.0}
    finally:
        await agent_settings_collection.delete_one({"_id": AGENT})


async def test_board_costs_can_be_hidden(api):
    from app.database import agent_settings_collection
    c, _, _ = api
    await agent_settings_collection.delete_one({"_id": AGENT})
    assert (await c.get(f"/api/boards/{BOARD}/usage")).json()["enabled"] is True  # on by default
    await agent_settings_collection.insert_one({"_id": AGENT, "usageDisplay": {"showBoardCosts": False}})
    try:
        one = (await c.get(f"/api/boards/{BOARD}/usage")).json()
        assert one["enabled"] is False and one["usd"] is None
        many = (await c.get(f"/api/agents/{AGENT}/usage/boards")).json()
        assert many["enabled"] is False and many["totals"] == {}
    finally:
        await agent_settings_collection.delete_one({"_id": AGENT})


async def test_batch_only_includes_visible_boards(api):
    c, fake, _ = api
    assert (await c.get(f"/api/agents/{AGENT}/usage/boards")).json()["totals"] == {BOARD: 1.0}
    assert fake.calls[-1][1]["boardIds"] == BOARD


async def test_pending_outbox_delta_is_added(api):
    c, _, _ = api
    for i in range(3):
        await usage_outbox_collection.insert_one({"_id": f"ua-{i}", "status": "pending", "createdAt": 1,
                                                  "event": {"boardId": BOARD, "taskId": TASK, "usd": 0.5}})
    assert (await c.get(f"/api/boards/{BOARD}/usage")).json()["usd"] == pytest.approx(3.5)
    assert (await c.get(f"/api/boards/{BOARD}/tasks/{TASK}/usage")).json()["usd"] == pytest.approx(3.5)


async def test_service_down_totals_stale_history_503(api):
    c, fake, roles = api
    roles["admin"] = True
    fake.down = True
    await SpendCounters().add(AGENT, BOARD, 1.25)
    assert (await c.get(f"/api/boards/{BOARD}/usage")).json() == {"usd": 1.25, "stale": True, "calls": 0, "enabled": True}
    task = (await c.get(f"/api/boards/{BOARD}/tasks/{TASK}/usage")).json()
    assert task["usd"] is None and task["stale"] is True
    r = await c.get(f"/api/agents/{AGENT}/usage/timeseries")
    assert r.status_code == 503 and r.json()["error"]["code"] == "accounting_unavailable"
    assert (await c.get(f"/api/boards/{BOARD}")).status_code != 503  # board loading unaffected by usage


async def test_deleted_flags(api):
    c, _, roles = api
    roles["admin"] = True
    rows = (await c.get(f"/api/agents/{AGENT}/usage/breakdown?groupBy=board")).json()
    assert {r["key"]: r["deleted"] for r in rows} == {BOARD: False, "ua-gone": True}
    row = (await c.get(f"/api/agents/{AGENT}/usage/rows")).json()["rows"][0]
    assert row["boardDeleted"] is True and row["taskDeleted"] is False


async def test_export_streams_passes_headers_and_limits_concurrency(api):
    c, _, roles = api
    roles["admin"] = True
    r = await c.get(f"/api/agents/{AGENT}/usage/export")
    assert r.text == "a,b\n1,2\n" and "x.csv" in r.headers["content-disposition"]
    usage.admin_usage._exports[AGENT] = 2
    assert (await c.get(f"/api/agents/{AGENT}/usage/export")).status_code == 429
    usage.admin_usage._exports.clear()
