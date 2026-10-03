# Phase 5: Outbox, Counters & Caps

PRD: FR-5, FR-6, FR-7, FR-8, FR-9, NFR-1, NFR-2. This is the phase where the core starts depending on accounting infrastructure, and it must **never** make a run depend on the service being up.

## Technical Design

### What `UsageRecorder.record` does now

Same single entry point (Phase 3), three durable steps, in this order:

1. **Insert the `llm_calls` row** (content + enriched fields). `_id` = `callId`.
2. **Insert a `usage_outbox` document** with the finished `UsageEvent` (durable intent to deliver).
3. **`$inc` the spend counters** (cap enforcement).

The core runs on a single-node Mongo (`mongo:7`, no replica set), so there are **no multi-document transactions**. The three writes are independent. The order is chosen so the failure modes are benign:

| Crash after… | Result | Repair |
| --- | --- | --- |
| step 1 only | call has content but no event | Phase 8 reconcile (and a re-run of backfill) re-enqueues rows from `llm_calls` missing in the ledger |
| step 2 only | event delivered, counter not incremented → caps slightly low | Phase 8 counter reconcile from service totals |
| step 3 only (impossible by order) | n/a | n/a |

Everything in `record` is inside a try/except at the `UsageRecorder` boundary: errors log at `error` level with the `callId` and are swallowed (FR-6). If the outbox insert itself fails, the event is appended to a **local fallback file** (`USAGE_FALLBACK_PATH`, JSON Lines) so spend isn't lost silently. A small `FallbackReplayer` re-ingests that file at startup.

### Outbox (`usage_outbox`, core database)

```
{ _id: callId, event: <UsageEvent>, status: "pending"|"sending",
  attempts, nextAttemptAt, lastError, createdAt, leaseUntil, deliveredAt }
```

- `_id = callId` makes enqueue idempotent.
- Indexes: `(status, nextAttemptAt)`, and a TTL on `deliveredAt` (7 days) so delivered rows are cleaned up. Pending rows have no TTL.
- Delivered rows are retained briefly for debugging, then expire. The ledger is the permanent record.

### `OutboxWorker`

A background asyncio task started in `main.py`'s lifespan (alongside the existing reconcile calls) and cancelled on shutdown.

Loop:
1. Atomically claim up to `OUTBOX_BATCH_SIZE` (default 100) due rows: `find_one_and_update` pending→sending with `leaseUntil = now + 60s`. Rows with an expired lease are reclaimable, so a crashed worker doesn't strand rows.
2. `UsageSink.send_batch(events)` (HTTP, timeout 10s).
3. Response handling:
   - 200: rows whose id is in `accepted`/`duplicates` → delivered (`deliveredAt`). Rows in `rejected` → `status=rejected` with `lastError` (poison events don't retry forever, but stay inspectable and raise the Phase 8 alert).
   - Network error / 5xx: back to pending with exponential backoff (`nextAttemptAt = now + min(2^attempts, 300)s`, jitter).
4. Idle sleep `OUTBOX_POLL_SECONDS` (default 2) when no work.

One worker per core process. If the core is scaled to multiple processes, claiming via `find_one_and_update` plus leases keeps them safe.

Observability: counters/gauges logged at an interval: pending count, oldest pending age, delivered/min, rejected total. Exposed through `GET /api/admin/usage/outbox` (admin, Phase 6) for the Phase 8 alert.

### Spend counters

Collection `spend_counters`, one document per scope:

```
{ _id: "board:<id>" | "agent:<id>" | "global", usd: <float>, updatedAt }
```

- `SpendCounters.add(agent_id, board_id, usd)`: a single `bulk_write` of three `$inc` upserts.
- `SpendCounters.get(scope) -> float` is an indexed `_id` read, so cap checks are O(1) (FR-8).

### `check_exceeded` rewrite

`budget_service.check_exceeded` keeps its signature and return value (`"budget_exceeded"` or `None`) and semantics (board → agent → global, cheapest first). It reads `SpendCounters` instead of `_sum_usd` over `llm_calls`. `_sum_usd` is deleted.

**Behavior change to call out:** today caps are computed from `llm_calls`, which has a TTL, so spend that expires **stops counting** and a "fixed" cap silently regains capacity over time. Counters are cumulative, so caps become what the code comments say: a fixed cap until changed. Mitigation and decision below.

### Seeding the counters (one-time migration)

`python -m app.accounting.cli seed-counters` computes, from current `llm_calls`, sum(`usd`) per `boardId`, per `agentId`, and total, and writes them. This preserves each cap's **current** state exactly (the same numbers `check_exceeded` uses today). Run it while no runs are active (or accept a small race. Phase 8's reconcile corrects drift). Idempotent: it sets (not increments), and supports `--dry-run`.

Option (documented, not default): seed from the ledger's lifetime totals instead. That makes caps count history that has already expired from `llm_calls`, and some boards may immediately read as over cap. Default is to preserve present behavior.

### Cutover order (important)

1. Deploy Phase 5 code with **delivery enabled but counters not yet read** (feature flag `SPEND_COUNTERS_ENFORCED=false`): the recorder increments counters and enqueues events, `check_exceeded` still sums `llm_calls`.
2. Run `seed-counters` (counters were accruing since deploy, so the seed must **not** double count. Use `--set-from-llm-calls`, which overwrites with the authoritative sum).
3. Re-run Phase 1's backfill. It is idempotent and fills the window between Phase 1 and now, including any `llm_calls` rows enqueued before the outbox existed.
4. Flip `SPEND_COUNTERS_ENFORCED=true`. `check_exceeded` now reads counters.
5. Watch the Phase 8 reconcile for a day, then remove the flag and the old path.

### Config (core `config.py`)

`ACCOUNTING_SERVICE_URL`, `ACCOUNTING_SERVICE_KEY`, `OUTBOX_BATCH_SIZE`, `OUTBOX_POLL_SECONDS`, `OUTBOX_LEASE_SECONDS`, `OUTBOX_MAX_BACKOFF_SECONDS`, `USAGE_FALLBACK_PATH`, `SPEND_COUNTERS_ENFORCED`.

### Files

```
backend/app/accounting/
  outbox.py              OutboxRepository (enqueue, claim, mark_delivered, mark_rejected)
  worker.py              OutboxWorker (lifecycle, loop, backoff)
  counters.py            SpendCounters
  fallback.py            FallbackWriter + FallbackReplayer
  recorder.py            (extended) llm_calls → outbox → counters
backend/app/services/budget_service.py   check_exceeded reads counters; _sum_usd removed
backend/app/database.py                  usage_outbox, spend_counters, usage_backfill_state collections + indexes
backend/app/main.py                      start/stop worker, replay fallback
```

## Implementation Plan

- [ ] Add collections + indexes to `database.py` (`usage_outbox` incl. delivered TTL, `spend_counters`)
- [ ] `OutboxRepository`, `OutboxWorker` (claim/lease/backoff/poison handling), lifecycle in `main.py`
- [ ] `SpendCounters` and the `SPEND_COUNTERS_ENFORCED` flag
- [ ] Extend `UsageRecorder`: outbox insert + counters increment, never raising, fallback file on enqueue failure
- [ ] `FallbackReplayer` at startup
- [ ] Rewrite `check_exceeded` (flagged) and remove `_sum_usd`; update `test_budget_service.py`
- [ ] `cli seed-counters` (`--dry-run`, `--set-from-llm-calls`)
- [ ] Add `accounting` to the backend's compose `depends_on` only for dev convenience. The backend must still boot when it's unreachable
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

- **Never blocks a run:** with `UsageSink` raising on every call, `record` returns normally and a run completes.
- **Idempotent enqueue:** enqueuing the same `callId` twice leaves one outbox row.
- **Worker:** delivers pending rows in batches. 5xx → backoff, `attempts` increments, `nextAttemptAt` moves out. `rejected` items → `status=rejected`, not retried. Expired lease → row reclaimed by a second worker. Shutdown mid-batch leaves rows `pending`/`sending` with a lease (no loss).
- **Outage drain:** 1,000 events queued while the sink is down → all delivered after recovery, ledger count matches, no duplicates.
- **Counters:** N recorded calls → board/agent/global equal the exact sum of `usd`. Concurrent `record` calls don't lose increments (parallel `asyncio.gather`).
- **Caps:** `check_exceeded` at cap−ε passes, at cap blocks. With the flag off it uses the legacy path. The result matches between the two paths on the same data.
- **Fallback:** outbox insert fails → event appended to the file → replayer enqueues it on next startup.
- **Seeding:** `seed-counters` matches the legacy per-scope sums on a fixture, is idempotent, and `--dry-run` writes nothing.

## Verification

1. Run a task. Within seconds: the `usage_outbox` row goes `pending → delivered`, and a ledger row with the same `callId` exists in the accounting DB.
2. Stop the accounting container, run two tasks, and check that both complete and `usage_outbox` shows 2+ pending with growing `attempts`. Start the container, and the rows drain and appear in the ledger.
3. Kill the backend mid-delivery and restart it. Nothing is lost or duplicated.
4. Follow the cutover order above on a copy of real data. After step 2, per-board counters equal the legacy sums. After flipping the flag, set a board cap just below its counter and confirm a run is blocked.
5. Confirm a cap-checking request takes constant time with a large `llm_calls` collection (compare a quick timing before vs after).

## Rollback

Set `SPEND_COUNTERS_ENFORCED=false` (instant return to the legacy cap path, which still works while `llm_calls` rows exist). Stop the worker by removing its startup hook. Outbox rows simply wait. Counters and outbox collections are additive.

## Inputs Needed From You

- **Decision:** seed counters from current `llm_calls` (preserves today's cap state, recommended) vs. from lifetime ledger totals (stricter, may lock some boards).
- Confirm that caps becoming truly cumulative (no longer decaying with `llm_calls` TTL) is intended. This is the described and documented behavior, but boards that were silently regaining capacity will stop doing so.
