# Phase 2: Core PM Tools (Jira, Notion, HubSpot)

## Technical Design

**The proof that Phase 1's plumbing generalizes**

No changes to `connect_session_service.py`, `webhook_service.py`, or `proxy_service.py` — this phase only adds 3 entries to `provider_registry.py` (`jira → jira`, `notion → notion`, `hubspot → hubspot`) and extends the monolith's `TOOL_TYPES` + Settings page UI with 3 more checkboxes. If this phase needs more than registry/config changes, that's a signal Phase 1's abstraction boundary was wrong — see Engineering Standards' Open/Closed principle.

**Action surface**

Each provider needs its proxy call shapes defined explicitly before an Agent can use it — e.g. Jira: create issue, transition issue; Notion: create page; HubSpot: create contact/deal. These are product decisions (see Inputs Needed From You), not inferable from the registry alone.

## Implementation Plan

- [ ] Register Jira, Notion, HubSpot OAuth apps in Nango's dashboard
- [ ] `provider_registry.py`: add 3 entries
- [ ] Extend `TOOL_TYPES` (`models_settings.py`) + Settings page UI with the 3 new tools
- [ ] Define and implement the specific proxy call shapes each provider's Agent actions need
- [ ] Apply Engineering Standards (see [integrations-00-overview.md](integrations-00-overview.md))

## UI Verification

1. Settings page shows Jira, Notion, and HubSpot as connectable tools.
2. Connect each via the Connect UI widget — confirm one-click OAuth with no manual token entry for all three.
3. Run an agent task configured to use Jira — confirm it creates/updates a real Jira issue, visible in the actual Jira project.
4. Run an agent task configured to use Notion — confirm a real page is created in the connected workspace.
5. Confirm this phase took materially less engineering effort than Phase 1 (pure config + action-surface definitions, no new plumbing) — the PRD's "time to add a new provider" success metric.

## Inputs Needed From You

- Register the 3 OAuth apps: Atlassian Developer Console (Jira), Notion's integrations page, HubSpot's developer account.
- Confirm which specific actions the Agent should be able to take per provider (e.g. can it transition a Jira issue to Done, or only comment? Which HubSpot objects — contacts, deals, both?) — a product/safety decision, not something engineering can infer.
