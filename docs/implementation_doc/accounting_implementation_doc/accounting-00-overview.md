# Usage & Cost Accounting: Technical Design & Implementation Plan

Companion to the [Usage & Cost Accounting PRD](../../PRD-usage-accounting.md). One document per phase, each with a technical design, an implementation checklist, tests, and a verification pass. Format mirrors the [integrations docs](../integration_docs/integrations-00-overview.md).

| Phase | Focus | PRD sections |
| --- | --- | --- |
| [Phase 1: Service, Ledger & Backfill](accounting-phase-1-service-ledger-backfill.md) | Stand up `accounting-service`, the immutable ledger, idempotent ingest, and backfill existing `llm_calls` **first** (they are expiring) | FR-11–14, FR-17 |
| [Phase 2: Rollups, Query & Export](accounting-phase-2-rollups-query-export.md) | Daily rollups, summary/time-series/rows/export APIs, rebuild tooling | FR-15, 16, 18 |
| [Phase 3: Pricing & Full Capture](accounting-phase-3-pricing-and-full-capture.md) | Per-model price table, model + cache tokens, name snapshots, usage event builder | FR-1, 3, 4 |
| [Phase 4: Chat & Dispatch Capture](accounting-phase-4-chat-dispatch-capture.md) | Record the two currently unrecorded call paths | FR-2 |
| [Phase 5: Outbox, Counters & Caps](accounting-phase-5-outbox-counters-caps.md) | Reliable delivery to the service, O(1) spend counters, caps include all calls | FR-5–10 |
| [Phase 6: Core Proxy API](accounting-phase-6-core-proxy-api.md) | Auth-gated usage endpoints in the core | FR-19, 20 |
| [Phase 7: UI](accounting-phase-7-ui.md) | Task badge, board total, Admin Console Usage tab, live updates | FR-21–25 |
| [Phase 8: Reconcile & Launch](accounting-phase-8-reconcile-launch.md) | Drift checks, operational alerts, verification, release | FR-10, 18, NFR-7, success metrics |

The phases follow the PRD's rollout plan (section 11), with one change: the PRD's step 1 ("service ingest plus backfill") is split into Phases 1 and 2, because the query layer is needed before the proxy (Phase 6) but is not urgent for preserving data. Each phase is independently shippable and reversible.

## Decisions carried over from the PRD

- USD only. Chat and dispatch calls count toward totals **and** caps.
- Members see task and board totals. Admins see everything else.
- Separate microservice, separate database. **Cap enforcement stays in the core.**
- Existing `llm_calls` are backfilled. The ledger is immutable and has no TTL.

## What is already in the codebase (grounding)

| Area | Today | File |
| --- | --- | --- |
| Per-call record | `record_call` writes one `llm_calls` row (tokens in/out, `usd`, content) and publishes an `llmCall` summary event | `backend/app/execution/tracing.py` |
| Cost | Flat `usd_for_usage(input, output)` using two global rates | `backend/app/services/budget_service.py`, `config.py:36-37` |
| Caps | `check_exceeded` sums `llm_calls.usd` in Python per board, agent, and global. Because `llm_calls` has a TTL (`database.py:46`), **spend silently falls out of caps as rows expire** | `budget_service.py:19-95` |
| Unrecorded calls | Board chat (`chat_service.py:98`) and dispatch planner (`dispatch.py:86`, hard-coded `claude-haiku-4-5`) | |
| Run attribution | `task_runs` has no triggering user | `execution/context.py` |
| Precedent for a sidecar | `integrations-service/` (FastAPI, Mongo, `X-Internal-Key`, `container.py` composition root, docker-compose entry) | `integrations-service/app/` |
| Realtime | Per-agent WebSocket delivers `llmCall`; `board-card-status.js:97` routes it | |

## Target architecture

```
 call sites: task loop / sub-agent / chat / dispatch
        │
        ▼
 core: UsageRecorder  ──► llm_calls (content, 90d TTL, unchanged)
        ├──────────────► spend_counters ($inc)  ──► check_exceeded (O(1))
        └──────────────► usage_outbox ──► OutboxWorker ──HTTP, X-Internal-Key──►
                                                    accounting-service
                                                      ├─ usage_ledger  (append-only, no TTL)
                                                      └─ usage_daily   (rollups)
 browser ◄─ core proxy (auth, membership, admin gating) ◄─ accounting-service query API
```

## Engineering Standards

Applies to every phase. Each phase's Implementation Plan has a checklist item pointing back here. These restate `CLAUDE.md` and the integrations service's standards.

**File size**
- No source file over 300 lines (docs included, as a house rule). A concern named in a phase is a package, not necessarily one file.

**SOLID**
- **Single Responsibility:** routers parse and validate HTTP and call one service. Each service owns one concern (ingest, rollups, queries, export). Core-side: `UsageRecorder` builds events, `OutboxWorker` delivers them, `SpendCounters` enforces caps. None does two jobs.
- **Open/Closed:** prices are data (`pricing.py` table), not branches. A new model or token type is a table entry. A new `callKind` is an enum member plus the call site, with no changes to ingest or rollups.
- **Liskov:** every storage implementation of `LedgerRepository` behaves identically (idempotent insert, ordered reads), so Mongo can later be swapped for Postgres.
- **Interface Segregation:** narrow Protocols. The core's `UsageSink` (enqueue one event) is separate from `UsageQueryClient` (read totals). Backfill depends on neither concrete client.
- **Dependency Inversion:** call sites depend on `UsageRecorder`, never on the outbox or HTTP client. The service's routers depend on service interfaces wired in one `container.py`, the only file naming concrete classes (same pattern as `integrations-service/app/container.py`).

**OOP**
- Immutable value objects: `UsageEvent`, `PriceRates`, `Money` (or a typed USD wrapper). No loose dicts passed across module boundaries.
- Composition over inheritance. Encapsulate collection access inside repositories so nothing else touches Mongo directly.
- Type hints on all signatures. Pydantic models at every HTTP boundary.

**Reliability rules (apply everywhere)**
- Recording must never raise into a run. Wrap at the `UsageRecorder` boundary, log, and fall through.
- Ingest is idempotent on `callId`. Every writer and every retry relies on it.
- The ledger is append-only. No code path updates or deletes ledger documents (enforced by the repository interface having no such methods, plus a test).
- Config only via environment variables. No secrets in code.

**Testing conventions**
- Backend tests: `backend/tests/` with pytest (existing `pytest.ini`). Service tests: `accounting-service/tests/` with its own `pytest.ini`, same layout as `integrations-service/tests`.
- Use fakes via Protocols (in-memory repository, fake sink). No test needs a live service or a live Anthropic call.
- Each phase lists its tests. A phase isn't done until they pass.

## Cross-phase dependencies

```
P1 ──► P2 ──────────────────────────────► P6 ──► P7
 └──► P3 ──► P4 ──► P5 ───────────────────┘       │
                     └────────────────────────────► P8
```

- P5 needs the event schema from P1 and the event builder from P3.
- P6 needs the query API from P2 and live counters from P5.
- P8 needs everything.

## Time-sensitive item (do before Phase 1 ships)

`llm_calls` rows are purged by TTL (default 90 days) and every day of delay loses history that cannot be reconstructed. As a stopgap, raise retention before Phase 1 is deployed: set `LLM_CALL_RETENTION_DAYS` higher in the backend env. This only affects rows written **after** the change. Rows already stamped with an `expiresAt` keep it. To extend those, one-time update `expiresAt` on existing rows (a documented one-line Mongo update in Phase 1's checklist). Do this deliberately and note it, because it changes retention.
