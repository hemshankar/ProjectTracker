from fastapi.testclient import TestClient

from app import config
from app.container import get_container
from app.main import app

H = {"X-Internal-Key": "secret"}


def _client(container, monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_KEY", "secret")
    app.dependency_overrides[get_container] = lambda: container
    return TestClient(app)


def test_requires_key(container, monkeypatch):
    c = _client(container, monkeypatch)
    assert c.get("/providers").status_code == 401
    assert c.post("/execute", json={}).status_code == 401
    app.dependency_overrides.clear()


def test_error_translation_table(container, monkeypatch):
    c = _client(container, monkeypatch)
    body = {"agentId": "a1", "toolType": "slack", "action": "slack.list_channels"}
    assert c.post("/execute", json=body, headers=H).status_code == 409  # not connected
    assert c.post("/execute", json={**body, "toolType": "zzz"}, headers=H).status_code == 404
    assert c.post("/execute", json={**body, "action": "zzz"}, headers=H).status_code == 404
    assert c.post("/execute", json=body, headers=H).json()["error"]["code"] == "not_connected"
    app.dependency_overrides.clear()


def test_session_then_status_then_execute(container, monkeypatch):
    c = _client(container, monkeypatch)
    r = c.post("/connections/session", json={"agentId": "a1", "toolType": "gmail", "callbackUrl": "http://x"}, headers=H)
    assert r.status_code == 200 and r.json()["url"].startswith("https://")
    statuses = {s["toolType"]: s["connected"] for s in c.get("/connections/a1", headers=H).json()}
    assert statuses == {"gmail": True, "calendar": False, "slack": False}
    ex = c.post("/execute", json={"agentId": "a1", "toolType": "gmail", "action": "gmail.list_messages"}, headers=H)
    assert ex.status_code == 200 and ex.json()["ok"]
    assert c.delete("/connections/a1/gmail", headers=H).json() == {"ok": True}
    app.dependency_overrides.clear()


def test_by_id_routes_and_acting_user_visibility(container, monkeypatch):
    c = _client(container, monkeypatch)

    def connect(owner=None, label=None):
        body = {"agentId": "a1", "toolType": "gmail", "callbackUrl": "http://x", "ownerUserId": owner, "label": label}
        return c.post("/connections/session", json=body, headers=H).json()["connectionId"]

    shared, mine = connect(label="work@acme.com"), connect("u1", "me@home.com")
    ids = lambda user: {s["connectionId"] for s in c.get("/connections/a1", headers={**H, "X-Acting-User": user}).json()
                        if s["connectionId"]}
    assert ids("u1") == {shared, mine} and ids("u2") == {shared}
    body = {"agentId": "a1", "toolType": "gmail", "action": "gmail.list_messages", "connectionId": mine}
    assert c.post("/execute", json=body, headers={**H, "X-Acting-User": "u2"}).status_code == 403
    assert c.post("/execute", json=body, headers={**H, "X-Acting-User": "u1"}).json()["ok"]
    assert c.post(f"/connections/a1/by-id/{mine}/default", headers={**H, "X-Acting-User": "u1"}).status_code == 422
    assert c.delete(f"/connections/a1/by-id/{mine}", headers={**H, "X-Acting-User": "u1"}).json() == {"ok": True}
    assert ids("u1") == {shared}
    app.dependency_overrides.clear()
