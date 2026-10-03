import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.execution import tools
from app.integrations_client import GatewayResult
from app.main import app
from app.routers.tools import get_integrations_client

CONNS = [
    {"toolType": "gmail", "connected": True, "label": "work@acme.com", "connectionId": "c1", "ownerUserId": None, "isDefault": True},
    {"toolType": "gmail", "connected": True, "label": "me@home.com", "connectionId": "c2", "ownerUserId": "u1", "isDefault": False},
]


class FakeClient:
    def __init__(self):
        self.sessions, self.removed, self.defaults, self.executed = [], [], [], []

    async def ping(self): return True

    async def create_session(self, agent_id, tool_type, callback_url, owner_user_id=None, label=None):
        self.sessions.append((tool_type, owner_user_id, label))
        return "https://connect.example/x"

    async def list_connections(self, agent_id, acting_user=None):
        return [c for c in CONNS if c["ownerUserId"] in (None, acting_user)]

    async def disconnect_connection(self, agent_id, connection_id, acting_user=None):
        self.removed.append((connection_id, acting_user))

    async def set_default(self, agent_id, connection_id, acting_user=None):
        self.defaults.append(connection_id)

    async def execute(self, agent_id, tool_type, action, args, connection_id=None, acting_user=None):
        self.executed.append((connection_id, args))
        return GatewayResult(ok=True)


@pytest.fixture
def api(monkeypatch):
    fake, state = FakeClient(), {"role": "member", "user": "u1"}

    async def membership(agent_id, user_id):
        return {"role": state["role"]}

    monkeypatch.setattr(dependencies, "get_agent_membership", membership)
    app.dependency_overrides[dependencies.get_current_user] = lambda: {"_id": state["user"]}
    app.dependency_overrides[get_integrations_client] = lambda: fake
    yield TestClient(app), fake, state
    app.dependency_overrides.clear()


def test_member_can_connect_personal_but_not_shared(api):
    client, fake, _ = api
    assert client.get("/api/agents/a1/tools/gmail/connect", follow_redirects=False).status_code == 403
    r = client.get("/api/agents/a1/tools/gmail/connect?personal=true&label=me%40home.com", follow_redirects=False)
    assert r.status_code == 307 and fake.sessions == [("gmail", "u1", "me@home.com")]


def test_list_is_scoped_to_the_acting_user(api):
    client, _, state = api
    assert [c["connectionId"] for c in client.get("/api/agents/a1/tools").json()] == ["c1", "c2"]
    state["user"] = "u2"
    assert [c["connectionId"] for c in client.get("/api/agents/a1/tools").json()] == ["c1"]


def test_disconnect_by_id_owner_vs_shared(api):
    client, fake, state = api
    assert client.delete("/api/agents/a1/tools/by-id/c2").json() == {"ok": True}  # own personal connection
    assert client.delete("/api/agents/a1/tools/by-id/c1").status_code == 403  # shared needs an admin
    state["role"] = "admin"
    assert client.delete("/api/agents/a1/tools/by-id/c1").json() == {"ok": True}
    assert [r[0] for r in fake.removed] == ["c2", "c1"]
    assert client.delete("/api/agents/a1/tools/by-id/nope").status_code == 404


def test_only_admin_sets_default(api):
    client, fake, state = api
    assert client.post("/api/agents/a1/tools/by-id/c1/default").status_code == 403
    state["role"] = "admin"
    assert client.post("/api/agents/a1/tools/by-id/c1/default").json() == {"ok": True} and fake.defaults == ["c1"]


async def test_account_arg_picks_connection_and_is_not_forwarded():
    fake = FakeClient()
    spec = tools.TOOLS["send_email"]
    assert "account" in spec.input_schema["properties"] and "account" not in spec.input_schema.get("required", [])
    await tools.execute_tool(spec, {"to": "a@b.c", "subject": "s", "body": "b", "account": "WORK@acme.com"}, "a1", fake)
    assert fake.executed == [("c1", {"to": "a@b.c", "subject": "s", "body": "b"})]
    await tools.execute_tool(spec, {"to": "a@b.c", "subject": "s", "body": "b"}, "a1", fake)
    assert fake.executed[-1][0] is None  # no account: gateway uses the default


async def test_unknown_account_lists_available_labels():
    with pytest.raises(tools.ToolExecutionError, match="work@acme.com"):
        await tools.execute_tool(tools.TOOLS["send_email"], {"to": "a@b.c", "subject": "s", "body": "b",
                                                              "account": "nobody@x.com"}, "a1", FakeClient())
