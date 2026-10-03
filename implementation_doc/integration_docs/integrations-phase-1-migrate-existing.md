# Phase 1: Migrate (Gmail, Calendar, Slack)

## Technical Design

**Registry gains its first real entries**

`provider_registry.py` gets 3 `ProviderConfig` entries: `gmail → google-mail`, `calendar → google-calendar`, `slack → slack` (the first two share the `google` Nango alias and OAuth app, registered once in the PRD's Prerequisite Steps).

**The connect flow (per the PRD's Connect Flow section)**

`connect_session_service.py` implements `POST /connections/session` — creates a Nango Connect session for the given `agentId`/`toolType`, returns a short-lived session token. `webhook_service.py` implements the inbound `POST /webhooks/nango` endpoint — verifies the signature with `NANGO_WEBHOOK_SECRET`, and on `connection.created`/`connection.deleted` upserts the connection record (keyed on Nango connection id, so duplicate deliveries are safe) and notifies the monolith.

**The proxy (execution-time path)**

`proxy_service.py` implements `POST /proxy/{agentId}/{toolType}` — resolves the stored Nango connection id, calls Nango's Proxy API, returns the response. This is the single endpoint that replaces all three hand-rolled connectors' `execute()` methods.

**Monolith-side changes**

- `routers/tools.py`'s redirect-based `/connect` and `/callback` endpoints are replaced by a call into the new service's `/connections/session`.
- Frontend's Settings page swaps the OAuth-redirect button for `nango.openConnectUI()`.
- `execution/dispatch.py` is pointed at the integrations-service's `/proxy` endpoint instead of `get_connector(tool_type)`.
- Once verified end-to-end: delete `backend/app/execution/connectors/gmail.py`, `calendar.py`, `slack.py`, `google_base.py`, `registry.py`, and the token-encryption logic in `tool_connections_service.py` — this is the "old code retired" gate from the PRD's Rollout Phases diagram.
- `tool_connections_collection`'s shape changes to `{agentId, toolType, nangoConnectionId, provider}` (no migration needed — app isn't live yet, per the PRD's Data Migration section).

## Implementation Plan

- [ ] Register `slack` and `google` OAuth apps in Nango's dashboard (per Prerequisite Steps)
- [ ] `provider_registry.py`: add gmail/calendar/slack entries
- [ ] Implement `POST /connections/session`
- [ ] Implement `POST /webhooks/nango` (signature verification + idempotent upsert)
- [ ] Implement `POST /proxy/{agentId}/{toolType}`
- [ ] Monolith: replace `routers/tools.py` connect/callback with a call into the new service
- [ ] Frontend: replace the OAuth-redirect button with `nango.openConnectUI()`
- [ ] Monolith: point `execution/dispatch.py` at the integrations-service proxy
- [ ] Delete `gmail.py`, `calendar.py`, `slack.py`, `google_base.py`, old `registry.py`, and the encrypted-token logic in `tool_connections_service.py`
- [ ] Re-connect the 3 existing dev connections through the new Connect UI flow
- [ ] Apply Engineering Standards (see [integrations-00-overview.md](integrations-00-overview.md))

## UI Verification

1. On the Agent Settings page, click Connect next to Gmail — confirm Nango's Connect UI widget opens inline (not a full page redirect) and completes without error.
2. After authorizing, confirm the Settings page flips to "Connected" without a manual page refresh.
3. Trigger an agent task that uses Gmail (e.g. send/read email) — confirm it behaves exactly as before from the end user's perspective.
4. Repeat steps 1–3 for Calendar and Slack.
5. Click Disconnect on any of the three — confirm the tool reverts to "Not connected," and a subsequent task attempt correctly falls back to the existing "not connected" behavior rather than erroring.
6. Engineering-facing gate (not strictly UI): confirm `backend/app/execution/connectors/` no longer contains `gmail.py`, `calendar.py`, `slack.py`, or `google_base.py`.

## Inputs Needed From You

- None beyond what Phase 0's Prerequisite Steps already covered, assuming the Slack and Google OAuth apps were registered there.
