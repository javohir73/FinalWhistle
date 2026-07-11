# State of Origin — Design

**Date:** 2026-07-11
**Status:** Approved (brainstorm 2026-07-11)
**Owner decisions:** Origin lives inside the NRL section; history seeded from a free
API; thin new lane reusing NRL parts.

## Summary

Add State of Origin (rugby league representative series, NSW Blues vs QLD Maroons,
three games per year) to FinalWhistle as a second lane on the existing sport-generic
rail. New pipeline modules ingest and predict Origin matches into the existing
`sport_*` tables under `sport="state-of-origin"`; the NRL margin-Elo model is reused
with Origin-tuned parameters; two new API endpoints and one new frontend page under
`/nrl/origin` surface the series, per-game predictions, series-winner odds, and the
model's record.

**Timing context:** the 2026 series completed on 2026-07-08 (Blues won 2–1). Launch
deliverable is the series history plus a backtested model record; live frozen
predictions begin when 2027 fixtures appear in the feed (~May 2027).

## Non-goals

- No ladder, leaderboard/bracket game, or team profile pages — they do not fit a
  2-team, 3-game format.
- No player-level or squad-selection modelling.
- No generalization refactor of the NRL lane beyond small backward-compatible
  parameter additions.
- No DB schema changes (the `sport_*` tables already support this).

## 1. Product shape

New page `/nrl/origin`, linked from the NRL section nav ("Origin"). Contents:

- **Series header** — season selector; series score and outcome (e.g. "2026:
  Blues win the series 2–1"); date and venue per game.
- **Game cards** — one per game: final score for played games, model
  probabilities (home/draw/away) and expected margin, and — once live seasons
  resume — the frozen-at-kickoff prediction with graded outcome.
- **Series-winner odds** — for a live or upcoming series: P(Blues win series),
  P(Maroons win series), P(series drawn), by exact enumeration of the remaining
  games' three outcomes (win/draw/loss per game) combined with the current
  series score. A drawn series (e.g. 1–1 with a drawn game) is a real historical
  outcome and is reported, not elided.
- **Model record strip** — accuracy, log loss, Brier over graded history.
  Pre-2025 numbers come from replay retrodictions and are labeled **"backtest"**;
  real frozen-prediction grades (2027+) are labeled as live record. The UI keeps
  the two visually distinct so the record page stays honest.

## 2. Data

Two sources, one canonical store:

- **History seed (1982–2024):** a one-time script pulls TheSportsDB
  (league id 5835, verified to hold full Origin results back to 1982:
  3 events/season with scores) and writes a static JSON committed to the repo
  at `data/raw/state_of_origin_history.json`. Ingest loads the committed file, so
  there is **no runtime dependency on TheSportsDB** and the immutable history
  cannot drift. The seed script records source and fetch date in the file header.
- **Live seasons (2025+):** `https://fixturedownload.com/feed/json/state-of-origin-{year}`
  — verified live; identical row shape to the NRL feed (`MatchNumber`,
  `RoundNumber`, `DateUtc`, `Location`, `HomeTeam`, `AwayTeam`, scores).
- **Name normalization:** the feeds disagree ("Blues"/"Maroons" vs
  "New South Wales Blues"/"Queensland Maroons"). Both are mapped to canonical
  `SportTeam` names — **"NSW Blues"** and **"QLD Maroons"** — before upsert, so
  the two sources can never create duplicate teams.
- **Storage:** existing tables `SportMatch` / `SportTeam` / `SportPrediction` /
  `SportPredictionResult`, keyed `sport="state-of-origin"`, `season`=year,
  `round`=game number (1–3), `match_no` from the feed. **No migration.**

## 3. Model

Reuse `ml/sports/nrl/model.py` unchanged — `update`, `predict`,
`regress_season`, and the frozen params dataclass are pure sport-agnostic math.
Origin gets its own params instance and persisted `params.json` under
`ml/sports/origin/`:

- `version="origin-elo-v0.1"`.
- Own K, home advantage, margin slope/sigma, and draw mass. Priors: higher K
  (3 games/year means each game carries more information), weak-or-zero season
  regression (same player pool era to era), draw mass fitted to Origin history
  (draws occurred pre-golden-point).
- **Neutral venues:** Origin games at MCG, Optus Stadium, Adelaide Oval etc.
  carry no true home advantage. A small `NEUTRAL_VENUES` set in the Origin
  module routes these through the model's existing `neutral=True` path. Venue
  strings missing from the seed data default to non-neutral (the designated
  home side keeps advantage) — an accepted approximation, noted in code.
- **Tuning:** a backtest over the seeded history with a chronological
  train/validate split selects the params; tuned values are committed like the
  NRL lane's `params.json`. The backtest doubles as the source of the labeled
  "backtest" record.

## 4. Pipeline and scheduling

- `pipeline/sports/origin_ingest.py` — thin module:
  - Reuses `nrl_ingest.parse_row` (already pure and sport-agnostic).
  - `nrl_ingest.upsert_season` and `_get_or_create_team` gain optional
    `sport=`/feed-URL keyword parameters with NRL defaults — a
    backward-compatible signature addition; NRL behavior and tests unchanged.
  - `--seed` mode loads the committed history JSON; `--seasons START END` mode
    pulls fixturedownload for 2025+. Both idempotent; the existing freshness
    guard (finished matches immutable) applies.
- `pipeline/sports/origin_predict.py` — mirrors `nrl_predict`:
  - `--generate`: replay all finished Origin matches in kickoff order → current
    Elo state (synced to `SportTeam.elo_rating`) → predictions for scheduled
    matches → `SportPrediction(is_shadow=True)`.
  - `--grade`: score finished matches against the latest pre-kickoff prediction
    → `SportPredictionResult` (append-only).
  - Imports `nrl_predict` helpers where they are cleanly reusable; small
    Origin-specific glue is written fresh rather than forcing reuse.
- **Series-odds function** — pure function in `ml/sports/origin/series.py`
  (pure math belongs in `ml/`, like the Elo model): inputs = current series
  score + per-game probability
  triples for remaining games; output = P(Blues series), P(Maroons series),
  P(drawn series) by exact enumeration (≤3³ outcomes).
- **Scheduling:** extend the existing `.github/workflows/nrl-refresh.yml` with
  Origin ingest + predict + grade steps (same Monday/Friday cadence; cheap
  no-ops off-season). No new cron workflow.

## 5. API

Two endpoints added to the existing `backend/app/api/sports.py` router
(prefix `/api/nrl`):

- `GET /api/nrl/origin/series?season={year}` — season defaults to the latest
  available. Returns: games (kickoff, venue, teams, status, scores), the latest
  prediction per game, current/final series score, series outcome if decided,
  and series-winner odds when games remain.
- `GET /api/nrl/origin/record` — aggregated model performance from the
  `SportPredictionResult` ledger, split into `backtest` and `live` segments so
  the frontend can label them separately.

Both read the same tables the NRL endpoints read; no new auth surface; response
shapes follow the existing NRL response idioms. `movers.py`'s sport validation
tuple gains `"state-of-origin"` only if Origin snapshots are wired into movers —
otherwise untouched (YAGNI; not part of this design).

## 6. Frontend

- `frontend/app/nrl/origin/page.tsx` — the page described in §1.
- `OriginGameCard` component, or `SportMatchCard` reused if it fits without
  contortion (decided at implementation; prefer reuse).
- `frontend/lib/sports.ts` — add an "Origin" entry to `SPORTS.nrl.navLinks`.
  No new `SportId`; Origin is not a third sport in the switcher.
- `frontend/lib/api.ts` — `getOriginSeries(season?)`, `getOriginRecord()`.
- `frontend/lib/types.ts` — `OriginSeriesResponse`, `OriginGame`,
  `OriginRecord` types mirroring the API shapes.

## 7. Error handling

- Feed failures follow the NRL idiom: fetch never raises, returns `[]`, one bad
  season cannot abort a backfill; finished matches are never clobbered.
- Malformed seed rows are skipped with a warning at seed-file build time (the
  committed file is expected to be 100% clean; ingest still tolerates).
- API endpoints return 404 for a season with no Origin matches; empty-record
  states return zeroed aggregates with counts so the frontend can render an
  honest "no graded predictions yet" state.
- Frontend renders gracefully with no live series (the common state ~10 months
  of the year): history + record only, no odds panel.

## 8. Testing

Mirror the NRL lane's test structure:

- `origin_ingest_test.py` — both sources, name normalization, seed idempotency,
  freshness guard, malformed rows.
- `origin_predict_test.py` — replay order, prediction writes, grading.
- Series-odds pure function — exhaustive enumeration cases including drawn
  games and already-decided series.
- Params/backtest tests mirroring `ml/sports/nrl/*_test.py`.
- API endpoint tests (season selection, series odds presence/absence, record
  segmentation).
- Frontend: page render test + API client typing, per existing NRL page tests.
- Gate: full `make test` (backend + ml + pipeline + frontend typecheck/lint/test).

## 9. Rollout

Guarded pipeline: feature branch → PR → CI green → plain-English summary →
explicit "go" → merge. Post-merge, the one-time prod backfill (seed + 2025–26
ingest + predict/grade replay) runs like a `refresh.yml`-style op against the
prod DB and therefore **goes through the stop gate**. Verify afterwards via
`GET /api/health`, `GET /api/nrl/origin/series?season=2026`, and the page on
the deployed frontend.
