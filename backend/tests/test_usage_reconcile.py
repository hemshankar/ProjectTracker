import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "scatterboard_test")

import logging

import pytest

from app import config
from app.accounting.counters import SpendCounters
from app.accounting.outbox import OutboxRepository
from app.accounting.query_client import AccountingUnavailable
from app.accounting.reconcile import alerts
from app.accounting.reconcile.completeness import LedgerCompletenessCheck
from app.accounting.reconcile.counters import CounterReconcile, parse_scope, within_tolerance
from app.accounting.reconcile.probe import HttpLedgerProbe
from app.accounting.reconcile.scheduler import ReconcileScheduler
from app.database import spend_counters_collection, usage_outbox_collection

pytestmark = pytest.mark.asyncio(loop_scope="session")


class FakeSource:
    def __init__(self, n):
        self.rows = [{"_id": f"rc-{i:03d}", "ts": 10_000, "usd": 1.0, "agentId": "a"} for i in range(n)]

    async def page(self, since, after, limit):
        return [{"_id": r["_id"], "ts": r["ts"], "usd": r["usd"]} for r in self.rows
                if r["_id"] > (after or "")][:limit]

    async def full(self, ids):
        return [r for r in self.rows if r["_id"] in ids]


class FakeProbe:
    def __init__(self, ledger):
        self.ledger = set(ledger)

    async def missing(self, ids):
        return [i for i in ids if i not in self.ledger]


class FakeQueue:
    def __init__(self, pending=()):
        self.pending, self.requeued = set(pending), []

    async def undelivered_ids(self, ids):
        return [i for i in ids if i in self.pending]

    async def requeue(self, event):
        self.requeued.append(event["callId"])


class FakeNames:
    async def resolve(self, row):
        return {}


def check(n=100, absent=(), pending=()):
    source = FakeSource(n)
    probe = FakeProbe({r["_id"] for r in source.rows} - set(absent) - set(pending))
    queue = FakeQueue(pending)
    return LedgerCompletenessCheck(source, probe, queue, FakeNames(), clock=lambda: 20), probe, queue


async def test_completeness_excludes_pending_and_repairs_only_missing():
    absent, pending = ["rc-003", "rc-050", "rc-099"], ["rc-010", "rc-011"]
    c, probe, queue = check(absent=absent, pending=pending)
    r = await c.run()
    assert (r.checked, r.missing, r.missing_usd, r.repaired) == (100, 3, 3.0, 0)
    assert queue.requeued == []  # no --repair: nothing written

    r = await c.run(repair=True)
    assert r.repaired == 3 and sorted(queue.requeued) == absent
    probe.ledger.update(queue.requeued)  # delivery succeeded
    assert (await c.run()).missing == 0


async def test_completeness_pages_past_page_size(monkeypatch):
    from app.accounting.reconcile import completeness
    monkeypatch.setattr(completeness, "PAGE", 10)
    c, _p, _q = check(n=35, absent=["rc-034"])
    r = await c.run()
    assert (r.checked, r.missing) == (35, 1)


class FakeCounters:
    def __init__(self, docs):
        self.docs, self.corrected = docs, {}

    async def all(self):
        return self.docs

    async def correct(self, scope, usd):
        self.corrected[scope] = usd


class FakeTotals:
    """Ledger totals keyed by (scope, since): lets a test prove `since=seededAt` is what is asked for."""

    def __init__(self, totals):
        self.totals, self.asked = totals, []

    async def total(self, kind, ident, since):
        self.asked.append((kind, ident, since))
        return self.totals[(kind, ident, since)]


class FakePending:
    def __init__(self, by_scope=None):
        self.by_scope = by_scope or {}

    async def since_total(self, field, ident, since):
        return self.by_scope.get(ident, 0.0)


def reconcile(docs, totals, pending=None):
    audits = []

    async def audit(scope, before, after):
        audits.append((scope, before, after))
    counters, probe = FakeCounters(docs), FakeTotals(totals)
    return CounterReconcile(counters, probe, FakePending(pending), audit=audit), counters, probe, audits


async def test_counter_within_tolerance_is_silent(caplog):
    r, counters, _p, audits = reconcile({"board:b1": {"usd": 10.005, "seededAt": 5, "seedUsd": 0.0}}, {("board", "b1", 5): 10.0})
    with caplog.at_level(logging.WARNING):
        report = await r.run(repair=True)
    assert report.drifts == [] and counters.corrected == {} and audits == [] and not caplog.records


async def test_counter_drift_warns_and_never_writes_without_repair(caplog):
    r, counters, probe, audits = reconcile({"agent:a1": {"usd": 12.0, "seededAt": 7, "seedUsd": 0.0}}, {("agent", "a1", 7): 9.0},
                                           pending={"a1": 1.0})
    with caplog.at_level(logging.WARNING):
        report = await r.run()
    assert len(report.drifts) == 1 and report.drifts[0].delta == 2.0  # 12 - (9 + 1 pending)
    assert "scope=agent:a1" in caplog.text and "delta=2.000000" in caplog.text
    assert counters.corrected == {} and audits == []
    assert probe.asked == [("agent", "a1", 7)]  # scoped to seed time, not lifetime


async def test_counter_repair_sets_value_and_audits():
    r, counters, _p, audits = reconcile({"global": {"usd": 3.0, "seededAt": 1, "seedUsd": 0.0}}, {("global", None, 1): 8.0})
    report = await r.run(repair=True)
    assert counters.corrected == {"global": 8.0} and audits == [("global", 3.0, 8.0)]
    assert report.drifts[0].repaired


async def test_seed_baseline_counts_and_unmarked_counters_are_skipped(caplog):
    docs = {"global": {"usd": 105.0, "seededAt": 9, "seedUsd": 100.0},   # seeded at $100, $5 since
            "board:old": {"usd": 4.0, "seededAt": None, "seedUsd": 0.0}}  # predates the marker
    r, counters, probe, _a = reconcile(docs, {("global", None, 9): 5.0})
    with caplog.at_level(logging.WARNING):
        report = await r.run(repair=True)
    assert report.drifts == [] and report.unmarked == ["board:old"] and counters.corrected == {}
    assert probe.asked == [("global", None, 9)] and "board:old" in caplog.text


def test_tolerance_and_scope_parsing():
    assert within_tolerance(100.05, 100.0) and not within_tolerance(100.2, 100.0)
    assert within_tolerance(0.005, 0.0) and not within_tolerance(0.05, 0.0)
    assert parse_scope("board:x") == ("board", "x", "boardId") and parse_scope("global") == ("global", None, None)


async def test_http_probe_pages_exists_calls(monkeypatch):
    calls = []

    class Client:
        async def post(self, path, body):
            calls.append(len(body["callIds"]))
            return {"missing": body["callIds"][:1]}
    out = await HttpLedgerProbe(Client()).missing([str(i) for i in range(2500)])
    assert calls == [1000, 1000, 500] and len(out) == 3


async def test_real_counters_stamp_seeded_at_and_correct_keeps_it():
    scope = "board:rc-real"
    await spend_counters_collection.delete_one({"_id": scope})
    c = SpendCounters()
    await c.add(None, "rc-real", 2.0)
    first = (await c.all())[scope]["seededAt"]
    await c.add(None, "rc-real", 1.0)
    assert (await c.all())[scope] == {"usd": 3.0, "seededAt": first, "seedUsd": 0.0} and first > 0
    await c.correct(scope, 1.5)
    assert (await c.all())[scope] == {"usd": 1.5, "seededAt": first, "seedUsd": 0.0}
    await spend_counters_collection.delete_one({"_id": scope})


async def test_real_outbox_requeue_revives_delivered_row():
    repo, ev = OutboxRepository(), {"callId": "rc-ob-1", "ts": 1, "agentId": "a", "usd": 1.0}
    await usage_outbox_collection.delete_one({"_id": "rc-ob-1"})
    await repo.enqueue(ev)
    assert await repo.undelivered_ids(["rc-ob-1"]) == ["rc-ob-1"]
    await repo.mark_delivered(["rc-ob-1"])
    assert await repo.undelivered_ids(["rc-ob-1"]) == []
    await repo.requeue(ev)
    assert await repo.undelivered_ids(["rc-ob-1"]) == ["rc-ob-1"]
    await usage_outbox_collection.delete_one({"_id": "rc-ob-1"})


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class StubOutbox:
    async def stats(self):
        return {"pending": 0, "rejected": 0, "oldestPendingAgeSeconds": 0}


class StubClient:
    async def ping(self):
        return True

    async def get(self, path, params):
        return {"rollupVerify": None}


class FakeStore:
    def __init__(self):
        self.calls = []

    async def apply(self, active, managed):
        self.calls.append(([a.key for a in active], list(managed)))


class Job:
    def __init__(self, exc=None):
        self.exc, self.runs = exc, 0

    async def run(self, **_kw):
        self.runs += 1
        if self.exc:
            raise self.exc
        return type("R", (), {"missing": 0, "repaired": 0, "drifts": []})()


async def test_scheduler_honors_intervals_and_survives_failures():
    clock, comp, cnt = Clock(), Job(RuntimeError("boom")), Job(AccountingUnavailable("down"))
    s = ReconcileScheduler(comp, cnt, StubOutbox(), StubClient(), FakeStore(), enabled=True, clock=clock)
    assert await s.tick() == ["completeness", "counters", "health"]  # failures don't raise
    clock.now = 30
    assert await s.tick() == []
    clock.now = 61
    assert await s.tick() == ["health"]
    clock.now = config.RECONCILE_COMPLETENESS_INTERVAL_SECONDS + 1
    assert "completeness" in await s.tick() and comp.runs == 2


async def test_scheduler_disabled_never_starts():
    s = ReconcileScheduler(Job(), Job(), StubOutbox(), StubClient(), FakeStore(), enabled=False)
    s.start()
    assert s._task is None


def test_alert_conditions(monkeypatch):
    assert alerts.outbox_alerts({"pending": 0, "rejected": 0, "oldestPendingAgeSeconds": 10}) == []
    found = alerts.outbox_alerts({"pending": 5, "rejected": 2, "oldestPendingAgeSeconds": 901})
    assert [a.key for a in found] == [alerts.OUTBOX_BACKLOG, alerts.OUTBOX_REJECTED]
    assert alerts.fallback_ratio_alert(5, 5) is None  # too few events to judge
    assert alerts.fallback_ratio_alert(100, 50) and alerts.fallback_ratio_alert(100, 5) is None
    w = alerts.ServiceDownWatch()
    assert w.observe(False, 0) is None and w.observe(False, 299) is None
    assert w.observe(False, 301).key == alerts.SERVICE_DOWN
    assert w.observe(True, 400) is None and w.observe(False, 401) is None  # recovery resets the clock


async def test_health_job_raises_and_clears_through_the_store():
    class Down(StubClient):
        async def ping(self):
            return False

    class Stuck(StubOutbox):
        async def stats(self):
            return {"pending": 3, "rejected": 0, "oldestPendingAgeSeconds": 5000}
    store = FakeStore()
    s = ReconcileScheduler(Job(), Job(), Stuck(), Down(), store, enabled=False)
    await s._check_health()
    keys, managed = store.calls[-1]
    assert keys == [alerts.OUTBOX_BACKLOG] and alerts.ROLLUP_MISMATCH not in managed  # unreachable: rollup unknown
    s2 = ReconcileScheduler(Job(), Job(), StubOutbox(), StubClient(), store, enabled=False)
    await s2._check_health()
    keys, managed = store.calls[-1]
    assert keys == [] and alerts.OUTBOX_BACKLOG in managed and alerts.ROLLUP_MISMATCH in managed
