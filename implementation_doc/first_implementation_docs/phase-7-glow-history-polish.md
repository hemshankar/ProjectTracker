# Phase 7: Glow & History Polish

## Technical Design

**Glow**

Consolidated into one derived field, `boards.glow` ∈ {`none`, `processing`, `done`, `needs_reply`, `needs_approval`}, recomputed on every status-affecting write (inside `transition_task_status` and the start/stop handlers) rather than left for the frontend to infer from raw task statuses — the SSE payload from Phase 3 then just carries the final answer. Precedence when tasks disagree (e.g. one `done`, another `awaiting_approval`): `needs_approval` > `needs_reply` > `processing` > `done` > `none` — the most actionable state wins.

**Undo/redo**

Built entirely from `audit_log` (Phase 2): a per-user, per-agent pointer into that user's own `actorType="human"` entries, newest first. Undo re-applies the `before` snapshot of the pointed-at entry through the normal update endpoints — so it re-enters the audit log itself and re-triggers a fresh transition, never a raw document overwrite; redo replays `after`. This is server-side (the audit log is server-side truth, not a client-only stack): `POST /api/agents/{id}/undo` / `/redo`, with Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z wired to them in the frontend.

**In-place chat edits**

Agent messages gain `edited` (bool) and `editedAt` fields; `PATCH /api/boards/{id}/chats/{chatId}/messages/{messageId}` lets the agent revise its own prior message content (e.g. updating an `action_request` card's `status` after approval). No `DELETE` route is ever exposed for chat messages — enforced by the route simply not existing, not by convention alone.

## Implementation Plan

- [ ] Derive and store `boards.glow`; update the SSE payload shape to carry it
- [ ] Frontend: full 4-state glow CSS, board-level and task-level indicators
- [ ] `POST /undo` / `/redo` endpoints reading the audit log
- [ ] Frontend Ctrl/Cmd+Z / Shift+Z keyboard wiring
- [ ] `PATCH` message-edit endpoint (agent-only; confirm no delete route exists for messages)
- [ ] End-to-end pass: create/edit/delete several boards and tasks as a human with agent actions interleaved, confirm undo/redo replays exactly the human sequence and skips the agent's changes
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): thin routers over a `services/` layer, no file over 300 lines

## UI Verification

1. Trigger each glow state in turn (Start = processing; let it finish = done; get an agent question = needs-reply; get a proposed action = needs-approval) and confirm all four are visually distinguishable side by side.
2. Edit a task's text as a human, press Ctrl/Cmd+Z — confirm it reverts; press Ctrl/Cmd+Shift+Z — confirm it re-applies.
3. Let the agent make a change in between two human edits, then undo twice from the human side — confirm the agent's change is left untouched and only the human edits are undone, in the correct order.
4. Confirm an approved/rejected action card updates in place in the chat (no duplicate message, nothing disappears) — proving in-place edit rather than delete-and-recreate.

## Inputs Needed From You

None — purely frontend/backend polish on data that already exists from earlier phases.
