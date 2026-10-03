# Phase 2: Foundations

## Technical Design

**Task status replaces the plain `done` flag**

Each task inside `boards.tasks[]` gains `status` (`idle`\|`queued`\|`running`\|`awaiting_reply`\|`awaiting_approval`\|`stopped`\|`failed`\|`blocked`\|`done`, default `idle`), `statusReason` (nullable, e.g. `user`\|`budget_exceeded`), and `currentRunId` (nullable). `done` is kept as a derived read-only field (`status == "done"`) so the existing frontend rendering keeps working untouched.

**New collections**

| Collection | Purpose | Key fields |
| --- | --- | --- |
| `task_runs` | One document per attempt — re-running a task never overwrites history | `_id`, `boardId`, `taskId`, `agentId`, `status`, `startedAt`, `endedAt`, `error`, `parentRunId` (for later sub-agent runs) |
| `audit_log` | Append-only, never updated or deleted | `_id`, `agentId`, `boardId`, `taskId`, `entityType`, `action` (`create`\|`update`\|`delete`), `actorType` (`human`\|`agent`), `actorId`, `before`, `after`, `ts` |
| `agent_settings` | Schema-only in this phase; enforcement lands in Phase 5 | `_id` = agentId, `tools: {gmail: {enabled}, calendar: {...}, slack: {...}}`, budget placeholder fields |

**Atomic transitions**

One shared helper, `transition_task_status(board_id, task_id, expected_statuses, new_status, **fields)`, implemented as a single `find_one_and_update` filtered on `{"_id": board_id, "tasks": {"$elemMatch": {"id": task_id, "status": {"$in": expected_statuses}}}}`, writing via the `tasks.$.status` positional operator. A filter miss returns `None` — that's the entire double-run guard, for free, with no separate locking mechanism. Every status-changing code path (Start, Stop, the agent loop, approve/reject in later phases) must go through this one function, never a raw `update_one`.

**Audit logging**

A `write_audit(...)` helper called from inside every existing mutating handler in `routers/boards.py` and `routers/chats.py`, right after each Mongo write succeeds — an addition at existing call sites, not a new layer.

**Settings (skeleton)**

`GET`/`PATCH /api/agents/{id}/settings` (Agent Admin only), backed by `agent_settings`. Tool-enable checkboxes and budget fields are saved here but not yet enforced anywhere — that's Phase 5.

## Implementation Plan

- [ ] Add `status`/`statusReason`/`currentRunId` to task documents; migrate existing tasks (`done: true` → `status: "done"`, else `"idle"`)
- [ ] Create `task_runs` and `audit_log` collections + indexes (`audit_log`: (agentId, ts), (boardId, ts))
- [ ] Implement `transition_task_status()` in `backend/app/task_state.py`; unit-test the race (two concurrent calls, exactly one succeeds)
- [ ] Implement `write_audit()`; call it from every existing mutating endpoint
- [ ] `agent_settings` collection + `routers/settings.py`
- [ ] Frontend Settings page (inert tool checkboxes + budget fields)
- [ ] Test: fire two simultaneous re-runs of the same task, confirm only one `task_runs` row reaches `running`
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): thin routers over a `services/` layer, SOLID boundaries anywhere more than one implementation exists, no file over 300 lines

## UI Verification

1. Open the new Settings page — confirm the tool-enable checkboxes and budget fields render, can be saved, and still show the saved values after a page reload.
2. Toggle a task's checkbox as before — confirm it still behaves exactly as it does today (the status-field migration didn't change visible behavior).
3. With browser dev tools' Network tab open, toggle a task and re-run a board action — confirm the requests still succeed with the same shapes as before (schema change is additive, not breaking).

There's no dedicated audit-log or run-history screen yet in this phase — that surfaces indirectly once undo/redo (Phase 7) and run history (Phase 3 onward) have UI of their own.

## Inputs Needed From You

None — this phase is internal engineering work (new collections, one shared status-transition helper, an audit-log helper). No new accounts, credentials, or decisions from you are required.
