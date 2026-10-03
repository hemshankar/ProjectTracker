# Phase 1: Identity, Agents & Sharing

## Technical Design

**New collections**

| Collection | Key fields |
| --- | --- |
| `users` | `_id` (Google `sub`), `email`, `name`, `pictureUrl`, `createdAt`, `lastLoginAt` |
| `agents` | `_id`, `name`, `createdBy`, `createdAt`, `updatedAt` |
| `agent_members` | `_id`, `agentId`, `userId`, `role` (`admin`\|`member`), `status` (`requested`\|`active`), `invitedBy`, `createdAt` — unique index on (agentId, userId) |
| `board_shares` | `_id`, `boardId`, `userId`, `role` (`viewer`\|`editor`), `invitedBy`, `createdAt` — unique index on (boardId, userId) |

`boards` documents gain an `agentId` (required) and `ownerId` field; everything else in the current schema (`title`, `tasks[]`, `chats[]`, ...) is unchanged.

**Auth**

- Google OAuth 2.0 authorization-code flow, new `routers/auth.py`: `GET /api/auth/google/login`, `GET /api/auth/google/callback` (upserts `users`, issues a signed httpOnly session cookie), `POST /api/auth/logout`, `GET /api/auth/me`.
- A `get_current_user` FastAPI dependency (401 if the cookie is missing/invalid), added to every existing router.
- `require_agent_admin(agent_id)` / `require_board_access(board_id, min_role)` dependencies for authorization, backed by `agent_members` / `board_shares` lookups.
- `main.py`'s CORS middleware needs `allow_credentials=True` and an explicit origin list once cookies are in play (`allow_origins=["*"]` today won't work with credentials).

**API surface**

- `POST /api/agents`, `GET /api/agents` (agents the caller belongs to)
- `POST /api/agents/{id}/members` (admin invite, or self-request → `status="requested"`), `PATCH /api/agents/{id}/members/{user_id}` (approve/change role/remove)
- `GET /api/agents/{id}/boards` (replaces today's unscoped `GET /api/boards`)
- `POST /api/boards/{id}/shares`, `DELETE /api/boards/{id}/shares/{user_id}` — sharing a board with someone not yet an `agent_member` auto-creates that row (`status="active"`), which is the mechanic behind "board access implies Agent access."

**Migration**

A one-off script creates a default Agent for whichever user first signs in post-launch, stamps `agentId` onto every existing board, and inserts their `agent_members` admin row — sufficient given there's no auth today and effectively one real user so far.

**Frontend**

- Login screen gating the app (`app.js` currently loads boards unconditionally on page load; wrap in a `GET /api/auth/me` check, redirect to login on 401).
- Agent switcher in the header once a user belongs to more than one Agent.
- "Share" modal on a board (email + viewer/editor) calling the new shares endpoint.

## Implementation Plan

- [ ] `users`, `agents`, `agent_members`, `board_shares` collections + indexes
- [ ] Google OAuth login/callback/logout/me in `routers/auth.py`
- [ ] Session-cookie auth dependency, wired into every existing router
- [ ] `agentId`/`ownerId` on board documents + the one-off migration script
- [ ] `routers/agents.py`: create/list agents, member invite/approve/role, agent-scoped board list
- [ ] Board-sharing endpoints + auto-membership-on-share behavior
- [ ] Frontend: login gate, agent switcher, share modal
- [ ] CORS config update for credentialed requests
- [ ] Manual test with two Google accounts: confirm board isolation and the full share flow
- [ ] Apply Engineering Standards (see [00-overview.md](00-overview.md)): thin routers over a `services/` layer, SOLID boundaries anywhere more than one implementation exists, no file over 300 lines

## UI Verification

1. Open the app in an incognito window — it should redirect to a Google sign-in screen instead of showing any boards.
2. Sign in — land back on the canvas; a default Agent/board set exists for a first-time user.
3. Create a board, refresh the page — it persists (confirms the new `agentId` scoping didn't break ordinary CRUD).
4. Click "Share" on a board, invite a second Google account as Viewer — sign in as that account (separate browser/incognito) and confirm it sees exactly that board, not the inviter's other boards.
5. As the second account, confirm task/board edit controls are disabled (Viewer), then have the inviter re-share as Editor and confirm the same account can now edit.
6. Try opening a board's URL that was never shared with the second account — confirm it's refused, not just hidden.

## Inputs Needed From You

| Input | Why | How to get it |
| --- | --- | --- |
| Google OAuth Client ID + Client Secret | Powers "Sign in with Google" | Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID (type: Web application) |
| OAuth consent screen configuration | Google requires this before it issues credentials | Same console → OAuth consent screen → app name, support email, scopes `openid`, `email`, `profile`; choose "Internal" if everyone signing in is inside one Google Workspace org, otherwise "External" |
| Redirect URI(s) | Google only redirects back to URLs you've registered | Add `http://localhost:3000/api/auth/google/callback` for local dev now; add the production URL once it's known |
| A session-signing secret | Signs the session cookie | Generate it yourself, no external account needed: `python -c "import secrets; print(secrets.token_hex(32))"` |

**Steps**
1. Create or pick a Google Cloud project at console.cloud.google.com.
2. Configure the OAuth consent screen (app name, support email, the three scopes above).
3. Create an OAuth client ID (Web application), adding the redirect URI(s).
4. Copy the Client ID and Client Secret into `backend/.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
5. Generate and add `SESSION_SECRET_KEY` to `backend/.env` the same way.
