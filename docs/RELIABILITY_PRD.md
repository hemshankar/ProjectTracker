# Task Resume & Multi-Replica Execution PRD

*2026-09-27 · Hemshankar Sahu*

Source (live, editable): https://claude.ai/code/artifact/6ac34359-d7b2-4fb7-9227-6c9d101305be

## Overview & Motivation

A reliability audit of Manifestation Board's execution engine (the code that runs an Agent's tasks and sub-agents) found two gaps that only matter once the backend restarts or scales: in-flight work is lost rather than resumed, and the whole execution model assumes exactly one backend process is ever running. Three smaller, already-shipped fixes (closing orphaned sub-agent run records, cancelling in-flight runner tasks gracefully on shutdown, and notifying connected clients before a restart) reduce the damage from both gaps but don't solve either one. This PRD covers the two remaining, larger problems:

- **Problem A — Task/Sub-agent Resume After a Crash**: a restart currently fails every in-flight task rather than continuing it from where it stopped.
- **Problem B — Multi-Replica / Horizontal Scaling Support**: the execution engine can only safely run as a single backend process; running two would risk one replica's restart corrupting another's live work.

Out of scope: encrypting the LLM call log at rest, cross-region deployment, and any UI work beyond what's needed to show a resumed vs. restarted task in its history.

## Problem A: Task/Sub-agent Resume After a Crash

Today a crash mid-task is fail-fast, not resume: `reconcile_interrupted_runs` marks any task/board a dead process left `running` or `queued` as `failed`, with reason `Interrupted by server restart`; a companion sweep closes any dangling `task_runs` record (including sub-agent runs) the same way. The task only starts again when a user re-triggers it, and it starts from zero — none of the reasoning, partial tool output, or spend from before the crash carries forward.

**Goal.** A task interrupted mid-run picks back up from its last completed step instead of restarting cold, without ever double-executing a mutating action (sending an email, writing a calendar event) that already went out before the crash.

**Proposed design — checkpoint at round boundaries.** `AgentRunner` already drives a task through discrete rounds (one model turn plus its tool calls, appended to the chat as a batch). Persist a checkpoint on the task's `task_runs` document after each round completes — which round it's on, and the chat message range already committed — rather than only writing a final status at the end. On startup, a task found `running` is split into two cases instead of one: if it has a completed-round checkpoint, it's requeued `idle` with that checkpoint attached, and `AgentRunner` resumes the conversation from there on its next pickup; if it crashed before completing any round (or mid-round, e.g. mid tool call), it's still failed outright, exactly as today — there's nothing safe to resume from partway through a round.

**Alternatives considered.**
| Option | Description | Effort |
| --- | --- | --- |
| A1. Keep fail-and-retry (status quo) | No change; rely on the existing reconciliation sweep and manual re-run | None |
| A2. Round-boundary checkpoint (recommended) | Resume from the last fully-completed round; anything mid-round still fails | Medium |
| A3. Full mid-round resume | Reconstruct exact partial model/tool-call state and continue mid-round | High, fragile |

**Recommendation.** A2, scoped to primary task runs first. Sub-agent runs are cheap, bounded delegations — re-running one from scratch costs little, so they can stay on the existing fail-fast path (A1) rather than carrying checkpoint logic too.

**Cost/effort.** Medium: a `checkpoint` field on `task_runs`, a persist-after-each-round write in `loop.py`/`agent_service.py`, and splitting `reconcile_interrupted_runs`'s zombie handling into resumable vs. not. Mutating actions stay safe under this design only because they already require human approval before executing (per the existing PRD's Execution Model) — a checkpoint is only ever taken after a round finishes, never mid-action.

## Problem B: Multi-Replica / Horizontal Scaling Support

`RunnerRegistry`, the in-process map of which `asyncio.Task` is driving each board, is explicitly documented as a single-process assumption. Board and task claiming already goes through an atomic, conditional Mongo update, so two processes can't both claim the *same* task — but nothing decides *which* replica should be running a given board's loop at all, and nothing detects a replica dying mid-task except that same replica's own next startup. Run two replicas today and a rolling restart of replica 1 would run `reconcile_interrupted_runs` against the whole database and fail every board — including ones replica 2 is actively, healthily working on. Multi-replica isn't just "not yet built"; it's actively unsafe with the current reconciliation design.

**Goal.** Run more than one backend replica safely: a replica's restart or crash only affects boards *it* was running, a healthy peer's work is never touched, and a board a dead replica was running gets picked up elsewhere automatically rather than waiting for that replica to come back.

**Proposed design — leases instead of a startup sweep.** Add a lease with a heartbeat to each actively-running board: a `holder` (a stable per-replica instance id) and a `leaseExpiresAt` the owning `AgentRunner` renews on an interval, using the same compare-and-swap pattern already used for task claiming. Claiming a board to run means acquiring this lease, not just flipping its status. Reconciliation stops being a startup-only pass over the whole database and becomes a periodic sweep — runnable from any replica, not tied to any one process's own restart — that only touches boards whose lease has actually expired (its holder stopped heartbeating), leaving every board with a live lease alone regardless of which replica currently holds it.

**Alternatives considered.**
| Option | Description | Effort |
| --- | --- | --- |
| B1. Stay single-instance | No change; document the limit, revisit if scaling is ever needed | None |
| B2. Mongo-based leases (recommended) | Lease/heartbeat per board, periodic expiry sweep; no new infrastructure | Medium–large |
| B3. External durable queue (Redis/SQS/Celery) | Replace the DB-polling model with a dedicated broker | Large, new infra dependency |

**Recommendation.** B1 unless horizontal scaling is an actual near-term need — this is real infrastructure work, not worth building speculatively. If it is needed, B2 first: it reuses patterns already in this codebase and adds no new dependency. B3 only becomes worth its cost if Mongo-polling throughput or backpressure genuinely becomes the bottleneck, which nothing today suggests.

**Cost/effort.** Large: touches board claiming (`/start`), replaces the startup-only reconciliation pass with a periodic lease-expiry job, and needs a stable per-replica instance id plus real failover testing (kill a replica mid-task, confirm a peer picks the board up within one lease TTL).

## Non-Goals

- Encrypting the captured LLM call log at rest — already a deferred item in the base PRD, unaffected by this work.
- Full mid-round resume (rejected as Option A3 above): reconstructing exact partial model/tool-call state is high-effort and fragile relative to its benefit.
- An external message broker (Option B3) — only revisited if Mongo-polling throughput genuinely becomes a bottleneck.
- Cross-region deployment or any infrastructure beyond running more than one replica in one region.
- Frontend work beyond showing whether a task's history entry was a resume or a fresh restart.

## Phased Rollout Plan

| Phase | Scope | Depends on |
| --- | --- | --- |
| 0. Reconciliation hygiene (shipped) | Close orphaned sub-agent `task_runs` records on startup; cancel in-flight runner tasks gracefully on shutdown; notify connected SSE clients before a restart | None — already landed |
| 1. Checkpoint schema (Problem A) | Add `checkpoint` to `task_runs`; persist it after each completed round in `loop.py`/`agent_service.py` | Phase 0 |
| 2. Resume on reconciliation (Problem A) | Split zombie handling into resumable (requeue `idle` with checkpoint) vs. not (fail as today); `AgentRunner` resumes from a checkpoint when present | Phase 1 |
| 3. Leases (Problem B, only if scaling is confirmed needed) | Add `holder`/`leaseExpiresAt` to board claiming; replace status-flip claiming with lease acquisition | Phase 2 (reconciliation logic is the same code both problems touch) |
| 4. Periodic lease sweep (Problem B) | Replace the startup-only reconciliation pass with a periodic, any-replica-runnable expiry sweep; add a stable per-replica instance id | Phase 3 |
| 5. Failover testing (Problem B) | Kill a replica mid-task; confirm a peer picks up the board within one lease TTL and no board with a live lease is ever touched | Phase 4 |

## Open Questions

- [ ] Do we actually need, or expect to need within the next few months, more than one backend replica? This decides whether Problem B is worth building now or deferring indefinitely.
- [ ] Is preserving partial progress/spend on a crashed task (Problem A) worth the schema and loop complexity, given tasks already retry automatically and cheaply once failed?
- [ ] What lease TTL and heartbeat interval balances fast failover against falsely taking over a replica that's just slow, not dead?
- [ ] Should sub-agent (delegated) runs get resume support too, or stay on the fail-fast path indefinitely (current recommendation: fail-fast only, since they're cheap to redo)?
