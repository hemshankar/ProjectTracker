# Usage & Cost Accounting: Release Notes and Launch Results

## What changes for users

- **Cost is now visible.** Task and board totals (USD) appear on task details and board cards and tick up while work runs. Workspace admins get a **Usage** tab in the Admin Console with a time series, a breakdown by board, task, model, user and call kind, a ledger drill-down, and CSV/JSONL export.
- **Caps now count chat and dispatch calls**, not only task runs. A workspace may reach a cap sooner than before. Caps themselves are unchanged. Only the accounting is more accurate.
- **Caps are cumulative.** They no longer shrink as old `llm_calls` rows expire (once the counter cutover below is done).
- **Costs before the rollout are estimates.** Backfilled history was priced at flat rates, and rows without a model snapshot are marked *estimated*.
- **System alerts.** Workspace admins get a bell in the top-right of the boards screen and a System alerts page for accounting problems (delivery backed up, service down, drift, and so on).

## Launch checklist results (2026-10-03)

Reproduce with `backend/scripts/accounting_drills` (see the runbook). The drills run in throwaway `zz_drill_*` databases and a throwaway accounting service on port 8299. The live ledger is only read, never written.

| # | Gate | Result | Evidence and caveats |
| --- | --- | --- | --- |
| 1 | Backfill complete, counts and USD match | **Pass** | Live: 26 ledger rows vs 26 `llm_calls`, $0.484761 both. Scratch: 2,000 legacy rows backfilled, count and sum equal, re-run created 0 duplicates. |
| 2 | 7 days live traffic, completeness 0 missing, drift in tolerance | **Not met (accelerated only)** | 3,000 mixed calls (task, sub-agent, chat, dispatch): every call has a ledger row, completeness `missing=0`, counter drift 0. A 7-day soak on real traffic has **not** happened. The hourly checks now run in the backend and will accumulate that evidence. |
| 3 | Rollups verified clean | **Pass** | Clean after backfill, after the outage drill, and after repair plus rebuild. Daily verify job is scheduled. |
| 4 | Sample workspaces: UI, ledger and `llm_calls` agree to the cent | **Pass** | Both existing workspaces (the "sample 5" is all there are) and all 3 boards agree to within $0.0001. UI figures are read from the same service endpoint the UI calls. |
| 5 | Outage drill: outbox drains, no gaps or duplicates | **Pass (shortened)** | 20 s outage at ~80 calls/s, not 1 hour: 1,288 events queued, the `service_down` and `outbox_backlog` alerts raised and the bell showed 2, restart drained to 0, ledger gained exactly 1,288, rollups matched, alerts cleared. Backoff was shortened for the drill. |
| 6 | Cap includes chat and dispatch, no TTL decay | **Pass in drill, not yet live** | A single chat and a single dispatch call each trip the cap. The cap still held after the board's `llm_calls` rows were deleted. The legacy mode forgot the same spend. **Live is still `SPEND_COUNTERS_ENFORCED=false`**, so live caps behave the old way until the cutover below. |
| 7 | Recorder p95 < 5 ms, cap check constant-time at 10x | **Pass** | `record` p95 2.67 ms; baseline insert p95 1.29 ms; added **1.38 ms**. Cap check 1.55 ms at 10k rows and 1.67 ms at 100k. The legacy check went from 15 ms to 127 ms. Measured on a local Mongo on the same host. |
| 8 | Permission audit | **Pass** | Authz matrix tests pass (15). Against the running build, all usage and alerts endpoints return 401 without a session, the service rejects missing and wrong keys, and it is bound to loopback. |
| 9 | Release notes | **Done** | This document. |

Also exercised: the phase doc's verification steps 1 and 2. Three deleted ledger rows were reported exactly, restored by `--repair`, and rollups were rebuilt. A corrupted counter was flagged, left alone without `--repair`, and fixed with it with an audit entry.

## Open items before announcing

1. **The price table is empty.** All 26 live rows are priced by fallback (`pricedByFallback=true`). Totals are therefore approximations, and the `pricing_fallback` alert will start firing once there are 10 or more events an hour. Provide the confirmed per-model prices and set `PRICING_OVERRIDES_JSON`. This is the PRD's open item.
2. **Counter cutover.** The four live counters predate the seed marker (`unmarked`). To turn on cumulative caps: run `seed-counters --dry-run`, then `seed-counters`, then set `SPEND_COUNTERS_ENFORCED=true` and restart the backend. Not done automatically because it changes live caps.
3. **7-day soak (gate 2)** and a **full-length outage drill (gate 5)** on staging, when convenient.
4. **Off-host backup destination** (`BACKUP_COPY_CMD`) and a cron entry for `scripts/accounting-backup.sh`.
