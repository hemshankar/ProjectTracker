# Composio Integration PRD — Connections Gateway

*2026-10-02 · Hemshankar Sahu*

Supersedes the backend choice in [INTEGRATIONS_PRD.md](INTEGRATIONS_PRD.md) (Nango). That document is left untouched; this one defines the gateway so Composio is the first backend and Nango or in-house connectors can be added later without changing callers.

## Overview & Goals

ProjectTracker's Agents need to act on external services (Gmail, Calendar, Slack, and many more later). Today that is done by hand-rolled connectors in `backend/app/execution/connectors/` with token storage and refresh in `tool_connections_service.py`. Every new provider is bespoke code, and the backend holds raw provider tokens.

This PRD defines **one microservice — the Connections Gateway** (`integrations-service`, scaffolded in Phase 0) — that is the only way anything in the system reaches an external service.

Goals:
- **One door.** Agents (over MCP), the monolith's tool-execution path (`execution/tools.py` `execute_tool`) and any other code call the gateway. Nothing else talks to a provider, Composio or Nango.
- **Backend-agnostic.** The gateway hides which backend serves a provider. Composio is built first; Nango and in-house ("native") connectors plug into the same interface later.
- **No raw provider tokens** in ProjectTracker's databases.
- **Operable from a UI.** Provider routing and credentials are managed from an internal admin UI, not code or config edits.
- **Agent-ready.** The gateway exposes its actions over MCP so an Agent can use them directly.
- **Rules stay in one place.** The gateway asks the monolith "may this Agent do this action?" before every call (Option A, see Permission Check).

## Scope & Non-Goals

**In scope (v1):**
- Providers: **Gmail, Google Calendar, Slack**, all on Composio managed auth.
- Gateway core: DB-backed provider registry, backend adapter interface, Composio adapter, connect sessions, action execution, proxy, webhooks.
- Monolith integration: `execute_tool` becomes a gateway client; the monolith serves the permission-check and usage-recording endpoints (used by MCP callers).
- Admin UI (React, separate port).
- MCP layer for Agents.
- Retiring `gmail.py`, `calendar.py`, `slack.py`, `google_base.py` once verified.

**Out of scope (v1):**
- The other 15 providers (Jira, Notion, HubSpot, GitHub, GitLab, Teams, Outlook, Discord, LinkedIn, Facebook, Instagram, X, TikTok, WhatsApp, Telegram). The registry and adapter interface are built so they are additions, not rewrites.
- A Nango adapter and a native-connector adapter. The interface is defined and tested with a fake backend; only Composio is implemented.
- A standalone access-control service. The permission check is a narrow interface the monolith implements in v1 (see Future Work).
- Visual workflow building, token export, multi-admin roles in the admin UI.

## Architecture

```
Admin UI (React, :8101) ─────────────┐
                                     ▼
Agents ──MCP──►┐             ┌──────────────────────────────┐
tools.py ─────►┼──────────►  │  Connections Gateway          │ ──► Composio (v1)
Other code ───►┘             │  authn → permission → backend │ ──► Nango   (later)
                             │  registry (DB) · audit · MCP  │ ──► Native  (later)
                             └──────────────┬───────────────┘
                                            │ check / record
                                            ▼
                                  Monolith (FastAPI backend)
                                  agents · tool enablement · limits · budget · approvals
```

The same pipeline runs for every call, whatever the entry point:

1. **Authenticate** the caller (service key for the monolith, per-Agent token for MCP).
2. **Ask the monolith** whether this Agent may perform this action: allow, deny, or needs-approval.
3. **Resolve** the provider's backend from the registry.
4. **Call the backend** through its adapter.
5. **Record** usage with the monolith and write an audit entry.

Deployment: one more service in `docker-compose.yml`. The API stays on the internal network; only the webhook endpoint is exposed publicly. The admin UI listens on its own port and is never publicly reachable.

## Gateway Design

**Layers** (same discipline as the monolith): `routers/` (HTTP only) → `services/` (one concern each) → `backends/` (the only code that imports a vendor SDK or calls a vendor API).

**Provider registry (database-backed).** One row per tool type: tool type, display name, backend (`composio` | `nango` | `native`), backend slug (e.g. Composio toolkit slug), auth mode, enabled flag. Code ships a seed; the admin UI edits rows at runtime. Changing a provider's backend is a row update and takes effect without a restart.

**Backend adapter interface** (a `typing.Protocol`; every backend implements the same small surface):

| Operation | Purpose |
| --- | --- |
| `create_connect_session(user_id, tool_type, callback_url)` | Returns a URL/token for the user to authorize |
| `get_connection(user_id, tool_type)` | Status: connected / not connected / expired |
| `disconnect(user_id, tool_type)` | Revoke and remove |
| `execute_action(user_id, tool_type, action, args)` | Run a named action |
| `proxy(user_id, tool_type, method, endpoint, params, body)` | Raw authenticated request (escape hatch) |
| `parse_webhook(headers, body)` | Verify and normalize an inbound event |
| `capabilities()` | Flags: supports named actions, proxy, triggers |

Adding provider #19 is a registry row. Adding a backend is one new adapter class. Neither edits routers or the pipeline.

**Named actions.** Callers use stable action names (`gmail.send_email`, `slack.post_message`), not backend tool slugs. A mapping per backend resolves an action name to a Composio tool slug (or, for another backend, a proxy request or handler). This keeps `execute_tool` and MCP tool names independent of the backend. `proxy` stays available for endpoints with no named action.

**User identity.** The Composio `userID` is the ProjectTracker `agentId`, matching how tool connections are scoped today. Fixed now because it is hard to change later.

**Events.** Backend webhooks are verified and normalized into one internal event shape (connection created, connection expired/removed, trigger fired) and relayed to the monolith. Handling is idempotent, keyed on the connection id.

**Errors.** Service-layer exceptions map to HTTP status codes in one shared place. Backend failures surface to callers as a typed error (not-connected, rate-limited, backend-unavailable, action-failed) so the monolith can move a task to `blocked` with a clear reason.

**Retries.** Composio proxy calls are sent once with no retries. The gateway retries with backoff on 429/5xx for **idempotent reads only**. Writes (send email, post message) are never auto-retried.

## Permission Check (Option A)

Before every action the gateway calls the monolith. The gateway depends on a narrow interface, not on monolith internals:

- `check(agent_id, tool_type, action) → allow | deny(reason) | needs_approval(approval_id)`
- `record(agent_id, tool_type, action, outcome, cost_units)`

The monolith implements these two internal endpoints in v1, backed by what it already owns: per-Agent tool enablement, per-tool rate limits (token bucket), budget caps, and the approval workflow. Rules live in one place; the gateway holds no copy.

- **Two caller kinds, no double-counting.** The monolith's own tool path already enforces rate limit, resource lock and approval *before* it calls `execute_tool` (`approval.py` and `enforcement.py`). Calls authenticated with the service key are therefore treated as **pre-authorized**: the gateway skips `check` and only writes the audit entry. `check` runs for **MCP callers** only. This avoids consuming a rate-limit token twice.
- **Fail closed.** If the monolith is unreachable, actions are denied and surface as a blocked reason.
- **Approvals.** Today approvals are tied to a board, chat and task message in the monolith. MCP callers have no such context, so in v1 MCP exposes **read-only actions only**; mutating actions via MCP need a standalone approval record and are Future Work.
- **Budget.** The existing budget check is per board and covers LLM spend. It does not apply to MCP calls, which have no board; MCP calls are limited by per-Agent rate limits only.
- **Extractable later.** Because the gateway depends only on this interface, a standalone access-control service can replace the monolith's implementation without changing the gateway.

## Connect Flow (v1: Gmail, Calendar, Slack)

1. User clicks Connect on the existing Settings page.
2. The frontend calls the monolith, which calls the gateway's `POST /connections/session` with `{agentId, toolType, callbackUrl}`.
3. The gateway returns a Composio Connect Link; the frontend sends the user there (or opens it in a popup) and the user authorizes.
4. Composio redirects back to `callbackUrl`; the backend's webhook confirms the connection to the gateway, which notifies the monolith.
5. Settings shows "Connected". Disconnect calls `DELETE /connections/{agentId}/{toolType}`.

The monolith's `routers/tools.py` `/connect` and `/callback` OAuth endpoints are replaced by this flow.

## Execution Flow

`execute_tool` (`execution/tools.py`) calls an injected `IntegrationsClient` (a protocol, so it is mockable) that sends `POST /execute {agentId, toolType, action, args}` to the gateway. It never special-cases a provider. A not-connected, denied or backend-down result becomes a `blocked` task with the reason. The monolith never holds, refreshes or sees a provider token.

## MCP Layer

The gateway exposes its actions as MCP tools so an Agent can use them directly.

- **Our MCP, not Composio's native MCP.** Tools are served by the gateway through the adapter interface, so they work for any backend.
- **Per-Agent scoping.** Each MCP session authenticates with a per-Agent token issued by the gateway. The tool list contains only actions for providers that Agent has connected and enabled.
- **Same pipeline.** MCP calls run the identical authenticate → permission check → backend → record flow, so enablement, rate limits and approvals apply as they do for the monolith's own tool calls (see Permission Check for how double-counting is avoided).
- **Tools.** One tool per named action (e.g. `gmail_send_email`, `slack_post_message`) plus a generic `proxy` tool.
- Tokens are revocable from the admin UI.

## Admin UI

A React app served on its own port (default `8101`), internal only.

- **Providers table:** every provider with its backend (Composio / Nango / native), auth mode, enabled flag, credential status (set / missing) and health.
- **Edit routing:** change a provider's backend or enabled flag. Changing the backend warns how many existing connections will be dropped (no token export between backends) and requires confirmation.
- **Credentials:** add or rotate the Composio API key and webhook secret, and per-provider custom OAuth client IDs/secrets. **Write-only** — values are never displayed, only "set" or "not set".
- **Test tools:** start a test connect and run a test action per provider; show recent calls and errors.
- **Agent MCP tokens:** list, issue, revoke.
- **Audit log:** who changed what, and when.
- **Access:** a single admin credential (one user for now), bound to the internal network. Separate from `INTERNAL_SERVICE_KEY`.

## Data Model (gateway database)

| Collection | Contents |
| --- | --- |
| `providers` | tool type, display name, backend, backend slug, auth mode, enabled |
| `backend_credentials` | backend, credential name, encrypted value, updated at/by |
| `connections` | agentId, toolType, backend, backend connection id, status, updated at |
| `mcp_tokens` | agentId, hashed token, created/revoked at |
| `audit_log` | actor, action, target, timestamp (admin changes and every proxied call) |

The gateway gets its own database. The monolith's `tool_connections_collection` is dropped; connection status is read from the gateway. No raw provider tokens are stored anywhere in ProjectTracker.

## Security

- **Secrets.** Stored encrypted at rest with a key from the environment (same approach as the monolith's `TOOL_ENCRYPTION_KEY`); never logged, never returned by any API. Bootstrap secrets (encryption key, admin credential, `INTERNAL_SERVICE_KEY`) come from env vars only.
- **Service auth.** Monolith ↔ gateway uses a shared service key over the internal network. MCP uses per-Agent tokens, stored hashed.
- **Webhooks.** Every inbound webhook signature is verified before processing; processing is idempotent.
- **Admin UI** is the most sensitive surface (it can reroute every call): internal-only port, its own credential, audit log on every change.
- **Fail closed** when the permission check cannot be reached.
- **Data retention.** Composio stores tool arguments/results in execution logs by default; evaluate its Zero Data Retention setting for Gmail content.

## Engineering Standards

Carried over from [implementation_doc/integration_docs/integrations-00-overview.md](implementation_doc/integration_docs/integrations-00-overview.md): routers are HTTP-only, one service module per concern, vendor SDK calls live only in `backends/`, Pydantic at every boundary, type hints throughout, config via env vars, idempotent webhooks, no source file over 300 lines, adapters and the monolith client are protocols so both sides are testable without a live vendor.

## Monolith Changes Required

- Internal endpoints implementing `check` and `record` (backed by existing tool enablement, rate-limit, budget and approval services).
- `execution/tools.py` `execute_tool` switches to the injected `IntegrationsClient`; remove `get_connector` special-casing. Callers (`approval.py`, `agent_service.py`, `subagent.py`) stop fetching tokens via `tool_connections_service.get_valid_tokens`.
- Settings page connect/disconnect flow points at the gateway; remove `/connect` and `/callback` in `routers/tools.py`.
- Retire `gmail.py`, `calendar.py`, `slack.py`, `google_base.py` and the encrypted-token logic in `tool_connections_service.py`.
- Drop `tool_connections_collection` (no live data to migrate; dev connections are re-created through the new flow).

## Rollout Phases

| Phase | Deliverable | Stop-and-verify in UI |
| --- | --- | --- |
| 0 | Scaffold (done): service, health, ping, monolith client | Settings page unchanged |
| 1 | Gateway core: DB registry, adapter interface, Composio adapter, connect sessions, webhooks, execute | Connect Gmail/Calendar/Slack from Settings via Composio; status shows Connected |
| 2 | Monolith integration: permission `check`/`record`, `execute_tool` as client, rate limit/budget/approval still enforced | Run a task that sends a Slack message and reads Gmail; confirm limits, approvals and blocked reasons |
| 3 | Admin UI | Change a provider's backend and add a credential from the UI; see audit entries |
| 4 | MCP layer | An Agent calls a Slack tool over MCP; confirm it is scoped, limited and approved like a monolith-originated call |
| 5 | Retire old connectors; delete dead code | Settings and tasks work with the old code gone |

Each phase stops for verification before the next begins.

## Prerequisites

1. A Composio account; project API key with **Proxy execute** enabled; a webhook secret. Enter them in the admin UI (or the service `.env` until Phase 3).
2. Confirm in Composio's dashboard that Gmail, Google Calendar and Slack show managed auth, and run one test connect.
3. Ask Composio support (see Risks) about Gmail production scopes.

## Cost

Composio's published Hobby tier is $0 with 100,000 tool calls and 50,000 triggers per month and unlimited connected accounts; Pro is $29/month with overage of $0.0003 per tool call. Verify current pricing on composio.dev/pricing before launch. Advanced white-labeling is $0.30 per connection as an add-on.

## Risks & Open Questions

- **Gmail production approval (unconfirmed).** Composio's docs do not state whether its managed Google app is verified for restricted Gmail scopes (reading mail). Ask Composio support in writing. If not covered, a custom Google OAuth app plus Google's verification (~6 weeks) and an annual security assessment (CASA) becomes our responsibility, with any backend.
- **Shared quota on managed apps.** Quota is shared with all Composio customers; expect intermittent 429s under load. Mitigation: gateway retry/backoff for reads, clear blocked reasons, and moving to our own OAuth app for production.
- **Fixed scopes and Composio branding** on managed consent screens.
- **No token export.** Moving off Composio means every user reconnects. Using our own OAuth apps does not remove this.
- **Polling latency.** Gmail new-message triggers on managed auth are polling-based (reported around 40–75 seconds; 15-minute minimum polling interval is documented).
- **Proxy limits.** Cross-domain requests are rejected and calls are sent once. Verify attachment/file downloads work through named actions.
- **Tool coverage.** Confirm each v1 action we need (send/read mail, list/create events, post/read Slack messages) exists as a Composio tool.
- **New single point of failure.** Every tool-using task depends on the gateway and Composio. Failures must move tasks to `blocked` with a reason, never hang.
- **Admin UI as attack surface.** It can reroute all traffic; keep it internal, authenticated and audited.
- **Disconnect sync.** Confirm Composio emits an event when a user disconnects outside ProjectTracker; `connected_account.expired` is documented, user-initiated removal is not confirmed.

## Future Work

- Remaining 15 providers (registry rows; X and WhatsApp need our own credentials, Telegram needs bot-token entry).
- Nango adapter and native-connector adapter.
- Standalone access-control service implementing the same `check`/`record` interface.
- Triggers (e.g. new Gmail message starts a task) once the monolith has an inbound path for them.
- Multi-admin roles for the admin UI.

## Success Metrics

- Time to add a new provider: under 1 hour (a registry row and action mappings).
- Time for an Agent Admin to connect a tool: under 1 minute, no manual token entry.
- Zero raw provider tokens in ProjectTracker's databases.
- 100% of tool calls pass through the gateway pipeline (no direct provider calls from the monolith).
- Old connector code (~4 files) deleted after Phase 5.
