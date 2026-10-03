# Phase 2: Guardrails & Cost

Goal: make auto-create safe to leave on. Add the kill switch, daily caps, a clear auto-created marker and review path, and a cost budget routed through the accounting service. After this phase, auto-create can be enabled on real agents.

## Technical Design

### Guardrails (all enforced in the intake service, backed by backend checks)

| Guardrail | Where enforced | Behavior |
| --- | --- | --- |
| Kill switch | intake scheduler + backend endpoint | Agent `intake.enabled=false` or feed `enabled=false` stops runs within one cycle; backend rejects creates when disabled (defense in depth) |
| Daily cap | `caps_service` | Per feed `caps.dailyMax` (default 25) and agent `intake.dailyCap` (default 50). Over-cap events are ledgered `capped`, no create |
| Per-run cap | `runner` | `caps.perRunMax` (default 10) prevents a burst after downtime |
| Required filters | `feed_service` | Already enforced on write in Phase 1; also re-checked at run time so a hand-edited document cannot bypass |
| Auto-created marker | backend task model | `source.autoCreated=true`, auto-created label, account label and message link (from Phase 1) plus a review view |
| Cost budget | accounting integration | Intake LLM usage (Phase 3) and event counts are recorded; budget exhaustion stops classification and creation |
| Auto-pause on failure | `scheduler` | After N consecutive failed runs (default 5) the feed pauses with `state.lastError`; token expiry shows "reconnect needed" |

### Caps service (`services/caps_service.py`)
- Counts today's `created` entries from the ledger (`feedId`, `agentId`, UTC day boundary, or the agent's timezone if configured in settings). `check(feed) -> CapDecision(allowed, reason, remaining)`.
- Counting from the ledger (not an in-memory counter) keeps it correct across restarts and multiple instances. Index `(feedId, decision, createdAt)`.
- A one-time `cap_reached` notice per feed per day is written (a ledger entry of kind `notice`) and forwarded to the backend, which raises a standard agent notification if the notification mechanism exists. Verify what the app uses today before wiring; if there is none, just surface it in the feed status.

### Cost budget
- Phase 2 builds the plumbing: `UsageReporter` protocol and `HttpUsageReporter` posting to `accounting-service` with `{agentId, feedId, kind:"intake", model, inputTokens, outputTokens, costUsd}`. Check the accounting service's real ingest contract (`accounting-service/` and `backend/app/accounting/`) before coding; follow its existing client pattern rather than inventing a payload.
- `BudgetGate` protocol: `allow(agent_id) -> bool`, backed by the accounting/budget check used for boards (`budget_service.check_budget`) with a dedicated intake budget (`intake.dailyBudgetUsd`, new agent setting). Fail-closed when the budget service is unreachable: events are ledgered `capped` with reason `budget_unavailable`, not created blindly.
- The rule-based decider has no LLM cost, so the gate is a no-op until Phase 3, but is already wired and tested.

### Backend changes
- `models_settings.py` / `models_intake.py`: `IntakeSetting` gains `dailyCap`, `dailyBudgetUsd`, `defaultPerFeedCap`.
- `POST /internal/intake/tasks` re-validates enabled state and agent-wide daily count (cheap query on tasks with `source.autoCreated` and today's date) as a second line of defense against a buggy intake instance.
- **Review path for auto-created tasks:** a task list filter `?autoCreated=true` and a bulk delete endpoint `POST /api/boards/{id}/tasks/bulk-delete` restricted to auto-created tasks (verify whether bulk delete already exists and reuse it). The existing undo service should cover deletes; check `undo_service` behavior for bulk operations.
- Audit: every capped, paused or disabled transition writes an audit entry (`entity_type="feed"`).

### Feed state machine
`active -> paused_error` (auto, after N failures) `-> active` (manual resume); `active <-> paused` (manual); `any -> disabled` when the agent toggle is off or the owner leaves. A single `FeedStatus` enum plus a `transition(feed, event)` function keeps this in one place.

### Offboarding rule (from PRD FR15)
Backend emits an event/call when a member is removed from an agent; intake disables that member's personal feeds. If the backend has no hook for member removal, add a call in the member-removal path of `agents_service` to `POST /internal/intake/owner-removed`.

## Implementation Plan
- [ ] `FeedStatus` and `transition()` with unit tests for every transition
- [ ] `caps_service` (feed day cap, agent day cap, per-run cap) with ledger indexes
- [ ] Runner integration: caps checked before sinking; `capped` ledger entries; `cap_reached` notice once per day
- [ ] Scheduler: auto-pause after N failures, resume endpoint, "reconnect needed" mapping for gateway `NotConnected`/expired
- [ ] `UsageReporter` and `BudgetGate` protocols, HTTP implementations matching the accounting contract, fakes
- [ ] Backend: new intake settings fields, endpoint re-validation, `autoCreated` filter, bulk delete of auto-created tasks (reuse existing if present)
- [ ] Owner-removed hook and personal feed disabling
- [ ] Audit entries for state transitions
- [ ] Tests: cap exactly at limit, cap resets next day, restart does not reset the count, budget unavailable fails closed, auto-pause then resume, backend rejects when disabled even if intake sends
- [ ] Verify no file over 300 lines

## Actions Required From You
1. Confirm default caps (per feed 25/day, agent 50/day, per run 10) and the failure threshold (5).
2. Confirm the intake daily budget default (suggest a small value such as 2 USD/day per agent) and whether it should share the agent's existing budget or be separate.
3. Confirm the day boundary: UTC, or each agent's timezone (does the app store one?).
4. Tell me how admins are normally notified in the app (notification center, email, none) so the cap notice uses the existing mechanism.
5. Provide the accounting ingest contract if it differs from what I find in the repo.

## Development Best Practices
- **SRP:** caps, budget, status transitions, and usage reporting are four separate classes; the runner only asks them yes/no questions.
- **DIP/ISP:** `BudgetGate` and `UsageReporter` are tiny protocols with fakes; the runner never imports `httpx` or the accounting client.
- **Fail closed** for anything that can create tasks or spend money; fail open only for read-only status endpoints.
- **Defense in depth:** the backend enforces enabled state and an agent-wide cap independently of intake.
- **No in-memory counters** as the source of truth; derive from the ledger.
- **Observability:** every `capped`/`paused` decision includes a reason string that the admin view (Phase 4) can show.
- **300-line rule:** `runner.py` grows with each guardrail; extract `guard_chain.py` (an ordered list of `Guard` objects returning allow/deny) instead of nested ifs.

## UI Verification
1. Set a feed's daily cap to 2. Send 4 matching emails: exactly 2 tasks appear; the ledger shows 2 `capped`; the feed status shows "cap reached".
2. Restart intake: the cap count persists (no extra tasks).
3. Toggle the feed off, then send a match: nothing is created. Toggle on: processing resumes.
4. Toggle **Enable intake** off at the agent level: all feeds stop; the backend also rejects a manual `curl` to the internal create endpoint.
5. Disconnect the Gmail connection: the feed auto-pauses with "reconnect needed" after the threshold; reconnecting and resuming works.
6. Filter the board by **auto-created**; select all and bulk delete; use undo to restore.
7. Remove a member who owns a personal feed: that feed becomes disabled; shared feeds are unaffected.
8. Stop the accounting service: matching events are `capped` with `budget_unavailable`; no tasks are created. Start it again and processing resumes.
