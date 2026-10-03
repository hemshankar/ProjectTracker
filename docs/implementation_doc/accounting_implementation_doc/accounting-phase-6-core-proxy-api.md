# Phase 6: Core Proxy API

PRD: FR-19, FR-20, section 4 (visibility). The browser never talks to the accounting service. The core exposes usage endpoints, applies its existing auth, and calls the service with `X-Internal-Key`.

## Technical Design

### Authorization (reuse what exists)

`backend/app/dependencies.py` already provides the guards this phase needs. No new auth model:

| Need | Guard |
| --- | --- |
| Task total, board total (members) | `require_board_access("viewer")`. Anyone who can view the board can see its cost |
| Workspace total, breakdown, history, rows, export, outbox health (admins) | `require_agent_admin()` |

The core derives `agentId` from the path or the board document and **always** sends it to the service. It never takes it from a query parameter, so a caller can't ask the service for another workspace's data (the service enforces `agentId` is required, Phase 2).

Do not widen existing endpoints. The existing admin-only `/llm-calls` stays admin-only.

### Endpoints

Added in a new router `backend/app/routers/usage.py` (HTTP only), backed by a `UsageService` (one concern: translate and enrich). Mounted in `main.py`.

| Method & path | Guard | Returns |
| --- | --- | --- |
| `GET /api/boards/{board_id}/usage` | board viewer | `{usd, calls, live}` for the board |
| `GET /api/boards/{board_id}/tasks/{task_id}/usage` | board viewer | `{usd, calls, inputTokens, outputTokens}` for the task (lifetime, across boards) |
| `GET /api/agents/{agent_id}/usage/boards` | agent member | batch of board totals for the board list: `{boardId: usd}` for boards the caller can see |
| `GET /api/boards/{board_id}/usage/tasks` | board viewer | batch of task totals `{taskId: usd}` for that board's tasks (for badges on cards) |
| `GET /api/agents/{agent_id}/usage/summary` | agent admin | workspace total, optional `since`/`until` |
| `GET /api/agents/{agent_id}/usage/timeseries` | agent admin | `granularity`, `groupBy`, range |
| `GET /api/agents/{agent_id}/usage/breakdown` | agent admin | top-N by `dimension`, range |
| `GET /api/agents/{agent_id}/usage/rows` | agent admin | paginated ledger rows (keyset cursor) |
| `GET /api/agents/{agent_id}/usage/export` | agent admin | streamed CSV/JSONL |
| `GET /api/agents/{agent_id}/usage/health` | agent admin | outbox pending count/oldest age + service reachability |

**Member visibility rule:** members only ever get **totals** (single numbers per board/task). No model, user, token, or call-kind breakdown is exposed through member endpoints. The response models for member endpoints physically don't contain those fields, so a later change can't leak them by accident.

**Board visibility:** the batch endpoints filter to boards the caller can see (reuse the same visibility query used by the board list / the agent WebSocket's visible-board set) so totals for boards shared with others aren't exposed.

### Enrichment in the core

- **Deleted flag:** for `breakdown`/`rows`, the service returns snapshots only. `UsageService` checks which board/task ids still exist (one `$in` query) and adds `deleted: true` for those that don't, so the UI can mark them.
- **Live numbers:** totals for **running** work come from `SpendCounters` (Phase 5) when the service lags. Rule: `usd = max(service_total, counter_total)` is **not** safe (different scopes). Instead, task and board totals shown in the UI are the service total **plus** the sum of outbox events for that scope that are still `pending`/`sending` (one indexed query on `usage_outbox`). That is exactly the not-yet-ingested delta, and it is zero when healthy. Implemented in `UsageService.with_pending(scope, service_total)`.

### Failure handling (FR-20)

`UsageQueryClient` (Protocol) with `HttpUsageQueryClient`: short timeout (3s), no retries on reads. If the service is unreachable or slow:
- Totals endpoints return `200` with `{usd: <pending-outbox sum or counter>, "stale": true}` where a local value exists (board totals can fall back to `spend_counters`). For task totals with no local source they return `{usd: null, stale: true}`.
- History endpoints (`timeseries`/`breakdown`/`rows`/`export`) return `503 {"error": {"code": "accounting_unavailable", ...}}`, which the UI renders as "History unavailable".
- The error never propagates into board loading or task execution. Usage endpoints are called separately from the board payload.

### Caching

Totals batch endpoints get a 5-second in-process TTL cache keyed by `(scope, ids, caller-visibility-hash)` to absorb the board list refreshing. Cache is skipped for admin history endpoints. Nothing is cached across callers with different visibility.

### Export proxying

`export` streams through the core (chunked `StreamingResponse`) rather than buffering. It re-checks admin on the core side, passes through `Content-Disposition`, and caps concurrent exports per workspace (default 2) with a `429`.

### Files

```
backend/app/routers/usage.py            HTTP only (< 200 lines; split into usage_member.py / usage_admin.py if it grows)
backend/app/services/usage_service.py   authz-aware orchestration, pending delta, deleted flag
backend/app/accounting/query_client.py  UsageQueryClient Protocol + HttpUsageQueryClient
backend/app/models_usage.py             Pydantic response models (member models ⊂ admin models)
```

## Implementation Plan

- [ ] `models_usage.py`: separate `MemberTotal` and `Admin*` response models (members' model has no breakdown fields)
- [ ] `query_client.py` (Protocol + HTTP client, timeouts, error mapping to `AccountingUnavailable`)
- [ ] `usage_service.py`: totals with pending-outbox delta, deleted flag, visible-board filtering, export concurrency limit
- [ ] `routers/usage.py` with the guards above; register in `main.py`
- [ ] Tiny TTL cache helper for batch totals
- [ ] Error handler mapping `AccountingUnavailable` → structured 503
- [ ] Document each endpoint in the project's API docs/README section
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests (`backend/tests/test_usage_api.py`, with a fake `UsageQueryClient`)

- **Authz matrix:** non-member → 403/404 everywhere. Viewer → board/task totals only, 403 on every admin endpoint. Member (non-admin) → totals and board batch, 403 on admin. Admin → all.
- **No leakage:** a member's response JSON contains no `model`, `userId`, token, or `callKind` keys. Asserted by schema and by raw-body check.
- **Tenant isolation:** the service is always called with the path-derived `agentId`. A request for board B (agent 2) via agent 1's path is rejected. A forged `agentId` query param is ignored.
- **Batch visibility:** a board the caller can't see isn't in the batch.
- **Pending delta:** with 3 pending outbox rows for a task, the task total = service total + their sum. With none, equals the service total.
- **Service down:** totals → 200 with `stale`, history → 503 with structured error, the board list endpoint is unaffected.
- **Deleted flag** set correctly for a removed board/task.
- **Export:** streams in chunks, headers passed through, concurrent-export limit returns 429.

## Verification

1. As a **viewer** on a board, call `/api/boards/{id}/usage` → a number. Call `/api/agents/{id}/usage/timeseries` → 403.
2. As an **admin**, call the same endpoints and confirm that the totals match the Phase 2 service numbers for the same scope.
3. Run a task and re-poll the task total: it increases within a few seconds (pending delta first, then service).
4. Stop the accounting container: totals respond with `stale: true`, history returns the 503 error shape, and the board page and chat still work.
5. Delete a board with spend: the admin `breakdown` still lists it, flagged `deleted: true`, with its old title.
6. Export a month as CSV through the core and compare the row count with the service's own `/internal/rows`.

## Rollback

Remove the router include in `main.py`. No data or schema changes in this phase.

## Inputs Needed From You

- Confirm that **board viewers** (read-only shares) may see cost totals. The PRD says "members"; this plan maps that to anyone who can open the board. If viewers should be excluded, change the guard to `editor` on the member endpoints.
