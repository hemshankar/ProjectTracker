import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.integrations_client import IntegrationsError
from app.main import app
from app.routers.tools import get_integrations_client


class FakeClient:
    def __init__(self):
        self.disconnected = []
        self.fail = None

    async def ping(self): return True

    async def create_session(self, agent_id, tool_type, callback_url):
        if self.fail:
            raise self.fail
        return f"https://connect.example/{tool_type}?cb={callback_url}"

    async def list_connections(self, agent_id):
        return [{"toolType": "slack", "connected": True, "label": "Slack"}]

    async def disconnect(self, agent_id, tool_type):
        self.disconnected.append((agent_id, tool_type))


@pytest.fixture
def api(monkeypatch):
    fake = FakeClient()

    async def membership(agent_id, user_id):
        return {"role": "admin"}

    monkeypatch.setattr(dependencies, "get_agent_membership", membership)
    app.dependency_overrides[dependencies.get_current_user] = lambda: {"_id": "u1"}
    app.dependency_overrides[get_integrations_client] = lambda: fake
    yield TestClient(app), fake
    app.dependency_overrides.clear()


def test_connect_redirects_to_gateway_url(api):
    client, _ = api
    r = client.get("/api/agents/a1/tools/slack/connect", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("https://connect.example/slack")


def test_list_and_disconnect_use_gateway(api):
    client, fake = api
    assert client.get("/api/agents/a1/tools").json()[0]["connected"] is True
    assert client.delete("/api/agents/a1/tools/slack").json() == {"ok": True}
    assert fake.disconnected == [("a1", "slack")]


def test_gateway_down_is_503_not_hang(api):
    client, fake = api
    fake.fail = IntegrationsError(503, "Integrations service is unreachable")
    assert client.get("/api/agents/a1/tools/slack/connect", follow_redirects=False).status_code == 503
