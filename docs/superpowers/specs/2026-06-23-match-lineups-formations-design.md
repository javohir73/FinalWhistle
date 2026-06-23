# Match Lineups & Formations — Design

_Date: 2026-06-23 · Status: approved (design) · Branch: `feat/match-lineups`_

## Goal

Show each team's **formation + starting XI (on a pitch) and bench** on every
**match detail** page, and the **most-recent match XI** on the **team/country
dashboard** (`/team/[id]`). Data must be **real and official**, sourced from
API-Football — consistent with the app's "real data, not betting advice" ethos.

## Context & constraints (why this shape)

- The app today has **no lineup/formation/player data**. The DB has `Team`,
  `Match`, `Prediction`, … but no players/lineups table. The only player-level
  data is goal scorers (`Match.goal_events` JSON), shown in the scoreboard.
- The model **deliberately excludes squads** ("individual player form and
  injuries aren't factored in"). Lineups are a **display-only** addition; they
  do **not** feed the prediction model.
- The data pipeline already integrates **API-Football** (`pipeline/ingest/
  api_football.py`) for fixtures + goal events, but does **not** fetch
  `/fixtures/lineups`.
- **Real lineups only exist ~40 min before kickoff.** Future fixtures have none.
- A national team has **no single canonical formation** — it varies per match.
  The team dashboard therefore shows the **most-recent finished match** XI,
  explicitly labeled, not a generic "team formation".
- Render free tier has **no cron/worker**, and live ingestion is currently off
  (`LIVE_MODE_ENABLED=false`). The design must not depend on a scheduler.

## Decisions (locked)

1. **Data source:** real lineups via API-Football `/fixtures/lineups`.
2. **Match detail UI:** pitch diagram (XI positioned by grid) + bench + coach.
3. **Team dashboard UI:** most-recent finished match's XI, labeled "vs {opp} · {date}".
4. **Ingestion strategy:** on-demand fetch + persist (lazy), no scheduler.

## Architecture

### Ingestion strategy — on-demand fetch + persist

The lineups endpoint is the single entry point:

1. If lineups for `(match_id)` are already in the DB → return them.
2. Else if the match is **within the lineup window** (kickoff − 75 min onward,
   through finished) **and** we can resolve a provider fixture id → call
   API-Football `/fixtures/lineups`, persist, return.
3. Else (future fixture, or no key, or provider returns empty) → return
   `{ available: false, message: "Lineups are announced ~40 minutes before kickoff." }`
   with **no** external call when out of window.

Each lineup is fetched **once** and cached permanently, minimizing API quota.
Rejected alternatives: scheduled near-kickoff ingestion (needs cron the free
tier lacks); manual admin trigger (operationally painful).

### Match → API fixture mapping

`Match` has no external id today. Add `Match.provider_fixture_id` (nullable).
Resolution order when fetching lineups:

1. Use `Match.provider_fixture_id` if set (also populated opportunistically by
   the existing live-scores ingestion when it matches a fixture).
2. Else resolve on demand by **home/away team + kickoff date** against
   API-Football `/fixtures`, store the resolved id on the match, then fetch.

### Data model (new SQLAlchemy tables, `backend/app/models`)

```
match_lineups
  id            PK
  match_id      FK -> matches.id
  side          str  "home" | "away"
  formation     str  e.g. "4-3-3"  (nullable)
  coach         str  (nullable)
  provider      str  "api_football"
  fetched_at    datetime (tz)
  UNIQUE(match_id, side)

lineup_players
  id                 PK
  match_lineup_id    FK -> match_lineups.id
  name               str
  number             int  (nullable)
  position           str  "G" | "D" | "M" | "F"  (nullable)
  grid               str  "row:col" e.g. "4:2"   (nullable; null for bench)
  is_starter         bool
  order              int  (stable sort within starter/bench)
```

Migration via the project's existing mechanism (confirm Alembic vs `create_all`
during planning).

### Backend

- `pipeline/ingest/api_football.py`: add `fetch_lineups(api_key, fixture_id)` →
  parse `response[].{team, formation, coach, startXI[].player{name,number,pos,grid},
  substitutes[].player{...}}` into our row shape. Pure mapping function, unit-tested.
- `backend/app/api/matches.py` (or new `lineups.py`):
  `GET /api/matches/{id}/lineups` → `LineupsResponse`:
  ```
  { available: bool,
    message: str | null,
    home: { team, formation, coach, startXI: Player[], bench: Player[] } | null,
    away: { ... } | null,
    fetched_at: str | null }
  Player = { name, number, position, grid, is_starter }
  ```
- Pydantic schemas in `backend/app/schemas`.
- Graceful degradation: missing API key, out-of-window, or provider error all
  resolve to `available: false` (never a 5xx that breaks the page).

### Frontend

- `lib/types.ts`: `Lineup`, `LineupPlayer`, `LineupsResponse`.
- `lib/api.ts`: `getMatchLineups(matchId)` (+ server variant if SSR'd).
- `components/FormationPitch.tsx`: renders a vertical pitch; positions the XI
  from `grid` (row = defensive→attacking line, col = left→right); shirt numbers;
  tap a player → name + position. AA contrast, `prefers-reduced-motion` safe,
  keyboard-accessible (matches existing app standards).
- `components/MatchLineups.tsx` (client island): lazy-fetches via
  `getMatchLineups`; renders home + away pitches + bench/coach lists; or the
  "announced ~40 min before kickoff" placeholder; or an error + "Try again"
  (reusing the `useFetch.retry` / `ErrorState` pattern). Honest attribution line:
  "Official lineup — via API-Football · fetched {time}".
- **Match detail** `app/match/[id]/page.tsx`: add a Lineups section under the
  scoreboard.
- **Team dashboard** `app/team/[id]/page.tsx`: resolve the team's most-recent
  finished match, render its XI via the shared component, labeled
  "Last XI · vs {opp} · {date}". If the team hasn't played, show a short
  "No recent lineup yet" note.

## Honesty & availability

- No fabricated data: when a lineup isn't available, say so plainly.
- Always attribute the source + fetched time.
- Keep the app's disclaimer tone; lineups are informational, not predictive.

## Dependencies / risks

1. **`API_FOOTBALL_API_KEY` must be set in prod** (currently commented out).
   Without it the feature degrades to placeholders everywhere — no errors.
2. **Near-kickoff-only data**: imminent + finished matches populate during the
   live tournament; far-future fixtures stay on the placeholder.
3. **Fixture-id resolution** reuses the live-ingestion matching logic; first
   resolution is by teams + kickoff date and is then cached on the match.
4. **API quota**: bounded by on-demand + permanent cache (one fetch per match).

## Testing

- Backend: `fetch_lineups` parser unit tests (API JSON → rows, incl. grid
  parsing, missing/optional fields, bench, coach). Endpoint tests for the three
  branches (cached / fetch-on-window / out-of-window placeholder) with the
  provider mocked.
- Frontend: `FormationPitch` render test (grid → on-pitch positions, 11
  starters), `MatchLineups` state tests (loading / available / placeholder /
  error+retry). Team-dashboard "most-recent XI" selection test.

## Out of scope (non-goals)

- Feeding lineups/players into the prediction model.
- Per-player stats, ratings, photos, or injuries.
- Predicting/fabricating a "likely XI" when no official lineup exists.
- A persistent squad database for all 48 teams (only fetched match lineups are
  stored).
- Scheduled/background ingestion (explicitly avoided; on-demand only).
