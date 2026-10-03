import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.backends.composio_backend import ComposioBackend
from app.backends.composio_http import ComposioHttp
from app.backends.fake_backend import FakeBackend
from app.container import build_container, get_container
from app.database import ensure_indexes
from app.main import app
from app.services.admin_auth_service import AdminAuthService, hash_password
from app.services.secret_store import DbSecretStore, EnvSecretStore, FallbackSecretStore

PASSWORD = "correct horse"


@pytest.fixture
async def ctx():
    db = AsyncMongoMockClient()["admin"]
    enc_key = Fernet.generate_key().decode()
    secrets = FallbackSecretStore(DbSecretStore(db, enc_key), EnvSecretStore())
    fake = FakeBackend()
    c = build_container(db, {"composio": fake}, secrets,
                        AdminAuthService(hash_password(PASSWORD), "s3cret", 3600))
    c.enc_key = enc_key
    await ensure_indexes(db)
    await c.providers.seed()
    app.dependency_overrides[get_container] = lambda: c
    yield c, fake, TestClient(app)
    app.dependency_overrides.clear()


def login(client):
    r = client.post("/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"X-Admin-CSRF": r.json()["csrf"]}


def test_login_and_session(ctx):
    _, _, client = ctx
    assert client.get("/admin/providers").status_code == 401
    assert client.post("/admin/login", json={"password": "nope"}).status_code == 401
    login(client)
    assert client.get("/admin/me").json()["authenticated"] is True
    assert "httponly" in client.post("/admin/login", json={"password": PASSWORD}).headers["set-cookie"].lower()


def test_login_is_throttled(ctx):
    _, _, client = ctx
    codes = [client.post("/admin/login", json={"password": "bad"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert client.post("/admin/login", json={"password": PASSWORD}).status_code == 429


def test_mutations_require_csrf(ctx):
    _, _, client = ctx
    login(client)
    assert client.patch("/admin/providers/slack", json={"enabled": False}).status_code == 403
    assert client.put("/admin/credentials/composio_api_key", json={"value": "x"}).status_code == 403
    assert client.patch("/admin/providers/slack", json={"enabled": False},
                        headers={"X-Admin-CSRF": "wrong"}).status_code == 403


def test_credentials_are_write_only_and_encrypted(ctx):
    c, _, client = ctx
    h = login(client)
    assert client.put("/admin/credentials/composio_api_key", json={"value": "SUPER-SECRET"}, headers=h).status_code == 200
    listing = client.get("/admin/credentials")
    assert "SUPER-SECRET" not in listing.text
    row = next(r for r in listing.json() if r["name"] == "composio_api_key")
    assert row["status"] == "set" and row["source"] == "db"
    # rotation is visible to the backend immediately, no restart
    assert c.secrets.get("composio_api_key") == "SUPER-SECRET"
    client.put("/admin/credentials/composio_api_key", json={"value": "ROTATED"}, headers=h)
    assert c.secrets.get("composio_api_key") == "ROTATED"
    audit = client.get("/admin/audit")
    assert "SUPER-SECRET" not in audit.text and "ROTATED" not in audit.text and "credential.set" in audit.text
    assert client.put("/admin/credentials/bogus", json={"value": "x"}, headers=h).status_code == 422


async def test_ciphertext_in_db_and_reload(ctx):
    c, _, client = ctx
    h = login(client)
    client.put("/admin/credentials/composio_webhook_secret", json={"value": "PLAINTEXT-ME"}, headers=h)
    doc = await c.db["backend_credentials"].find_one({"name": "composio_webhook_secret"})
    assert "PLAINTEXT-ME" not in json.dumps(doc, default=str)
    fresh = DbSecretStore(c.db, c.enc_key)  # same key, new process: value must reload from the DB
    await fresh.load()
    assert fresh.get("composio_webhook_secret") == "PLAINTEXT-ME"


def test_cannot_store_without_encryption_key():
    import asyncio
    db = AsyncMongoMockClient()["x"]
    store = DbSecretStore(db, "")
    from app.errors import ConfigError
    with pytest.raises(ConfigError):
        asyncio.run(store.set("composio_api_key", "v", "admin"))


async def test_backend_switch_needs_confirm_then_drops_connections(ctx):
    c, fake, client = ctx
    h = login(client)
    await c.connections.create_session("a1", "slack", "cb")
    await c.connections.status("a1", "slack")  # persists connected state
    r = client.patch("/admin/providers/slack", json={"backend": "nango"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["detail"]["connectionsAffected"] == 1
    assert next(p for p in client.get("/admin/providers").json() if p["toolType"] == "slack")["backend"] == "composio"
    r = client.patch("/admin/providers/slack", json={"backend": "nango", "confirm": True}, headers=h)
    assert r.status_code == 200 and r.json()["connectionsAffected"] == 1 and r.json()["backend"] == "nango"
    doc = await c.db["connections"].find_one({"agentId": "a1", "toolType": "slack"})
    assert doc["status"] == "disconnected"
    entry = next(a for a in client.get("/admin/audit").json() if a["action"] == "provider.backend")
    assert entry["extra"]["from"] == "composio" and entry["extra"]["to"] == "nango"


async def test_invalid_backend_rejected_and_disabled_provider_unavailable(ctx):
    c, _, client = ctx
    h = login(client)
    assert client.patch("/admin/providers/slack", json={"backend": "zzz"}, headers=h).status_code == 422
    assert client.patch("/admin/providers/slack", json={"enabled": False}, headers=h).json()["enabled"] is False
    status = await c.connections.status("a1", "slack")
    assert status["connected"] is False and status["status"] == "disabled"
    from app.errors import ProviderDisabled
    with pytest.raises(ProviderDisabled):
        await c.actions.execute("a1", "slack", "slack.list_channels", {})


def test_test_action_returns_status_not_body(ctx):
    _, fake, client = ctx
    h = login(client)
    r = client.post("/admin/providers/slack/test-action", headers=h).json()
    assert r["ok"] is False and "not_connected" in r["error"]
    client.post("/admin/providers/slack/test-connect", json={}, headers=h)
    r = client.post("/admin/providers/slack/test-action", headers=h).json()
    assert r["ok"] is True and "result" not in r and "data" not in r and r["action"] == "slack.list_channels"


def test_actions_admin_api(ctx):
    _, _, client = ctx
    assert client.get("/admin/actions").status_code == 401
    h = login(client)
    rows = client.get("/admin/actions").json()
    assert {r["action"] for r in rows} >= {"slack.list_channels", "slack.post_message"}
    r = client.patch("/admin/actions/gmail.list_messages", json={"maxAttempts": 5, "baseDelayMs": 100}, headers=h)
    assert r.status_code == 200 and r.json()["maxAttempts"] == 5
    assert client.patch("/admin/actions/gmail.send_email", json={"maxAttempts": 2}, headers=h).status_code == 422
    assert client.patch("/admin/actions/zzz", json={"maxAttempts": 2}, headers=h).status_code == 404
    assert client.patch("/admin/actions/gmail.list_messages", json={"maxAttempts": 2}).status_code == 403
