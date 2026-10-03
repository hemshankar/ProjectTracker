# Integrations Microservice — Technical Design & Implementation Plan

Companion to the [Integrations Microservice PRD](../INTEGRATIONS_PRD.md) — one document per phase, each with a technical design, an implementation checklist, and a UI verification pass.

| Phase | Focus |
| --- | --- |
| [Phase 0: Scaffold](integrations-phase-0-scaffold.md) | Stand up the microservice, Nango sandbox, prove monolith ↔ microservice connectivity |
| [Phase 1: Migrate](integrations-phase-1-migrate-existing.md) | Gmail, Calendar, Slack move off the hand-rolled connectors onto Nango; old connector code retired |
| [Phase 2: Core PM Tools](integrations-phase-2-core-pm-tools.md) | Jira, Notion, HubSpot |
| [Phase 3: Dev & Comms](integrations-phase-3-dev-comms-tools.md) | GitHub, GitLab, Microsoft Teams, Outlook, Discord |
| [Phase 4: Social](integrations-phase-4-social-tools.md) | WhatsApp Business, Telegram, LinkedIn, Facebook, Instagram, X, TikTok |

## Engineering Standards

Applies to every phase below — each phase's Implementation Plan has a checklist item pointing back here.

**SOLID**
- **Single Responsibility** — the microservice's `routers/` only parse/validate HTTP input and call a service; each service owns exactly one bounded concern (`connect_session_service.py` creates Connect sessions, `webhook_service.py` handles inbound Nango events, `proxy_service.py` makes authenticated calls on an Agent's behalf) — never one file doing all three.
- **Open/Closed** — every provider is one entry in `provider_registry.py` (tool type → Nango provider key, auth mode, scopes, display metadata). Adding provider #19 means adding a registry entry, never editing `connect_session_service.py`, `webhook_service.py`, or `proxy_service.py`.
- **Liskov Substitution** — from the monolith's point of view, every tool type behind the proxy is interchangeable; `execution/dispatch.py` never special-cases "if toolType == jira."
- **Interface Segregation** — a narrow `Connectable` protocol (connect/disconnect lifecycle) stays separate from an `Actionable` protocol (the actual proxy call shape), rather than one interface trying to cover both OAuth2 and API-key providers identically.
- **Dependency Inversion** — the monolith's `execution/dispatch.py` depends on an abstract `IntegrationsClient` protocol (injected), never a concrete HTTP client constructed inline. Inside the microservice, routers depend on an abstract `NangoGateway` protocol, never the raw Nango SDK/REST calls — this is what makes both sides unit-testable without a live Nango connection.

**Backend design**
- Layered structure inside the microservice, same discipline as the monolith: `routers/` (HTTP only) → `services/` (one module per bounded concern) → `nango_client.py` (the only file that imports the Nango SDK/calls its REST API).
- `provider_registry.py` is a single declarative source of truth — no provider-specific `if/elif` chains anywhere else in the codebase.
- Config via environment variables only (`NANGO_SECRET_KEY`, `NANGO_WEBHOOK_SECRET`, `INTERNAL_SERVICE_KEY`); no secrets in code, same rule as the monolith's `config.py`.
- Webhook handling is idempotent by construction — every inbound event upserts keyed on the Nango connection id, safe to receive the same event twice.
- Errors translated from service-layer exceptions to HTTP status codes in one shared place, not ad hoc `HTTPException`s scattered per branch.
- Type hints on every function signature; Pydantic models at every API boundary, matching the monolith's existing `models.py` discipline.

**OOP**
- A small immutable `ProviderConfig` value object per entry in `provider_registry.py`, not scattered dict literals passed around by string key.
- Composition over inheritance: `ProxyService` *uses* a `NangoGateway` and the `ProviderRegistry`; it doesn't inherit from either.
- `typing.Protocol` for `NangoGateway` so both sides of the integration are mockable in tests without ever hitting Nango's real API.

**File size**
- No source file over 300 lines, same rule as the monolith. Where a phase names one concern (e.g. "the proxy layer"), treat that as a package, not literally one file — split by responsibility once it grows.
