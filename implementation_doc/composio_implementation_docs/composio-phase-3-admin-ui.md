# Phase 3: Admin UI

Goal: you can see which provider runs on which backend, change routing, and add or rotate credentials from a React UI on its own port — no code or config edits.

## Technical Design

### Deployment
- New container `integrations-admin` (Vite + React build served by nginx) on host port **8101**.
- nginx proxies `/api/*` to `http://integrations:8100/admin/*` over the internal docker network, so the browser never talks to the gateway directly and the gateway needs no CORS.
- Bind the published port to localhost only: `127.0.0.1:8101:80` in `docker-compose.yml`.

### Gateway admin API (`routers/admin/`, all under `/admin`)
Protected by a session cookie from `POST /admin/login` (not by `X-Internal-Key`).

| Route | Purpose |
| --- | --- |
| `POST /admin/login`, `POST /admin/logout`, `GET /admin/me` | single admin; password checked against `ADMIN_PASSWORD_HASH` (bcrypt/argon2) from env; signed, httpOnly, SameSite=Strict cookie; rate-limited login |
| `GET /admin/providers` | each provider: backend, slug, auth mode, enabled, credential status (`set`/`missing`), connection count |
| `PATCH /admin/providers/{toolType}` | change backend / slug / enabled; response includes `connectionsAffected` |
| `GET /admin/credentials` | names + `set`/`unset` + updated at/by. **Never values.** |
| `PUT /admin/credentials/{name}` | write-only set/rotate |
| `DELETE /admin/credentials/{name}` | clear |
| `POST /admin/providers/{toolType}/test-connect` | returns a connect URL for the admin's own test user |
| `POST /admin/providers/{toolType}/test-action` | run a read-only action as the test user, return status + latency (no body) |
| `GET /admin/audit` | paged audit log |

All mutating admin routes require a CSRF header (`X-Admin-CSRF`, value from `/admin/me`) in addition to the cookie.

### Secrets move into the database
- `secret_store.py` gains `DbSecretStore` (collection `backend_credentials`: `name, ciphertext, updatedAt, updatedBy`), Fernet-encrypted with `SECRETS_ENCRYPTION_KEY` from env. `container.py` composes `FallbackSecretStore(DbSecretStore, EnvSecretStore)` so env values keep working until you move them.
- `ComposioBackend` reads its API key and webhook secret via `SecretStore` at call time, so a rotation in the UI takes effect without a restart.
- Bootstrap secrets that stay in env: `SECRETS_ENCRYPTION_KEY`, `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_SECRET`, `INTERNAL_SERVICE_KEY`.

### Safe backend switching
`PATCH` with a changed `backend` and `confirm=false` returns `409` with `connectionsAffected`. Only `confirm=true` applies it, and it then marks that provider's connections `disconnected` (they cannot move between backends — no token export). Every change writes an `audit_log` entry (actor, field, old → new; credential changes record the name only, never values).

### React app (`integrations-admin/`)

```
src/
  main.jsx, App.jsx
  api/            client.js (fetch wrapper, CSRF, 401→login), providers.js, credentials.js, audit.js
  hooks/          useProviders.js, useCredentials.js, useAudit.js
  components/
    ProvidersTable.jsx      backend badge (Composio/Nango/Native), status, enabled toggle
    BackendBadge.jsx
    ProviderEditor.jsx      edit slug/backend with the confirm dialog
    ConfirmDialog.jsx
    CredentialsPanel.jsx    write-only fields; "set"/"not set"
    TestPanel.jsx           test-connect / test-action
    AuditLog.jsx
    LoginForm.jsx
  pages/          ProvidersPage.jsx, CredentialsPage.jsx, AuditPage.jsx
```
Plain React + `fetch`; no state library. UI states required: loading, empty, error, and "no gateway connection".

## Implementation Plan
- [ ] `DbSecretStore`, `FallbackSecretStore`, Fernet helpers; `SECRETS_ENCRYPTION_KEY` handling
- [ ] Admin auth: password hash check, signed session cookie, CSRF, login throttling
- [ ] `/admin` routers split by resource (providers, credentials, test, audit) — one router file each
- [ ] Provider switch with `connectionsAffected` + confirm flow + audit entries
- [ ] Rewire `ComposioBackend` to read secrets through `SecretStore` per call
- [ ] Scaffold `integrations-admin/` (Vite, React), Dockerfile (build → nginx), nginx conf with `/api` proxy
- [ ] `docker-compose.yml`: add `integrations-admin` bound to `127.0.0.1:8101`
- [ ] Build the API layer, hooks, then components; wire pages
- [ ] Tests: admin auth, CSRF, credentials never returned, switch/confirm/audit, secret rotation picked up without restart
- [ ] Apply Engineering Standards ([overview](composio-00-overview.md)); no file over 300 lines

## Actions Required From You
1. **Choose an admin password.** Generate its hash (I will provide a one-line command) and put `ADMIN_PASSWORD_HASH` in `integrations-service/.env`.
2. **Generate `SECRETS_ENCRYPTION_KEY`** (Fernet key; command provided) and `ADMIN_SESSION_SECRET`; add to `.env`. **Back up the encryption key** — losing it makes stored credentials unreadable.
3. After verifying the UI works, **remove `COMPOSIO_*` values from `.env`** (they now live in the DB).
4. Decide whether port 8101 stays localhost-only (recommended) or must be reachable from another machine; if the latter, put it behind a VPN or an authenticating reverse proxy, never open to the internet.

## Development Best Practices
- **SRP (backend):** one router per resource; `admin_auth_service`, `credentials_service`, `provider_admin_service`, `audit_service` each own one job.
- **SRP (React):** components render; hooks fetch and hold state; `api/` modules own HTTP. A component never calls `fetch` directly.
- **OCP:** the providers table renders from API data. A new provider or backend appears with no UI code change (the badge falls back to the backend's name).
- **LSP / ISP:** `SecretStore` stays a two-method protocol (`get`, `set`); the Env and Db implementations are interchangeable.
- **DIP:** admin services depend on `SecretStore`, `ProviderRepository`, `AuditSink` protocols; the React API client is injected into hooks so it can be stubbed.
- **OOP:** immutable view models for provider rows; never pass raw Mongo docs into the API layer.
- **Write-only secrets:** values are accepted once and never echoed in responses, logs, error messages or audit entries; inputs use `type="password"` with `autocomplete="off"`.
- **No secrets in the browser bundle** or in localStorage. The session cookie is httpOnly.
- **300-line rule:** if a page grows, split into components; if `providers.py` grows, split read vs. write routes.
- **Accessibility/UX:** destructive actions need a confirm dialog that states the impact in numbers.
- **Tests:** component tests for the confirm dialog and write-only inputs; API tests that assert no value ever appears in a response.

## UI Verification
1. Open `http://localhost:8101`. You see a login form; a wrong password is rejected; the correct one signs you in.
2. **Providers table** shows Gmail, Google Calendar and Slack, each with a **Composio** badge, auth mode, enabled state and credential status.
3. **Credentials:** enter the Composio API key and webhook secret. The page shows **set** but never the value; reloading still shows only **set**. Remove them from `.env` and restart the gateway: connecting Gmail from Settings still works (secrets now come from the DB).
4. **Rotate** the API key to a wrong value: a test action fails with a clear error; set the correct value: it works again, without a restart.
5. **Test panel:** run test-connect and a read-only test action for Slack; see status and latency.
6. **Switch backend:** try changing Slack's backend to another value. A dialog states how many connections will be disconnected; cancel leaves everything unchanged; confirming applies it and Settings shows Slack disconnected. Switch it back.
7. **Disable** a provider: Settings and task execution report it unavailable; re-enable restores it.
8. **Audit log** lists every change above, with actor and timestamp, and no secret values.
9. Confirm `curl localhost:8101/api/credentials` without logging in returns 401, and that the port is not reachable from another machine.
