# Phase 3: Dev & Comms (GitHub, GitLab, Teams, Outlook, Discord)

## Technical Design

**5 more registry entries, one shared Microsoft app**

`provider_registry.py` gains `github → github`, `gitlab → gitlab`, `microsoft-teams → microsoft-teams`, `outlook → outlook`, `discord → discord`. Teams and Outlook both alias Nango's `microsoft` provider — one Microsoft Entra app registration covers both, so connecting either shouldn't prompt the user through a second consent screen for the same Microsoft account.

**Action surface**

E.g. GitHub: open/comment on an issue, comment on a PR; GitLab: equivalent; Discord: post a message to a channel. Same "define explicit proxy call shapes" discipline as Phase 2.

## Implementation Plan

- [ ] Register GitHub, GitLab, Microsoft (covers Teams + Outlook), and Discord OAuth apps in Nango's dashboard
- [ ] `provider_registry.py`: add 5 entries
- [ ] Extend `TOOL_TYPES` + Settings page UI with the 5 new tools
- [ ] Define and implement the specific proxy call shapes each provider's Agent actions need
- [ ] Apply Engineering Standards (see [integrations-00-overview.md](integrations-00-overview.md))

## UI Verification

1. Settings page shows all 5 new tools as connectable.
2. Connect GitHub — confirm an agent task can open or comment on a real issue in a test repository.
3. Connect Discord — confirm an agent task can post a message to a real test channel.
4. Connect Teams, then separately connect Outlook (same underlying Microsoft account) — confirm the second connection doesn't force a duplicate consent flow for an account already authorized.

## Inputs Needed From You

- Register: a GitHub OAuth App (github.com/settings/developers), a GitLab OAuth application, a Microsoft Entra app registration (covers Teams + Outlook), and a Discord application (discord.com/developers).
- Confirm the specific actions needed per provider — e.g. should the Agent be able to merge a pull request, or only comment? This is a scope/safety decision that should also be checked against the Approval Workflow in the main [PRD.md](../PRD.md) (mutating actions need human approval there).
