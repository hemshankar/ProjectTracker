# Integrations Microservice PRD

*2026-10-02 · Hemshankar Sahu*

Source (live, editable): https://claude.ai/code/artifact/d9dcd72d-d399-47e9-8944-c15cad40fe62

## Overview & Goals

ProjectTracker already hand-rolls OAuth connectors (`backend/app/execution/connectors/`: `gmail.py`, `calendar.py`, `slack.py`, `google_base.py`) with their own token storage and refresh logic in `tool_connections_service.py` — but only 3 providers exist, and each new one is bespoke, maintained code. This PRD replaces that pattern with a standalone **integrations microservice** backed by Nango, so new providers are config, not code.

Goals:
- Let an Agent connect any of 18 target providers (Jira, Notion, HubSpot, Teams, Outlook, Discord, GitHub, GitLab, WhatsApp, Telegram, LinkedIn, Facebook, Instagram, X, TikTok, plus the existing Slack/Gmail/Calendar) without a new hand-written connector per service.
- Keep raw provider access/refresh tokens out of ProjectTracker's own database — Nango custodies them.
- Preserve the existing Agent-level "tool connection" UX already described in PRD.md (Settings page, per-board tool enablement) — this is an infrastructure swap underneath it, not a new user-facing concept.
- Isolate all third-party auth/proxy logic in its own deployable service, so the monolith never talks to Google/Slack/Atlassian/etc. directly.

## Scope & Non-Goals

**In scope:**
- v1: stand up the microservice and migrate the 3 live connectors (Gmail, Calendar, Slack) onto it.
- v1.1: add Jira — the originating ask for this project.
- Later phases: Notion, HubSpot, GitHub, GitLab, Teams, Outlook, Discord, then WhatsApp Business, Telegram, LinkedIn, Facebook, Instagram, X, TikTok (see Rollout Phases).

**Non-goals:**
- Not building a visual flow/automation builder (the Activepieces/n8n path considered and rejected earlier) — this only covers account-connect plus the Agent executing actions it already knows how to do.
- Not exposing Nango's sync/webhook-as-workflow features to end users — those stay internal plumbing.
- End users never see a separate Nango UI; all interaction stays on ProjectTracker's existing Agent Settings page.

## Microservice Architecture

A new standalone `integrations-service`, separate from the FastAPI monolith, sits between it and every third-party provider:

```
Frontend (Settings page)
        │
        ▼
FastAPI Monolith (task execution)
        │
        ▼
Integrations Service  ◄── webhooks: connection created / refreshed ──┐
(holds the Nango secret; the only component that proxies both ways) │
        │                                                             │
        ▼                                                             │
Nango Cloud (manages tokens) ──────────────────────────────────────────┘
        │
        ▼
Provider APIs (18 services)
```

The monolith never talks to a provider directly; the microservice is the only thing holding the Nango secret and proxying calls both ways. It owns:
- Nango Connect session creation, so the frontend can embed Nango's Connect UI widget.
- Webhook receipt from Nango (connection created/removed/refreshed), which it relays to the monolith.
- A small internal proxy API the monolith's `execution/dispatch.py` calls instead of talking to providers directly.

Deployment: added as another service in `docker-compose.yml`, on the internal docker network only — never exposed publicly except its Nango webhook endpoint.

## Provider Mapping

Verified directly against Nango's provider catalog (`packages/providers/providers.yaml`).

| Service | Nango provider key | Auth mode | Notes |
| --- | --- | --- | --- |
| Slack | `slack` | OAuth2 | Live today (hand-rolled) — migrates first |
| Gmail | `google-mail` | OAuth2 (alias: `google`) | Live today — migrates first |
| Google Calendar | `google-calendar` | OAuth2 (alias: `google`) | Live today — migrates first |
| Jira | `jira` | OAuth2 | Originating ask for this project |
| Notion | `notion` | OAuth2 | |
| HubSpot | `hubspot` | OAuth2 | |
| Microsoft Teams | `microsoft-teams` | OAuth2 (alias: `microsoft`) | |
| Outlook | `outlook` | OAuth2 (alias: `microsoft`) | |
| GitHub | `github` | OAuth2 | |
| GitLab | `gitlab` | OAuth2 | |
| Discord | `discord` | OAuth2 | |
| LinkedIn | `linkedin` | OAuth2 | |
| Facebook | `facebook` | OAuth2 | |
| Instagram | `instagram` | OAuth2 | |
| X (Twitter) | `twitter-v2` | OAuth2 | Use v2 — legacy `twitter` key is OAuth1 |
| TikTok | `tiktok-accounts` | OAuth2 | |
| WhatsApp Business | `whatsapp-business` | API key | Meta access token, not OAuth |
| Telegram | `telegram` | API key | Bot token — Telegram bots have no OAuth |

Almost every OAuth2 row still needs a one-time OAuth app registered by us in that provider's developer console (Nango doesn't pre-register apps for us) — see Risks & Open Questions.

## Connect Flow (End-User UX)

1. Agent Admin opens the existing Settings page and clicks Connect next to a tool (e.g. Jira) — same entry point as today.
2. Frontend calls the integration microservice: `POST /connections/session` with `{agentId, toolType}`.
3. Microservice calls Nango's Connect Session API for the mapped provider key, returns a short-lived session token.
4. Frontend opens Nango's Connect UI widget (`nango.openConnectUI(...)`) with that token — no redirect away from ProjectTracker's own page.
5. User authorizes against the real provider (Atlassian, Slack, etc.) inside that widget.
6. Nango fires a `connection.created` webhook to the microservice, which resolves `agentId`/`toolType` from the session metadata and records the connection.
7. Microservice notifies the monolith (internal call) so the Settings page reflects "Connected" — replacing today's OAuth-redirect round trip through `routers/tools.py`'s `/connect` and `/callback` endpoints.

## Execution-Time Usage

Today, `execution/dispatch.py` calls `get_connector(tool_type)` to get a `GmailConnector`/`SlackConnector`/`CalendarConnector` instance, which calls the provider API directly using tokens that `tool_connections_service.get_valid_tokens()` fetched and refreshed locally.

Going forward, dispatch calls one generic client against the integration microservice's internal proxy endpoint (e.g. `POST /proxy/{agentId}/{toolType}`), passing the request the connector wants to make. The microservice resolves the stored Nango connection id and calls Nango's authenticated Proxy API, which attaches a valid (auto-refreshed) token and forwards the call to the provider. Token refresh becomes entirely Nango's responsibility — the monolith never holds, refreshes, or even sees a raw provider token again.

## Data Migration

ProjectTracker isn't live yet, so there's no existing user data or in-production connections to migrate. The 3 connections that already exist in dev (Gmail, Calendar, Slack) can simply be re-created through the new Connect UI flow once the microservice ships — no migration logic needed. The old `tool_connections_collection` entries and their encrypted-token shape are just dropped and replaced by `{agentId, toolType, nangoConnectionId, provider}`.

## Security

- The Nango secret key lives only in the integration microservice's environment — never reaches the frontend or the monolith.
- Connect-session tokens handed to the frontend are short-lived and scoped to a single connect attempt.
- Monolith ↔ integration microservice calls are internal-only (docker-compose network), authenticated with a shared service key — never exposed publicly.
- No raw provider access/refresh tokens are stored in ProjectTracker's own database for OAuth2 providers — only a Nango connection id, which is useless outside Nango.

## Cost

Nango Cloud free tier (10 connections, 10 compute-hours, 10GB/month) likely covers early testing. Production estimate: Pay-as-you-go tier, ~$50/month base, then ~$0.29/connection, ~$0.72/compute-hour, ~$0.50/GB — real monthly cost depends on Agent/connection volume, which isn't established yet (open question in Risks).

## Prerequisite Steps to Activate Nango

These are account/console steps someone needs to do before or alongside Phase 0 — none of this is code:

1. Create a Nango account at nango.dev — the free tier already gives a working Dev environment to build against.
2. Grab the Dev environment's secret key from Nango's dashboard; this goes only into the new integrations-service's environment, never committed to the repo.
3. Register one OAuth app per v1 provider — required before Nango can use that provider at all:
   - **Google** (Gmail + Calendar): Google Cloud Console, new project, enable the Gmail API and Calendar API, configure the OAuth consent screen, create an OAuth 2.0 Client ID (Web application), add the redirect URI Nango's dashboard shows for the `google` integration.
   - **Slack**: api.slack.com/apps, create an app, add the OAuth scopes the current `slack.py` connector already requests, add Nango's redirect URI, copy the Client ID/Secret.
   - **Jira**: developer.atlassian.com, create an OAuth 2.0 (3LO) app, add scopes `read:jira-work`, `write:jira-work`, `offline_access`, add Nango's callback URL, copy the Client ID/Secret.
4. In Nango's dashboard, paste each app's Client ID/Secret into its matching Integration (`slack`, `google` — covers both `google-mail` and `google-calendar` — and `jira`).
5. Configure a webhook URL and signing secret in Nango's dashboard, pointed at the integrations-service's webhook endpoint (stood up in Phase 0) — this is what delivers connection-created/refreshed events.
6. Decide the Dev vs. Prod environment split in Nango now, even though Prod isn't needed until go-live — cheaper than re-registering every app later.

## Rollout Phases

```
Phase 0        Phase 1        Phase 2 ◄gate: old   Phase 3          Phase 4
Scaffold       Migrate        Core PM  code retired Dev & Comms      Social
Oct 2026       Nov 2026       Dec 2026              Jan 2027         Feb 2027
Stand up       Gmail,         Jira,                 GitHub, GitLab,  WhatsApp,
service +      Calendar,      Notion,               Teams, Outlook,  Telegram,
Nango sandbox  Slack re-auth  HubSpot               Discord          LinkedIn,
                                                                      Facebook,
                                                                      Instagram,
                                                                      X, TikTok
```

Bands are equal width and not to scale — actual phase length depends on engineering availability. The gate between Phase 1 and Phase 2 marks when the old hand-rolled connector code is retired.

## Risks & Open Questions

- **OAuth app registration is still manual, per provider.** Nango doesn't pre-register apps for us (confirmed against its own provider catalog) — someone needs access to ProjectTracker's Google Cloud, Slack, Atlassian, Meta, and Microsoft developer accounts to register one OAuth app per provider before it's usable.
- **New single point of failure.** Every tool-using task now depends on Nango's uptime. Needs an explicit failure path (task moves to `blocked` with a clear reason) rather than a silent hang.
- **Multi-tenant isolation.** Connections are keyed by our own `agentId` as the Nango end-user id — needs a final decision on exactly what identifier to use and how it's scoped.
- **WhatsApp Business and Telegram aren't OAuth.** Their connect UX will look different (token/bot-key entry) from the one-click flow everything else gets.
- **Two-way disconnect sync.** If a user disconnects from Nango's own dashboard directly (rather than ProjectTracker's Settings page), the monolith needs to learn about it via webhook, not just assume `connected: true` forever.
- **Expected connection volume** isn't established yet — needed to firm up the Cost estimate above.

## Success Metrics

- **Time to add a new provider** (engineering): under 1 day — Nango config + Settings-page wiring, vs. days per hand-rolled connector today.
- **Time for an Agent Admin to connect a tool**: under 1 minute, zero manual token entry for every OAuth2 provider in the mapping table.
- **Connector code deleted**: `gmail.py`, `calendar.py`, `slack.py`, `google_base.py` removed entirely once migration is verified.
- **Zero raw provider tokens** stored in ProjectTracker's own database, for any provider.
