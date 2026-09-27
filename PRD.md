# Scatterboard Agent PRD

*2026-09-26 · Hemshankar Sahu*

Source (live, editable): https://claude.ai/code/artifact/dcac2c61-f5c4-4638-96ac-fae9a4cc27f3

## Overview & Goals

Scatterboard boards today have tasks and an advisory-only chat — the assistant can talk about a board's tasks but can't act on them. This adds an agent that can actually work on tasks: doing read-only work itself, and taking real actions (send an email, book a calendar event) once a human approves.

Goals:
- Let an agent pick up open tasks and make progress on them, automatically or on demand.
- Gate any action that changes the outside world behind explicit human approval.
- Give every board access to the same tools (Gmail, Calendar, ...) without leaking one board's tasks or chat into another.
- Keep a full history of what the agent did, separate from human-made edits.

## Identity & Multi-Tenancy

- Users sign in with Google SSO. A user's identity doesn't own boards directly — boards belong to Agents.
- An **Agent** (e.g. "Marketing Agent") is the top-level entity: it owns exactly one Scatterboard — all of its boards, tasks, chat, and audit log — plus its own tool connections and budget. A user only sees the Agents they've been invited to.
- **Agent Admin** — manages an Agent's tool connections, budget, and invites. Separate from ordinary board access, so a board collaborator can't rewire what account the Agent sends from.
- **Board sharing** — a board's owner or editor can invite other users to it as viewer or editor. Board access automatically grants the ability to interact with that board's Agent — no separate Agent-level invite needed for ordinary use.

## Settings

- Dedicated Settings page (per Agent) holds everything below.
- Tool access — enable or disable each of the Agent's connected tools (Gmail, Calendar, Slack, ...) for a board; enabled at the Agent level, with a per-board override.
- Budget — board, Agent, and global spend caps (see Cost & Budget Controls).
- No "auto-run" setting: a board only starts when a user explicitly clicks Start (see Execution Model).

## Cost & Budget Controls

- Three enforced spend ceilings: a per-board quota, a per-Agent budget (shared across all of that Agent's boards), and one global budget. All configurable, in dollars or tokens.
- Spend is tracked internally in one normalized unit (USD), regardless of which unit is configured, so board, Agent, and global quotas stay comparable.
- Hitting any of the three mid-run doesn't cut anything off mid-step: the current in-flight tool call finishes, then the board halts before its next step (status `stopped`, reason `budget_exceeded`) — the same graceful behavior as a user-initiated Stop.
- Configured on the Settings page, alongside tool connections and invites.

## Task Lifecycle & Status

Tasks move through a state machine instead of a plain done/not-done flag:

| Status | Meaning |
| --- | --- |
| idle | Not started; waiting for the user to click Start |
| queued | Start clicked, waiting for an agent slot |
| running | Agent actively working (board shows a "processing" glow) |
| awaiting_reply | Agent needs more info from the user, in chat |
| awaiting_approval | Agent has a proposed action ready, needs approve/reject |
| stopped | Halted gracefully — by the user (Stop) or by hitting a budget quota |
| done | Completed (board shows a "done" glow once every task is done) |
| failed | Agent hit an error |
| blocked | Can't proceed (e.g. rejected action, missing info) |

Each run is its own record (status, timestamps, which agent/sub-agent ran it, error if any, and — for `stopped` — a reason of `user` or `budget_exceeded`), so re-running a task never erases its prior history.

## Execution Model

**Starting a board.** A board only starts when a user explicitly clicks Start ("Manifest") — there's no background or automatic trigger. While it's processing, the board's background shows a "processing" glow; once every task in it resolves, the glow switches to "done" (see Notifications (Glow)).

**Read-only vs. mutating work.**
- Read-only work (checking a calendar, searching email, drafting text): the agent does this itself, no approval needed.
- Mutating actions (sending an email, creating/editing/deleting a calendar event, or anything that changes something outside Scatterboard): the agent prepares the action and posts it to the board's chat as a pending approval request. It does not execute until the user approves.
- Chat becomes interactive: alongside normal text, it can hold "action request" cards — what the agent wants to do, plus Approve/Reject. Approve runs it; Reject moves the task to blocked, and the agent can revise and re-propose.

**Chat during a run.** The agent watches the chat throughout a run, not only when it's explicitly waiting on a reply — a human can add guidance at any point, and the agent picks it up on its next step.

## Multi-Agent Orchestration

- For a given task, the owning Agent can spin up one or more scoped **sub-agents** — ephemeral workers with no identity or budget of their own, just a slice of the owning Agent's tools — to decompose the work. This is the owning Agent's call, whenever a task needs it.
- If a task needs a specialization the owning Agent doesn't have, it can instead delegate to a different top-level Agent it has access to (e.g. Marketing Agent asking Support Agent) — its own decision, never a manual per-task assignment by a human.
- The owning Agent decides whether sub-agents, delegated Agents, or its own tasks run in parallel or sequentially, based on dependencies and whether they touch the same resource.
- "One Agent per Scatterboard" is an identity/ownership boundary, not a single worker: tasks across different boards owned by the same Agent can run fully in parallel — the resource-level locks (see Concurrency & Reliability) are what keep that safe, not board boundaries.
- Sub-agents and delegated Agents draw from the same enforced budgets (board/Agent/global) and can only use tools that Agent has connected and enabled.

## Concurrency & Reliability

- **No double runs.** A task can only move idle/queued → running through an atomic, conditional database update. If two triggers race, only one wins; the other is a no-op.
- **Safe parallelism.** Whether it's sub-agents on one task, or separate tasks across different boards the same Agent owns, the backend enforces a lock per external resource (same calendar, same email thread, same Slack channel) so two runs can never take conflicting actions on the same resource at once. The Agent's parallel/sequential choice is an optimization, not the only safety net.
- **Stopping.** A running or queued board can be halted with Stop. Stop is graceful: the in-flight tool call finishes, then processing halts before the next step — nothing is killed mid-call. A budget quota hit mid-run halts the same way, automatically (see Cost & Budget Controls).
- **Deleting.** A board or task can only be deleted from idle, done, stopped, failed, or blocked — never from queued or running. Deleting a running board requires Stop first.

## Notifications (Glow)

Four distinct visual states, at both board and task level:
- **Processing** (board-level) — the board is actively running after Start.
- **Done** (board-level) — every task in the board has resolved.
- **Needs reply** — agent asked a question, waiting on text input.
- **Needs approval** — agent has a proposed action, waiting on approve/reject.

Processing/Done reflect the board's overall run state; Needs reply/Needs approval are driven by individual task status (`awaiting_reply` / `awaiting_approval`) bubbled up to the board — so there's one source of truth behind all four.

## Audit Log & Undo/Redo

- The agent can create and update chat messages, but never delete one.
- Every create/update/delete on a board, task, or chat message — by a human or the agent — is written to one append-only audit log (who, what, before/after, when), scoped per user.
- Stops, budget-triggered halts, and approvals/rejections are logged the same way.
- Undo/redo (Ctrl/Cmd+Z) replays human-made changes only, filtered from that same audit log — agent actions are never undone this way.

## Observability & Debug Console

- Every LLM call (system prompt, request, response, tool calls and results) is captured in full detail by default — not opt-in. It's the same data budget enforcement already needs, so it's one log, not two.
- This is debug data with its own retention window, not the permanent record — that's still the audit log. Encrypting it at rest is real future work, explicitly out of scope for this plan.
- One Agent Admin console, three tabs: **Config** (tools, budget, invites — what was called Settings), **Activity** (the audit log, filterable by board/task/actor/time), **Traces** (the LLM call log, drillable per run, including nested sub-agent/delegated-agent calls).
- A live tail: opening Traces on a board that's still processing shows new calls appear as they happen, not just after the fact.
- A lighter, board-scoped Activity view is available to any board viewer/editor — just that board's audit trail, no raw prompts, no cross-board visibility. Full Traces access stays Agent-Admin only.

## Tool Access

- Gmail, Calendar, Slack, and future channels are connected to an Agent (see Identity & Multi-Tenancy), not to a person — including a generic/shared identity (e.g. a company inbox). Each is connected through that tool's own in-app consent flow; no manually entered keys or credentials, ever.
- Board isolation still applies to context: one board's chat and tasks are never included in another board's context or history, even within the same Agent's scatterboard.

## Phase-Wise Development Plan

| Phase | Scope | Why this order |
| --- | --- | --- |
| 1. Identity, Agents & sharing | Google SSO login; Agent as the top-level entity (owns one Scatterboard, its own tool connections and budget); Agent Admin role; board-level view/edit sharing | Everything after this is scoped to an Agent, so it comes first |
| 2. Foundations | Task state machine + atomic status transitions, append-only audit log, Settings page skeleton | The backbone every later phase reads and writes through |
| 3. Manual start/stop | Start ("Manifest") and graceful Stop per board; processing/done glow; single agent, read-only work only, sequential | Lowest-risk agent behavior, explicit trigger, no external side effects yet |
| 4. Approval workflow | Chat action-request cards, approve/reject; mutating actions gated behind approval | Unlocks real actions safely, on top of Phase 2's state machine |
| 5. Tools & budget enforcement | Gmail/Calendar/Slack via each tool's own in-app OAuth, owned by the Agent; per-board, per-Agent, and global budget with graceful quota-triggered stop; resource-level locks | Needs Phase 4's approval gate before any tool can actually send or write, and a budget ceiling before it can spend |
| 6. Multi-agent orchestration | Owning Agent spawns scoped sub-agents and can delegate to peer Agents; decides parallel vs. sequential across tasks and boards; backend enforces Phase 5's locks and budgets | Adds concurrency on a foundation that already has locking, budgets, and approvals |
| 7. Glow & history polish | Full glow taxonomy (processing/done/needs-reply/needs-approval), undo/redo derived from the audit log (human-only), in-place chat edits | UI polish once the underlying states and actions are trustworthy |
| 8. Observability & Debug Console | Full LLM call logging (`llm_calls`) with live tail; one Agent Admin console (Config/Activity/Traces); lighter board-scoped Activity view for collaborators | Needs every earlier phase's data (audit log, task runs, budget, multi-agent runs) to already exist to have something to surface |

## Non-Goals & Open Questions

Non-goals for this version:
- No cross-board task references or shared task lists.
- No agent-initiated deletes, anywhere.
- No moving a board from one Agent to another — a board is created under one Agent and stays there.
- Encrypting captured LLM call data at rest is deferred — not in scope for this plan.

Open questions (all resolved):
- **Exact approval UI (inline card vs. modal)?** Decided: an inline card in the chat thread showing the proposed action with Approve / Reject buttons; no separate modal.
- **Retry/backoff policy for failed tasks?** Decided: standard exponential backoff with jitter — up to 3 retries (about 1s, 4s, 16s), honoring any Retry-After header, for transient errors only (timeouts, 429, 5xx); side-effecting actions retry only with an idempotency key; once retries are exhausted the task moves to failed.
- **Per-tool rate limits (e.g. max emails/day)?** Decided: standard per-tool defaults per Agent (token bucket, capped below each provider's own limits), adjustable by the Agent Admin; a task that hits a limit waits in queued until the window resets.
- **Per-tool rate limits, separate from the dollar/token budget caps?** Decided: yes, separate — the same standard per-tool defaults above apply alongside the budget caps; hitting a rate limit pauses the task until the window resets, while hitting a budget stops it.
- **Do board, Agent, and global budgets reset periodically (daily/monthly), or are they a fixed cap until changed?** Decided: fixed cap until changed — no periodic reset; an admin raises or resets the cap manually.
- **Can more than one user hold the Agent Admin role for a given Agent, or exactly one?** Decided: yes, an Agent can have multiple Agent Admins.
- **Does a user need to request access to a board/Agent, or can an Agent Admin invite anyone directly?** Decided: both — users can request access (an Agent Admin approves or denies), and an Agent Admin can also invite anyone directly.
- **What retention window should the LLM call log use before old entries are purged?**

## Migration Note

The current per-board chat's system prompt explicitly tells the model it "cannot edit the board" and must ask the user to make any change. That framing, and the prompt itself, need to change as part of this work. Existing chat history was generated under the old framing and can stay as read-only history — it's not a precedent for what the assistant can or can't do going forward.
