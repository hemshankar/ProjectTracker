import inspect

from app.database import LEDGER_COLLECTION
from app.repositories.ledger_repository import LedgerRepository
from app.repositories.mongo_ledger import MongoLedgerRepository
from .conftest import make_event


def _body(events, version=1):
    return {"schemaVersion": version, "events": events}


async def test_valid_batch_inserts_all(client, auth, container):
    r = await client.post("/internal/events", json=_body([make_event("a"), make_event("b")]), headers=auth)
    assert r.status_code == 200
    assert r.json() == {"accepted": 2, "duplicates": 0, "rejected": []}
    assert await container.db[LEDGER_COLLECTION].count_documents({}) == 2


async def test_same_batch_twice_is_idempotent(client, auth, container):
    body = _body([make_event("a"), make_event("b")])
    await client.post("/internal/events", json=body, headers=auth)
    r = await client.post("/internal/events", json=body, headers=auth)
    assert r.json()["accepted"] == 0 and r.json()["duplicates"] == 2
    assert await container.db[LEDGER_COLLECTION].count_documents({}) == 2


async def test_mixed_batch_rejects_only_bad_event(client, auth, container):
    bad = make_event("bad", callKind="nonsense")
    r = await client.post("/internal/events", json=_body([make_event("ok"), bad]), headers=auth)
    data = r.json()
    assert r.status_code == 200 and data["accepted"] == 1
    assert data["rejected"][0]["callId"] == "bad"
    assert await container.db[LEDGER_COLLECTION].count_documents({}) == 1


async def test_partial_duplicate_batch(client, auth):
    await client.post("/internal/events", json=_body([make_event("a")]), headers=auth)
    r = await client.post("/internal/events", json=_body([make_event("a"), make_event("b")]), headers=auth)
    assert r.json()["accepted"] == 1 and r.json()["duplicates"] == 1


async def test_auth_required(client, container):
    body = _body([make_event()])
    assert (await client.post("/internal/events", json=body)).status_code == 401
    assert (await client.post("/internal/events", json=body, headers={"X-Internal-Key": "x"})).status_code == 401


async def test_fails_closed_when_key_unset(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "ACCOUNTING_SERVICE_KEY", "")
    r = await client.post("/internal/events", json=_body([make_event()]), headers={"X-Internal-Key": ""})
    assert r.status_code == 401


async def test_unsupported_schema_version(client, auth):
    r = await client.post("/internal/events", json=_body([make_event()], version=99), headers=auth)
    assert r.status_code == 400


async def test_oversize_batch(client, auth, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MAX_BATCH_SIZE", 2)
    r = await client.post("/internal/events", json=_body([make_event(str(i)) for i in range(3)]), headers=auth)
    assert r.status_code == 400


async def test_id_is_call_id_and_no_ttl_index(client, auth, container):
    await client.post("/internal/events", json=_body([make_event("xyz")]), headers=auth)
    doc = await container.db[LEDGER_COLLECTION].find_one({"_id": "xyz"})
    assert doc["_id"] == "xyz" and "callId" not in doc and doc["schemaVersion"] == 1
    indexes = await container.db[LEDGER_COLLECTION].index_information()
    assert not any("expireAfterSeconds" in v for v in indexes.values())


def test_ledger_is_append_only():
    for cls in (LedgerRepository, MongoLedgerRepository):
        names = {n for n, _ in inspect.getmembers(cls) if not n.startswith("_")}
        assert not {n for n in names if any(w in n for w in ("update", "delete", "remove", "replace"))}


async def test_health(client):
    assert (await client.get("/health")).json() == {"ok": True}
