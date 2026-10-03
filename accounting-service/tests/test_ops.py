import logging
from datetime import datetime, timezone

from app import config
from app.services.scheduler import RollupVerifyScheduler, seconds_until_hour
from tests.conftest import make_event


async def _ingest(client, auth, events):
    r = await client.post("/internal/events", headers=auth, json={"schemaVersion": 1, "events": events})
    assert r.status_code == 200
    return r.json()


async def test_exists_returns_only_missing(client, auth):
    await _ingest(client, auth, [make_event("c1"), make_event("c2")])
    r = await client.post("/internal/events/exists", headers=auth, json={"callIds": ["c1", "c9", "c2", "c8"]})
    assert r.json() == {"missing": ["c9", "c8"]}


async def test_exists_enforces_cap_and_auth(client, auth, monkeypatch):
    monkeypatch.setattr(config, "MAX_EXISTS_IDS", 3)
    r = await client.post("/internal/events/exists", headers=auth, json={"callIds": ["a", "b", "c", "d"]})
    assert r.status_code == 413
    r = await client.post("/internal/events/exists", json={"callIds": ["a"]})
    assert r.status_code == 401


async def test_stats(client, auth):
    await _ingest(client, auth, [make_event("c1"), {"callId": "bad"}])
    s = (await client.get("/internal/stats", headers=auth)).json()
    assert s["ledgerCount"] == 1 and s["rejectedSinceStart"] == 1
    assert s["latestTs"] == 1_700_000_000_000
    assert (await client.get("/internal/stats")).status_code == 401


async def test_ledger_total_scopes_and_since(client, auth):
    await _ingest(client, auth, [make_event("c1", ts=1000, usd=1.0), make_event("c2", ts=2000, usd=2.0),
                                 make_event("c3", ts=2000, usd=4.0, boardId="b2")])
    get = lambda **p: client.get("/internal/ledger/total", headers=auth, params=p)
    assert (await get(scope="global")).json() == {"usd": 7.0, "calls": 3}
    assert (await get(scope="board", id="b1", since=1500)).json() == {"usd": 2.0, "calls": 1}
    assert (await get(scope="agent", id="a1")).json()["usd"] == 7.0
    assert (await get(scope="board")).status_code == 422


async def test_health_vs_ready(client, container, monkeypatch):
    assert (await client.get("/health")).status_code == 200
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json() == {"ready": True}

    async def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(container.db, "command", boom)
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 503


def test_seconds_until_hour():
    now = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
    assert seconds_until_hour(now, 3) == 7200
    assert seconds_until_hour(datetime(2026, 10, 3, 4, 0, tzinfo=timezone.utc), 3) == 23 * 3600


async def test_verify_scheduler_alerts_and_survives(client, auth, container, caplog):
    await _ingest(client, auth, [make_event("c1", ts=1_700_000_000_000)])
    sched = RollupVerifyScheduler(container.rollups, lookback_days=30, enabled=True)
    assert await sched.run_once(now_ms=1_700_000_100_000) == 0
    await container.rollups._rollups.replace_range(0, 2_000_000_000_000, [])  # corrupt: drop rollups
    with caplog.at_level(logging.ERROR):
        assert await sched.run_once(now_ms=1_700_000_100_000) == 1
    assert "ALERT" in caplog.text

    async def boom(*_a):
        raise RuntimeError("x")
    container.rollups.verify = boom
    assert await sched.run_once() == -1  # failing check doesn't raise


async def test_scheduler_disabled_does_not_start(container):
    sched = RollupVerifyScheduler(container.rollups, enabled=False)
    sched.start()
    assert sched._task is None


async def test_stats_exposes_last_rollup_verify(client, auth, container):
    assert (await client.get("/internal/stats", headers=auth)).json()["rollupVerify"] is None
    await container.verifier.run_once(now_ms=1_700_000_100_000)
    result = (await client.get("/internal/stats", headers=auth)).json()["rollupVerify"]
    assert result == {"at": 1_700_000_100_000, "mismatchedDays": 0}
