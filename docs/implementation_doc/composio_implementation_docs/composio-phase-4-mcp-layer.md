# Phase 4: MCP Layer

Goal: an external Agent can connect to the gateway over MCP, see only the tools it is allowed to use, and call them. Calls pass through the same pipeline as the monolith's own calls. **v1 exposes read-only actions only.**

## Technical Design

### Transport and mounting
Mount an MCP server on the gateway at `/mcp` using the official MCP Python SDK (streamable HTTP transport). Pin the SDK version and verify its current API in its docs before coding; this is the only module allowed to import it (`app/mcp/server.py`).

```
app/mcp/
  server.py          builds the MCP app, registers the dynamic tool list
  tool_factory.py    ActionDef -> MCP tool definition (name, description, JSON schema)
  session_auth.py    bearer token -> agentId (ASGI middleware)
  adapter.py         MCP tool call -> action_service.execute(caller="mcp", agentId, ...)
app/services/mcp_token_service.py   issue / verify / revoke
```

### Authentication
- Per-Agent bearer tokens: `Authorization: Bearer <token>`. Tokens are random (≥32 bytes), shown **once** at issue time, stored **hashed** (SHA-256) in `mcp_tokens` (`agentId, hash, label, createdAt, lastUsedAt, revokedAt`). Revocation takes effect on the next call.
- A token maps to exactly one `agentId`. The MCP client can never supply or override an agent id.

### Tool list (per Agent, dynamic)
`tools/list` returns the catalog actions where **all** hold: the action is non-mutating; the provider is enabled in the registry; the Agent has a live connection (`connections`); the Agent has the tool enabled in the monolith (via `check`). Tool names are `<tool_type>_<verb>` (`gmail_list_messages`, `calendar_list_events`, `slack_list_channels`). Tool schemas come from `ActionDef.input_schema`, so they never mention Composio.

### Call pipeline (same as every caller)
authenticate token → `PermissionGate.check(agentId, toolType, action, mutating, caller="mcp")` (monolith: enablement, connection, **rate limit token consumed**) → backend execute (read retries allowed) → `PermissionGate.record` + gateway audit. Denials are returned as MCP tool errors with a readable reason (`rate_limited`, `tool_disabled`, `not_connected`); they are not HTTP failures.

### Why read-only in v1
Mutating actions need human approval, and today approvals are tied to a board/chat/task message that MCP callers do not have. `check` therefore denies mutating MCP actions with `approval_required_not_supported`. Enabling writes later requires a standalone approval record surfaced in the UI — listed as Future Work in the PRD. Budget checks are per board and do not apply to MCP calls; rate limit is the control.

### Admin UI additions
A **MCP Tokens** page: pick an Agent, issue a token (shown once, copy button), list tokens with last-used time, revoke. Backed by `/admin/mcp-tokens` routes (admin session + CSRF, as in Phase 3). Audit entries for issue and revoke.

### Data
`mcp_tokens` (new). Audit log gains `caller` (`monolith` | `mcp`) and `tokenId` on every call entry.

## Implementation Plan
- [ ] Add and pin the MCP SDK; confirm its streamable-HTTP server API
- [ ] `mcp_token_service` (issue/verify/revoke, hashed storage) + tests
- [ ] `session_auth.py` middleware resolving token → agentId
- [ ] `tool_factory.py`: build tools from the catalog filtered per Agent
- [ ] `adapter.py`: route calls through `action_service` with `caller="mcp"`
- [ ] Wire `check`/`record` for the MCP caller (monolith endpoints already exist from Phase 2); ensure mutating actions are denied
- [ ] Admin: `/admin/mcp-tokens` routes and the MCP Tokens page (hook, API module, components)
- [ ] Tests: tool list filtering, revoked token, unknown token, mutating denied, rate limit consumed once per call, no payload logging
- [ ] Apply Engineering Standards ([overview](composio-00-overview.md)); no file over 300 lines

## Actions Required From You
1. Confirm **read-only in v1** (writes via MCP are deferred until a standalone approval flow exists).
2. Pick a test client: **MCP Inspector** (`npx @modelcontextprotocol/inspector`) or Claude Code (`claude mcp add --transport http …`).
3. Have an Agent with Gmail/Calendar/Slack connected and enabled in Settings.
4. Decide where the MCP endpoint is reachable from: only the docker network and localhost (default), or exposed through a reverse proxy with TLS if an external agent must reach it.

## Development Best Practices
- **SRP:** token handling, tool construction, auth middleware and call adapting are four separate modules.
- **OCP:** tools are generated from `ActionDef`; a new action or provider appears in MCP with no MCP code change.
- **LSP:** the MCP adapter and the monolith client call the same `action_service.execute`; neither gets special treatment inside it.
- **ISP:** the MCP layer depends only on the `Actionable` and `PermissionGate` protocols and a token verifier protocol.
- **DIP:** inject `McpTokenVerifier`, `PermissionGate` and `ActionService`; only `container.py` builds concretes; tests use fakes (no SDK needed).
- **OOP:** `McpPrincipal` (frozen) carries `agentId` and `tokenId` through the call; no globals.
- **Security:** hash tokens at rest; constant-time compare; token value never logged; deny by default; reject requests that try to name another agent in tool arguments (schemas contain no `agentId` field).
- **Don't bypass the pipeline.** No MCP tool may call a backend directly.
- **300-line rule:** keep SDK glue thin in `server.py`; logic lives in services.
- **Tests:** a contract test that the same action called as `monolith` and as `mcp` produces equivalent audit entries (apart from caller).

## UI Verification
1. Admin UI → **MCP Tokens** → pick your Agent → **Issue token**. The token is shown once; reloading the page does not show it again.
2. Connect MCP Inspector (or Claude Code) to `http://localhost:8100/mcp` with that bearer token. **Tools list** shows only read-only tools for providers this Agent has connected (for example `slack_list_channels`, `gmail_list_messages`, `calendar_list_events`); no send/create tools.
3. Call `slack_list_channels`: it returns your channels. In the admin **Audit** page, an entry appears with caller `mcp`, the Agent and the token label, and no result content.
4. **Disconnect Slack** in Settings, then list tools again: Slack tools are gone. Reconnect: they return.
5. **Rate limit:** set Slack's capacity to 2/day in Settings; call a Slack tool three times: the third returns a readable `rate_limited` error. Settings' bucket reflects the consumption.
6. **Disable Slack** for the Agent in Settings: Slack tools disappear/deny.
7. **Revoke** the token in the admin UI: the very next call fails with an authentication error.
8. A request with no token or a bad token is rejected. Calling a mutating action by name (if forced) is denied with `approval_required_not_supported`.
9. Regression: board tasks still send Slack/Gmail/Calendar actions through approval exactly as in Phase 2.
