# Phase 1: Gateway Core

Goal: the gateway can connect a user's Gmail, Google Calendar and Slack through Composio and execute actions on them. The Settings page connects and disconnects through it. The monolith's tool **execution** path is unchanged until Phase 2.

## Technical Design

### Package layout (`integrations-service/app/`)

```
main.py                 app + exception handlers wiring
container.py            composition root: builds concrete classes once
config.py               bootstrap env vars only
database.py             Motor client, ensure_indexes (own DB: "integrations")
errors.py               domain exceptions + one HTTP translation table
security.py             require_internal_key (kept)
models/                 Pydantic API models + frozen value objects
backends/
  base.py               Backend protocol, Capabilities, ConnectSession, ActionResult
  composio_backend.py   the ONLY file importing the Composio SDK / calling its API
  fake_backend.py       in-memory Backend for tests
actions/
  catalog.py            ActionDef(name, tool_type, mutating, input_schema)
  composio_map.py       action name -> Composio tool slug (+ arg translation)
services/
  provider_service.py   reads registry rows, resolves tool_type -> backend
  connection_service.py create session / status / disconnect
  action_service.py     execute + proxy, read-only retry with backoff
  webhook_service.py    verify + normalize + idempotent upsert
  audit_service.py      append-only audit entries
  secret_store.py       SecretStore protocol + EnvSecretStore (DbSecretStore in Phase 3)
routers/                health, connections, execute, webhooks, providers (HTTP only)
tests/                  unit tests + backend contract suite
```

### Core types
- `Backend` (Protocol): `create_connect_session`, `get_connection`, `disconnect`, `execute_action`, `proxy`, `parse_webhook`, `capabilities`. `ComposioBackend` implements it; so does `FakeBackend`.
- `ProviderConfig` (frozen dataclass): `tool_type, display_name, backend, backend_slug, auth_mode, enabled`.
- `ActionDef` (frozen dataclass): name such as `gmail.send_email`, tool type, `mutating`, JSON-schema for args.
- Domain exceptions (`errors.py`): `UnknownProvider`, `ProviderDisabled`, `NotConnected`, `RateLimited`, `BackendUnavailable`, `ActionFailed`.

### Registry (DB-backed)
Collection `providers`, seeded on startup from `PROVIDER_SEED` (code) **only if a row does not exist**, so later edits in the admin UI are never overwritten. v1 seed:

| tool_type | backend | backend_slug (Composio toolkit) |
| --- | --- | --- |
| `gmail` | composio | `gmail` |
| `calendar` | composio | `googlecalendar` |
| `slack` | composio | `slack` |

### Action catalog (v1)
Named actions the rest of the system uses. Mutating ones mirror the three tools the monolith already has; reads are added so Phase 4 MCP has read-only tools.

| Action | Mutating | Notes |
| --- | --- | --- |
| `gmail.send_email` | yes | `to, subject, body` |
| `gmail.list_messages` | no | query, max results |
| `calendar.create_event` | yes | `title, start, end?, attendees?` |
| `calendar.list_events` | no | time range |
| `slack.post_message` | yes | `channel, text` |
| `slack.list_channels` | no | |

`composio_map.py` maps each to a Composio tool slug. **Verify every slug and argument name in your Composio dashboard's tool list before coding the mapping**; do not assume them. Add `proxy` as an escape hatch for endpoints without a named action.

### HTTP API (all except health/webhook require `X-Internal-Key`)

| Route | Purpose |
| --- | --- |
| `GET /health` | open |
| `GET /providers` | registry rows (no secrets) |
| `POST /connections/session` | `{agentId, toolType, callbackUrl}` → `{url}` (Composio Connect Link) |
| `GET /connections/{agentId}` | status for every provider; live-checks the backend, short TTL cache |
| `GET /connections/{agentId}/{toolType}` | one provider |
| `DELETE /connections/{agentId}/{toolType}` | disconnect |
| `POST /execute` | `{agentId, toolType, action, args, caller}` → `{ok, result}` |
| `POST /proxy` | `{agentId, toolType, method, endpoint, params, body}` |
| `POST /webhooks/composio` | public; signature verified; idempotent |

`userID` sent to Composio is the `agentId`.

### Error and retry behaviour
- `execute` returns a typed error body; the translation table in `errors.py` maps `NotConnected→409`, `ProviderDisabled→403`, `RateLimited→429`, `BackendUnavailable→503`, `ActionFailed→502`.
- `action_service` retries a **non-mutating** action up to 3 times with exponential backoff and jitter on 429/5xx. A mutating action is sent exactly once.

### Webhooks
`POST /webhooks/composio`: verify `webhook-id` / `webhook-timestamp` / `webhook-signature` using the webhook secret **before parsing**; reject stale timestamps; upsert into `connections` keyed on the backend connection id; record `webhook-id` to drop duplicates. Handle connection-created and `composio.connected_account.expired`. Phase 1 stores state only; relaying events to the monolith comes when something needs them.

### Data (`integrations` database)
`providers`, `connections` (`agentId, toolType, backend, backendConnectionId, status, updatedAt`; unique index on `agentId+toolType`), `audit_log`, `webhook_events` (`webhook-id`, TTL index). No tokens stored.

### Monolith changes in this phase (connect/disconnect/status only)
- `integrations_client.py`: add `create_session`, `list_connections`, `disconnect` to the `IntegrationsClient` protocol and `HttpIntegrationsClient`.
- `routers/tools.py`: `GET .../connect` calls `create_session` and `RedirectResponse`s to the returned URL (same URL, so `settings.js` needs no change); `DELETE` calls `disconnect`; the list route reads gateway status. Behind env flag `INTEGRATIONS_GATEWAY_ENABLED` (default true) so the old flow can be restored while verifying.
- Old callback routes stay until Phase 5.
- Note: until Phase 2, a tool connected through Composio shows "Connected" but tasks still run through the old simulated/OAuth path.

## Implementation Plan
- [ ] Remove `nango_client.py`, `NANGO_*` config, `.env.example` entries
- [ ] Add `motor`, `composio` SDK to `requirements.txt`; give the service its own Mongo DB
- [ ] `errors.py` with exceptions and the single HTTP translation table
- [ ] `backends/base.py` protocol + value objects; `fake_backend.py`
- [ ] Backend contract test suite; run against `FakeBackend`
- [ ] `ComposioBackend`; make it pass the same contract tests (against mocked HTTP)
- [ ] Registry: `providers` collection, seed, `provider_service`
- [ ] `actions/catalog.py` and `actions/composio_map.py`
- [ ] `connection_service`, `action_service` (retry rules), `audit_service`, `secret_store.EnvSecretStore`
- [ ] Routers: connections, execute, proxy, providers, webhooks
- [ ] `webhook_service` with signature verification and idempotency
- [ ] `container.py` composition root
- [ ] Monolith: extend `IntegrationsClient`; rewire `routers/tools.py` connect/disconnect/list; add `INTEGRATIONS_GATEWAY_ENABLED`
- [ ] Update `docker-compose.yml` (public webhook path note) and `.env.example`
- [ ] Apply Engineering Standards ([overview](composio-00-overview.md)); verify no file over 300 lines

## Actions Required From You

1. **Create a Composio account** and note the project **API key**.
2. **Create a scoped project API key with "Proxy execute" enabled** (needed by the proxy; session tool execution alone does not cover it).
3. **Create a webhook subscription** in Composio pointing at `https://<public-url>/webhooks/composio`; copy the **webhook secret**. For local dev expose port 8100's webhook path with a tunnel (ngrok or cloudflared) and tell me the URL pattern.
4. **Put the keys in `integrations-service/.env`**: `COMPOSIO_API_KEY`, `COMPOSIO_PROXY_API_KEY`, `COMPOSIO_WEBHOOK_SECRET`. They move into the admin UI in Phase 3.
5. **Confirm in the Composio dashboard** that Gmail, Google Calendar and Slack show managed auth, and send me the exact tool names and argument names for the six actions above (I will not guess slugs).
6. **Confirm identity choice:** Composio `userID` = ProjectTracker `agentId`.
7. **Email Composio support (do this now, it has lead time):** "Is your managed Google app verified for restricted Gmail scopes (`gmail.readonly`, `gmail.modify`), and which Gmail scopes are approved?" Share the answer; it decides whether Gmail production needs your own Google app.
8. Use a throwaway Google/Slack account for testing; managed consent screens will say "Composio".

## Development Best Practices

- **SRP:** `composio_backend.py` only translates between the `Backend` protocol and Composio; it contains no registry, retry, audit or HTTP-status logic. Retries live in `action_service`; audit in `audit_service`.
- **OCP:** adding a provider = a seed row + catalog entries + map entries. Prove it by adding a fake provider in tests without editing a router or service.
- **LSP:** the same contract suite (connect → status → execute → disconnect → webhook parse) runs against `FakeBackend` and `ComposioBackend`; both must pass identically.
- **ISP:** services depend on the narrow protocol they use (`Connectable` / `Actionable` / `EventSource`), not on all of `Backend`.
- **DIP:** services take `Backend`, `SecretStore`, a clock and the audit sink via constructors; only `container.py` names `ComposioBackend`. The monolith depends on `IntegrationsClient`.
- **OOP:** `ProviderConfig`, `ActionDef`, `ConnectSession`, `ActionResult` are frozen dataclasses; no dict-of-dict passing between layers.
- **Security:** never log args or results (Gmail bodies); redact the key headers; constant-time compare for the webhook signature; reject webhooks with stale timestamps.
- **300-line rule:** `composio_backend.py` is the likeliest to grow — split by concern (`composio_auth.py`, `composio_actions.py`, `composio_events.py`) before it nears 300 lines.
- **Tests:** webhook idempotency (same `webhook-id` twice), signature failure, retry applies to reads and never to writes, unknown/disabled provider, not-connected.

## UI Verification

Prerequisites: services running, keys set, tunnel up.

1. **Settings → Gmail → Connect.** You are redirected to a Composio-hosted consent page, authorize, and land back on the app. Gmail shows **Connected** (with the account label if available).
2. Repeat for **Calendar** and **Slack**. All three show Connected.
3. **Reload** the Settings page: status persists.
4. **Disconnect** Gmail: it shows not connected. Reconnect works.
5. In Composio's dashboard, delete a connection directly; reload Settings: it shows not connected (live check) — and the audit/webhook record exists.
6. Direct check (engineering): `curl -H "X-Internal-Key: …" -X POST localhost:8100/execute …` for `slack.list_channels` returns your channels; `gmail.list_messages` returns messages; a bad key returns 401.
7. Set `INTEGRATIONS_GATEWAY_ENABLED=false` and confirm the old connect flow still works (regression), then set it back.
8. Run a board task as before: tools still behave exactly as before (execution is unchanged this phase).
