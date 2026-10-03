# Phase 2: Monolith Integration

Goal: every tool call the monolith makes runs through the gateway. Rate limits, resource locks, approvals and budgets keep working exactly as today. The monolith no longer holds or refreshes any provider token.

## Technical Design

### Where the change lands (verified in code)
- `execution/tools.py` → `execute_tool(spec, params, tokens)` currently calls `get_connector(spec.tool_type).execute(spec.name, params, tokens)`. It becomes a call to an injected `IntegrationsClient.execute(agent_id, tool_type, action, args)`.
- `execution/approval.py` (`_execute_and_resume`) stops calling `tool_connections_service.get_valid_tokens` and passes `agent_id` instead of `tokens`.
- `agent_service.py` / `subagent.py` call `execute_tool(spec, params, None)` for **non-mutating** tools. Keep their behaviour (simulated results) unless a read-only action is wired to a real gateway call — see "Reads" below.
- `execution/dispatch.py` is **not** touched (it only groups tasks).

New `execute_tool` shape:

```python
async def execute_tool(spec, params, agent_id: Optional[str], client: IntegrationsClient) -> str
```
`spec.tool_type is None` → `spec.simulate(params)` as today. Otherwise map the tool name to a gateway action through one table (`TOOL_TO_ACTION`: `send_email→gmail.send_email`, `create_calendar_event→calendar.create_event`, `send_slack_message→slack.post_message`), then call the client.

### Behaviour mapping (preserve today's semantics)
| Gateway outcome | Monolith behaviour |
| --- | --- |
| success | result text returned to the model, as today |
| `NotConnected` | fall back to the simulated result, exactly as today when `tokens is None` |
| `RateLimited` / `BackendUnavailable` / `ActionFailed` | raise `ToolExecutionError(reason)`; the loop turns it into a tool-error result the model can report, and the reason is recorded on the task. (PRD wants a clear *blocked* reason; this is the simplest faithful version — decide in verification if you want a hard `blocked` status.) |

### Pre-authorized callers (no double counting)
Rate limit and lock are consumed in `approval.py` / `enforcement.py` **before** `execute_tool`. The monolith therefore calls the gateway with `caller="monolith"` (service key); the gateway skips its permission `check` for that caller and only writes the audit entry. This is stated in the PRD under Permission Check.

### New internal endpoints (served by the monolith, for MCP in Phase 4)
Add `routers/internal.py`, authenticated with `INTERNAL_SERVICE_KEY` (a FastAPI dependency, same pattern as the gateway), **not** reachable from the browser (no CORS route, not proxied by the Express frontend):

- `POST /internal/permission/check` `{agentId, toolType, action, mutating}` → `{decision: allow|deny|needs_approval, reason?}`
  - deny if the Agent has the tool disabled (`agent_settings.tools[tool].enabled`);
  - deny if the Agent has no connection (asks gateway);
  - consume one token via `rate_limit_service.try_consume`; deny with reason `rate_limited` when empty;
  - `mutating` and caller is MCP → `deny` with reason `approval_required_not_supported` (v1: MCP is read-only).
- `POST /internal/usage/record` `{agentId, toolType, action, outcome, durationMs}` → append to `audit_service` (monolith side).

Logic lives in a new `services/permission_service.py` (one concern); the router only validates and calls it. `PermissionGate` is a protocol so the gateway side is testable with a fake.

### Gateway side
- Implements `PermissionGate` via an `HttpPermissionGate` that calls the monolith endpoints. **Fail closed**: a timeout or non-2xx from the monolith returns `deny(reason="permission_service_unavailable")`.
- `action_service` pipeline: authenticate → (`caller != monolith`) `gate.check` → resolve backend → execute → `gate.record` + audit.

### Reads
Non-mutating tools in `tools.py` today are simulated (`search_notes` etc.) and are not connector-backed. Leave them as they are. The new read actions (`gmail.list_messages`, …) are for MCP and are not wired into the monolith's model tool list in this phase.

## Implementation Plan
- [ ] Extend `IntegrationsClient` with `execute(...)`; typed result/exception mapping in one place (`integrations_errors.py`)
- [ ] `execute_tool` accepts `agent_id` + client; add `TOOL_TO_ACTION`; remove `get_connector` import
- [ ] `approval.py`: drop token fetch, pass `agent_id`; keep lock release in `finally`
- [ ] Update `agent_service.py` / `subagent.py` call sites for the new signature
- [ ] `services/permission_service.py` + `routers/internal.py` (service-key auth)
- [ ] Gateway: `HttpPermissionGate`, pipeline in `action_service`, caller kinds
- [ ] Inject the client via the existing app wiring (module-level provider function, overridable in tests)
- [ ] Update/extend tests: `test_rate_limit_service.py`, approval tests, new `test_permission_service.py`, `test_execute_tool.py` with a `FakeIntegrationsClient`
- [ ] Apply Engineering Standards ([overview](composio-00-overview.md)); no file over 300 lines (`approval.py` is already 202 — do not push it past 300; extract helpers if needed)

## Actions Required From You
1. Complete Phase 1 verification first (all three tools connected through Composio).
2. Use a **test Slack channel** and a **test Gmail recipient** (yourself) — these actions send real messages.
3. Decide the failure behaviour: tool-error result to the model (default described above) or hard `blocked` task status for gateway/Composio outages.
4. Make sure `INTERNAL_SERVICE_KEY` is identical in `backend/.env` and `integrations-service/.env`.

## Development Best Practices
- **SRP:** `permission_service` decides; `routers/internal.py` only parses and delegates; `execute_tool` only maps tool→action and calls the client.
- **OCP:** adding a tool type means a `TOOL_TO_ACTION` entry plus a catalog entry in the gateway — no new branch in `approval.py`.
- **LSP:** the loop must not care whether the client is the real HTTP client or the fake; both raise the same typed exceptions.
- **ISP:** `execute_tool` receives only the `Actionable`-shaped client methods it needs.
- **DIP:** inject `IntegrationsClient` and `PermissionGate`; no `httpx` import in `execution/`.
- **OOP:** a frozen `GatewayResult` value object; typed `ToolExecutionError`.
- **Fail closed** on every permission failure path; log the reason, never the payload.
- **Do not refactor unrelated code** in `approval.py`/`tools.py`; keep the diff to the call-site change.
- **Tests:** NotConnected→simulated fallback; each error type; double-counting guard (monolith call never triggers a second `try_consume`); deny when tool disabled; deny when gateway/monolith unreachable.

## UI Verification
1. **Slack:** create a task that sends a Slack message to your test channel. An **approval card** appears; approve it. The message appears in Slack and the task completes with the result.
2. **Gmail:** a task that emails you; approve; the email arrives.
3. **Calendar:** a task that creates an event; approve; the event appears in Google Calendar.
4. **Not connected:** disconnect Slack in Settings and repeat step 1: the task falls back to the simulated result as before.
5. **Rate limit:** set Slack's daily capacity to 1 in Settings; run two Slack tasks; the second parks as **queued** and is not charged twice for the first (check the bucket drops by exactly 1 per call).
6. **Stop / reject:** reject an approval — nothing is sent. Hit Stop on a parked task — it stops cleanly.
7. **Outage:** `docker compose stop integrations`, approve an action: the task shows a clear failure reason (not a hang). Start it again and retry.
8. **No tokens in the monolith DB:** in Mongo, `tool_connections` has no new rows for these connections and nothing contains an access token.
9. Run `pytest` in `backend/` and `integrations-service/`: green.
