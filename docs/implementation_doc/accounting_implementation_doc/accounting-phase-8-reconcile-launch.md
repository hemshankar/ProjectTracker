# Phase 8: Reconcile & Launch

PRD: FR-10, FR-18, NFR-7, NFR-10, sections 11 (step 7) and 12 (success metrics). Makes the system self-checking, observable, and safe to announce.

## Technical Design

### Three consistency layers and who checks them

| Layer pair | Drift cause | Check | Repair |
| --- | --- | --- | --- |
| `llm_calls` ↔ ledger (completeness) | crash between steps in `record`, poison events, pre-Phase-5 gap | `LedgerCompletenessCheck` | re-enqueue missing rows (same idempotent path as backfill) |
| ledger ↔ rollups | crash between ledger insert and rollup `$inc` | `rollups verify` (Phase 2) | `rollups rebuild` for the affected days |
| core counters ↔ ledger | crash after outbox insert before `$inc`, seeding race | `CounterReconcile` | reset counter from the authoritative total |

### `LedgerCompletenessCheck` (core)

Runs while `llm_calls` rows still exist (they expire, so it only covers the retention window, and that is the window where a repair is still possible):
1. For a time window (default last 48h, configurable), page through `llm_calls` `_id`s.
2. Ask the service which of those callIds exist: `POST /internal/events/exists` with a list of ids (new endpoint: returns the **missing** ids, capped at 1,000 per request, ledger primary-key lookups).
3. Report `{checked, missing, missingUsd}`. With `--repair`, enqueue the missing rows through the normal outbox (rebuilding events with the Phase 1 mapper, `estimated` per its rule).
4. Excludes outbox rows currently `pending`/`sending`, since those are expected to be missing and aren't drift.

### `CounterReconcile` (core)

For each scope with a counter: compare to the service's lifetime total (`/internal/summary`) **plus** the pending outbox delta. Expected counter = `seedUsd` (the baseline stamped at seed time) + ledger since `seededAt` + pending. Counters from before the marker (no `seededAt`) are reported as `unmarked` and skipped until `seed-counters` is re-run. A mismatch greater than `max($0.01, 0.1%)` is logged at `warning` with scope, counter, ledger, and delta. Policy for correction:

- **Never auto-lower a counter** (it could unblock a capped board by mistake) and **never auto-raise**, by default. Only `--repair` writes, and it is explicit and audited (entry in `audit_log` with before/after).
- Caveat documented: the ledger includes backfilled spend older than `llm_calls` retention, while counters were seeded from `llm_calls` (Phase 5 default). So the **expected** difference for old data is nonzero. The reconcile therefore compares **since the counters' seed time** (`seededAt` stored on each counter, or global in `spend_counters._id="meta"`), not lifetime.

### Scheduling

A small `ReconcileScheduler` background task in the core's lifespan (same pattern as the outbox worker): completeness hourly (window 48h), counter reconcile hourly, rollup verify daily at a quiet hour (service side, via its own scheduler or a cron-triggered CLI inside the container; start with a loop in the service's lifespan, `ROLLUP_VERIFY_HOUR_UTC`). All intervals env-configurable and disable-able.

### Operational visibility (NFR-7)

Service:
- `GET /health`: process up. `GET /health/ready`: DB reachable and indexes present.
- Structured JSON logs with `callId`, batch sizes, durations, and rejected reasons.
- `GET /internal/stats` (key-protected): ledger count, latest `ts`, ingest rate (last 1h), rejected count since start, rollup lag.

Core:
- Periodic log line: outbox `pending`, `oldestPendingAgeSeconds`, `rejected`, `deliveredLastHour`.
- `GET /api/agents/{id}/usage/health` (Phase 6) surfaces these to admins. The Usage tab shows a small amber banner when `oldestPendingAgeSeconds` exceeds the threshold ("Usage data is delayed. N events waiting").

**Alert conditions** (documented; wire to whatever alerting exists, or log at `error` level if none): oldest pending > 15 min, any `rejected` events, ledger-completeness `missing > 0` after a repair pass, counter drift above tolerance, accounting service not ready for > 5 min, spike in `pricedByFallback` events (price table stale or an unknown model).

### Backups and durability (NFR-10)

- Document in the deploy notes that the accounting database is the permanent financial record and must be in the backup plan (daily snapshot minimum; separate Mongo instance/volume in compose for production, with its own named volume, e.g. `accounting-mongo-data`).
- A `restore drill` checklist: restore a snapshot into a scratch instance, run `rollups verify` and `ledger stats`, and compare totals to the app.
- Optional follow-up (PRD open item): periodic export to cold storage using the Phase 2 export endpoint via a scheduled job.

### Launch checklist (PRD section 11, step 7)

Pre-announcement gates, all must be green:
1. Backfill complete, and `ledger count == llm_calls count` and `sum(usd)` equal for the backfilled range.
2. Seven days of live traffic with `LedgerCompletenessCheck` reporting `missing == 0` and counter drift within tolerance.
3. Rollups verified clean.
4. Sample 5 workspaces: UI board/task totals vs ledger sums vs hand sums of `llm_calls` agree to the cent.
5. Outage drill: stop the service for 1 hour under load, then restart. The outbox drains to zero, with no gaps or duplicates.
6. Cap drill: confirm a cap now includes chat and dispatch spend and no longer decays with TTL.
7. Load check: p95 added latency of `UsageRecorder.record` under 5 ms on the call path. Cap check constant-time at 10× current data.
8. Permission audit: re-run the Phase 6 authz matrix against the deployed build.
9. Release notes: caps now count chat and dispatch, and are cumulative (no decay). Usage UI and history are new. Costs before the rollout are estimates.

### Success metrics measurement (PRD section 12)

| Metric | How measured |
| --- | --- |
| 100% of calls have a ledger row (drift < 1%) | completeness check `missing / checked` |
| Zero run failures caused by accounting | grep run errors for accounting exceptions (expected: none). Chaos test in the outage drill |
| Task cost shown == sum of its ledger rows | UI vs `rows` sums on sampled tasks |
| "What drove last quarter's spend?" answerable in the UI | scripted walk-through by an admin, no DB access |
| Cap checks constant-time | timing at increasing `llm_calls` sizes |

### Files

```
backend/app/accounting/reconcile/
  completeness.py        LedgerCompletenessCheck
  counters.py            CounterReconcile
  scheduler.py           ReconcileScheduler
  cli.py                 reconcile {completeness|counters} [--repair --window --dry-run]
accounting-service/app/
  routers/events.py      (+ POST /internal/events/exists)
  routers/stats.py       GET /internal/stats, GET /health/ready
  services/scheduler.py  rollup verify loop
docs/…/accounting-runbook.md   operations runbook (below)
```

### Runbook (`accounting-runbook.md`, written in this phase)

Sections: architecture one-pager, "outbox is backing up", "ledger missing rows" (completeness `--repair`), "totals look wrong" (rollup verify/rebuild, counter reconcile), "price changed" (override JSON, recompute policy), "restore from backup", "re-run backfill", "schema version bump procedure". Each with exact commands.

## Implementation Plan

- [x] Service: `POST /internal/events/exists`, `GET /internal/stats`, `GET /health/ready`, rollup-verify scheduler
- [x] Core: `LedgerCompletenessCheck` (+ `--repair`), `CounterReconcile` (+ `--repair` with audit entry), `ReconcileScheduler`, `seededAt` marker on counters
- [x] Outbox health logging and the Usage-tab amber banner hook (uses Phase 6 `/usage/health`)
- [x] Alert conditions wired to logs (ERROR `ALERT ...`); external alerting pending the input below
- [x] Production compose (`docker-compose.prod.yml` override): dedicated accounting Mongo service and named volume. Backup notes in the deploy docs
- [x] Write `accounting-runbook.md`
- [x] Execute the launch checklist and record results in [accounting-release-notes.md](accounting-release-notes.md): 7 gates pass, gate 2 (7-day soak) is accelerated only, gate 6 is proven in a drill but live is not yet on counters
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

- **Completeness:** fixture with 100 `llm_calls`, 3 absent from a fake ledger and 2 pending in the outbox → reports exactly 3 missing. `--repair` enqueues exactly those 3. A second run → 0.
- **Counter reconcile:** drift within tolerance → silent. Drift above → warning with correct numbers. Without `--repair` nothing is written. With `--repair` the counter is set and an audit entry is written. Seed-time scoping excludes pre-seed spend.
- **Scheduler:** intervals honored, a failing check doesn't kill the loop, and disabling via env stops it.
- **Service endpoints:** `/exists` returns only missing ids, enforces the 1,000-id cap. `/stats` and `/ready` behave when the DB is down (`ready` fails, `health` passes).

## Verification

1. Delete one ledger row in a **scratch** copy (the real ledger is immutable, so use a test database). `reconcile completeness` reports it. `--repair` restores it.
2. Corrupt one counter in a scratch DB, and `reconcile counters` warns. `--repair` fixes it and writes an audit entry.
3. Stop the service for an hour (staging). The amber banner appears, the alert condition fires, then everything clears after restart.
4. Walk the 9-gate launch checklist and record each result.
5. Restore drill: restore last night's snapshot into a scratch instance and verify totals.

## Rollback

Disable the schedulers via env. The checks and repairs are read-mostly and only write on explicit `--repair`. Nothing here changes product behavior.

## Inputs Needed From You

- ~~Where alerts should go~~ Decided: in-app alerts page plus a bell on the boards screen.
- Production topology for the accounting database (separate instance) and the backup mechanism you use.
