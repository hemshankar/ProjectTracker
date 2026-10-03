# Phase 4: Social (WhatsApp Business, Telegram, LinkedIn, Facebook, Instagram, X, TikTok)

## Technical Design

**Two different connect UX paths, driven by one registry field**

5 of these 7 are OAuth2 (LinkedIn, Facebook, Instagram, X via the `twitter-v2` Nango key, TikTok via `tiktok-accounts`) and follow the exact Connect UI pattern from Phase 1–3. WhatsApp Business and Telegram are API-key/bot-token based — no OAuth consent screen exists for either. `provider_registry.py`'s `ProviderConfig` gains an `auth_mode` field (`OAUTH2` \| `API_KEY`); the Settings page branches its rendering on that field — an OAuth connect button for one group, a token-entry form for the other — never on individual provider names. This is the Open/Closed principle in practice: a future API-key provider needs no new UI branch, just a registry entry with `auth_mode: API_KEY`.

**Scope flag**

Unlike Phases 1–3, no existing Agent capability in the main [PRD.md](../PRD.md) currently uses these 7 providers — confirm the product need before building (see Inputs Needed From You).

## Implementation Plan

- [ ] Register LinkedIn, Facebook, Instagram, X, and TikTok OAuth apps in Nango's dashboard
- [ ] Obtain a WhatsApp Business API token and a Telegram bot token (different process — no OAuth app registration for either)
- [ ] `provider_registry.py`: add 7 entries, including the new `auth_mode` field
- [ ] Settings UI: branch rendering on `auth_mode` (Connect UI widget vs. token-entry form)
- [ ] Define and implement the specific proxy call shapes each provider's Agent actions need
- [ ] Apply Engineering Standards (see [integrations-00-overview.md](integrations-00-overview.md))

## UI Verification

1. Settings page shows all 7 new tools — LinkedIn/Facebook/Instagram/X/TikTok with the Connect UI widget, WhatsApp/Telegram with a token-entry form.
2. Connect LinkedIn — confirm one-click OAuth.
3. Enter a WhatsApp Business token — confirm it's accepted, stored, and never re-displayed once saved (matching the PRD's Security section — no raw tokens surfaced after entry).
4. Run one agent task end-to-end through at least one of these providers.

## Inputs Needed From You

- Register OAuth apps: LinkedIn Developer Portal, Meta for Developers (covers Facebook + Instagram), X Developer Portal, TikTok for Developers.
- Obtain a WhatsApp Business API access token (Meta Business account) and a Telegram bot token (via @BotFather) — manual processes, not app registrations.
- Confirm what these 7 providers are actually for, product-wise (which Agent capability needs them) — not yet defined anywhere in the main PRD, so this phase shouldn't start until that's answered.
