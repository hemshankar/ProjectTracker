# Phase 4: Approval Workflow

## Technical Design

**Chat message schema**

The embedded message shape (`boards.chats[].messages[]`, currently `{role, text}`) gains an optional `type`: `"text"` (default, unchanged behavior) or `"action_request"` with a `payload`: `{description, tool, params, status: "pending"|"approved"|"rejected"}`.

**Introducing tool use**

`chat_service.stream_reply` becomes the base for a new `agent_service.run_task_step()` that calls Anthropic with tool-use declared, split into two kinds: read-only tools execute immediately and feed their result back into the loop; mutating tools are never executed directly — instead the loop appends an `action_request` message, transitions the task to `awaiting_approval` (a status that existed since Phase 2 but only gets real meaning here), and suspends.

**Approve / reject**

`POST /api/boards/{id}/chats/{chatId}/messages/{messageId}/approve` transitions the message to `approved`, the task back to `running` via `transition_task_status`, and resumes the loop — which now actually executes the tool call and appends its result as a follow-up message.

`POST /.../reject` transitions the message to `rejected`, the task to `blocked`; the agent's next turn sees the rejection in its context and can revise and re-propose.

**Chat during a run**

The run loop re-reads `chat["messages"]` for new human entries after every tool-call round-trip, not only once at task start — so a human typing guidance mid-run actually reaches the next step, not just the next task.

**Frontend**

The chat renderer branches on message `type`: `action_request` renders a distinct card (description + Approve/Reject buttons) instead of a plain bubble; plain-text messages render exactly as today.

## Implementation Plan

- [ ] Extend chat message schema with `type`/`payload`; confirm existing plain-text messages are unaffected
- [ ] Split `chat_service.stream_reply` into a tool-use-aware `agent_service` module; define the read-only vs. mutating tool split
- [ ] Implement `awaiting_approval` suspend/resume in the execution loop
- [ ] Approve/Reject endpoints wired through `transition_task_status`
- [ ] Live mid-run chat ingestion (re-read messages between tool-call rounds)
- [ ] Frontend action-request card UI
- [ ] Test: propose a mutating action, reject it, confirm the task lands in `blocked` and the agent's next message acknowledges the rejection
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): keep the tool-use loop in its own `execution/` package, distinct from `services/agents.py`'s entity/membership logic, despite the shared "agent" name; no file over 300 lines

## UI Verification

1. Start a board with a task that implies a mutating action (e.g. "email the client an update") — confirm an action-request card (description + Approve/Reject) appears in chat instead of a plain reply.
2. Click Reject — confirm the card shows "Rejected," the task's status reflects `blocked`, and the agent's next chat message acknowledges it.
3. On a fresh proposal, click Approve — confirm the card shows "Approved" and a follow-up chat message reports the (simulated, in this phase) result.
4. While a task is running, type a message in the chat mid-run — confirm the agent's next message visibly reflects that input, proving live chat ingestion works, not just start-of-task context.

## Inputs Needed From You

None — extends the existing Anthropic integration; no new credentials. The read-only-vs.-mutating tool split is a design decision made in code, not something that needs an account or secret from you.
