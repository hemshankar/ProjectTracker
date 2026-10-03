# Phase 2: Rollups, Query & Export

PRD: FR-15, FR-16, FR-18. Adds the read side of the service on top of Phase 1's ledger. Still no change to the core.

## Technical Design

### Rollup collection: `usage_daily`

One document per unique combination of **UTC day × agentId × boardId × taskId × model × userId × callKind**. The `_id` is a deterministic string of those parts (null → `-`), so an upsert with `$inc` is naturally idempotent per combination.

```
{ _id: "2026-10-03|agentA|boardB|taskC|claude-sonnet-5|userD|task_run",
  day: "2026-10-03", dayTs: <UTC midnight ms>,
  agentId, boardId, taskId, model, userId, callKind,
  calls, inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens,
  webSearchCount, usd }
```

Name snapshots are **not** stored in rollups. They are looked up from the ledger on demand (latest row per id) so renames and deletes don't need rollup rewrites.

**Indexes:** `(agentId, dayTs)`, `(boardId, dayTs)`, `(taskId)`, `(userId, dayTs)`, `(model, dayTs)`.

### Keeping rollups correct

- On ingest, `IngestService` returns the ids of rows **actually inserted** (Phase 1). `RollupService.apply(inserted_events)` groups them in memory by rollup key and issues one bulk `$inc` upsert per key. Duplicates never reach it, so redelivery cannot double-count.
- The ledger insert and the rollup update are two writes. A crash between them leaves a ledger row missing from rollups. That is acceptable because the ledger is the source of truth and the **rebuild/verify** commands (below) repair it. Phase 8 schedules the verify.
- `RollupService.rebuild(day_from, day_to)` recomputes days from the ledger with an aggregation and replaces those days' documents (delete the day range then insert, inside one logical operation per day). Idempotent, safe to run any time.
- `RollupService.verify(day_from, day_to)` compares ledger vs rollup sums per day and returns mismatches (day, ledger usd, rollup usd, delta).

### Query layer (read-only)

`services/query_service.py` plus a `UsageQuery` value object (scope filters, range, group-by, granularity). Routers only translate query params into it.

| Endpoint | Purpose | Source |
| --- | --- | --- |
| `GET /internal/summary` | totals for one scope: `taskId` \| `boardId` \| `agentId` (+ optional `since`/`until`) → `{usd, calls, inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens}` | rollups |
| `GET /internal/summary/batch` | totals for many `boardId`s or `taskId`s in one call (board list / task list badges) | rollups |
| `GET /internal/timeseries` | `granularity=day\|week\|month`, `groupBy=board\|task\|model\|user\|callKind\|none`, range | rollups, `$dateTrunc` on `dayTs` |
| `GET /internal/breakdown` | top-N by dimension for a range (table view) | rollups |
| `GET /internal/rows` | paginated ledger drill-down with filters (agent, board, task, run, model, user, callKind, outcome, range). Keyset pagination on `(ts, _id)` | ledger |
| `GET /internal/export` | streamed CSV or JSON Lines for a range, filters as in `rows` | ledger |

Common rules:
- All require `X-Internal-Key`. `agentId` is a **required** filter on every endpoint except the batch ones that are explicitly scoped by id lists. The core always supplies it from its own authorization, so the service can never return another workspace's data by accident.
- Bounded: max range for `rows`/`export` configurable (default 400 days per request), max page size 500, `export` streams in 1,000-row chunks and never loads everything in memory.
- Money is returned as a plain number of USD (float stored, rounded to 6 decimals on output). Totals sum in the database, not in Python.
- Name snapshots appear in `breakdown`/`rows`: for each id the **most recent** snapshot. A `deleted` hint is **not** computed here (the service doesn't know). The core adds it in Phase 6.

### Export formats

- `format=csv`: stable column order matching the ledger field list, ISO-8601 UTC timestamps in an added `tsIso` column plus raw `ts` ms, header row always present.
- `format=jsonl`: one ledger document per line.
- `Content-Disposition` with a filename including the range. CSV values escaped, and fields beginning with `= + - @` prefixed with a quote to prevent spreadsheet formula injection.

### Rebuild CLI

`python -m app.cli rollups rebuild --from 2026-01-01 --to 2026-10-03` and `... rollups verify`. Add `... ledger stats` (count, min/max ts, total usd) for operators.

## Implementation Plan

- [ ] `models/queries.py`: `UsageQuery`, `Granularity`, `GroupBy`, response models
- [ ] `repositories/rollup_repository.py` Protocol + `mongo_rollup.py` (bulk upsert `$inc`, aggregate helpers, ensure indexes)
- [ ] `services/rollup_service.py`: `apply`, `rebuild`, `verify`
- [ ] Wire `RollupService.apply` into `IngestService` (only newly inserted rows)
- [ ] `services/query_service.py` (summary, batch summary, timeseries, breakdown) and `services/rows_service.py` (keyset pagination)
- [ ] `services/export_service.py` (streaming CSV and JSONL, formula-injection guard)
- [ ] Routers: `summary.py`, `timeseries.py`, `rows.py`, `export.py` (HTTP only)
- [ ] `cli.py`: rebuild, verify, ledger stats
- [ ] Run the rollup rebuild once after Phase 1's backfill so existing data is covered
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

- **Idempotent rollups:** ingest a batch, ingest it again → rollup sums unchanged.
- **Correctness:** known fixture of events across days/boards/models → summary, timeseries (day/week/month boundaries in UTC, including a month change), and breakdown match hand-computed values.
- **Rebuild:** corrupt a rollup doc, `verify` reports the day, `rebuild` fixes it, and `verify` is clean.
- **Scope safety:** every endpoint without `agentId` (non-batch) → 422. Querying agent A never returns agent B's rows, even with a known board id from B.
- **Pagination:** keyset paging returns each row exactly once across pages, including rows with the same `ts`.
- **Export:** CSV escaping, formula-injection prefixing, header present for empty results, streaming doesn't load the full range (assert chunked iteration with a fake repository).
- **Bounds:** over-range and over-page-size requests are rejected.

## Verification

1. After backfill and `rollups rebuild`, call `GET /internal/summary?agentId=...` and compare `usd` to the Mongo `sum(usd)` of that agent's ledger rows. They must match.
2. `timeseries?granularity=day&groupBy=board` for a known week: spot-check two days against the ledger.
3. Pick a known spike day, then `rows` with the same filters and confirm the row total equals the bar.
4. `export?format=csv` → open in a spreadsheet, confirm columns, and confirm the row count equals `rows` total.
5. `rollups verify` across all days returns no mismatches.
6. Post a new live event: summary changes by exactly its `usd`.

## Rollback

All additive and read-side. Drop `usage_daily` and re-run `rebuild` to regenerate. Ledger data is untouched.

## Inputs Needed From You

- Maximum export range you're comfortable with (default 400 days per request) and whether CSV and JSONL are both wanted.
