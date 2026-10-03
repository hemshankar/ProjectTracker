# Phase 1: Intake Service & Gmail

Goal: a new `intake-service` watches a Gmail feed, applies mandatory filters, and asks the backend to auto-create a task for each matching message. Rule-based only (no LLM). Ledger and dedup work. Agents opt in with an **Enable intake** setting. Guardrails beyond filters come in Phase 2, so this phase is tested on an internal agent with a narrow filter.

## Technical Design

### Package layout (`intake-service/app/`)

```
main.py                 app + exception handlers
container.py            composition root
config.py               env vars only
database.py             Motor client (own DB "intake"), ensure_indexes
errors.py               domain exceptions + one HTTP translation table
security.py             require_internal_key
models/                 feed.py, event.py, ledger.py (Pydantic + frozen value objects)
sources/
  base.py               FeedSource protocol, SourceRef, Capabilities
  gmail.py              Gmail source via the gateway (list_messages, get_message)
  fake_source.py        in-memory source for tests
  registry.py           sourceType -> FeedSource
pipeline/
  normalizer.py         raw -> Event
  filters.py            deterministic sender/label/keyword matching
  dedup.py              ledger-backed duplicate check
  decider.py            RuleDecider (Phase 3 adds LLMDecider behind the same protocol)
  runner.py             orchestrates one feed run
sinks/
  task_sink.py          TaskSink protocol + HttpTaskSink (backend internal API)
gateway_client.py       thin client for the integrations service (list/execute)
services/
  feed_service.py       CRUD + validation
  ledger_service.py     write/query ledger
  scheduler.py          per-connection polling loop
routers/                feeds.py, health.py, internal.py
tests/
```

### Core types
- `FeedSource` (Protocol): `capabilities()`, `list_sources(connection)`, `fetch(feed, cursor) -> (list[RawEvent], new_cursor)`, `normalize(raw) -> Event`.
- `Event` (frozen): `source, connection_id, account_label, external_id, thread_id, author, subject, body (truncated), links, received_at`.
- `Decision` (frozen): `kind` (`create|append|ignore`), `reason`, `task` (title, description, priority, labels).
- `FeedConfig` (frozen) mirrors the stored feed.

### Gmail source
Uses the gateway only (no Google credentials here): `gmail.list_messages` with a query built from the feed (`label:"Support" newer_than:1d`, plus the stored cursor) and a new read action `gmail.get_message` (id to headers/body/threadId). **Add `gmail.get_message` to the gateway catalog and Composio map in this phase** (verify the Composio slug first; do not guess). Cursor = last seen internal date plus a seen-id window, because Gmail ordering is not guaranteed. First run uses a bounded backfill (default: last 24 hours, `perRunMax` messages) to avoid ingesting an entire inbox.

### Pipeline (`runner.py`)
For each fetched event: normalize, dedup against the ledger, filter, decide, sink, ledger. Order matters: ledger the outcome (`ignored`, `created`, `failed`) for every event, then advance the cursor once for the batch. Failures of one event never abort the batch.

### Data (`intake` database)
- `feeds`: as in the PRD (`agentId, connectionId, sourceType, sourceParams, target, filters, caps(unused until Phase 2), enabled, state`). Validation: connection belongs to the agent and is visible to the creator; board belongs to the agent; `filters` must not be empty.
- `intake_events`: ledger; unique `(connectionId, externalId)`; index `(feedId, createdAt)`.
- No bodies persisted beyond a short preview (200 chars) used by the admin view later.

### Backend changes (monolith)
- `models_settings.py`: add `IntakeSetting {enabled: bool}`; keep in a small `models_intake.py` if `models_settings.py` nears 300 lines. Wire into `AgentSettingsUpdate` and the settings service so `intake.enabled` persists (default false).
- New router `routers/intake_internal.py` (internal key only):
  - `POST /internal/intake/tasks` `{agentId, boardId, task{title, description, priority, labels}, source{type, connectionId, accountLabel, externalId, url, feedId, autoCreated:true}}`. Checks: intake enabled, board in agent, idempotent by `(feedId, source.externalId)` returning the existing task. Creates through `tasks_service` (so audit and websockets fire), with audit `actor_type="intake"`, `actor_id=feedId`.
- Task model: add `source` sub-document and an `auto-created` label applied automatically. Serialize in the task JSON.
- Feed management proxy (UI-facing, auth by agent role; intake-service is never exposed to browsers): `routers/feeds_proxy.py` forwarding `GET/POST/PATCH/DELETE /api/agents/{id}/feeds` with the acting user; only agent admins (shared) or the owner (personal) may write.
- `integrations_client.py` unchanged; the intake service has its own `gateway_client.py`.

### Intake-to-backend auth
`X-Internal-Key` shared secret (`INTERNAL_SERVICE_KEY`, same variable the gateway uses). The backend rejects without it.

### docker-compose
New `intake` service: `build: ./intake-service`, `env_file`, `expose: 8200`, bound to `127.0.0.1:8200` only, depends on `mongo`, `integrations`, `backend`. No public port.

### Scheduling
`scheduler.py` runs one asyncio task per **connection** (not per feed) with a default 120 s interval and jitter; it iterates that connection's enabled feeds. A feed run holds a Mongo lease (`state.leaseUntil`) so a restarted instance cannot run it twice concurrently.

## Implementation Plan
- [ ] Scaffold `intake-service` (Dockerfile, requirements, `.env.example`, `pytest.ini`, health, `container.py`, errors)
- [ ] Value objects, `FeedSource` protocol, `FakeSource`, source contract test suite
- [ ] Gateway: add `gmail.get_message` action (catalog + Composio map); verify slug
- [ ] `GmailSource` and contract tests against mocked gateway responses
- [ ] Pipeline: normalizer, filters, dedup, `RuleDecider`, runner (with ledger-then-cursor ordering)
- [ ] `feed_service` validation (connection ownership/visibility via gateway, board ownership via backend, non-empty filters)
- [ ] `ledger_service`, indexes, `scheduler` with per-connection loops and lease
- [ ] `HttpTaskSink` and backend `POST /internal/intake/tasks` with idempotency
- [ ] Backend: `intake.enabled` setting, task `source` field and auto-created label, feeds proxy router
- [ ] `docker-compose.yml` service and `.env.example` entries
- [ ] Tests: runner with fakes (create, ignore, duplicate, failure mid-batch, cursor only advances after ledger), backend endpoint (disabled, wrong board, idempotent retry)
- [ ] Verify no file over 300 lines

## Actions Required From You
1. Choose a **test agent and board** and a **throwaway Gmail account** connected through the gateway (Phase 0 done).
2. Create a Gmail **label** (for example `Intake-Test`) and send a few test emails to it, including a reply in the same thread.
3. Confirm the Composio tool slug and argument names for **get message** (I will not guess).
4. Confirm the first-run backfill window (default 24 h) and whether auto-created tasks should land in a fixed board for v1.
5. Confirm the service port (default 8200) and that intake stays internal-only.
6. Add `INTERNAL_SERVICE_KEY` to `intake-service/.env` (same value used by the other services).

## Development Best Practices
- **SRP:** the runner orchestrates; it does not parse emails (normalizer), match rules (filters) or call HTTP (sink, gateway client).
- **OCP:** adding Slack in Phase 4 must not touch `runner.py`, `filters.py` or the sink; verify by writing `FakeSource` as a second source in tests first.
- **LSP/ISP:** `GmailSource` and `FakeSource` share one contract test. Push support is a capability flag, not a stub.
- **DIP:** the runner receives its collaborators; unit tests need no network and no Mongo (in-memory ledger).
- **Idempotency:** every create is retry-safe through `(feedId, externalId)`; at-least-once delivery cannot create duplicates.
- **Security:** treat email content as untrusted; truncate bodies; never log content; the sink sends plain text only (no HTML).
- **Failure isolation:** one connection's loop crashing is caught and restarted; it must not stop others.
- **300-line rule:** keep `gmail.py` to fetch/normalize; query-building goes in `gmail_query.py`.

## UI Verification
1. Settings, Intake: the **Enable intake** toggle appears on the test agent (off by default). Turn it on.
2. Create a feed via the API (the UI panel comes in Phase 3): connection = test Gmail, label = `Intake-Test`, target = test board, one sender filter.
3. Send a matching email. Within about two minutes a task appears on the board (live, without refresh) with an **auto-created** label and a Gmail source badge or link in its details.
4. Send a non-matching email: no task; the ledger records `ignored` with a reason.
5. Restart the intake container: no duplicate tasks are created for already processed mail.
6. Disable intake on the agent: the next matching email creates nothing.
7. Reply in the same thread: a second task is created (thread appending arrives in Phase 3). Note this as expected behavior.
8. Run `pytest` in all three services: green.
