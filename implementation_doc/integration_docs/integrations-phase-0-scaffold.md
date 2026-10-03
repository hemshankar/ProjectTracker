# Phase 0: Scaffold

## Technical Design

**A new deployable, not a new module in the monolith**

A standalone FastAPI app — `integrations-service` — added as its own service in `docker-compose.yml`, on the internal docker network only (no public port except the Nango webhook endpoint, reverse-proxied). It gets its own layered structure from day one:

```
integrations-service/
  routers/      connections.py, webhooks.py, health.py   (HTTP only)
  services/     connect_session_service.py, webhook_service.py   (empty/stubbed this phase)
  nango_client.py                                          (thin wrapper over Nango's SDK/REST API)
  provider_registry.py                                      (empty map this phase — proves the seam exists before any real provider uses it)
```

**Proving connectivity before any real provider**

This phase's only functional goal is proving the monolith and the new service can talk to each other safely — zero end-user-visible behavior changes. `GET /health` (unauthenticated, for container orchestration) and `POST /internal/ping` (authenticated with `INTERNAL_SERVICE_KEY`, shared secret between the two services) are the full surface area.

**Secrets**

`NANGO_SECRET_KEY` (from the Nango Dev environment set up in the PRD's Prerequisite Steps), `NANGO_WEBHOOK_SECRET`, and `INTERNAL_SERVICE_KEY` are environment variables on the `integrations-service` container only — never passed to the monolith or frontend.

## Implementation Plan

- [ ] Scaffold `integrations-service/` with `routers/`, `services/`, `nango_client.py`, `provider_registry.py`
- [ ] Add `integrations` entry to `docker-compose.yml`, internal network only
- [ ] Wire `NANGO_SECRET_KEY` / `NANGO_WEBHOOK_SECRET` / `INTERNAL_SERVICE_KEY` as env vars (document in `.env.example`, never commit real values)
- [ ] Implement `GET /health`
- [ ] Implement `POST /internal/ping` (shared-key authenticated)
- [ ] Monolith: add a minimal `integrations_client.py` that calls `/internal/ping`
- [ ] Apply Engineering Standards (see [integrations-00-overview.md](integrations-00-overview.md))

## UI Verification

1. There's no new end-user-visible UI in this phase — it's pure plumbing underneath the existing Settings page.
2. Confirm nothing regressed: open the existing Settings page, confirm Gmail/Calendar/Slack connect buttons still behave exactly as they do today (untouched in this phase).
3. (Engineering-facing, not end-user) hit the new service's `/health` endpoint directly — confirm `200 OK`.

## Inputs Needed From You

- Complete the PRD's "Prerequisite Steps to Activate Nango" (Nango account + Dev environment secret key) — this phase can't finish without it.
