# Manifestation Board Agent — Technical Design & Implementation Plan

Companion to the [Manifestation Board Agent PRD](../PRD.md) — one document per phase, each with a technical design and an implementation checklist.

Live, editable version: https://claude.ai/code/artifact/05b7ff97-cdf6-458a-a0c9-fa7ad086fc19

| Phase | Focus |
| --- | --- |
| [Phase 1: Identity, Agents & Sharing](phase-1-identity-agents-sharing.md) | Google SSO, the Agent entity, Agent Admin, board sharing |
| [Phase 2: Foundations](phase-2-foundations.md) | Task state machine, atomic transitions, audit log, Settings skeleton |
| [Phase 3: Manual Start/Stop](phase-3-manual-start-stop.md) | Board glow, the execution loop, read-only agent work |
| [Phase 4: Approval Workflow](phase-4-approval-workflow.md) | Chat action-request cards, approve/reject |
| [Phase 5: Tools & Budget Enforcement](phase-5-tools-budget-enforcement.md) | OAuth connections, budgets, rate limits, resource locks |
| [Phase 6: Multi-Agent Orchestration](phase-6-multi-agent-orchestration.md) | Sub-agents, peer delegation, parallel vs. sequential |
| [Phase 7: Glow & History Polish](phase-7-glow-history-polish.md) | Full glow taxonomy, undo/redo, in-place chat edits |
| [Phase 8: Observability & Debug Console](phase-8-observability-debug-console.md) | Full LLM call tracing, live tail, Agent Admin console (Config/Activity/Traces) |

## Engineering Standards

Applies to every phase below — each phase's Implementation Plan has a checklist item pointing back here.

**SOLID**
- **Single Responsibility** — routers only parse/validate HTTP input and call a service; a service only orchestrates one bounded concern (auth, sharing, task execution, budget, ...); anything beyond a trivial single-document read/write gets its own small module, never scattered across routers.
- **Open/Closed** — tool integrations (Gmail/Calendar/Slack, Phase 5) implement one common `ToolConnector` interface (`connect()`, `refresh()`, `execute(action, params)`); adding a fourth tool later means adding a new class, never editing the dispatch code that calls connectors.
- **Liskov Substitution** — every `ToolConnector` subclass is interchangeable wherever the interface is used; the execution loop never checks `isinstance(connector, GmailConnector)` to special-case behavior.
- **Interface Segregation** — narrow, purpose-built interfaces over one do-everything base (e.g. an `Approvable` protocol for anything that can be approved/rejected, separate from `Runnable` for anything the execution loop can step through) rather than one bloated `Task` interface.
- **Dependency Inversion** — routers and the execution loop depend on abstractions (a `BudgetChecker`, a `ToolConnector`, a `LockManager` protocol) injected via FastAPI's `Depends`, never a concrete Mongo collection imported directly — this is what keeps the system testable without a live database.

**Backend design**
- Layered structure: `routers/` (HTTP only) → `services/` (business logic, one module per bounded concern) → small dedicated data-access helpers for anything beyond trivial single-document CRUD (compare-and-swap, aggregation, multi-step queries).
- Idempotency by construction: every side-effecting write goes through a `transition_task_status`-style compare-and-swap (introduced in Phase 2), never a bare `update_one` — stated here as the general rule, not a one-off.
- Config via environment variables only (already the pattern in `config.py`); no secrets in code.
- Errors translated from service-layer exceptions to HTTP status codes in one shared place, not ad hoc `HTTPException`s scattered per branch.
- Type hints on every function signature; Pydantic models at every API boundary (already the pattern in `models.py`) — extend that discipline to internal service inputs/outputs too.
- Where two different concepts could share a name across phases (e.g. "agent" the top-level entity from Phase 1 vs. the per-task LLM execution loop from Phase 4), keep them in clearly separate modules — `services/agents.py` (entity/membership CRUD) vs. an `execution/` package (the tool-use loop) — never one file doing both.

**OOP**
- Prefer a small class with one clear responsibility over a bag of module-level functions once there's real state or several related operations to group (e.g. an `AgentRunner` class encapsulating one board's execution loop, rather than free functions passing the same arguments around).
- Composition over inheritance: an `AgentRunner` *uses* a `BudgetChecker` and a `LockManager`; it doesn't inherit from them.
- Abstract base classes / `typing.Protocol` for anything with more than one implementation, or that will grow one (tool connectors; the parallel/sequential dispatch strategy in Phase 6) — the seam is what makes "add a tool" or "add an Agent capability" additive instead of invasive, even with only one implementation today.

**File size**
- No source file over 300 lines. Where a phase's design names one file for a whole concern (e.g. "the execution loop"), treat that as the package, not literally one file — split by responsibility once it grows (e.g. `execution/loop.py`, `execution/context.py`, `execution/registry.py`). A simple line-count check in CI or a pre-commit hook enforces this automatically rather than relying on remembering to check.
