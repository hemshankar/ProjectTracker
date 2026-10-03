# Phase 0: Scaffold (Complete)

Recorded for completeness. Built and running; nothing further to implement.

## Technical Design

A standalone FastAPI app, `integrations-service/`, added to `docker-compose.yml` as `integrations` (internal network, `expose: 8100`, no public port). The backend depends on it and pings it at startup.

```
integrations-service/
  Dockerfile, requirements.txt, .env.example, pytest.ini
  app/main.py            FastAPI app, includes routers
  app/config.py          env vars (NANGO_*, INTERNAL_SERVICE_KEY)
  app/security.py        require_internal_key (constant-time compare, fails closed)
  app/provider_registry.py   empty map + AuthMode + ProviderConfig
  app/nango_client.py    NangoGateway protocol + HTTP impl   (replaced in Phase 1)
  app/routers/           health.py, connections.py, webhooks.py
  app/services/          stubs
  tests/test_health.py
backend/app/integrations_client.py   IntegrationsClient protocol + HttpIntegrationsClient.ping()
```

Surface: `GET /health` (open) and `POST /internal/ping` (header `X-Internal-Key`). The backend logs `integrations-service ping: ok|UNREACHABLE` at startup and never blocks on it.

## What Phase 1 changes from this scaffold
- `nango_client.py` and the `NANGO_*` settings are removed; the vendor seam becomes the `backends/` package.
- `provider_registry.py` (static map) becomes a database-backed registry.

## Actions Required From You
None. Optionally re-run the checks below if you have not.

## Development Best Practices (as applied)
- Layered: router → service → client, matching the monolith.
- `Protocol` for both sides (`NangoGateway`, `IntegrationsClient`) so each is mockable.
- Fail closed when `INTERNAL_SERVICE_KEY` is unset; constant-time key comparison.
- 4 pytest tests; all files far under 300 lines.

## UI Verification
1. No end-user UI changed. Open the Settings page; Gmail/Calendar/Slack behave as before.
2. `docker compose logs backend | grep "integrations-service ping"` shows `ok`.
3. `docker compose exec integrations python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8100/health').read())"` prints `{"status":"ok"}`.
