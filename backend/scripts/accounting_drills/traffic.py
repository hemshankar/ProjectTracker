"""Gates 1, 2 (accelerated), 3: backfill, live traffic, completeness and counter reconcile with injected faults."""
import time

from app.accounting.backfill import BackfillRunner
from app.accounting.backfill_mongo import (MongoCheckpointStore, MongoLlmCallSource, MongoNameResolver,
                                           usage_backfill_state_collection)
from app.accounting.client import HttpUsageClient
from app.accounting.counters import SpendCounters
from app.accounting.outbox import OutboxRepository
from app.accounting.pending import PendingUsage
from app.accounting.query_client import HttpUsageQueryClient
from app.accounting.reconcile.completeness import LedgerCompletenessCheck
from app.accounting.reconcile.counters import CounterReconcile
from app.accounting.reconcile.probe import HttpLedgerProbe
from app.accounting.reconcile.sources import MongoCallSource
from app.accounting.seed import seed_counters
from app.accounting.worker import OutboxWorker
from app.database import audit_log_collection, llm_calls_collection, spend_counters_collection

from .common import KINDS, drain, ledger_total, make_board, record

LEGACY = 2000
LIVE = 3000


async def backfill(svc, r) -> None:
    print("Gate 1/3: backfill of legacy llm_calls", flush=True)
    await make_board("B")
    now = int(time.time() * 1000)
    await llm_calls_collection.insert_many([
        {"_id": f"leg-{i}", "agentId": "A", "boardId": "B", "taskId": "T", "runId": f"r{i}", "ts": now - (LEGACY - i) * 1000,
         "usd": round(0.001 * (i % 7 + 1), 6), "inputTokens": 100, "outputTokens": 50, "expiresAt": now + 10**10}
        for i in range(LEGACY)])
    expected = round(sum(0.001 * (i % 7 + 1) for i in range(LEGACY)), 6)
    runner = lambda: BackfillRunner(MongoLlmCallSource(), HttpUsageClient(timeout=30), MongoCheckpointStore(),
                                    MongoNameResolver(), log=lambda _m: None)
    rep = await runner().run()
    got = await ledger_total()
    r.check("G1", "ledger count == llm_calls count", got["calls"] == LEGACY, f"{got['calls']} vs {LEGACY}")
    r.check("G1", "ledger sum(usd) == llm_calls sum(usd)", abs(got["usd"] - expected) < 1e-6, f"{got['usd']} vs {expected}")
    await usage_backfill_state_collection.delete_many({})
    again = await runner().run()
    r.check("G1", "re-running backfill creates no duplicates", again.accepted == 0 and again.duplicates == LEGACY,
            f"accepted={again.accepted} duplicates={again.duplicates}")
    code, out = svc.cli("rollups", "verify")
    r.check("G3", "rollups verify clean after backfill", code == 0, out.splitlines()[-1])
    await seed_counters(SpendCounters())  # documented order: backfill, then seed-counters


async def live_traffic(svc, r) -> None:
    print(f"Gate 2 (accelerated): {LIVE} live calls across chat, dispatch, task and sub-agent", flush=True)
    for b in ("B1", "B2", "B3"):
        await make_board(b)
    worker = OutboxWorker(OutboxRepository(), HttpUsageClient(timeout=10))
    worker.start()
    before = (await ledger_total())["calls"]
    for i in range(LIVE):
        await record(KINDS[i % 4], f"B{i % 3 + 1}", i=i)
    r.check("G2", "outbox drains after live traffic", await drain(), "")
    await worker.stop()
    got = await ledger_total()
    r.check("G2", "every call has a ledger row", got["calls"] - before == LIVE, f"{got['calls'] - before} of {LIVE}")
    probe = HttpLedgerProbe(HttpUsageQueryClient(timeout=10))
    check = LedgerCompletenessCheck(MongoCallSource(), probe, OutboxRepository(), MongoNameResolver())
    rep = await check.run(window_hours=48)
    r.check("G2", "completeness check: missing == 0", rep.missing == 0, f"checked={rep.checked} missing={rep.missing}")
    counters = CounterReconcile(SpendCounters(), probe, PendingUsage())
    rc = await counters.run()
    r.check("G2", "counter drift within tolerance", not rc.drifts and not rc.unmarked,
            f"checked={rc.checked} drifts={[(d.scope, d.delta) for d in rc.drifts]}")
    await fault_injection(svc, r, check, counters)


async def fault_injection(svc, r, check, counters) -> None:
    print("Verification steps 1-2: delete 3 ledger rows, corrupt a counter", flush=True)
    from motor.motor_asyncio import AsyncIOMotorClient
    from .harness import ACC_DB
    ledger = AsyncIOMotorClient("mongodb://localhost:27017")[ACC_DB]["usage_ledger"]
    victims = [d["_id"] async for d in ledger.find({"source": "live"}, {"_id": 1}).limit(3)]
    await ledger.delete_many({"_id": {"$in": victims}})
    rep = await check.run(window_hours=48)
    r.check("V1", "completeness reports exactly the 3 deleted rows", sorted(rep.missing_ids) == sorted(victims), f"missing={rep.missing}")
    fixed = await check.run(window_hours=48, repair=True)
    worker = OutboxWorker(OutboxRepository(), HttpUsageClient(timeout=10))
    worker.start()
    await drain()
    await worker.stop()
    r.check("V1", "--repair restores them; next run reports 0", fixed.repaired == 3 and (await check.run(window_hours=48)).missing == 0)
    svc.cli("rollups", "rebuild")  # rows deleted behind the service's back were already in the rollups: rebuild
    code, out = svc.cli("rollups", "verify")
    r.check("V1", "rollups verify clean after rebuild", code == 0, out.splitlines()[-1])
    await spend_counters_collection.update_one({"_id": "board:B1"}, {"$inc": {"usd": 5.0}})
    rep = await counters.run()
    r.check("V2", "reconcile warns about the corrupted counter only", [d.scope for d in rep.drifts] == ["board:B1"], f"{[(d.scope, d.delta) for d in rep.drifts]}")
    before = (await SpendCounters().all())["board:B1"]["usd"]
    await counters.run()
    r.check("V2", "without --repair nothing is written", (await SpendCounters().all())["board:B1"]["usd"] == before)
    rep = await counters.run(repair=True)
    audits = await audit_log_collection.count_documents({"entityType": "spend_counter"})
    r.check("V2", "--repair fixes it and writes an audit entry", rep.drifts[0].repaired and audits == 1 and not (await counters.run()).drifts)
