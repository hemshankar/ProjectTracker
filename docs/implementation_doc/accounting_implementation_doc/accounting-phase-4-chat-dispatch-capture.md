# Phase 4: Chat & Dispatch Capture

PRD: FR-2, plus decision "chat and dispatch calls count toward totals and caps". Brings the two unrecorded Anthropic call paths onto `UsageRecorder` from Phase 3. Nothing is delivered to the service until Phase 5, and caps do not change until Phase 5.

## Technical Design

### Board chat (`chat_service.stream_reply`)

Today `stream_reply` yields `text_stream` deltas only and never reads usage (`chat_service.py:98-105`).

Change:
1. After the `async for text in stream.text_stream` loop, call `response = await stream.get_final_message()` while still inside the `async with` block. This returns the final message with `usage` and `model` and is already what the task loop does.
2. Record through `UsageRecorder.record(call_kind=CHAT, ...)`.

Design points:
- **Recording must not affect the stream.** Recording happens after the last delta was yielded, inside a `try/except` that logs and never raises. A recording failure can never truncate or error the user's reply.
- **Cancelled or disconnected streams.** The SSE route (`routers/chats.py:69-116`) can be cut off when the client disconnects, which raises `GeneratorExit`/`CancelledError` in the generator and `get_final_message()` is never reached. Anthropic still bills partial output. Handle it in a `finally`: if the stream object exists but wasn't finalized, take whatever usage is available from the stream's accumulated message snapshot (`stream.current_message_snapshot`) and record with `outcome=cancelled`. If nothing is available, record nothing and log at `warning` (so the gap is visible, and Phase 8's reconcile will show it as drift in the corresponding place).
- **API errors** (`APIStatusError`): no usage object exists, so no cost is recorded. A `warning` log notes the failed call. This is correct, since Anthropic doesn't bill failed requests.
- `stream_reply` currently takes `(board, history)` and has no run id or user. Extend the signature with an optional `UsageAttribution` (`user_id`, `task_id`) passed by the route (`chats.py`). The route knows the session user and the chat's `taskId` when the conversation is task-tagged. This keeps `stream_reply` free of auth concerns (Single Responsibility).

Attribution for chat rows:
| Field | Value |
| --- | --- |
| `agentId` | `board["agentId"]` |
| `boardId` | board |
| `taskId` | the chat message's `taskId` if task-tagged, else `null` |
| `runId` / `parentRunId` | `null` |
| `callKind` | `chat` |
| `userId` | session user |

Because the existing record path requires a `task_id` string, make `taskId` and `runId` **optional** in `record_llm_call` and `record_call` (they are `Optional[str]` in the ledger anyway). `observability` filters (`boardId`, `taskId`, `runId`) already work with nulls. Add a `callKind` filter to `list_llm_calls` so the Traces tab can show or hide chat rows.

### Dispatch planner (`DispatchPlanner._ask_model`)

`dispatch.py:86-89` uses a hard-coded `claude-haiku-4-5` and reads `get_final_message()` already, so usage is available and unused.

Change:
1. After `response = await stream.get_final_message()`, call `UsageRecorder.record(call_kind=DISPATCH, ...)`.
2. Attribution: `boardId` is known to the planner's caller. Dispatch groups tasks from one board, so `taskId = null` and the cost is board-level overhead. **Do not** split a planner call across tasks (it isn't attributable to one).
3. `agentId` and `userId` come from the caller. The planner receives `tasks`/`all_tasks` today and not the board. Introduce a small `DispatchAttribution` value object passed through `group(...)` (or set on the planner instance by its factory) rather than reaching for globals. The three planner classes at `dispatch.py:20/39/49` share the `group` signature, so add the argument in a backward-compatible way (default `None` → record with nulls).
4. Model name: stop hard-coding the string in the call. Take it from one constant (`DISPATCH_MODEL`) so it is the same value the price table needs.

### Cap semantics

Chat and dispatch spend becomes visible in `llm_calls` as soon as this phase ships, and the **current** cap check sums `llm_calls` per board/agent/global. So caps start including this spend immediately, which is the intended decision, but it is a visible behavior change and arrives before the Phase 5 counters. Two options:
- (Recommended) Ship Phase 4 and Phase 5 together in one release, so there is a single behavior change.
- If shipped separately, call it out in release notes.

Edge: **chat is not gated by `check_budget` today.** A user can keep chatting after a cap is hit. Decide whether to block chat when over budget (consistent) or allow it and just record it (less disruptive). Default: enforce the board/agent/global cap check before a chat call with a clear message ("Budget cap reached for this board"). Flagged below as a decision.

### Files touched

```
backend/app/chat_service.py            +finalize/record (kept < 300 lines)
backend/app/routers/chats.py           pass UsageAttribution
backend/app/execution/dispatch.py      record + DISPATCH_MODEL + attribution arg
backend/app/execution/<caller of group()>   pass attribution
backend/app/services/budget_service.py / observability.py   optional taskId/runId, callKind filter
```

## Implementation Plan

- [ ] Make `task_id`/`run_id` optional in `UsageRecorder`, `record_call`, and `record_llm_call`. Add a `callKind` filter to `list_llm_calls`
- [ ] `UsageAttribution` and `DispatchAttribution` value objects
- [ ] Chat: finalize message, record on success, record partial on cancel (`current_message_snapshot`), log (never raise) on failure
- [ ] `routers/chats.py`: pass user and task attribution into `stream_reply`
- [ ] Dispatch: `DISPATCH_MODEL` constant, record after `get_final_message`, thread attribution through the `group` signatures and its caller
- [ ] (Decision) pre-chat budget check and the blocked-chat message
- [ ] Update `test_dispatch.py`, add `test_chat_usage.py`
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

- Chat success: one `llm_calls` row, `callKind=chat`, tokens/model/`usd` set, `taskId` set only for task-tagged chats.
- Chat recording failure (recorder raises): the reply is still streamed in full and no exception escapes.
- Chat cancelled mid-stream: a row with `outcome=cancelled` and partial output tokens when a snapshot exists. Nothing recorded (and a warning logged) when it doesn't.
- Chat API error (429/5xx): no row, user-facing error message unchanged.
- Dispatch: a row with `callKind=dispatch`, model `claude-haiku-4-5`, `taskId=null`, `boardId` set. Fake planners (the non-LLM variants at `dispatch.py:20,39`) record nothing.
- Cap: a board whose summed `usd` (now including chat and dispatch) crosses its cap → `check_exceeded` returns `budget_exceeded` (regression guard for the decision).
- Traces: filter by `callKind` works. Rows with null `taskId`/`runId` render.

## Verification

1. Send a board chat message. A new `llm_calls` row appears with `callKind=chat` and plausible tokens.
2. Send a chat tagged to a task. The row's `taskId` matches.
3. Start a board with several ready tasks (to trigger dispatch grouping). There's a `callKind=dispatch` row on `claude-haiku-4-5`.
4. Close the browser tab mid-reply. A cancelled row appears (or a warning is in the logs).
5. Set a very low board cap, spend it with chat alone, and confirm that task runs on that board are now blocked and (per the decision) chat shows the cap message.
6. The Traces tab shows the new rows and the filter works.

## Rollback

Revert the two call-site edits. Rows already written stay in `llm_calls` and expire normally. They were also added to the ledger only after Phase 5.

## Inputs Needed From You

- **Decision:** should board chat be blocked when a cap is exceeded (recommended, consistent with "caps include chat") or allowed and merely counted?
- Confirm the Phase 4 + 5 same-release recommendation.
