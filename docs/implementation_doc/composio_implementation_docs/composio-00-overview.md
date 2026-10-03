# Connections Gateway — Technical Design & Implementation Plan

Companion to [Composio_Integration_PRD.md](../../Composio_Integration_PRD.md). One document per phase. Each has a technical design, an implementation checklist, **Actions Required From You**, **Development Best Practices**, and a **UI Verification** pass. Work stops at the end of every phase for you to verify.

| Phase | Focus | Status |
| --- | --- | --- |
| [Phase 0: Scaffold](composio-phase-0-scaffold.md) | Service, health, ping, monolith client | Done |
| [Phase 1: Gateway Core](composio-phase-1-gateway-core.md) | DB registry, adapter interface, Composio adapter, connect, execute, webhooks; Settings page connects via Composio | Next |
| [Phase 2: Monolith Integration](composio-phase-2-monolith-integration.md) | `execute_tool` becomes a gateway client; `check`/`record` endpoints | |
| [Phase 3: Admin UI](composio-phase-3-admin-ui.md) | React admin on its own port; secrets and routing editable | |
| [Phase 4: MCP Layer](composio-phase-4-mcp-layer.md) | Per-Agent MCP tools, read-only in v1 | |
| [Phase 5: Retire Old Code](composio-phase-5-retire-old-connectors.md) | Delete hand-rolled connectors and token storage | |

## What the existing code looks like (verified)

These facts shape every phase; they correct an assumption in earlier drafts.

- Real tool execution is `execute_tool` in `backend/app/execution/tools.py`, called from `execution/approval.py` (`_execute_and_resume`). `execution/dispatch.py` is only the task-grouping strategy and is **not** touched.
- `agent_service.py` and `subagent.py` call `execute_tool(spec, params, None)` for non-mutating tools (simulated); mutating tools only run after human approval in `approval.py`.
- Rate limit (`rate_limit_service.try_consume`) and the resource lock are enforced in `approval.py` / `enforcement.py` **before** `execute_tool`. Budget (`check_budget`) is per board, for LLM spend.
- Tokens come from `tool_connections_service.get_valid_tokens`, which refreshes via `get_connector(...)`.
- Settings page (`frontend/public/settings.js`) connects via `GET /api/agents/{id}/tools/{tool}/connect` (a redirect) and disconnects via `DELETE /api/agents/{id}/tools/{tool}`. The frontend is vanilla JS served by Express; only the new admin UI is React.
- `TOOL_TYPES = ("gmail", "calendar", "slack")` in `models_settings.py`.

## Engineering Standards (apply to every phase)

**SOLID**
- **Single Responsibility.** `routers/` parse and validate HTTP and call one service. Each service owns one concern (`connection_service`, `action_service`, `webhook_service`, `audit_service`, `secret_store`). Nothing does two.
- **Open/Closed.** A new provider is a row in the registry plus entries in the action catalog. A new backend is one new class implementing `Backend`. Neither edits routers, the pipeline or `execute_tool`.
- **Liskov Substitution.** Every `Backend` implementation is interchangeable behind the protocol; no `isinstance` checks and no `if backend == "composio"` outside `backends/`. A `FakeBackend` used in tests must pass the same contract tests as `ComposioBackend`.
- **Interface Segregation.** Small protocols, not one large one: `Connectable` (session, status, disconnect), `Actionable` (execute, proxy), `EventSource` (webhook parsing), `SecretStore` (get/set), `PermissionGate` (check/record). A backend that cannot do a thing declares it via `capabilities()` instead of implementing a stub that raises.
- **Dependency Inversion.** Services take their collaborators through constructors (a `Backend`, a `SecretStore`, a `PermissionGate`, a clock). Only the composition root (`app/container.py`) builds concrete classes. The monolith depends on an `IntegrationsClient` protocol, never on `httpx` directly.

**OOP**
- Immutable value objects (`@dataclass(frozen=True)`) for `ProviderConfig`, `ActionDef`, `ConnectSession`, `ActionResult`, `PermissionDecision`.
- Composition over inheritance: services hold a backend; no service subclasses a backend.
- Typed domain exceptions (`NotConnected`, `ActionDenied`, `RateLimited`, `BackendUnavailable`, `ActionFailed`), translated to HTTP status codes in **one** handler module, never ad hoc `HTTPException` per branch.
- Pydantic models at every API boundary; type hints on every function signature.

**File size**
- **No source file over 300 lines** (Python, JS, JSX). Where a phase names one concern, treat it as a package and split by responsibility once it grows. Check with `find <dir> -name '*.py' -o -name '*.js*' | xargs wc -l | sort -n | tail`.

**Testing**
- Unit tests use fakes (`FakeBackend`, `FakePermissionGate`, in-memory stores), never a live vendor. One contract test suite runs against every `Backend` implementation.
- Every phase ends with the suite green (`pytest` in the service and in `backend/`).

**Config and secrets**
- Bootstrap secrets only from environment variables. Everything else lives in the database, encrypted. No secret in code, logs, API responses or error messages. `.env` files stay gitignored; `.env.example` documents every variable.

**Other**
- Webhooks: verify signature first, then process idempotently (upsert keyed on the backend connection id).
- Retries: backoff on 429/5xx for **idempotent reads only**; never auto-retry a write.
- One log line per call with caller, provider, action, outcome and duration, with no payload contents.
