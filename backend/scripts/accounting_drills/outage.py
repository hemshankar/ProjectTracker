"""Gate 5: outage drill. Service down under load, alerts appear, service restarts, outbox drains, nothing lost or doubled."""
import asyncio
import time

from app.accounting.client import HttpUsageClient
from app.accounting.outbox import OutboxRepository
from app.accounting.query_client import HttpUsageQueryClient
from app.accounting.reconcile.alert_store import AlertStore
from app.accounting.reconcile.scheduler import ReconcileScheduler
from app.accounting.worker import OutboxWorker

from .common import drain, ledger_total, make_board, record

OUTAGE_SECONDS = 20
RATE_PER_SECOND = 80


class _Idle:
    async def run(self, **_kw):
        raise AssertionError("not used")


async def outage(svc, r) -> None:
    print(f"Gate 5: outage drill ({OUTAGE_SECONDS}s at ~{RATE_PER_SECOND} calls/s)", flush=True)
    await make_board("OUT")
    repo, store = OutboxRepository(), AlertStore()
    worker = OutboxWorker(repo, HttpUsageClient(timeout=3))
    sched = ReconcileScheduler(_Idle(), _Idle(), repo, HttpUsageQueryClient(timeout=2), store, enabled=False)
    worker.start()
    before = (await ledger_total())["calls"]
    svc.stop()
    sent, end, i = 0, time.monotonic() + OUTAGE_SECONDS, 0
    while time.monotonic() < end:
        for _ in range(RATE_PER_SECOND // 10):
            await record("task_run", "OUT", i=i)
            i += 1
        sent = i
        if i % (RATE_PER_SECOND * 5) == 0:
            await sched._check_health()  # first observation starts the down-clock, later ones exceed 1s
        await asyncio.sleep(0.1)
    await sched._check_health()
    stats = await repo.stats()
    open_keys = {a["key"] for a in await store.list()}
    r.check("G5", "events queue instead of failing while the service is down", stats["pending"] >= sent * 0.9, f"pending={stats['pending']} of {sent}")
    r.check("G5", "alerts raised: service_down and outbox_backlog", {"service_down", "outbox_backlog"} <= open_keys, str(sorted(open_keys)))
    summary = await store.summary()
    r.check("G5", "bell count reflects the open alerts", summary["unacknowledged"] >= 2 and summary["severity"] == "error", str(summary))
    svc.start()
    r.check("G5", "outbox drains to zero after restart", await drain(120), str(await repo.stats()))
    await worker.stop()
    got = (await ledger_total())["calls"] - before
    r.check("G5", "no gaps and no duplicates", got == sent, f"ledger gained {got}, recorded {sent}")
    code, out = svc.cli("rollups", "verify")
    r.check("G5", "rollups match the ledger (no double counting)", code == 0, out.splitlines()[-1])
    await sched._check_health()
    still = {a["key"] for a in await store.list()}
    r.check("G5", "alerts clear after recovery", not ({"service_down", "outbox_backlog"} & still), str(sorted(still)))
