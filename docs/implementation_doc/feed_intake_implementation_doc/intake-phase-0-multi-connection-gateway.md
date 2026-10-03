# Phase 0: Multi-Connection Gateway

Goal: one agent can hold several connections of the same tool (two Gmail accounts), each with an optional owner and a visibility, without breaking any existing caller. No intake code yet.

## Technical Design

### Problem (verified)
`connections` has a unique index on `agentId+toolType`; `ConnectionService.status/disconnect` and its cache use `(agent_id, tool_type)`; `Backend` methods take `user_id` plus `ProviderConfig`; `ComposioBackend` looks accounts up by `user_ids` + `toolkit_slugs`. There is no way to address "the second Gmail".

### New concepts
- **`connectionId`:** gateway-generated id (`conn_<uuid>`), the stable handle for one account.
- **`label`:** human account name (email), read from the backend after connect.
- **`ownerUserId`:** null means shared; a user id means personal.
- **`visibility`:** `agent` or `owner`. Derived: `owner` iff `ownerUserId` is set (stored for query speed).
- **`isDefault`:** the connection that a bare `(agentId, toolType)` resolves to. Exactly one per agent+tool among shared connections.
- **`backendUserId`:** the id sent to Composio as `user_id`. Existing connections keep `backendUserId = agentId`, so nothing changes at Composio. New connections use `"{agentId}:{connectionId}"`, which gives each a distinct Composio user and avoids ambiguity in `_accounts()`.

### Data migration (`connections` collection)
Idempotent startup migration in `database.py`/`ensure_indexes`:
1. For each doc without `connectionId`: set `connectionId`, `ownerUserId=null`, `visibility="agent"`, `isDefault=true`, `backendUserId=agentId`.
2. Drop the unique index `agentId+toolType`. Create unique `connectionId`, a unique partial index on `(agentId, toolType)` where `isDefault=true`, and an index on `(agentId, ownerUserId)`.
3. Re-runnable: skips docs already migrated.

### Value objects (`models/`)
`ConnectionRef(agent_id, tool_type, connection_id: str | None)` (frozen). `None` means "the default". `ConnectionRecord` carries the fields above. The `Backend` protocol changes from `user_id: str` to `ref: BackendRef(user_id, connection_id)`. Backends only use `user_id`; `connection_id` is passed for logging/metadata. `FakeBackend` keys on `(user_id, tool_type)` and works unchanged.

### Service changes (`services/`)
- `connection_resolver.py` (new, small): `resolve(ref, caller) -> ConnectionRecord`. Rules: explicit `connection_id` returns that record, else the default shared connection, else the caller's single personal one, else `NotConnected`. Applies visibility: a record with `visibility="owner"` is returned only if `caller.user_id == ownerUserId`, otherwise `ConnectionForbidden` (maps to 403).
- `connection_service.py`: `create_session` accepts `owner_user_id`, `label_hint`; pre-creates the record in `pending` state with a new `connectionId` and `backendUserId`, and the callback activates it. `status_all(agent_id, caller)` returns a list (all visible connections per tool). Cache key becomes `(agent_id, connection_id)`.
- `action_service.py`: `execute` accepts optional `connectionId`; goes through the resolver.
- If `connection_service.py` approaches 300 lines, split `connection_queries.py`.

### HTTP API (backward compatible)

| Route | Change |
| --- | --- |
| `POST /connections/session` | adds optional `ownerUserId`, `label`; returns `{url, connectionId}` |
| `GET /connections/{agentId}` | returns **all** visible connections (`connectionId, toolType, label, ownerUserId, isDefault, status`); a new `X-Acting-User` header drives visibility |
| `GET /connections/{agentId}/{toolType}` | unchanged; returns the default (or first visible) |
| `DELETE /connections/{agentId}/{toolType}` | unchanged; deletes the default |
| `DELETE /connections/{agentId}/by-id/{connectionId}` | new; disconnect one |
| `POST /execute` | adds optional `connectionId`; omitted means default |
| `POST /connections/{agentId}/by-id/{connectionId}/default` | new; make a shared connection the default |

`X-Acting-User` is trusted only because requests carry the internal key. The monolith sets it from the authenticated user.

### Monolith changes
- `integrations_client.py`: extend `IntegrationsClient` and `HttpIntegrationsClient` with optional `connection_id`, `owner_user_id`, `acting_user`. Existing positional calls keep working.
- `routers/tools.py`: connect route accepts optional `?personal=true&label=`; passes the acting user; list route returns all connections. `GET .../connect` stays a redirect, so `settings.js` keeps working.
- `execution/tools.py`: no change; it uses the default. Add an optional `account` param to tool schemas so an agent can pick a connection by label; resolve the label to `connectionId` through the list call.
- Permission check on the monolith side: only agent admins create shared connections; any member may create personal ones.

### Settings page (small)
`frontend/public/settings.js`: per tool, list connected accounts with label and "personal/shared" badge, a **Connect another account** button, and per-account Disconnect. If this pushes the file near 300 lines, extract `settings-connections.js`.

## Implementation Plan
- [ ] Add `ConnectionRef`, `ConnectionRecord`, `BackendRef` value objects; update `Backend` protocol signature and `FakeBackend`/`ComposioBackend` call sites
- [ ] Startup migration + new indexes; migration unit test on a legacy-shaped fixture (run twice, assert idempotent)
- [ ] `connection_resolver.py` with visibility rules
- [ ] Rework `connection_service` (multi-record, `pending` activation, cache key); add `set_default`
- [ ] `action_service` and routers accept `connectionId` and `X-Acting-User`
- [ ] New by-id routes; keep the old routes as aliases to the default
- [ ] Composio callback/webhook handler activates the right pending record by `backendUserId`
- [ ] Monolith: client protocol, `routers/tools.py`, role checks, optional `account` tool arg
- [ ] `settings.js` multi-account list and "connect another"
- [ ] Contract tests: two connections for one agent+tool; personal hidden from others; default resolution; legacy single-connection flow unchanged
- [ ] Update `.env.example` (nothing new expected) and `docs` notes; verify no file over 300 lines

## Actions Required From You
1. **Confirm in Composio** that connecting two accounts under distinct `user_id` values for the same toolkit works with your managed auth config. I will not assume this. If it does not, I will propose using one `user_id` with account selection by `connected_account_id`.
2. Confirm the `backendUserId = "{agentId}:{connectionId}"` scheme is acceptable (existing connections keep `agentId`, so nothing is reconnected).
3. Have two test Gmail accounts ready (one can be a throwaway).
4. Back up the `integrations` Mongo database before the first run with migration code (`mongodump`).

## Development Best Practices
- **SRP:** the resolver only resolves and authorizes; `connection_service` only manages lifecycle; the action path never re-implements visibility.
- **OCP/LSP:** the `Backend` signature change is made once; both backends pass the same contract suite, extended with a two-connection case.
- **DIP:** services get the resolver by constructor; `container.py` is the only place wiring changes.
- **Backward compatibility is a test, not a hope:** keep the existing test files green without edits, and add new tests beside them.
- **Safe migration:** idempotent, no deletes of data, index swap in the order create-new then drop-old.
- **Security:** `X-Acting-User` is honored only with a valid internal key; personal connection labels and ids never appear to non-owners; log connection ids, never account emails in bulk logs.
- **300-line rule:** `connection_service.py` is the likeliest to grow; split queries and activation early.

## UI Verification
1. **Regression:** existing Gmail/Calendar/Slack connections still show Connected after restart (migration ran, no reconnect needed).
2. Settings, Gmail: click **Connect another account**, authorize a second Gmail. Both appear with their email labels.
3. Mark one account as default; run a task that sends mail with no `account`, and it uses the default.
4. As a different member, connect a **personal** Gmail. Another member does not see it; the owner does.
5. Disconnect one account; the other keeps working.
6. Engineering check: `POST /execute` with `connectionId` of each Gmail account returns that account's messages.
7. Run `pytest` in `integrations-service/` and `backend/`: all green with no edits to old tests.
