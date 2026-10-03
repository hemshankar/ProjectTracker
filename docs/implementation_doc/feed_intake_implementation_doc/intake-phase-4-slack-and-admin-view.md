# Phase 4: Slack & Admin View

Goal: prove the plugin design with a second source (Slack), add basic board creation from intake, and give admins visibility into what intake did (ledger and feed health).

## Technical Design

### Slack source (`sources/slack.py`)
- Implements the existing `FeedSource` protocol with no changes to `runner.py`, `filters.py`, sinks, or services (acceptance test for Open/Closed). If any pipeline file needs editing, stop and revisit the protocol.
- `list_sources(connection)`: channels via `slack.list_channels` (exists in the gateway catalog). `fetch(feed, cursor)`: channel history since the cursor timestamp via a new read action `slack.list_messages` (add to catalog + Composio map; verify the Composio slug and arguments; do not guess). Thread replies via `slack.list_thread_replies` if the toolkit supports it (verify), otherwise treat the parent `ts` as `thread_id` and ingest replies from channel history.
- Normalization: `external_id = "{channel}:{ts}"`, `thread_id = thread_ts or ts`, `author` resolved to a display name through a cached `slack.get_user` lookup (or left as the user id if not available), `links` = permalink if returned, `subject` = first line of text (truncated).
- Filters apply to Slack as: sender, keywords, and `mentions` (messages that @-mention a given user/group, a Slack-specific filter registered via the filter registry, not hard-coded in the filter module). Bot/self messages are skipped by default.
- Cursor = latest `ts` plus a seen-ts window. Rate limits are per connection (already handled by the scheduler); Slack tier limits mean the default interval for Slack feeds is 60 to 120 s.
- Push: Slack events are not required for this phase; polling only. Capability flag `supports_push=False`.

### Board creation (`sinks/board_target.py`)
- `target.mode = "new_board_per_thread"` or `"new_board_per_feed"`: the sink calls `POST /internal/intake/boards {agentId, name, labels?, source}` first (idempotent by `(feedId, key)` where key is the thread id or a fixed key), then creates the task on it. Backend creates via `boards` service so audit and websockets apply.
- Guardrails: a **board creation cap** per feed per day (default 3) in `caps_service` (separate from the task cap), and boards created by intake are named with the source (for example "Slack #support: <subject>") and tagged `source.autoCreated` so they can be bulk-reviewed.
- Default stays `board` (existing board). Admin must opt into board creation per feed.
- Backend: new `routers/intake_internal.py` endpoint (split from tasks if the file nears 300 lines), membership: created boards are shared with the feed creator (shared feed: agent admins; personal feed: owner only). Verify the existing board ownership/sharing model in `boards.py`/`sharing_service.py` and reuse it.

### Admin view
Backend proxy plus frontend (vanilla JS):
- `GET /api/agents/{id}/feeds/{feedId}/ledger?decision=&from=&to=&page=` returns paged ledger rows (`receivedAt`, decision, reason, preview, task link, cost).
- `GET /api/agents/{id}/intake/health` returns per feed: status, lastRunAt, lag (now minus newest event time), 24 h counts (created/appended/ignored/capped/failed), last error, spend today.
- Visibility rule: shared-feed ledgers are visible to agent admins; **personal-feed ledgers only to the owner**. Previews are the short preview stored in Phase 1.
- UI: `settings-intake-ledger.js` (table with filters and pagination, link to the task, "why" column), `settings-intake-health.js` (status cards). Extend the Feeds list with a "View activity" action. Keep each file under 300 lines.
- Retention: a TTL index on `intake_events` (default 90 days, configurable) so the ledger does not grow without bound. Dedup beyond TTL: Gmail/Slack ids will not re-appear after cursors advance, but note the first-run backfill window in docs.

### Contract suite
The `FeedSource` contract test now runs against `FakeSource`, `GmailSource` and `SlackSource` with identical assertions (list sources, fetch with cursor, idempotent re-fetch, normalization shape).

## Implementation Plan
- [ ] Gateway: `slack.list_messages` (+ thread replies, user lookup if supported) in catalog and Composio map; verify slugs
- [ ] `SlackSource` + normalizer details; register in `sources/registry.py`
- [ ] Source contract suite extended to Slack; confirm zero edits to `pipeline/` and `services/` files
- [ ] Filter registry: `mentions` filter registered by the Slack source module
- [ ] Board-creating sink, board cap in `caps_service`, backend `POST /internal/intake/boards`
- [ ] Ledger query service with visibility rules; health aggregation
- [ ] Backend proxy routes for ledger and health
- [ ] Frontend: ledger table, health cards, "View activity" action
- [ ] TTL index and config
- [ ] Tests: Slack normalization and cursor, board creation idempotency, board cap, personal ledger hidden from other admins, ledger pagination
- [ ] Update PRD status and docs; verify no file over 300 lines

## Actions Required From You
1. Connect a **test Slack workspace** and channel through the gateway; confirm which Slack scopes the managed auth grants (history, channels, users), because Slack history reading needs specific scopes. I will not assume this.
2. Confirm Composio's Slack tool names and arguments for history, thread replies, and user lookup.
3. Decide if board creation should ship now or wait (it is optional for the MVP value; it can be dropped without affecting the rest).
4. Confirm ledger retention (default 90 days) and who may see shared-feed ledgers (default agent admins).
5. Decide whether Slack bot messages should ever be ingested (default: skipped).

## Development Best Practices
- **OCP is the test of this phase:** the diff for Slack should be new files plus registry and catalog entries, nothing in the runner. A change to the runner means the Phase 1 abstraction was wrong; fix the abstraction, not the symptom.
- **ISP:** push-capable sources add an `EventReceiver` implementation later; Slack declares no push.
- **SRP:** the board-creating sink composes the existing task sink with a board creator (composition, not subclassing).
- **Privacy:** ledger visibility is enforced in the service layer, not only in the UI.
- **Pagination everywhere:** ledger queries are paged and index-backed; never return unbounded lists.
- **Escape all rendered text:** Slack and email content appears in the ledger table.
- **300-line rule:** split `slack.py` into fetch and normalize modules if needed; keep UI files single-purpose.

## UI Verification
1. Feeds form: choose a **Slack** connection; the source picker lists channels. Create a feed on `#intake-test` with a keyword filter.
2. Post a matching message: a task appears with a "Slack · #intake-test" badge and permalink. A non-matching message is ignored; a bot message is skipped.
3. Reply in thread: it appends to the existing task (same behavior as Gmail).
4. Run Gmail account A, Gmail account B and Slack feeds simultaneously: each is independent; pausing one does not affect the others.
5. Set a feed to **new board per thread**: a new board appears for the first matching thread, the task is on it, and a second thread creates a second board; exceeding the board cap stops creation and shows "cap reached".
6. Open **View activity** on a feed: the ledger lists created/ignored/capped/failed with reasons, filters work, task links navigate.
7. Open the health cards: lag, counts, last error and spend are shown. Break the connection and watch the status turn to "reconnect needed".
8. As a different admin, confirm a **personal** feed's ledger is not visible; as the owner it is.
9. `pytest` green in all services and the contract suite passes for all three sources.
