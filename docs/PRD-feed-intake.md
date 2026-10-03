# PRD: Feed Intake — Auto-Creating Tasks and Boards from Connection Feeds

Status: Draft for review · Owner: hem@neoflo.ai · Date: 2026-10-03

## 1. Summary

Add a separate **intake-service** microservice that watches feeds from connected tools (Gmail first, Slack next), decides which events matter, and asks the backend to create or update tasks and boards. Agents opt in with an **Enable intake** toggle. The existing UI stays as-is; created tasks appear through the existing websocket updates. Only a small settings panel for feeds is added.

## 2. Problem

Work arrives in inboxes and chat channels, and users copy it into boards by hand. Agents can call integration tools on demand, but nothing reacts to incoming events. Users lose requests, or spend time on triage that software can do.

## 3. Goals and Non-Goals

### Goals
- G1. Ingest events from connected tools automatically and turn relevant ones into tasks (or boards) with no manual step.
- G2. Support **multiple connections of the same tool per agent** (for example two Gmail accounts).
- G3. Support **shared** (agent-level) and **personal** (member-owned) connections.
- G4. Keep intake isolated: its own service, data store collections, deploy, and failure domain.
- G5. Make it safe to auto-create: filters, caps, kill switch, cost budget, provenance.
- G6. Make adding a new source (Slack, Jira, ...) a plugin, with no pipeline changes.

### Non-Goals
- Multi-step workflow/automation engine. After creation, the existing agent execution loop handles the task.
- Two-way sync (updating the email when the task changes).
- Draft/approval mode for v1 (auto-create only; see Future Work).
- Feeds shared across agents. Two agents wanting one inbox create two feeds.
- UI redesign.

## 4. Terminology

| Term | Meaning in this codebase |
|---|---|
| **Agent** | The tenant/workspace. Owns members, boards, settings, budgets. Intake is scoped to an agent. |
| **Connection** | An authenticated account for a tool (for example work@acme.com on Gmail), held by the integrations service. |
| **Feed** | A configured subscription: one connection + one source (inbox, label, channel) + rules + target. |
| **Event** | A normalized item from a feed (an email, a Slack message). |
| **Intake decision** | Outcome for an event: ignore, append to task, create task, create board. |

## 5. Users and Stories

- **Agent admin:** enables intake, connects shared accounts, creates feeds on shared connections, sets caps and budget.
- **Member:** connects a personal account, creates feeds on it, sees tasks it produced.
- U1. As an admin I connect support@ as a shared Gmail and route label "Support" to the Support board.
- U2. As a member I connect my own Gmail and have invoices become tasks on my board only.
- U3. As a user with two Gmail accounts I get both feeds, and each task shows which account it came from.
- U4. As an admin I can pause a feed instantly, cap daily creation, and bulk-review auto-created tasks.
- U5. As an admin I can see what was ingested, skipped, and why.

## 6. Scope: Phases

| Phase | Deliverable |
|---|---|
| 0 | Gateway change: multi-connection per agent+tool, owner, visibility |
| 1 | intake-service scaffold, Gmail source, normalizer, filters, task sink, ledger and dedup, agent toggle |
| 2 | Guardrails: kill switch, daily cap, auto-created marker, cost budget via accounting |
| 3 | LLM classifier/extractor, thread-to-task appending, feed settings UI |
| 4 | Slack source, board creation, admin ledger view |

## 7. Architecture

```
 Gmail/Slack ──(Composio triggers / polling)──▶ integrations-service (gateway)
                                                      │ events (webhook / pull API)
                                                      ▼
                                              intake-service
   FeedSource ▶ Normalizer ▶ Filter ▶ Classifier(LLM) ▶ Dedup/Ledger ▶ TaskSink
                                                      │ internal HTTP (X-Internal-Key)
                                                      ▼
                                                  backend (monolith)
                                   permissions · audit · websockets · budgets
```

### 7.1 Services and responsibilities
- **integrations-service** (existing): owns connections and credentials, executes provider actions, receives provider webhooks, exposes events to intake. It gains multi-connection support (Phase 0).
- **intake-service** (new): feed configuration, scheduling, polling/consuming, normalization, filtering, classification, dedup, ledger, caps. It holds no board data and writes no board collections directly.
- **backend** (existing): the only writer of tasks and boards. Gains an internal endpoint for intake plus the agent toggle and feed-settings proxy endpoints.
- **accounting-service** (existing): receives LLM usage from intake for budgeting.
- **frontend** (existing): unchanged apart from the settings panel (section 12).

### 7.2 Module layout (intake-service, each file at most 300 lines)
```
intake-service/app/
  main.py, config.py, database.py, security.py
  sources/         base.py (FeedSource protocol), gmail.py, slack.py (phase 4), registry.py
  pipeline/        normalizer.py, filters.py, classifier.py, dedup.py, runner.py
  sinks/           task_sink.py (backend HTTP client)
  services/        feed_service.py, ledger_service.py, caps_service.py, scheduler.py
  routers/         feeds.py, health.py, internal.py
  models/          feed.py, event.py, ledger.py
```
Composition over inheritance: the runner receives a `FeedSource`, `Filter`, `Classifier`, `Sink` by injection (testable with fakes, consistent with the injectable `IntegrationsClient` already in the backend).

### 7.3 FeedSource interface
```
list_sources(connection)  -> selectable sources (labels, channels)
fetch(feed, cursor)       -> (raw_events, new_cursor)     # polling path
parse_webhook(payload)    -> raw_events                    # push path
normalize(raw)            -> Event
```
Adding a provider means implementing this once and registering it.

## 8. Phase 0: Integrations Gateway Changes

Today connections are keyed by `(agentId, toolType)` (see `integrations_client.py`: `list_connections(agent_id)`, `disconnect(agent_id, tool_type)`), so a second Gmail on one agent collides with the first.

Changes:
- New connection identity: `connectionId` plus a human `label` (account email). `(agentId, toolType)` stays as a lookup that resolves to the agent's **default** connection, so existing tool callers keep working unchanged.
- New fields: `ownerUserId` (null means shared), `visibility` (`agent` or `owner`).
- Gateway API additions:
  - `POST /connections/session` accepts optional `ownerUserId`, `label`.
  - `GET /connections/{agentId}` returns all connections, each filtered by the caller's visibility.
  - `DELETE /connections/{agentId}/{connectionId}`.
  - `POST /execute` accepts an optional `connectionId`; when omitted, uses the default.
- The Composio backend maps each connection to its own connected account (distinct account IDs for one user ID); backends keyed only by `user_id` today (see `backends/base.py`) need the connection ID threaded through.
- Migration: backfill existing records with a generated `connectionId`, `ownerUserId=null`, `visibility=agent`, `label` from provider account info.
- Agent tool execution: when an agent has several connections of one tool, a tool call must specify which (new optional `account` arg); with none specified, the default is used. Document the default-selection rule.

Acceptance: two Gmail connections on one agent can be listed, used for `execute` by ID, and disconnected independently; existing single-connection flows pass unchanged tests.

## 9. Data Model

### 9.1 Feed (intake-service, collection `feeds`)
```
_id, agentId, connectionId, sourceType ("gmail_label"|"gmail_inbox"|"slack_channel"),
sourceParams {label|channel|query}, createdBy, ownerUserId|null,
target { boardId | "create_new_board" },
filters { senders[], excludeSenders[], keywords[], labels[], requireFilter: true },
classification { enabled, instructions },
caps { dailyMax, perRunMax },
enabled, state { cursor, lastRunAt, lastError, consecutiveFailures },
createdAt, updatedAt
```
At least one filter is required (`requireFilter`), enforced at write time.

### 9.2 Ledger (`intake_events`)
```
_id, feedId, agentId, connectionId, externalId, threadId, messageIdHeader,
receivedAt, decision ("created"|"appended"|"ignored"|"failed"|"capped"),
reason, taskId|null, boardId|null, llmUsage {tokens, cost}|null, createdAt
```
Unique index: `(connectionId, externalId)`. Index on `(feedId, createdAt)` for caps and the admin view.

### 9.3 Thread map (`intake_threads`)
`(connectionId, threadId) -> taskId`, so replies append to an existing task and never create duplicates.

### 9.4 Backend additions
- Agent settings: `intake.enabled` (bool), `intake.dailyBudgetUsd`, `intake.defaultDailyCap`. Added to `models_settings.py`, kept in a new small module if the file nears 300 lines.
- Task provenance field: `source { type, connectionId, accountLabel, externalId, url, autoCreated: true, feedId }`.

### 9.5 Event shape (normalized)
`source, connectionId, accountLabel, externalId, threadId, author, subject, body (truncated), links[], attachmentsMeta[], receivedAt, raw (not persisted)`.

## 10. Functional Requirements

### 10.1 Feed lifecycle
- FR1. Intake can only be used on agents where `intake.enabled` is true. Disabling pauses all feeds without deleting them.
- FR2. Create/update/delete/pause feeds via the intake API (proxied by the backend for auth).
- FR3. `list_sources` populates the picker (labels, channels) for a chosen connection.
- FR4. Feeds validate at write time: connection exists, caller may use it, filter present, target board belongs to the agent.

### 10.2 Ingestion
- FR5. Prefer push (Composio trigger webhooks via the gateway); fall back to polling at a per-connection interval with a stored cursor (Gmail `historyId`).
- FR6. Scheduling, rate limits, and backoff are **per connection**. A failing or slow account must not delay others.
- FR7. Failures increment `consecutiveFailures`; after N failures the feed auto-pauses and surfaces `lastError` (token expiry shows as "reconnect needed").

### 10.3 Pipeline
1. **Dedup:** skip when `(connectionId, externalId)` is in the ledger. Optional cross-feed collapse on `messageIdHeader`.
2. **Filter:** deterministic sender/label/keyword rules. Non-matching events are ledgered as `ignored` with a reason, with no LLM call.
3. **Cap check:** if the feed's daily count or the agent's budget is exhausted, ledger `capped` and do not create.
4. **Classify/extract (phase 3):** a tool-less LLM call returning schema-validated JSON `{decision, title, description, priority, labels, targetBoardHint}`. Invalid output results in `failed`, never a retry loop.
5. **Thread mapping:** if the thread is already mapped, append a comment/update to that task. Otherwise create.
6. **Sink:** call the backend internal endpoint (section 11). Record the result in the ledger.

Phase 1 uses a rule-only decision (every filtered event creates a task, with title from subject and body as description). Phase 3 replaces this with the classifier.

### 10.4 Guardrails (all required for v1 auto-create)
- FR8. **Kill switch:** per-feed `enabled` plus agent-level toggle; takes effect within one polling cycle, and in-flight events finish.
- FR9. **Daily cap:** per feed (and an agent-wide default). Over-cap events are ledgered `capped`, with a notice shown once to admins.
- FR10. **Required filters:** a feed cannot be saved without at least one filter.
- FR11. **Auto-created marker:** every created task carries `source.autoCreated`, the account label, and the message link, and gets an "auto-created" label. The task list can filter by it for bulk review and delete.
- FR12. **Cost budget:** LLM usage is reported to accounting-service tagged `{agentId, feedId, kind:"intake"}`. When the agent's intake budget is hit, classification stops and events are `capped` (not created blindly).

### 10.5 Permissions and privacy
- FR13. Shared connections (`ownerUserId=null`): agent admins create feeds; resulting tasks follow the target board's normal permissions.
- FR14. Personal connections: only the owner sees them or creates feeds on them. Tasks from personal feeds default to a board the owner chooses; the owner is warned that board members will see the content. Optional later: owner-only task visibility.
- FR15. When a member is removed from an agent, their personal connections and feeds are disabled; existing tasks stay.
- FR16. The intake service authenticates to the backend with `X-Internal-Key`; the backend records the acting identity as `actor_type="intake"` with the feed ID for audit (`audit_service`).

### 10.6 Observability
- FR17. Ledger query API: per feed, filter by decision, date. Metrics: events seen/created/ignored/capped/failed, lag, last success time.
- FR18. Admin view (phase 4) shows the ledger and feed health.

## 11. APIs

### Backend internal (called by intake-service)
- `POST /internal/intake/tasks` `{agentId, boardId|newBoard{name}, task{title, description, priority, labels}, source{...}}` returns `{taskId, boardId}`.
- `POST /internal/intake/tasks/{taskId}/updates` `{note, source{...}}` for thread appends.
- Backend enforces: board belongs to the agent, intake enabled, and idempotency via `source.externalId` (a safe retry returns the existing task).

### Backend public (UI-facing, proxies to intake)
- `GET/PUT /agents/{id}/settings` extended with `intake`.
- `GET/POST/PATCH/DELETE /agents/{id}/feeds`, `GET /agents/{id}/feeds/sources?connectionId=`, `GET /agents/{id}/feeds/{feedId}/ledger`.

### Intake service
- Mirrors the feed CRUD and ledger; `POST /webhooks/gateway` receives events from the integrations service; `GET /health`.

### Gateway
- Phase 0 changes in section 8, plus an event-delivery path to intake (push to `POST /webhooks/gateway`, signed with the internal key).

## 12. UI Changes (minimal)

The existing UI is unchanged except:
- Agent settings: an **Enable intake** toggle, intake daily cap and budget fields.
- A **Feeds** panel in agent settings: list with account label, source, target board, status (running/paused/error), last run, today's count. Create-feed form: connection picker (shows account labels, hides others' personal connections), source picker, filters, target board, daily cap.
- Task cards and details: show source badge ("Gmail · work@acme.com") with a link, and an "auto-created" label.
- Tasks appear through the existing websocket flow; no change to boards.

Implementation follows the 300-line rule per file (frontend modules split like the existing `board-*.js` files).

## 13. Security and Compliance

- Email and chat content is **untrusted input**. The classifier has no tools, output is schema-validated, content is delimited and labeled as data in prompts, and created tasks never auto-trigger agent execution from external text without the normal start rules.
- Store minimal content: truncate bodies; do not persist raw payloads or attachments in v1 (metadata and links only).
- Credentials remain solely in the integrations service.
- Internal endpoints are not exposed publicly; only the gateway webhook receiver is reachable from the gateway.
- Audit every create/append with feed and connection identifiers.
- Personal-connection content respects FR14; ledger access follows the same visibility as the feed.

## 14. Reliability

- At-least-once ingestion with idempotent sinks (ledger unique index plus backend `externalId` idempotency).
- Cursors advance only after the event batch is ledgered.
- Retries use exponential backoff per connection; poison events are marked `failed` and skipped after N attempts.
- Intake outages do not affect the backend or UI; events are recovered from the cursor (polling) or provider retry (webhooks).

## 15. Performance and Cost

- Target: event-to-task latency under 60 s on the push path and under 2 polling intervals on the poll path (default interval 2 min).
- LLM runs only on events that pass filters and caps. Use the cheapest adequate model, configured in settings like existing model config.
- Per-agent default daily cap: 50 tasks (configurable). Per-feed default: 25.

## 16. Success Metrics

- At least 80% of auto-created tasks are kept (not deleted) after 7 days (precision proxy).
- Median event-to-task latency within target.
- Duplicate task rate under 1%.
- Zero cross-visibility incidents for personal connections.
- Intake LLM spend per created task tracked and within budget.

## 17. Testing

- Unit: each pipeline stage with fakes (FeedSource, Classifier, Sink).
- Contract: backend internal endpoint (idempotency, board ownership, disabled-intake rejection).
- Integration: two Gmail connections on one agent, with the same message ID in both producing two tasks and no collisions; thread reply appends.
- Guardrails: cap reached, kill switch mid-run, budget exhausted, missing filter rejected.
- Privacy: personal connection hidden from other members in picker and API.
- Gateway regression: existing single-connection tool calls unchanged.

## 18. Rollout

1. Ship Phase 0 behind compatibility defaults; verify existing tools.
2. Deploy intake-service (new `docker-compose` service, internal network only) with the toggle off everywhere.
3. Enable for one internal agent with a low cap; review the ledger for a week.
4. Widen gradually; Slack after Gmail stabilizes.

Rollback: disable the agent toggle (stops all intake); the service can be stopped without affecting the backend.

## 19. Risks and Open Questions

| Risk / Question | Mitigation / Proposal |
|---|---|
| Auto-create floods boards | Required filters, caps, marker, kill switch |
| Prompt injection via email | Tool-less classifier, schema validation, untrusted-content handling |
| Personal content leaking via shared boards | Warn on target selection; owner-only visibility as a fast follow |
| Composio trigger availability per provider | Polling fallback behind the same interface |
| Gmail OAuth token expiry | Auto-pause, "reconnect needed" status |
| Which identity owns auto-created tasks? | Proposal: a service actor `intake` on behalf of the feed's creator |
| Default for personal-feed target board | Proposal: require the owner to pick explicitly |

## 20. Future Work
- Draft/approval mode (reusing the approval workflow).
- Owner-only task visibility for personal feeds.
- More sources (Jira, Calendar, Notion), board creation rules, and replies sent back to the source.
- Cross-feed fingerprint collapse as a default.
