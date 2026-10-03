# Phase 7: UI

PRD: FR-21–FR-25. The frontend is vanilla JS with no build step (`frontend/public/`), modules attached to `window.*`, plain CSS files in `css/`. This phase follows that style exactly. No framework, no bundler, no new dependency (a chart is drawn with inline SVG).

## Technical Design

### New and touched files

| File | Role | Size note |
| --- | --- | --- |
| `usage-api.js` (new) | thin fetch wrapper for the Phase 6 endpoints, error → `{stale}` / `{unavailable}` states. No DOM | small |
| `usage-format.js` (new) | `UsageFormat.usd(n)` and shared helpers, replacing the local `fmtUsd` copies | small |
| `usage-badges.js` (new) | task badge + board total rendering and live updates | |
| `usage-tab.js` (new) | Admin Console **Usage** tab (controls, orchestration) | |
| `usage-chart.js` (new) | stacked-bar time series as inline SVG, no library | |
| `usage-table.js` (new) | breakdown + drill-down rows table, pagination | |
| `css/usage.css` (new) | styles for badges, tab, chart | |
| `index.html` | script/link tags, Usage tab button + panel, badge placeholders | |
| `board-task-detail.js` / `-render.js` | mount the task badge in the modal header | |
| `board-card.js` | mount the board total in the card header | |
| `board-card-status.js:97` | route live usage to badges | |
| `admin-console.js` | register the Usage tab with the existing tab switcher, reuse `setBoards` for titles | already large, so only a small hook |

`admin-console.js` is already a big file (`fmtUsd` etc. live there). Keep the Usage tab in its **own** modules and only hook it in, so the 300-line limit isn't pressured.

### Formatting (FR-25)

`UsageFormat.usd(n)`: `$0.00` for exactly 0, `$0.0042` for values under one cent (4 significant decimals), `$1.23` at 2 decimals for ≥ $1, thousands separators for ≥ $1,000. `null`/`undefined` → "—". A `stale` response renders the value with a subtle "≈" and a title tooltip "May be a few seconds behind". The existing `fmtUsd` in `admin-console.js:34` is switched to this helper so Traces and Usage format identically.

### Task detail badge (FR-21)

- A small pill in the task detail modal header (`index.html` `#chat-modal` header region), for example `$0.1250`. Members see the USD only (tokens are a breakdown field, admin-only per the PRD). Admins additionally get a tooltip with tokens in/out and cache.
- Loads on `loadTaskDetail` (`board-task-detail.js:74`) via `GET .../tasks/{id}/usage`.
- **Live:** while the task is running, each `llmCall` WebSocket event for that `taskId` adds its `usd` to the displayed value immediately (optimistic increment), and a debounced (3s) refetch reconciles with the server so drift can't accumulate.

### Board total (FR-22)

- Shown in the board card header (`board-card.js`): a muted pill next to the status.
- Initial values come from **one** batch call per workspace (`/usage/boards`) when the board list loads, not N calls.
- Live: the same optimistic increment on `llmCall` for that `boardId`, plus periodic reconcile.
- Task cards in the board (`board-card-tasks.js`) get a cost badge from the board's task batch (`GET /api/boards/{id}/usage/tasks`) loaded lazily when a board card is expanded or in view.

### Live updates (FR-24)

`board-card-status.js:97` currently routes `data.llmCall` only to `AdminConsole.onLiveLlmCall`. Extend it to also call `UsageBadges.onLlmCall(boardId, llmCall)`. The `llmCall` payload now carries `usd` (it already does) plus `taskId`, so no new WebSocket event type is needed. `UsageBadges` keeps a map `{boardId: usd, taskId: usd}`, increments on events, and re-renders only the affected badges.

Chat and dispatch calls (no `taskId` / `runId`) update the board total only.

### Admin Console → Usage tab (FR-23)

New tab button `admin-tab-btn-usage` and panel in `#settings-modal` (`index.html:189-191` pattern), registered alongside Config/Activity/Traces.

Layout, top to bottom:
1. **Controls row:** range presets (7d, 30d, 90d, 12m, custom date pickers), granularity (Day/Week/Month, defaults by range), group-by (Board, Task, Model, User, Call kind, None), Export button (CSV/JSONL).
2. **Headline:** workspace total for the range + a comparison with the previous equal period (percentage up/down).
3. **Chart:** stacked bars by the group-by dimension over time (inline SVG, accessible: each bar has `<title>` text, and the same data is available in the table below for keyboard/screen-reader users). Top 8 groups plus "Other". Clicking a bar sets the drill-down filter to that day (or week/month) and group.
4. **Breakdown table:** top groups by cost (rank, name, calls, tokens, USD, % of total). Names come from snapshots, a "deleted" tag where the core flagged it, an "estimated" tag when the group contains backfilled rows (the API returns `estimatedCalls` count).
5. **Drill-down:** ledger rows for the current filter (time, board/task names, kind, model, tokens, USD, outcome), keyset-paged ("Load more"). Row click shows the full row. When `llmCallRef` still resolves, a "View trace" link jumps to the Traces tab for that call.

States for every panel: loading skeleton, empty ("No usage in this range"), error with retry ("History unavailable. Totals above may be stale"), and `503 accounting_unavailable` handled distinctly from generic failures.

Charts follow the project's existing theme (light/dark via `board-theme.js`). Colors are CSS variables from `css/usage.css`, using the existing `HUES` family where possible so the palette matches boards.

### Permissions in the UI

- The Usage tab is shown only to workspace admins (the same condition the Traces tab uses). The core still enforces it.
- Members never see a token count, model, or breakdown anywhere.

### Accessibility and polish

Keyboard-reachable controls, `aria-live="polite"` on the headline total so updates aren't noisy (updated at most every few seconds), color is never the only channel (patterns/labels in the table), and badges don't shift layout when values change (tabular figures).

## Implementation Plan

- [ ] `usage-format.js` and switch `admin-console.js` `fmtUsd` to it
- [ ] `usage-api.js` (fetch wrapper, state mapping: ok / stale / unavailable)
- [ ] `usage-badges.js`: state map, optimistic increments, debounced reconcile; mount points in task detail, board card, task cards
- [ ] Wire `board-card-status.js` to `UsageBadges.onLlmCall`
- [ ] `css/usage.css` and add the tags in `index.html`
- [ ] Usage tab: `usage-tab.js` (controls/state), `usage-chart.js` (SVG), `usage-table.js` (breakdown + drill-down + paging); register the tab in `admin-console.js`
- [ ] Export button → download via the core export endpoint
- [ ] Hide admin-only UI for non-admins
- [ ] Apply Engineering Standards (see [accounting-00-overview.md](accounting-00-overview.md))

## Tests

The frontend has no test harness today. Keep logic testable and pure, and verify with the browser-automation approach:
- Pure functions (`UsageFormat.usd`, bar-chart scale/stack computation, optimistic-increment reducer) are exported on `window.UsageFormat` / a small `UsageCore` object and exercised with a tiny node script or an HTML test page (no new tooling).
- Browser pass (use the `browser-automation` skill against the running app): load the board list, open a task, open Admin Console → Usage. Assert no console errors, no failed network requests, and expected elements present. Capture screenshots (light and dark).

## Verification

1. **Member view:** log in as a non-admin member. Board cards and task details show USD only. There's no Usage tab, and tokens/model aren't visible anywhere (also confirm via network tab that no breakdown calls are made).
2. **Live:** start a task and watch the task badge and the board total tick up per round, then settle on the server value after a refresh. They must match.
3. **Chat/dispatch:** send a board chat message. The board total rises, the task badge doesn't (unless task-tagged).
4. **Admin:** open Usage. Check the range presets, group-by, chart ↔ table agreement, drill-down paging, the "View trace" link, the "deleted" tag on a deleted board, and "estimated" on backfilled data.
5. **Export:** download CSV, and open it to check the row count against the drill-down total.
6. **Outage:** stop the accounting container: totals show "≈" (stale), the Usage tab shows "History unavailable", and the rest of the app works.
7. **Dark mode and narrow width:** badges and the chart remain legible, with no horizontal page scroll.
8. Run the browser-automation check and attach screenshots.

## Rollback

Remove the new script/link tags and the hook lines in `board-card-status.js`, `board-card.js`, and `board-task-detail*.js`. No data changes.

## Inputs Needed From You

- Any preference on chart style (stacked bars is the plan) and the default range (30 days).
- Whether task cards on the board should show cost badges, or only the task detail modal (to keep the cards uncluttered).
