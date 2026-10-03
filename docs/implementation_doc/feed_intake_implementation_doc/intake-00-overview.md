# Feed Intake — Technical Design & Implementation Plan

Companion to [PRD-feed-intake.md](../../PRD-feed-intake.md). One document per phase. Each has a technical design, an implementation checklist, **Actions Required From You**, **Development Best Practices**, and a **UI Verification** pass. Work stops at the end of every phase for you to verify.

| Phase | Focus | Status |
| --- | --- | --- |
| [Phase 0: Multi-Connection Gateway](intake-phase-0-multi-connection-gateway.md) | Several connections per agent + tool; owner and visibility; backward compatible | Next |
| [Phase 1: Intake Service & Gmail](intake-phase-1-service-and-gmail.md) | New service, Gmail source, rule-based create, ledger + dedup, agent toggle | |
| [Phase 2: Guardrails & Cost](intake-phase-2-guardrails-and-cost.md) | Kill switch, daily caps, auto-created marker, budget via accounting | |
| [Phase 3: LLM Classification & Feed UI](intake-phase-3-classification-and-ui.md) | Classifier/extractor, thread appends, feeds panel in Settings | |
| [Phase 4: Slack & Admin View](intake-phase-4-slack-and-admin-view.md) | Second `FeedSource`, board creation, ledger/health view | |

## What the existing code looks like (verified)

- **Connections are keyed by `(agentId, toolType)`.** `ConnectionService` caches on that tuple, the `connections` collection has a unique index on `agentId+toolType`, and `IntegrationsClient` methods (`list_connections(agent_id)`, `disconnect(agent_id, tool_type)`, `execute(agent_id, tool_type, ...)`) take no connection id. A second Gmail on one agent therefore collides with the first. Phase 0 fixes this.
- **The Composio `user_id` is the `agentId`** (`ComposioBackend._accounts(user_id, slug)`). The `Backend` protocol takes `user_id` and a `ProviderConfig` everywhere.
- **The "agent" is the workspace/tenant:** it owns members (`agent_members`), boards, settings (`models_settings.py`), budgets and audit scope. There is no separate workspace concept, so feeds are agent-scoped.
- **Gateway service layout** (`integrations-service/app/`): `backends/`, `actions/`, `services/`, `routers/`, `container.py` composition root, `errors.py` translation table, `X-Internal-Key` auth. The intake service copies this layout.
- **Backend (monolith)** is the only writer of boards and tasks; it owns permissions, audit (`audit_service`), websockets and budgets. `accounting-service` receives usage. Both are called over HTTP with `X-Internal-Key`.
- `docker-compose.yml` already runs `integrations`, `integrations-admin` and `accounting` as separate services. Intake is added the same way.

## Cross-cutting design decisions

1. **Intake never writes board collections.** It calls backend internal endpoints. The backend enforces permissions, audit and websocket fan-out.
2. **A feed references exactly one connection.** Merge across accounts at the target board level, never inside a feed.
3. **Dedup key is `(connectionId, externalId)`.** Cursors, rate limits and failure state are per connection.
4. **Rule-only first, LLM later.** Phase 1 creates tasks with deterministic mapping, so the whole pipeline can be verified before spending on a model.
5. **Filters are mandatory.** A feed cannot be saved without at least one filter.
6. **External text is untrusted.** The classifier has no tools; its output is schema-validated.
7. **Existing callers must not break.** `(agentId, toolType)` keeps resolving to the agent's default connection.

## Engineering Standards (apply to every phase)

**SOLID**
- **Single Responsibility.** Routers parse HTTP and call one service. Pipeline stages (`normalizer`, `filters`, `classifier`, `dedup`, `runner`) each own one concern. Services own one concern each (`feed_service`, `ledger_service`, `caps_service`, `scheduler`).
- **Open/Closed.** A new source is one `FeedSource` implementation plus a registry entry. No pipeline, router or sink edits.
- **Liskov Substitution.** Every `FeedSource` passes one shared contract test suite (`FakeSource` and `GmailSource` identically). No `isinstance` or `if source == "gmail"` outside `sources/`.
- **Interface Segregation.** Small protocols: `FeedSource` (list/fetch/normalize), `EventReceiver` (webhook parsing, optional), `Classifier`, `TaskSink`, `Clock`. A source without push support declares it via `capabilities()` instead of stubbing.
- **Dependency Inversion.** The runner takes `FeedSource`, `Filter`, `Classifier`, `TaskSink`, `LedgerStore`, and `Clock` through its constructor. Only `container.py` builds concrete classes.

**OOP**
- Frozen dataclasses for `Event`, `Decision`, `FeedConfig`, `SourceRef`, `SinkResult`. No dict-of-dict passing between layers.
- Composition over inheritance: the runner holds collaborators; nothing subclasses a source.
- Typed domain exceptions (`FeedInvalid`, `ConnectionForbidden`, `CapReached`, `SourceUnavailable`, `ClassificationFailed`), translated to HTTP codes in one module.
- Pydantic models at every API boundary; type hints on every signature.

**File size**
- **No source file over 300 lines** (Python, JS). Check with `find <dir> -name '*.py' -o -name '*.js' | xargs wc -l | sort -n | tail`. Split by responsibility before a file nears 300 lines.

**Testing**
- Unit tests use fakes (`FakeSource`, `FakeSink`, `FakeClassifier`, in-memory ledger), never live Gmail or an LLM. Every phase ends with `pytest` green in `integrations-service/`, `intake-service/` and `backend/`.

**Config and secrets**
- Bootstrap secrets from environment variables only; `.env` gitignored; `.env.example` documents every variable. No credentials are stored in intake (the gateway holds them). No secret, email body or token in logs or error messages.

**Other**
- Webhook handling: verify the internal signature first, then process idempotently.
- Retries with backoff on 429/5xx for reads only. Creation calls are idempotent through `externalId`, so they may be retried safely.
- One log line per processed event with feed, connection, decision and duration, and no content.
- Cursors advance only after the batch is ledgered.
