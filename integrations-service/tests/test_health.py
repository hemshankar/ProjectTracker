from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def test_health_is_unauthenticated():
    assert client.get("/health").json() == {"status": "ok"}


def test_ping_rejects_missing_or_wrong_key(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_KEY", "secret")
    assert client.post("/internal/ping").status_code == 401
    assert client.post("/internal/ping", headers={"X-Internal-Key": "nope"}).status_code == 401


def test_ping_fails_closed_when_key_unset(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_KEY", "")
    assert client.post("/internal/ping", headers={"X-Internal-Key": ""}).status_code == 401


def test_ping_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_KEY", "secret")
    resp = client.post("/internal/ping", headers={"X-Internal-Key": "secret"})
    assert resp.status_code == 200 and resp.json()["ok"] is True
