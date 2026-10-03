# Usage Accounting Runbook

Operations guide for the accounting service and the core's usage pipeline. Commands run from the repo root against the docker-compose stack (service names `backend`, `accounting`). Prefix with `docker compose exec`.

## 1. Architecture in one page

```
call sites -> UsageRecorder -> llm_calls (content, TTL)
                            -> spend_counters ($inc, O(1) cap checks)
                            -> usage_outbox -> OutboxWorker -> accounting service
                                                                 |- usage_ledger (append-only, no TTL)
                                                                 '- usage_daily  (rollups)
core proxy (auth, admin gating) <- accounting query API <- browser Usage tab
```

Three consistency layers, each with its own check and repair:

| Pair | Check | Repair |
| --- | --- | --- |
| `llm_calls` and ledger | `reconcile completeness` | `--repair` re-enqueues missing rows |
| ledger and rollups | `rollups verify` (daily, automatic) | `rollups rebuild` |
| core counters and ledger | `reconcile counters` (hourly, automatic) | `--repair` (audited) |

Background jobs (core): completeness hourly with repair, counters hourly (read-only), health every minute. All stop with `RECONCILE_ENABLED=false`. Service: rollup verify daily at `ROLLUP_VERIFY_HOUR_UTC` (stop with `ROLLUP_VERIFY_ENABLED=false`).

Alerts are stored in `system_alerts` and shown on the **System alerts** page (bell in the top-right of the boards screen, workspace admins only). An alert opens when its condition fires, clears on its own when the condition clears, and each new alert is also logged as `ERROR ALERT ...` (`docker compose logs backend | grep ALERT`). Acknowledging only removes it from the bell count.

## 2. Outbox is backing up

Symptoms: amber "Usage data is delayed" banner, `ALERT usage outbox backed up`.

1. `curl -s localhost:8200/health/ready` should return `{"ready":true}`. If not, the service or its Mongo is down: `docker compose logs accounting`.
2. If the service is up, check the key: backend `ACCOUNTING_SERVICE_KEY` must equal the service's. A wrong key shows as 401 in `docker compose logs backend | grep "usage delivery failed"`. Rows are retried, never dropped. Fixing the key drains the queue.
3. Nothing is lost while the service is down: events wait in `usage_outbox` and drain on recovery. Check `GET /api/agents/{id}/usage/health`.
4. `rejected > 0`: the service refused an event as invalid. Inspect with `db.usage_outbox.find({status:"rejected"})` (`lastError` has the reason), fix the cause, then `reconcile completeness --repair` re-enqueues the row from `llm_calls`.

## 3. Ledger is missing rows

```
docker compose exec backend python -m app.accounting.reconcile.cli completeness --window-hours 48
docker compose exec backend python -m app.accounting.reconcile.cli completeness --window-hours 48 --repair
```

Reports `checked`, `missing`, `missingUsd`. Rows still `pending`/`sending` in the outbox are excluded. Exit code 1 means rows remain missing after repair. Only rows still in `llm_calls` (retention window) can be repaired, which is why the check runs hourly.

## 4. Totals look wrong

Work from the bottom layer up:

```
docker compose exec accounting python -m app.cli ledger stats
docker compose exec accounting python -m app.cli rollups verify               # read-only
docker compose exec accounting python -m app.cli rollups rebuild --from 2026-09-01 --to 2026-10-03
docker compose exec backend python -m app.accounting.reconcile.cli counters   # read-only, warns on drift
docker compose exec backend python -m app.accounting.reconcile.cli counters --repair   # sets counter, writes audit_log entry
```

Counters created before the `seededAt`/`seedUsd` marker are listed as `unmarked` and skipped. Run `python -m app.accounting.cli seed-counters --dry-run`, then without `--dry-run`, to baseline them (it sets each counter from the current `llm_calls` sum). Counter reconcile never changes anything without `--repair`, because lowering a counter can unblock a capped board. It compares against the ledger since the counter's `seededAt`, so pre-seed backfilled spend is not counted as drift.

## 5. Price changed

Set `PRICING_OVERRIDES_JSON` in the backend env (see `config.py`), restart the backend. Only new calls use the new rates. Past ledger rows keep the rates they were charged at (immutable). Recomputing history is a deliberate decision: it would be done with compensating entries, not edits. `ALERT ... priced by fallback` means an unknown model: add it to the table.

## 6. Restore from backup (drill, run quarterly)

Only `usage_ledger` is backed up. Rollups are rebuilt from it, and counters and the outbox are recoverable.

1. Restore into a scratch database, never over the live one:
   `docker compose exec -T mongo mongorestore --gzip --archive --nsFrom 'scatterboard_accounting.*' --nsTo 'zz_restore_drill.*' < usage_ledger-<stamp>.archive.gz`
2. Compare row count and total USD with the live ledger (`ledger stats`, or `db.usage_ledger.aggregate([{$group:{_id:null,n:{$sum:1},usd:{$sum:"$usd"}}}])` in both databases).
3. Drop the scratch database: `db.dropDatabase()` in `zz_restore_drill`.

Real disaster recovery: restore the archive into `scatterboard_accounting` (same command without `--nsFrom/--nsTo`), then `python -m app.cli rollups rebuild` and `rollups verify` in the accounting container, then `ledger stats`. Counters that disagree afterwards are handled by section 4.

Last tested 2026-10-03: 26 rows and $0.484761 matched after a restore into a scratch database.

## 7. Re-run backfill

Safe at any time: ingest is idempotent on `callId`, so re-running creates no duplicates. It resumes from its checkpoint.

```
docker compose exec backend python -m app.accounting.cli backfill --dry-run
docker compose exec backend python -m app.accounting.cli backfill
```

## 8. Schema version bump

1. Deploy the service accepting both versions: `SUPPORTED_SCHEMA_VERSIONS=1,2`.
2. Deploy the core sending version 2 (`SCHEMA_VERSION` in `accounting/client.py`).
3. After the outbox has drained (pending 0), drop version 1 from the service env.

## 9. Backups and topology (NFR-10)

The ledger is the permanent financial record. Topology: the same Mongo instance as the app, in its own database (`scatterboard_accounting`). The protection is an off-host copy of the ledger dump:

```
scripts/accounting-backup.sh                                          # local dump only
BACKUP_COPY_CMD='aws s3 cp "$FILE" s3://<bucket>/accounting/' scripts/accounting-backup.sh
```

Schedule it daily (cron or your scheduler), for example `15 2 * * * cd /path/to/repo && BACKUP_COPY_CMD='...' scripts/accounting-backup.sh`. The script writes under a temp name so a failed dump is never mistaken for a backup, fails the job if the copy step fails, warns when no copy is configured, and keeps the newest `BACKUP_KEEP` (14) local archives. **A backup that only exists on the same host does not protect against losing the host: set `BACKUP_COPY_CMD`.** The off-host destination is not chosen yet.

The ledger is small (about 0.5 KB per row), so a full dump each day is cheap. Because rows are never updated, incremental dumps are possible later if it grows.

Optional later: `docker-compose.prod.yml` moves the ledger to a dedicated Mongo and volume for failure isolation.

## 10. Alert conditions

| Condition | Where it fires | Threshold env |
| --- | --- | --- |
| Oldest pending outbox event too old | worker + health job | `ALERT_OUTBOX_AGE_SECONDS` (900) |
| Any rejected events | worker + health job | |
| Ledger missing rows after repair | completeness job | |
| Counter drift above tolerance | counters job | `max($0.01, 0.1%)` |
| Accounting service unreachable | health job | `ALERT_SERVICE_DOWN_SECONDS` (300) |
| Spike in `pricedByFallback` | health job | `ALERT_FALLBACK_RATIO` (0.2), `ALERT_FALLBACK_MIN_EVENTS` (10) |
| Rollup/ledger mismatch | service daily job | |

Shown on the alerts page and logged. Pushing to Slack or email is not wired.

## 11. Service endpoints for operators

`GET /health` (process up), `GET /health/ready` (DB reachable, indexes present, 503 otherwise), `GET /internal/stats` (key required: ledger count, latest ts, ingested last hour, rejected since start, rollup lag in days).

## 12. Launch drills

Re-run the launch checks any time (after a large change or before a release). They use throwaway `zz_drill_*` databases and a throwaway service on port 8299, and refuse to run against anything else:

```
cd backend
DRILL_ACCOUNTING_PYTHON=/path/to/accounting-service/venv/bin/python python -m scripts.accounting_drills scratch   # gates 1-3, 5-7
python -m scripts.accounting_drills live                                                                       # gates 1, 4 (read-only)
```
