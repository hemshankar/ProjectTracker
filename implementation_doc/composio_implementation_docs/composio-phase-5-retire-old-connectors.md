# Phase 5: Retire the Old Connectors

Goal: delete the hand-rolled connector code and token storage now that everything runs through the gateway. This phase only removes code; it adds no features.

**Gate:** do not start until Phases 1–4 are verified. Deleting is the least reversible step, so do it on a branch and commit before and after.

## Technical Design

### Delete
| Path | Why |
| --- | --- |
| `backend/app/execution/connectors/` (`base.py`, `registry.py`, `gmail.py`, `calendar.py`, `slack.py`, `google_base.py`, `__init__.py`) | replaced by the gateway |
| `backend/app/services/tool_connections_service.py` encryption, refresh and token paths | no tokens held in the monolith; keep only what `list_statuses` needs, delegated to the gateway client, or fold into a thin `tool_status_service.py` |
| `backend/app/models_tools.py` → `ConnectedTokens`, `connection_status_json` token fields | no tokens |
| `backend/app/crypto.py` | delete only if the grep below shows no other user |
| `backend/app/routers/tools.py` → `/api/tools/google/callback`, `/api/tools/slack/callback`, `_handle_callback`, `sign_state`/`verify_state` use | OAuth now returns through Composio |
| `database.py` → `tool_connections_collection` and its index | no longer used |
| `config.py` → `TOOL_ENCRYPTION_KEY`, `GOOGLE_TOOLS_REDIRECT_URI`, `SLACK_CLIENT_ID/SECRET/REDIRECT_URI` | no longer used |
| `backend/.env.example` entries for the above | tidy |
| `INTEGRATIONS_GATEWAY_ENABLED` flag and the old branch in `routers/tools.py` | single path now |
| Tests that exercise the deleted code | replace with gateway-client tests |

### Keep
`GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` (they belong to **login**, not tools), `rate_limit_service`, `lock_service`, `budget_service`, the approval workflow, and `TOOL_TYPES`.

### Safety checks before deleting
1. `grep -rn "get_connector\|ConnectedTokens\|tool_connections_collection\|crypto\b" backend/` — every remaining hit must be in code being deleted.
2. `grep -rn "SLACK_\|GOOGLE_TOOLS\|TOOL_ENCRYPTION" backend/ frontend/ docker-compose.yml` — same rule.
3. Confirm `crypto.py` has no use outside tool storage; otherwise leave it.
4. Drop the old Mongo collection in dev **after** the code is gone (`db.tool_connections.drop()`); there is no live data to migrate.

### Clean the gateway too
Remove any leftover Nango scaffolding (`nango_client.py`, `NANGO_*` settings) if Phase 1 left any, and remove dead seeds.

## Implementation Plan
- [ ] Create a branch; commit a checkpoint
- [ ] Run the grep safety checks and list every remaining reference
- [ ] Remove the `connectors/` package and fix imports
- [ ] Remove token logic from `tool_connections_service.py` (or replace with `tool_status_service.py` calling the gateway)
- [ ] Remove callbacks and signed-state use from `routers/tools.py`; drop the feature flag
- [ ] Remove unused config, collection, models, `.env.example` entries
- [ ] Delete or rewrite affected tests; run `pytest` for both services
- [ ] Update `README.md` / `PRD.md` tool-connection sections that describe the old OAuth flow
- [ ] Final size and dead-code check across both services (no file over 300 lines; no unused imports)

## Actions Required From You
1. Confirm Phases 1–4 are verified and approve starting the deletion.
2. **Optional cleanup in provider consoles:** the old Google OAuth redirect for tools (`/api/tools/google/callback`) and the old Slack app redirect can be removed; the login OAuth client stays.
3. Reconnect any tool connections made through the old flow (their data is dropped).
4. Review the final diff before merging.

## Development Best Practices
- **Delete, don't deprecate.** No commented-out code, no "removed" stubs, no compatibility shims.
- **SRP/OCP check:** after deletion no module in `execution/` or `services/` should import a provider-specific class; provider knowledge exists only in the gateway registry and catalog.
- **DIP check:** the monolith's only integration dependency is `IntegrationsClient`.
- Make deletions in small commits (connectors, then token service, then routes, then config) so any one can be reverted.
- Let the tests and imports guide you: run the suite after each deletion step.
- Keep the diff free of unrelated formatting changes.
- Re-verify the 300-line rule on any file you touched.

## UI Verification
Full regression, in order:
1. App starts cleanly: `docker compose logs backend` has no import errors or warnings about missing config.
2. **Settings:** Gmail, Calendar and Slack connect, show Connected, persist after reload, and disconnect.
3. **Tasks:** a Slack message, an email and a calendar event each go through approval and arrive; reject sends nothing; Stop works.
4. **Not connected:** disconnect a tool and confirm the simulated fallback.
5. **Rate limit and lock** behaviour as in Phase 2 steps 5–6.
6. **Admin UI:** providers, credentials, test panel, audit log and MCP tokens all work.
7. **MCP:** list and call a read-only tool.
8. **Login** with Google still works (its OAuth client was kept).
9. Mongo: `tool_connections` is gone and no token-shaped fields exist anywhere in the monolith database.
10. `pytest` green in `backend/` and `integrations-service/`; line-count check shows no file over 300 lines.
