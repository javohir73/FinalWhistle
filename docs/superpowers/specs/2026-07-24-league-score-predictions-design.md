# League Score Predictions — "Beat the AI's scoreline"

Date: 2026-07-24
Status: APPROVED (design), spec pending user review
Scope: EPL-first, league-generic. La Liga + Bundesliga follow as Phase 2 config.
Related: NRL tips loop (PRs #174–#177) — the proven pattern this ports;
`docs/LEAGUE-PIVOT-PLAN.md` — the pipeline foundation this builds on.

## Problem

The EPL 2026-27 season kicks off ~Aug 21 (verify exact date in Phase 1, task 0).
The league-pivot work made the pipeline league-ready (fixtures, club Elo, home
advantage, `poisson-elo-club-v*` ledger) but there is no user-facing loop for
football leagues: the retention bridge promises "Premier League predictions
arrive" and nothing participatory exists behind it. The NRL slices proved the
loop pattern (tipsheet → beat-the-AI → leaderboards → share). Football needs the
culturally native variant before kickoff — and the user has committed to La Liga
and Bundesliga next, so nothing may be EPL-hardcoded.

## Product

Per matchweek, per league:

- The tipsheet shows every fixture with the AI's predicted scoreline — the
  Dixon–Coles most-likely score the pipeline already freezes pre-kickoff. Shown
  openly (same transparency posture as the NRL tipsheet). Copying the AI is
  legal and self-defeating: identical predictions can only tie.
- The player predicts a scoreline per fixture (home/away goals, bounded 0–15).
  Each prediction locks at its match's kickoff, enforced by the server clock.
- Scoring (Super 6-compatible): **5 points exact score, 2 points correct
  result** (win/draw/loss direction), 0 otherwise. Not cumulative — an exact
  score earns 5, not 7. The AI is scored under identical rules; its entry is
  its published scoreline.
- Matchweek + season leaderboards, visible at ≥10 participants (same gate
  pattern as NRL; below the gate, a quiet participant count only).
- You-vs-AI running record with current/best streak (consecutive scoring
  predictions — any points > 0 — in kickoff order, season-scoped) and best
  matchweek.
- Unfakeable share cards: handle-addressed share pages rendering only stored
  graded results; unknown handle or ungraded matchweek → 404.

## Architecture

### Data model (one migration — stop-gated ship sequencing)

New table `league_score_predictions` (name per repo taste at build time):

- `tournament_id` FK → tournaments (the league)
- `match_id` FK → `matches.id` (football Match table; league fixtures live
  here per LEAGUE-PIVOT-PLAN D1)
- `player_id` FK → `tip_players` — **reuses the existing cross-sport identity
  pool**: device-first play, generated handles, and the account-claim flow all
  come for free
- `predicted_home`, `predicted_away` (small ints, 0–15, validated)
- `created_at`, `updated_at` (no ORM onupdate — set explicitly, per the NRL
  slice-2 critical-finding lesson)
- Grading columns: `points` (nullable int), `exact` (nullable bool),
  `graded_at` (nullable)
- Unique (match_id, player_id); indexes for per-matchweek leaderboard and
  per-player reads

No changes to `tip_players`, `matches`, or any NRL table.

### API (mirror of the NRL five, league-parameterized)

All endpoints take a league identifier (short code, e.g. `epl`, resolved to a
tournament; 404 on unknown/inactive league). Follow the NRL routes' idioms for
validation, error shapes, rate limits, and cache classes:

- `POST .../submit` — {device_id, match_id, predicted_home, predicted_away}.
  UUIDv4 device validation, per-device + per-IP rate limit, 422 `match_locked`
  at/after kickoff (server clock), upsert until kickoff, creates the TipPlayer
  row on first submit. No-store.
- `GET .../mine` — the device's predictions for a matchweek with grading once
  graded, plus the AI's scorelines and points. No-store.
- `GET .../summary` — season you-vs-AI: per-matchweek points, totals, streaks,
  best matchweek. No-store.
- `GET .../leaderboard` (matchweek) and `.../leaderboard/season` — ≥10 gate,
  participant_count always; rank by points desc, then exact-count desc (the
  natural score-prediction tiebreak, replacing NRL's margin), then handle for
  stability. Public 60s cache.
- `GET .../share/{league}/{matchweek}/{handle}` — graded results only; never
  pre-kickoff picks, never device ids. Public cache, 60s revalidate on the
  page (pre-grading-404 lesson from slice 2.5).
- `POST /api/nrl/tips/claim` already claims the shared TipPlayer — verify it
  needs no change (it operates on the identity row, not sport rows).

### Pipeline

- `run_pipeline`'s league branch iterates a configured league list
  (Phase 1: `["epl"]`): structure/fixtures ingest → finished-results sync →
  club Elo → predictions → learning loop → **new: score-prediction grading
  pass** (idempotent by recompute, mirroring `pipeline/sports/nrl_user_tips.py`;
  only predictions with updated_at ≤ kickoff count; re-grades on corrected
  results; non-fatal to the rest of the pipeline).
- Per-league model record: tournament-filtered queries over the
  `poisson-elo-club-v*` ledger (version prefix stays shared across leagues).
- Matchweek derivation: fixtures carry round/matchweek from API-Football
  ingestion; the tipsheet's "current matchweek" = earliest matchweek containing
  a scheduled fixture, else the latest played (same rule shape as NRL's
  `_current_round`).

### Frontend

- `/tips` on the football side: current-matchweek score picker — stepper UI per
  fixture, AI scoreline displayed, per-fixture lock state, optimistic UI with
  confirmed-only localStorage cache (PlayRound patterns), matchweek prev/next
  navigation, "from the model, frozen pre-kickoff" provenance, disclaimer.
- You-vs-AI section + Weekly|Season leaderboard toggle (ports of the NRL
  components, league-aware).
- Share pages + route-param OG cards (`/tips/share/[league]/[matchweek]/[handle]`).
- Entry: home-page card, matches-page link, retention-bridge copy updated to
  point at `/tips` when the league goes live.
- League switcher: deferred to Phase 2 (appears when >1 league is active).
  All components take the league from context/props — no hardcoding.
- ISR posture identical to NRL pages (revalidate ~300s; user state client-side
  only).

## Phasing

- **Phase 1 (now → live with buffer before EPL kickoff):** everything above,
  EPL only. Ship order: migration + backend + pipeline + frontend on one
  branch → PR → CI → stop gate → merge → dispatch refresh workflow (migration)
  → **separate stop-gated step: flip prod `pipeline_target` to "league"**
  (this turns the WC26 pipeline branch off — correct post-Cup, but it is a
  prod-behavior change and ships explicitly, not as a side effect) → verify
  fixtures/predictions flow → verify the loop end-to-end.
- **Phase 2 (days later, zero product code):** La Liga + Bundesliga — teams
  JSONs, league configs (API-Football ids 140/78), football-data.co.uk
  `SP1`/`D1` historical backfills, per-league club Elo + home-advantage fits,
  league switcher UI. **Gated on the API-Football quota check (founder
  action): three leagues ≈ 3× fixture polling.**

## Edge cases

- Postponed/rescheduled fixtures: ingestion upserts by provider fixture id;
  locks are per-kickoff, so a rescheduled match re-opens until its new kickoff.
- Abandoned matches: grade null (never scored), consistent with the ledger.
- 0-0 is a valid prediction and a valid exact score.
- Promoted clubs with no Elo history: seeded at the default rating by
  `compute_club_elo` (verify at build; document actual behavior).
- A fixture moved across matchweeks keeps its prediction (keyed by match, not
  matchweek).
- Draw predictions and draw results are first-class in the 2-point result rule.

## Testing

Mirror the NRL suites: kickoff-lock matrix (before/at/after, edit-after),
scoring matrix (exact / result-only / miss, including draws and 0-0),
idempotent regrade + corrected-result regrade, leaderboard gates and the
exact-count tiebreak, share 404s (unknown handle, ungraded matchweek,
pre-kickoff-leak test), cross-league isolation (an EPL prediction never
surfaces under another league), matchweek derivation, promoted-club Elo
seeding, and frontend picker/lock/URL states.

## Open items (resolve during build or before Phase 2)

1. Exact EPL 2026-27 opening fixture date/time — pin the ship deadline.
2. API-Football quota headroom for 3 leagues (founder checks plan).
3. Whether `/api/model-record`'s public football record page should grow a
   league filter now or in Phase 2 (default: Phase 2).
4. Bridge email send ("your league kicks off") still blocked on Resend domain
   verification (founder action; outward send is stop-gated).
