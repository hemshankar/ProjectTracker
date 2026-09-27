# Phase 3: Manual Start/Stop

## Technical Design

**Board status**

Boards gain `status` (`idle`\|`queued`\|`running`\|`stopped`\|`done`) and `stopRequested` (bool). Board status is a small, cached summary the execution loop maintains as it works through the board's tasks — it is not itself the source of truth for any one task's state.

**Execution loop**

`POST /api/boards/{id}/start` atomically transitions board status `idle`\|`stopped`\|`failed`\|`blocked` → `queued`, then to `running`, and spawns `run_board(board_id)` as an `asyncio.create_task`, tracked in an in-process `Dict[str, asyncio.Task]` registry so Stop can find it. (Single-process assumption — fine for now; a multi-replica deployment would need this registry moved to a durable queue, noted for later, not required here.)

`run_board` loops over tasks with `status == "idle"`: transitions each to `running` via `transition_task_status`, does read-only work only in this phase (a plain Anthropic call reusing today's `chat_service.build_board_context`, no tool_use yet), transitions to `done`. Before starting each new task it checks `stopRequested`; if set, the board transitions to `stopped` and the loop exits instead of continuing.

`POST /api/boards/{id}/stop` just sets `stopRequested = true` — that flag check between tasks is the entire "graceful" behavior; nothing is ever killed mid-call.

**Live status to the frontend**

A new `GET /api/boards/{id}/events` SSE endpoint, reusing the `StreamingResponse` pattern `routers/chats.py` already uses for streamed replies, pushing `{boardId, status}` / `{taskId, status}` deltas. `app.js` has no live-update mechanism today (no polling, no `EventSource`) — this is the first one, and later phases (approvals, glow) ride the same channel rather than each inventing their own.

**Frontend**

Start/Stop buttons on each board's toolbar (mutually exclusive by status); `.board.processing` (animated) and `.board.done` (steady) glow classes in `styles.css`, driven by the SSE client.

## Implementation Plan

- [ ] Add `status`/`stopRequested` to board documents
- [ ] `backend/app/agent_runner.py`: `run_board()` loop + in-process task registry
- [ ] `POST /start` / `POST /stop` endpoints (atomic board-status transition + flag)
- [ ] SSE `GET /events` endpoint for board + task status push
- [ ] Frontend: Start/Stop buttons, SSE client, processing/done glow CSS
- [ ] Test: start a board, hit Stop mid-task, confirm the current task finishes and no new task starts
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): the execution loop is a package (`execution/loop.py`, `execution/registry.py`, ...), not one growing file; encapsulate the loop in an `AgentRunner` class rather than free functions

## UI Verification

1. Open a board with open tasks, click Start — the board's background should switch to the "processing" glow immediately, with no page reload.
2. Watch the task list update live as each task starts and finishes, one at a time — confirms the SSE push is working, not just a one-time load.
3. Click Stop mid-run — confirm the current task visibly finishes before anything halts, and no further task starts afterward.
4. Let a board run to completion untouched — confirm the glow changes to "done" once every task is finished.
5. Refresh the browser mid-run — confirm the board still shows "processing" (state is server-side, not just in-memory on the client) and the live updates resume.

## Inputs Needed From You

None — uses the `ANTHROPIC_API_KEY` you've already configured. No new credentials needed for this phase.
