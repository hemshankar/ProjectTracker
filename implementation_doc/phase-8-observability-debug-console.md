# Phase 8: Observability & Debug Console

## Technical Design

**`llm_calls` (supersedes Phase 5's `spend_ledger` — same one-row-per-call shape, now capturing full detail by default)**

Fields: `_id`, `agentId`, `boardId`, `taskId`, `runId`, `parentRunId` (nested sub-agent/delegated runs), `systemPrompt`, `messages` (the full request sent to the model), `response` (text + any tool_use blocks), `toolCalls` (name, params, result per tool invoked), `usd`, `inputTokens`, `outputTokens`, `latencyMs`, `ts`.

Detailed capture is the default, not opt-in — full bodies are stored as-is. Encrypting this collection at rest is real future work, explicitly **out of scope for every phase in this plan**; noting it here so it isn't mistaken for already covered. A TTL index (default 90 days, configurable per Agent in Config) keeps it from growing unbounded — it's debug data, not the permanent record; `audit_log` stays the permanent one.

**Agent Admin Console (new frontend surface)**

Three tabs, replacing the standalone Settings page from Phase 2/5:
- **Config** — tool connections, budget, invites (exactly what Settings held before; just relocated under this console).
- **Activity** — a filterable view over `audit_log` (board / task / actor / action / time range), showing before/after values.
- **Traces** — a filterable view over `llm_calls`, drillable per `task_run` into each call's full system prompt, request messages, tool calls/results, cost, and latency; nested sub-agent/delegated runs render as a tree via `parentRunId`.

Access: Agent Admin only, scoped to that Agent's own data.

**Board-level Activity view (lighter, for any collaborator)**

A per-board "Activity" tab (viewer or editor access is enough) showing just that board's slice of `audit_log` — no raw prompts, no cross-board visibility. It's a strict subset of the Admin Console's Activity tab, same query with a `boardId` filter, so it isn't a separate implementation.

**Live tail**

Reuses the SSE channel introduced in Phase 3 (`GET /api/boards/{id}/events`), extended to also push a lightweight `llm_call` summary event (tool, status, cost) as each one happens for anything currently `running`. The Traces tab, opened on a currently-processing task, subscribes to that channel and appends new entries live instead of only showing history after the fact. Clicking a live entry still fetches its full detail (prompt/response bodies) from `llm_calls` on demand — streaming full prompt bodies through the same status channel that glow and board-status also ride would bloat every other consumer of that stream that doesn't need them.

## Implementation Plan

- [ ] Rename/expand `spend_ledger` → `llm_calls` with full request/response/tool-call fields; point Phase 5's budget-check helper at this collection's `usd` field
- [ ] TTL index on `llm_calls` (default 90 days, configurable per Agent in Config)
- [ ] `GET /api/agents/{id}/audit` (filterable) + `GET /api/agents/{id}/llm-calls` (filterable, drillable) endpoints, Agent-Admin gated
- [ ] `GET /api/boards/{id}/audit` — the lighter per-board Activity endpoint, board-viewer gated
- [ ] Extend the Phase 3 SSE channel with `llm_call` summary events
- [ ] Frontend: Agent Admin Console shell with Config/Activity/Traces tabs (Config = today's Settings page, moved under this shell)
- [ ] Frontend: per-board Activity tab
- [ ] Frontend: Traces tab live-tail subscription + on-demand full-detail fetch per call
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): the Activity/Traces query logic lives in its own `services/observability.py`, not bolted onto `services/agents.py`; no file over 300 lines

## Inputs Needed From You

None for this phase's engineering work. One future decision, not needed now: when at-rest encryption of `llm_calls` is eventually added, that will need a key-management decision — explicitly out of scope here.

## UI Verification

1. Start a board, open the Agent Admin Console's Traces tab while it's still running — confirm new LLM call entries appear live as the task progresses, without refreshing the page.
2. Click into a completed call — confirm the full system prompt, request messages, tool call arguments, tool result, and response text are all visible verbatim.
3. Open the Config tab — confirm it's the same tool/budget/invite settings from earlier phases, now under one console rather than a separate page.
4. Open the Activity tab, filter by a specific board and by actor=human — confirm only that board's human-made changes show, with before/after values.
5. As a board viewer (not an Agent Admin), confirm you can open that board's own lighter Activity tab, but the full Admin Console (Config/Traces) is not accessible.
6. Confirm a task run from Phase 6's multi-agent delegation shows its sub-agent/delegated calls nested under the parent run in the Traces tree.
