"""One contract suite; every Backend must pass it (FakeBackend + ComposioBackend over mocked HTTP)."""
import json

import httpx
import pytest

from app.backends import composio_events
from app.backends.base import CONNECTED, NOT_CONNECTED, ProviderConfig
from app.backends.composio_backend import ComposioBackend
from app.backends.composio_http import ComposioHttp
from app.backends.fake_backend import FakeBackend
from app.errors import NotConnected
from app.services.secret_store import StaticSecretStore

SECRETS = StaticSecretStore({"composio_api_key": "k", "composio_webhook_secret": "shh"})
SLACK = ProviderConfig("slack", "Slack", "composio", "slack")


def _composio_handler():
    state = {"connected": False}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/v3/auth_configs" and req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "ac_1"}]})
        if path == "/api/v3/connected_accounts/link":
            state["connected"] = True
            return httpx.Response(200, json={"redirect_url": "https://connect.composio.dev/x", "connected_account_id": "ca_1"})
        if path == "/api/v3/connected_accounts" and req.method == "GET":
            items = [{"id": "ca_1", "status": "ACTIVE"}] if state["connected"] else []
            return httpx.Response(200, json={"items": items})
        if path == "/api/v3/connected_accounts/ca_1" and req.method == "DELETE":
            state["connected"] = False
            return httpx.Response(200, json={})
        if path.startswith("/api/v3/tools/execute/"):
            return httpx.Response(200, json={"successful": True, "data": {"echo": json.loads(req.content)["arguments"]}})
        return httpx.Response(404, json={})
    return handler


def make_composio():
    http = ComposioHttp(SECRETS, transport=httpx.MockTransport(_composio_handler()))
    return ComposioBackend(http, SECRETS)


def _fake_webhook(_):
    return {"id": "w1", "kind": "connected", "connection": "c1"}, {}


def _composio_webhook(ts="1700000000"):
    body = json.dumps({"type": "composio.connected_account.created", "data": {"id": "ca_1", "user_id": "u1"}}).encode()
    headers = {"webhook-id": "w1", "webhook-timestamp": ts, "webhook-signature": composio_events.sign("shh", "w1", ts, body)}
    return headers, body


@pytest.fixture(params=["fake", "composio"])
def backend(request):
    return FakeBackend() if request.param == "fake" else make_composio()


async def test_connect_status_execute_disconnect(backend):
    assert (await backend.get_connection("u1", SLACK)).status == NOT_CONNECTED
    with pytest.raises(NotConnected):
        await backend.execute_action("u1", SLACK, "slack.list_channels", {})
    session = await backend.create_connect_session("u1", SLACK, "http://cb")
    assert session.url.startswith("https://")
    assert (await backend.get_connection("u1", SLACK)).status == CONNECTED
    result = await backend.execute_action("u1", SLACK, "slack.post_message", {"channel": "C1", "text": "hi"})
    assert result.ok
    await backend.disconnect("u1", SLACK)
    assert (await backend.get_connection("u1", SLACK)).status == NOT_CONNECTED


def test_capabilities_declared(backend):
    assert backend.capabilities().named_actions is True


def test_composio_translates_args():
    from app.actions.composio_map import get_tool
    assert get_tool("slack.post_message").translate({"channel": "C1", "text": "hi"}) == {"channel": "C1", "text": "hi"}
    assert get_tool("gmail.send_email").translate({"to": "a@b.c", "subject": "s", "body": "b"})["recipient_email"] == "a@b.c"


def test_composio_webhook_parse_and_signature(monkeypatch):
    import time
    monkeypatch.setattr(time, "time", lambda: 1700000010)
    b = make_composio()
    headers, body = _composio_webhook()
    event = b.parse_webhook(headers, body)
    assert event.kind == "connected" and event.backend_connection_id == "ca_1" and event.user_id == "u1"
    headers["webhook-signature"] = "v1,AAAA"
    from app.errors import InvalidWebhook
    with pytest.raises(InvalidWebhook):
        b.parse_webhook(headers, body)


def test_composio_webhook_rejects_stale(monkeypatch):
    import time
    monkeypatch.setattr(time, "time", lambda: 1700009999)
    from app.errors import InvalidWebhook
    headers, body = _composio_webhook()
    with pytest.raises(InvalidWebhook):
        make_composio().parse_webhook(headers, body)
