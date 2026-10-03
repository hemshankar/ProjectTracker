# Phase 1: Service, Ledger & Backfill

PRD: FR-11, FR-12, FR-13, FR-14, FR-17. **Ships first.** Its goal is to stop losing history, so it contains no UI and no changes to run behavior.

## Technical Design

### A new deployable: `accounting-service/`

A standalone FastAPI app modeled on `integrations-service/`: same layering, same shared-secret auth, own `Dockerfile`, own docker-compose entry, own database.

```
accounting-service/
  Dockerfile
  requirements.txt
  pytest.ini
  .env.example
  app/
    main.py            lifespan: ensure_indexes, include routers
    config.py          env vars only
    database.py        client, get_database(), ensure_indexes()
    container.py       composition root (only file naming concrete classes)
    security.py        require_internal_key (X-Internal-Key, constant-time)
    errors.py          domain errors → HTTP in one place
    models/
      events.py        UsageEvent (Pydantic), CallKind, Outcome, EventBatch, IngestResult
    repositories/
      ledger_repository.py     Protocol LedgerRepository
      mongo_ledger.py          MongoLedgerRepository
    services/
      ingest_service.py        validate, normalize, insert idempotently
    routers/
      health.py                GET /health
      events.py                POST /internal/events
  tests/
```

Rollups, queries, and export are Phase 2. This phase only needs ingest.

### Configuration (`config.py`)

| Variable | Purpose | Default |
| --- | --- | --- |
| `MONGO_URI` | Accounting DB server. **Separate instance recommended**, but works on the existing `mongo` container for dev | `mongodb://mongo:27017` |
| `MONGO_DB_NAME` | Distinct from the core's `scatterboard` | `scatterboard_accounting` |
| `ACCOUNTING_SERVICE_KEY` | Shared secret for core → service calls. Fails closed when unset | none |
| `MAX_BATCH_SIZE` | Per-request event cap | `500` |
| `SUPPORTED_SCHEMA_VERSIONS` | Current and previous | `1` |

### Ledger document (`usage_ledger`)

`_id` **is** the `callId`. A duplicate delivery then fails on the primary key. No separate unique index is needed and no read-before-write is required.

| Group | Fields |
| --- | --- |
| identity | `_id` (callId), `schemaVersion`, `ts` (ms, call time), `ingestedAt` |
| scope | `agentId`, `boardId`, `taskId`, `runId`, `parentRunId`, `callKind`, `userId` (all nullable except `agentId`, `callKind`) |
| name snapshots | `agentName`, `boardTitle`, `taskTitle` |
| usage | `model`, `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheCreationTokens`, `webSearchCount` |
| pricing | `rates` {input, output, cacheRead, cacheWrite, webSearch ($/MTok or $/search)}, `usd`, `pricedByFallback` |
| outcome | `latencyMs`, `outcome`, `anthropicRequestId` |
| provenance | `source` (`live`/`backfill`), `estimated`, `llmCallRef` |

`CallKind`: `task_run | subagent | chat | dispatch`. `Outcome`: `success | error | cancelled`.

**Indexes (`ensure_indexes`)**
- `(agentId, ts)`, `(boardId, ts)`, `(taskId, ts)`, `(userId, ts)`, `(model, ts)`, `(callKind, ts)`
- **No TTL index. No expiry field.**

### Ingest semantics (`POST /internal/events`)

1. `require_internal_key`.
2. Body is `EventBatch {schemaVersion, events[]}`. Reject the whole request on a bad or unsupported `schemaVersion` or oversize batch (400).
3. Validate each event with Pydantic. Invalid events are collected, not fatal.
4. `insert_many(valid, ordered=False)`. A `BulkWriteError` whose errors are all code 11000 (duplicate key) is success for those items. Other errors propagate as 500 so the caller retries.
5. Response: `{accepted: n, duplicates: n, rejected: [{callId, reason}]}`. A request is **200** even when some items are rejected. Rejected events never block the batch.

Hand the **actually inserted** callIds back to the caller layer (internal return value of `ingest_service`). Phase 2 applies rollups only to newly inserted rows, keeping rollups idempotent.

### Immutability enforcement

`LedgerRepository` exposes only `insert_many`, `find`, `aggregate`-style reads, and `count`. It has **no** update or delete method, and there is no router for them. A test asserts the Protocol and Mongo implementation expose none.

### Backfill (runs in the core, not the service)

The old rows live in the core's database, so the script belongs in `backend/` and posts through the same ingest endpoint.

```
backend/app/accounting/
  __init__.py
  client.py            Protocol UsageSink + HttpUsageClient (X-Internal-Key, retries)
  backfill.py          BackfillRunner (batching, resume, reporting)
  cli.py               python -m app.accounting.cli backfill [--since --until --dry-run]
```

**Mapping `llm_calls` → event** (old rows lack model and cache data):

| Event field | Source |
| --- | --- |
| `callId` | `llm_calls._id` (so a re-run, or later live delivery of the same row, is a no-op) |
| `ts`, `agentId`, `boardId`, `taskId`, `runId`, `parentRunId` | same-named fields |
| `callKind` | `subagent` if `parentRunId` is set, else `task_run` |
| `inputTokens`, `outputTokens`, `usd`, `latencyMs` | same-named fields. **`usd` is copied verbatim**, since it is what caps were enforced against |
| `model` | row's `model` if present (rows written after Phase 3), else `"unknown"` |
| `cache*`, `webSearchCount` | row's value or `0` |
| `rates` | row's snapshot if present, else the flat rates from config at run time |
| `estimated` | `true` when the row has no `model`/rates snapshot, else `false` |
| `source` | `backfill` |
| name snapshots | looked up from `agents`/`boards` if still present, else `null` |
| `llmCallRef` | `llm_calls._id` |

Note: this refines the PRD's wording ("priced at the default model's rates"). Copying the recorded `usd` is more faithful, because it is the number actually used for caps. Rates are stored only as provenance.

**Runner behavior**
- Cursor over `llm_calls` ordered by `ts, _id`, batches of 500.
- **Resumable:** checkpoint (`lastTs`, `lastId`) in a core collection `usage_backfill_state`. Re-run continues, and re-sending is harmless (idempotent).
- Retry with backoff on 5xx/connection errors. Abort cleanly with a nonzero exit after N consecutive failures.
- Prints counts per batch and a final summary (read, accepted, duplicates, rejected, total USD sent). `--dry-run` computes totals only.
- Run once manually: `docker compose exec backend python -m app.accounting.cli backfill`.

### docker-compose

```yaml
  accounting:
    build: ./accounting-service
    container_name: scatterboard-accounting
    restart: unless-stopped
    env_file: [./accounting-service/.env]
    environment:
      MONGO_URI: mongodb://mongo:27017        # point at a dedicated instance in prod
      MONGO_DB_NAME: scatterboard_accounting
    volumes: [./accounting-service/app:/srv/app]
    expose: ["8200"]
    ports: ["127.0.0.1:8200:8200"]            # loopback only; never public
    depends_on: [mongo]
```

`backend` gets `ACCOUNTING_SERVICE_URL=http://accounting:8200` and `ACCOUNTING_SERVICE_KEY`. Add `accounting` to the backend's `depends_on` only when Phase 5 makes it required. In this phase the backend must still start if the service is down.

## Implementation Plan

- [ ] (Stopgap) raise `LLM_CALL_RETENTION_DAYS` for the backend and, after confirming with the owner, extend `expiresAt` on existing `llm_calls` rows (one documented Mongo update)
- [ ] Scaffold `accounting-service/` (layout above) and add the `accounting` compose entry
- [ ] `config.py`, `database.py`, `security.py`, `errors.py`, `container.py`, `main.py`
- [ ] `models/events.py`: `UsageEvent`, enums, `EventBatch`, `IngestResult` (frozen/immutable where possible)
- [ ] `LedgerRepository` Protocol + `MongoLedgerRepository` (insert-many idempotent, reads only) + `ensure_indexes` (no TTL)
- [ ] `IngestService` (validation, partial-reject, duplicate handling, returns inserted ids)
- [ ] `routers/health.py` (`GET /health`, unauthenticated) and `routers/events.py` (`POST /internal/events`)
- [ ] Core: `backend/app/accounting/client.py` (`UsageSink` Protocol + `HttpUsageClient`), config entries in `backend/app/config.py`
- [ ] Core: `backfill.py`, `cli.py`, `usage_backfill_state` checkpoint
- [ ] `.env.example` for both sides (`ACCOUNTING_SERVICE_KEY`, URLs); never commit real values
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

Service (`accounting-service/tests/`):
- Ingest: valid batch inserts all. Same batch twice yields `duplicates == n`, no extra rows.
- Mixed batch: a bad event is rejected individually, the rest land.
- Wrong or missing `X-Internal-Key` → 401, and the service fails closed when the key is unset.
- Unsupported `schemaVersion` → 400. Oversize batch → 400.
- Immutability: repository exposes no update/delete.
- `_id == callId` and no TTL index exists after `ensure_indexes`.

Core (`backend/tests/test_accounting_backfill.py`):
- Mapping function: `usd` copied verbatim, `callKind` inference, `estimated` flag rules, missing `model` → `"unknown"`.
- Runner resumes from checkpoint, tolerates a transient 5xx, and is idempotent when re-run (fake `UsageSink`).
- Dry run sends nothing.

## Verification

1. `docker compose up accounting`, then `GET http://localhost:8200/health` → 200.
2. Post a one-event batch with the right key → `accepted: 1`. Post it again → `duplicates: 1`. Wrong key → 401.
3. `backfill --dry-run`: the printed total USD should equal the sum of `usd` over `llm_calls` (check with a Mongo aggregate).
4. Run the real backfill. Compare `count` and `sum(usd)` in `usage_ledger` to `llm_calls`: they must match exactly. Re-run: all duplicates.
5. Confirm the app is otherwise unchanged. Run a task and confirm it works and costs are shown as before.
6. Stop the accounting container and run a task. Nothing should break (nothing in the core depends on it yet).

## Rollback

Stop and remove the `accounting` container. The core is untouched. The ledger DB can be dropped and backfill re-run at any time.

## Inputs Needed From You

- Deployment target for the accounting database (separate Mongo instance vs. a second database on the existing container) and its backup policy (NFR-10).
- Approval to run the stopgap retention extension on existing `llm_calls` rows.
- A value for `ACCOUNTING_SERVICE_KEY`.
