# PRD: Usage & Cost Accounting

| | |
|---|---|
| Status | Draft, awaiting approval ("Proceed") |
| Owner | hem@neoflo.ai |
| Date | 2026-10-03 |

Terminology: the UI says **Workspace**; the code calls it **Agent** (`agents_collection`). This PRD uses *workspace* for the user-facing concept and *agent* only when referring to code.

---

## 1. Problem

LLM spend is invisible to users. Tokens and USD are recorded for some calls in `llm_calls`, but:

1. Totals are not shown per task, per board, or per workspace.
2. Pricing is a flat input/output rate for all models (`config.py`), so Opus/Haiku costs, cache reads and cache writes are wrong.
3. Board chat (`chat_service.py`) and the dispatch planner (`dispatch.py`) make LLM calls that are never recorded, so totals and budget caps undercount.
4. `llm_calls` rows (which hold full prompts and responses) are purged by TTL (default 90 days). There is no long-term record of how money was spent.
5. Budget checks sum rows in Python on every call (O(n)).

## 2. Goals

- G1. Show USD spent per **task**, per **board**, and per **workspace**, updating live while work runs.
- G2. Capture **every** Anthropic call (task run, sub-agent, board chat, dispatch) with correct per-model pricing, including cache tokens.
- G3. Keep a permanent, immutable, self-describing **historical record** of spend that remains diagnosable years later, even after boards, tasks, or workspaces are deleted or renamed.
- G4. Provide a **history view** and **export** for diagnosing how spend happened over time.
- G5. Isolate accounting from the core product: its own service and its own database. Accounting failures must never break agent runs.
- G6. Budget caps include all call kinds and no longer degrade as data grows.

## 3. Non-goals

- Display in tokens (USD only; the existing unenforced "tokens" budget unit is out of scope).
- Storing prompt or response content in the accounting service (that stays in `llm_calls` with its TTL).
- Billing, invoicing, or charging end users.
- Forecasting or anomaly alerting (possible future work).
- Tracking non-Anthropic providers.

## 4. Users and visibility

| Persona | Can see |
|---|---|
| Workspace member | Task total and board total (USD). |
| Workspace admin | Everything above, plus workspace total, breakdown (by board, task, model, user, call kind), history/time series, ledger drill-down, export. |

Existing call-level data (`llm_calls` traces) remains admin-only.

## 5. Decisions already made

| Topic | Decision |
|---|---|
| Chat and dispatch calls | Included in totals **and** budget caps. |
| Existing `llm_calls` | Backfilled into the ledger, marked as estimated. |
| Display unit | USD only. |
| Visibility | Members: task and board totals. Admins: breakdown, history, export. |
| Architecture | Separate accounting microservice with its own database and collections. |
| Cap enforcement | Stays in the core product (see 7.2). |

## 6. User stories

- As a member, I open a task and see what it has cost so far, ticking up while it runs.
- As a member, I see each board's total cost in its header/card.
- As an admin, I see the workspace's total spend and which boards, tasks, models, and users drive it.
- As an admin, I pick a date range and see spend per day/week/month, then drill into the exact calls behind a spike.
- As an admin, two years later, I investigate a past cost spike on a board that has since been deleted and still see its name, model, tokens, rates, and cost.
- As an admin, I export a date range to CSV/JSON for finance or BI tools.
- As an admin, I set a cap and trust that chat and dispatch calls count toward it.

## 7. Functional requirements

### 7.1 Capture (core product)

- FR-1. Every Anthropic call records: model, input tokens, output tokens, cache-read tokens, cache-creation tokens, web-search count, latency, outcome (`success|error|cancelled`), and the Anthropic request ID.
- FR-2. Call sites to cover: task execution loop (`agent_service.py`), sub-agent loop (`subagent.py`), board chat (`chat_service.py`, via the final message's usage after streaming), dispatch planner (`dispatch.py`). Sub-agent calls without a parent run must still be recorded.
- FR-3. Each call is attributed to: workspace, board, task (when known; chat messages tagged to a task carry the task), run and parent run (when they exist), triggering user, and call kind (`task_run|subagent|chat|dispatch`).
- FR-4. USD is computed in the core at call time from a **per-model price table** (input, output, cache-read, cache-write rates; web-search rate if applicable). Rates are overridable by config/env. Unknown models fall back to a configured default and are flagged `pricedByFallback`.
- FR-5. Core stores one usage event per call in a local **outbox** and delivers it to the accounting service asynchronously (see 7.3). Event IDs are the call ID, making delivery idempotent.
- FR-6. Recording never raises into the caller: a failure to record is logged and retried, and never fails or slows a run.

### 7.2 Budget caps (core product)

- FR-7. Core maintains small running spend counters (per board, per workspace, global), updated atomically with `$inc` when a call is recorded.
- FR-8. `check_exceeded` reads those counters (O(1)) instead of summing `llm_calls`. Caps keep their current semantics and USD unit.
- FR-9. Chat and dispatch spend counts toward the counters and therefore toward caps.
- FR-10. A periodic reconcile job compares core counters with the service's totals and logs drift beyond a threshold.

### 7.3 Accounting service

- FR-11. Runs as a separate process in `accounting-service/` with its own database (ideally its own MongoDB instance) and configuration. Internal-only; authenticated with a service token; never exposed to browsers.
- FR-12. **Ledger** (`usage_ledger`): append-only, **no TTL**, one document per call. Fields:
  - identity: `callId` (unique), `schemaVersion`, `ts`
  - scope: `agentId`, `boardId`, `taskId`, `runId`, `parentRunId`, `callKind`, `userId`
  - name snapshots: workspace name, board title, task text/title at call time
  - usage: `model`, `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheCreationTokens`, `webSearchCount`
  - pricing: rates applied per token type, `usd`, `pricedByFallback`
  - outcome: `latencyMs`, `outcome`, `anthropicRequestId`
  - provenance: `source` (`live|backfill`), `estimated` (bool), `llmCallRef` (link to `llm_calls` while it exists)
- FR-13. The ledger is **immutable**: no update or delete endpoints. Corrections are new compensating entries referencing the original `callId`.
- FR-14. `POST /events` accepts batches and is idempotent on `callId` (duplicates are ignored, not errors). Invalid events are rejected individually without failing the batch.
- FR-15. **Daily rollups** (`usage_daily`): pre-aggregated by day × workspace × board × task × model × user × call kind (sums of tokens and USD, plus call counts). Derived from the ledger, rebuildable on demand, updated on ingest.
- FR-16. Query API (all read-only):
  - `GET /summary`: totals for a scope (task, board, workspace) and optional date range
  - `GET /timeseries`: spend per day/week/month, grouped by board, task, model, user, or call kind
  - `GET /rows`: paginated ledger drill-down with filters
  - `GET /export`: CSV/JSON streaming export for a date range
- FR-17. **Backfill**: a one-time, resumable script reads existing `llm_calls` and posts them through the normal ingest path with `source=backfill`, `estimated=true`, priced at the default model's rates (model is unknown for old rows). Re-running creates no duplicates.
- FR-18. Rollup rebuild command and a ledger-vs-rollup consistency check.

### 7.4 Core API (proxy)

- FR-19. Core exposes usage endpoints that proxy to the service and apply existing session auth and workspace membership checks:
  - member-allowed: task total, board total
  - admin-only: workspace total, breakdown, time series, rows, export
- FR-20. If the service is unavailable, core returns the live counter values where available and a clear "history unavailable" state otherwise; it never errors the whole page.

### 7.5 UI

- FR-21. **Task detail modal:** cost badge (USD) in the header, updating live during a run.
- FR-22. **Board header/card:** board total USD.
- FR-23. **Admin Console:** new **Usage** tab with:
  - workspace total for a selectable range
  - time-series chart (day/week/month) with group-by (board, task, model, user, call kind)
  - breakdown table; drill-down from any bar/row to ledger rows
  - export button
  - deleted boards/tasks shown using their name snapshots, marked "deleted" when applicable
  - an "estimated" marker for backfilled rows
- FR-24. Live updates: the existing `llmCall` WebSocket event gains `usd`, token fields, and running totals; `board-card-status.js` routes them to the badges.
- FR-25. Amounts are formatted consistently as USD, with sub-cent precision for small values (for example `$0.0042`).

## 8. Non-functional requirements

- NFR-1. **Durability:** no usage event is lost if the service is down. The outbox retries with backoff, and delivery resumes on recovery. Failures to enqueue are logged and written to a local fallback file.
- NFR-2. **Performance:** recording adds negligible latency to an LLM call. Cap checks are O(1). Summary queries over years use rollups and return within 1 second for typical workspaces.
- NFR-3. **Consistency:** UI totals are eventually consistent (seconds). Live running-task totals come from core counters.
- NFR-4. **Retention:** ledger and rollups retained indefinitely. `llm_calls` retention is unchanged.
- NFR-5. **Size:** about 0.5 KB per ledger row, so around 500 MB per million calls. No prompt or response content stored.
- NFR-6. **Security:** service reachable only from core (internal network/loopback plus service token). Admin-only endpoints enforced in core. No PII beyond user ID and names already in the product.
- NFR-7. **Operability:** health endpoint, structured logs, metrics for outbox depth and ingest lag, and an alert condition for outbox age above a threshold.
- NFR-8. **Versioning:** events and the ledger carry `schemaVersion`. The service accepts the current and the previous version.
- NFR-9. **Code standards (CLAUDE.md):** at most 300 lines per file, SOLID, and OOP best practices. The service is split into focused modules (ingest, ledger, rollups, query, export, backfill) behind a repository interface so the storage engine can be swapped later (for example, Postgres).
- NFR-10. **Backups:** the accounting database must be covered by backups. This is an operational requirement, documented in the deploy notes.

## 9. Architecture overview

```
 LLM call sites (task, subagent, chat, dispatch)
        │  usage + price snapshot
        ▼
  Core: tracing.record_call ──► llm_calls (content, TTL)
        │                    ├─► spend counters ($inc) ──► cap checks, live totals
        │                    └─► usage_outbox
        ▼ (async worker, retries, idempotent)
  Accounting service ──► usage_ledger (immutable, no TTL)
        │            └─► usage_daily (rollups)
        ▲
  Core proxy endpoints (auth, membership, admin gating) ◄── Browser UI
```

## 10. Edge cases

- Task or board deleted: ledger rows remain, name snapshots keep them readable.
- Task moved between boards (`Tasks can move between boards`): new calls attribute to the new board. Past rows keep their original board. Task totals sum across boards by `taskId`, so a task's lifetime total stays correct, while board totals reflect where the spend occurred.
- Price change: past rows keep the rates they were charged at. New rows use new rates.
- Unknown or new model: priced at the fallback rate and flagged, so admins can fix the table and optionally recompute using the stored token counts.
- Cancelled or errored calls that still consumed tokens: recorded with their `outcome`.
- Clock or ordering skew: ordering uses ledger `ts`. Rollups are keyed by UTC day.
- Duplicate delivery or backfill re-run: ignored via unique `callId`.
- Service down for an extended period: the outbox grows. Alert on age. It drains on recovery.
- Chat message with no task: attributed to the board only (task is null).

## 11. Rollout plan

1. **Backfill first:** ship the service ingest plus the backfill script before anything else, because `llm_calls` rows are expiring now.
2. Per-model price table plus capture of model and cache tokens.
3. Record chat and dispatch calls.
4. Outbox, counters, O(1) cap checks, and the reconcile job.
5. Core proxy endpoints.
6. UI: task badge, board total, Admin Console Usage tab, export.
7. Run a reconcile pass and verify that totals match for a sample of workspaces before announcing.

Each step is independently shippable and reversible.

## 12. Success metrics

- 100% of Anthropic calls produce a ledger row (reconcile drift under 1%).
- Zero agent-run failures caused by accounting.
- Cost shown for a finished task equals the sum of its ledger rows.
- An admin can answer "what drove spend last quarter?" in the UI without database access.
- Cap checks stay constant-time as call volume grows.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Service outage loses data | Local outbox with retry and fallback file. |
| Counters and ledger drift | Idempotent events, periodic reconcile, rebuild tooling. |
| Price table goes stale | Configurable table, `pricedByFallback` flag, recompute from stored tokens. |
| Chat now counts toward caps, so users may hit caps sooner | Called out in release notes. Caps are unchanged. Only the accounting is more accurate. |
| Backfilled costs are approximate | Marked `estimated`, shown as such in the UI. |
| Extra service to operate | Single small FastAPI process, health and metrics, documented deploy. |

## 14. Open items

- Deployment mechanism (Docker, process manager, or local only) so the service can be wired into it.
- Confirm the current per-model prices to seed the table, since rates change and this PRD does not fix them.
- Whether to add optional periodic export of the ledger to cold storage (file or object store).
- Whether the accounting database should live on a separate MongoDB instance from day one (recommended) or a separate database on the existing one.
