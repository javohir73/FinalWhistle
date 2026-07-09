# Multi-Sport Navigation + Midnight Theme — Design Spec

**Date:** 2026-07-09
**Status:** Approved (Template A + Midnight skin + Movers hero, chosen from three mockup templates)
**Mockups:** https://claude.ai/code/artifact/34068357-38f3-4ec3-b934-ffff7e3aa262

## Goal

Add NRL as a second sport alongside Football (World Cup 2026) using a header **sport switcher**
(Template A), restyle the platform in a premium dark **Midnight** theme (Kalshi/Polymarket-style
market presentation), and replace the "Your team" home hero with a **Today's movers** panel.

The backend already serves NRL: 1,976 matches ingested (2017–2026), 71 frozen predictions,
`GET /api/nrl/matches` and `GET /api/nrl/model/record` live, refreshed daily by the
`nrl-refresh` workflow.

## Approved decisions

1. **Navigation: Template A — Sport Switcher.** A segmented ⚽ Football / 🏉 NRL control swaps the
   whole app between sports. Rejected: B (unified mixed-sport home feed — noisier home, needs a
   combined feed endpoint) and C (portal landing fork — extra click, two navs to maintain).
   A upgrades gracefully into B later if cross-sport engagement becomes a goal.
2. **Theme: Midnight becomes the platform theme** for both sports. Daylight token values stay in
   the codebase behind a theme flag for rollback/light mode later.
3. **Home hero: "Today's movers"** replaces the "Your team" panel for returning users. The
   country-follow feature itself stays (team pages, favorites, onboarding chooser unchanged).

## Navigation architecture

- **Sport config** — new `frontend/lib/sports.ts`:
  `{ id, label, icon, basePath, navLinks[] }` per sport.
  - Football: Home `/`, Matches `/matches`, Groups `/groups`, Bracket `/brackets`, You `/leaderboard` — labels and routes unchanged.
  - NRL: Home `/nrl`, Matches `/nrl/matches`, Ladder `/nrl/ladder`, Record `/nrl/record`, You `/leaderboard`.
  - "You" is account-level and shared across sports.
- **Active sport detection** — pathname prefix (`/nrl/*` → nrl, else football). `SiteNav.tsx` and
  `BottomNav.tsx` stop hardcoding the five football links and derive them from the active sport's
  config; the existing `activePrefixes` folding (e.g. `/match` under Matches) moves into the config.
- **`SportSwitcher`** — client component. Desktop: segmented control in the header next to the brand.
  Mobile: pill row under the header (bottom tab bar keeps 5 tabs, re-scoped per sport). Switching
  navigates to the equivalent page in the other sport where one exists (Matches ↔ Matches),
  otherwise to that sport's home. Persist last sport in a cookie so returning visitors land there.
- **Routes** — new App Router subtree `frontend/app/nrl/{page,matches,ladder,record}` following the
  existing server-component + `...Client.tsx` island pattern with ISR.

## Midnight theme

The design system is HSL CSS variables in `frontend/app/globals.css` mapped through
`tailwind.config.ts`, so the retheme is primarily a token swap plus a component audit.

Token values (from the approved mockups):

| Token | Midnight value |
|---|---|
| `--background` | `#0d1118` (deep blue-black) |
| `--surface` | `#141926`, gradient to `#121722` on cards |
| `--surface-2` | `#1b2231` |
| `--foreground` | `#eef2f7` |
| `--muted` | `#8b95a7` |
| `--border` | `rgba(255,255,255,.07)` |
| `--win` (lime) | `#a4e34a` — accessible as text on dark, so `--lime-deep` maps to it |
| `--draw` | `#eab54e` |
| `--loss` | `#f4587a` |
| `--pitch` (hero panels) | gradient `#12301e → #0e2418 → #0a1a11` with a lime radial glow |

Market-style presentation (new):

- **Chance chips** — probabilities render as bold tabular chips with tinted backgrounds
  (lime/amber/rose) and daily movement deltas (▲ 1.8 / ▼ 1.2).
- **Sparklines** — small 7-day probability trend lines on match cards (match of the day and
  match detail; omitted on compact cards).
- **Probability bars** — slimmer (7px), lime segment gets a soft glow.

Audit pass required on: `.glass`, `.panel-pitch`, shadows, focus ring, recharts palette, skeleton
shimmer, `/embed/[matchId]` cards, OG images, `manifest.ts` `themeColor`, and the Capacitor
status-bar/webview colors on iOS/Android.

## Home hero: Today's movers

- Replaces the "Your team" panel in `HomeExperience.tsx` / `HomeDashboard` for returning users.
- Shows the top 3 absolute daily probability changes across tracked markets — Football: knockout
  odds, group-winner odds, title odds; NRL home shows win-probability swings for the upcoming round.
- Each row: flag/club badge, entity, market label, current probability, delta chip. Links to the
  full forecast page ("See all movement →").
- First-time visitors still get the country onboarding chooser; choosing a team still personalizes
  match ordering and team pages.

## Backend additions

1. **`GET /api/nrl/ladder`** — standings computed from ingested `SportMatch` results: played, wins,
   losses, draws, points (2/win, 1/draw), for/against differential; ordered by points then
   differential. Lives in `backend/app/api/sports.py`.
2. **Probability snapshots** — new table `probability_snapshots(sport, entity_id, market, prob,
   snapshot_date)`. The pipeline appends one row per tracked market on each refresh (football
   `refresh-data`, NRL `nrl-refresh`). Serves movers deltas and 7-day sparkline series via
   **`GET /api/movers?sport=`**. Until two snapshots exist, deltas/sparklines are hidden and chips
   show plain probabilities.
3. Existing `GET /api/nrl/matches` and `GET /api/nrl/model/record` are consumed as-is through the
   `/backend-api` rewrite.

## Frontend data layer

- `lib/api.ts` gains `getNrlMatches()`, `getNrlLadder()`, `getNrlRecord()`, `getMovers(sport)`.
- `lib/types.ts` gains `SportMatch`, `SportPrediction`, `LadderRow`, `Mover` mirroring backend models.
- NRL pages use the same ISR cadence as football pages.

## Components

- `SportSwitcher` — described above.
- `SportMatchCard` — generalization of `MatchCard`: club monogram badge (club colors, 2–3 letter
  code) instead of `Flag`; outcome rows with chance chips; W/D/L bar keeps three segments (NRL's
  draw segment is naturally small, ~4–6%).
- `LadderTable` — modeled on `GroupTable` (top-8 finals qualification tint instead of top-2).
- `MoversPanel` — the home hero.
- NRL record page reuses the `/record` track-record presentation fed by `/api/nrl/model/record`.

## Error & empty states

- NRL record starts at 0 graded → "Season live — grading starts as Round 19 completes."
- Movers with <2 snapshots → plain probabilities, no deltas.
- API failures reuse existing error boundaries and the offline banner.

## Testing

- Unit: sport detection from pathname; switcher equivalent-route mapping; movers delta calculation.
- Backend: ladder ordering (points, then differential; draws counted once); movers endpoint.
- E2E smoke: `/nrl` renders fixtures; home renders MoversPanel; extend the existing `smoke` workflow.
- Visual: screenshot regression of home + match card in Midnight; Capacitor dark status-bar check.

## Out of scope

- NFL/NBA verticals (the sport config and backend schema are ready for them; not built now).
- Template B's mixed cross-sport home feed (documented upgrade path from A).
- The NRL 2020 ingest dedup bug (32 real matches dropped because the feed reuses `MatchNumber`
  within rounds and dedup keys on `match_no` alone — fix keys on `(round_no, match_no)` and re-run
  ingest). Tracked separately; should land before heavy NRL promotion since it skews 2020–21 Elo.

## Rollout

1. **Phase 1 — Midnight + movers (football only):** token swap, component audit, snapshots table,
   movers endpoint + panel. Ships value immediately and de-risks the retheme.
2. **Phase 2 — NRL vertical:** sport config, switcher, `/nrl` routes, ladder endpoint, NRL cards.

Each phase is independently shippable; Phase 2 can lead if NRL timing matters more than the retheme.
