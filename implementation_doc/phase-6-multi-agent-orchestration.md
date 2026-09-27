# Phase 6: Multi-Agent Orchestration

## Technical Design

**Sub-agents (no new top-level entity)**

Implemented as nested tool-use loops within one `task_runs` row: the top-level agent call can invoke a `delegate_subtask` tool, which recursively calls `agent_service.run_task_step()` with a restricted tool allowlist (a subset of the Agent's enabled tools) and no independent budget — its spend posts to the same `runId`/`taskId` in `llm_calls`. `task_runs.parentRunId` (reserved back in Phase 2) links a sub-agent's run to its parent.

**Peer-Agent delegation**

New collection `agent_links`: `_id`, `fromAgentId`, `toAgentId`, `grantedBy`, `createdAt` — an explicit, Agent-Admin-granted permission for one Agent to call another. Without a link, `delegate_to_agent` is refused outright; it's never implicit.

A `delegate_to_agent(target_agent_id, request)` tool checks `agent_links`, then creates a task under the *target* Agent's own scatterboard (a reserved inbound-delegation board), tagged with the requesting `runId` for traceability. The requesting task transitions to `awaiting_reply` (the existing status, reused) until the delegated task resolves, and its result comes back as that reply. Delegated work spends against the *target* Agent's own budget and tools — never the requester's, per the PRD.

**Parallel vs. sequential dispatch**

Before dispatching a batch of ready tasks or sub-tasks, one lightweight orchestration LLM call groups them into an ordered sequence or independent parallel groups, based on stated dependencies and whether they name the same external target (thread/event/channel id). This is advisory only: the dispatcher still acquires Phase 5's resource locks before running anything, so a wrong grouping call degrades to "one of them waits," never a conflict.

**Concurrency cap**

`agent_settings.maxConcurrentTasks` bounds how many `task_runs` an Agent can have `running` at once — a simple `count_documents` check before starting the next one, guarding cost and DB load independent of budget.

## Implementation Plan

- [ ] `delegate_subtask` tool + recursive `run_task_step` call with a scoped tool allowlist
- [ ] `agent_links` collection + Agent Admin UI to grant/revoke delegation permission
- [ ] `delegate_to_agent` tool + inbound-delegation board/task creation on the target Agent
- [ ] Orchestration LLM call for parallel/sequential grouping (advisory only, locks still enforced)
- [ ] `maxConcurrentTasks` cap check before starting new runs
- [ ] Test: Agent A without a granted link to Agent B is refused; with a link, a delegated task's spend lands in B's `llm_calls`, not A's
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): the parallel/sequential dispatch strategy sits behind its own small interface (so a future smarter strategy is additive, not a rewrite); no file over 300 lines

## UI Verification

1. As an Agent Admin, grant Agent A a delegation link to Agent B — confirm it appears in Agent A's "delegates to" list in the UI.
2. Give Agent A a task that clearly needs Agent B's specialty, click Start — confirm chat shows a delegation message and the task's status shows `awaiting_reply` while delegated.
3. Switch to Agent B (agent switcher) — confirm a new inbound task appears there, tagged as coming from Agent A.
4. Approve/complete that inbound task under Agent B, switch back to Agent A — confirm the original task resumes and the reply appears in its chat.
5. Try the same delegation from an Agent with no granted link — confirm the UI shows a clear refusal, not a silent failure.
6. Start a board with several independent tasks — confirm more than one shows as running at the same time; give it two tasks referencing the same resource and confirm only one runs at once.

## Inputs Needed From You

None — the only "input" this phase needs is a decision Agent Admins make inside the app itself (granting one Agent permission to delegate to another via `agent_links`), not an external credential.
