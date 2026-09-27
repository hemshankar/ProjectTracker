# Phase 5: Tools & Budget Enforcement

## Technical Design

**New collections**

| Collection | Purpose | Key fields |
| --- | --- | --- |
| `tool_connections` | One connected identity per tool per Agent | `_id`, `agentId`, `toolType` (`gmail`\|`calendar`\|`slack`), `label` (e.g. "Support Inbox"), `encryptedTokens`, `scopes`, `connectedBy`, `createdAt`, `expiresAt` |
| `llm_calls` | Every LLM/tool call appends one row — full detail by default (full schema in Phase 8); totals are derived, never hand-maintained | `_id`, `agentId`, `boardId`, `taskId`, `runId`, `usd` (this phase only needs the running total; full request/response capture is specified in Phase 8) |
| `resource_locks` | Compare-and-swap lock per external resource | `_id` = resource key (e.g. `gmail:thread:<id>`, `calendar:event:<id>`), `heldBy` (runId), `expiresAt` |
| `rate_limits` | Token-bucket per (Agent, tool) | `_id` = `<agentId>:<toolType>`, `tokens`, `lastRefill` |

Budget caps live where they're configured: `boards.budgetCapUsd` (nullable = inherit the Agent's), `agent_settings.budgetCapUsd`, and one singleton `global_settings.budgetCapUsd` document.

**OAuth connect flow (per tool)**

`GET /api/agents/{id}/tools/{type}/connect` redirects to that provider's own consent screen (Google's for gmail/calendar, Slack's own OAuth for slack) with `agentId` embedded in `state`; `GET .../callback` exchanges the code and stores the result, encrypted at rest, in `tool_connections`. Token refresh happens lazily wherever a tool is invoked (check `expiresAt`, refresh before use) — no separate refresh job needed at this scale.

**Enforcement, in order, before every tool call in the agent loop**

1. **Rate limit** — token-bucket check; empty bucket means the task waits (stays `queued`), it does not fail.
2. **Budget** — board, then Agent, then global (cheapest/most specific first, short-circuiting). Any cap exceeded: let the in-flight call finish, then `transition_task_status(..., "stopped", statusReason="budget_exceeded")` before the next step — the graceful-stop rule from the PRD, implemented as "check happens between steps, never mid-call."
3. **Resource lock** (mutating calls only) — acquire via the same `find_one_and_update` compare-and-swap pattern as `transition_task_status`; held elsewhere means this task waits/retries instead of racing.

**Frontend**

The Settings page from Phase 2 gets real tool-connect buttons (replacing the inert checkboxes) and live-editable budget fields, per Agent/board.

## Implementation Plan

- [ ] `tool_connections` collection + an encryption-at-rest helper (e.g. Fernet with a server-held key)
- [ ] Gmail/Calendar OAuth connect + callback routes; Slack OAuth connect + callback routes
- [ ] `llm_calls` (see Phase 8) + a board/Agent/global running-total budget check helper reading its `usd` field
- [ ] `resource_locks` compare-and-swap helper, wired into every mutating tool call
- [ ] `rate_limits` token-bucket helper, wired the same way
- [ ] Settings page: real connect buttons + live budget fields
- [ ] Test: two tasks racing on the same calendar event id serialize correctly via the lock; a task hitting its board budget mid-run stops gracefully only after its in-flight call finishes
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): each tool (Gmail/Calendar/Slack) is a `ToolConnector` subclass behind one common interface, never a set of if/elif branches keyed on `toolType`; no file over 300 lines

## UI Verification

1. On the Settings page, click Connect next to Gmail — confirm it opens Google's real consent screen, and afterward Settings shows "Connected as <email>" in place of the plain checkbox. Repeat for Calendar and Slack.
2. Set a very low board budget cap in Settings, click Start — confirm the board quickly transitions to stopped with a visible "budget exceeded" reason, with tasks still left undone.
3. Approve a real mutating action (test email/calendar invite) — confirm it actually shows up in the connected Gmail/Calendar account, not just in the app's chat.
4. Configure a very low per-tool rate limit, trigger enough approved actions to hit it — confirm the next task visibly waits rather than failing outright.
5. Start two tasks that touch the same calendar event — confirm only one proceeds at a time rather than both racing.

## Inputs Needed From You

| Input | Why | How to get it |
| --- | --- | --- |
| Gmail API + Calendar API enabled | Lets the backend call these APIs at all | Same Google Cloud project as Phase 1 (or a new one) → APIs & Services → Library → enable "Gmail API" and "Google Calendar API" |
| Gmail/Calendar OAuth scopes added to the consent screen | Needed to request send/read/calendar access | OAuth consent screen → Scopes → add `.../auth/gmail.send`, `.../auth/gmail.readonly`, `.../auth/calendar` |
| Slack app (Client ID, Client Secret, Signing Secret) | Powers the Slack tool connection | api.slack.com/apps → Create New App → From scratch → OAuth & Permissions: add bot scopes (`chat:write`, `channels:read`, `users:read`) and a redirect URL → Install to Workspace → copy credentials from "Basic Information" and "OAuth & Permissions" |
| An encryption key for stored tool tokens | `tool_connections` tokens are encrypted at rest | Generate one yourself: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` → add as `TOOL_ENCRYPTION_KEY` |
| Initial budget cap amounts (board / Agent / global) | Someone has to pick the actual dollar numbers | Your call as product owner — not fetched from anywhere; just needs a starting number for each level |
| Per-tool rate-limit defaults (e.g. max emails/day) | Same as above — a policy number, not a credential | Your call; can start conservative and loosen later since it's just a config value |

**A heads-up on lead time:** if the OAuth consent screen ends up "External" (not everyone signing in is inside one Google Workspace org) and you request `gmail.send`, Google classifies that as a sensitive/restricted scope requiring its app-verification review — this can take days to weeks. Worth starting that process as soon as the consent screen exists, well before the rest of this phase is otherwise ready to ship.
