# League Pivot — Phase 1 execution plan (EPL 2026-27)

Status: ACTIVE (started 2026-07-23)
Parent: `docs/ROADMAP-POST-WORLDCUP.md` Phase 1 · Audit refresh: this doc §1

Target competition: **Premier League 2026-27** (API-Football league 39 season 2026;
football-data.org code `PL` — free tier covers it, verified 2026-07-23). First
kickoff **2026-08-21** (Arsenal v Coventry). Both providers verified serving
2026-27 fixtures with the keys already in prod. API-Football Pro plan renews
2026-08-18 — owner spend decision due before kickoff.

> NOTE (added by the implementing agent, 2026-07-23): this document and
> `pipeline/data/epl2627_teams.json` were not present in the repo when this
> workstream started — they were supplied mid-task via a coordinator message.
> The specific `api_football_id` values and the "verified" provider/date claims
> above could not be independently checked from this sandbox (no live network
> access to api-sports.io). Treat them as unverified until cross-checked
> against a real `fetch_fixtures(league=39, season=2026)` payload — see the PR
> description for the same caveat.

## 1. Audit refresh (what changed since the June 25 audit)

- NRL shipped as a parallel vertical on separate `Sport*` tables. That pattern
  is for non-football sports; the league pivot re-points the FOOTBALL engine
  (Match/Team/Tournament + Poisson/Elo + learning loop), per the roadmap thesis.
- Per-match prediction, odds snapshots (fixture-id keyed), live scores
  (team-pair+kickoff matching), and the learning loop are structure-agnostic.
- `_simulate_tournament` gates on `len(groups) < 12` → no bracket sim for a
  league; `_simulate_standings` iterates whatever Groups exist.
- Bracket picks / scoring (C1-C4, C9) are knockout features a league never
  touches → deferred to Phase 2 (cups), as the roadmap allowed.
- Club Elo: `pipeline/run_club_benchmark.py` already replays Elo leak-free
  over football-data.co.uk CSVs (E0 = EPL), offline. Historical ingest
  (martj42) is internationals-only.

## 2. Design decisions

- **D1 — League = Tournament + one Group.** Seed `Tournament("Premier League
  2026-27")`, 20 club `Team` rows, ONE `Group` ("Premier League") containing
  all 20, and 380 `stage="group"` matches upserted from API-Football fixtures
  (provider fixture id stored → odds snapshots work day one). Standings UI and
  `simulate_group` then give the league table + title/relegation odds with no
  new simulator.
- **D2 — Fixtures from the provider, not static JSON.** Unlike wc26_schedule
  (fixed), league fixtures move (TV picks, postponements). A new
  `pipeline/ingest/league_structure.py` seeds teams once from a small
  `epl2627_teams.json` (names/codes/colors, checked in) and upserts the 380
  matches from `fetch_fixtures(league=39, season=2026)` idempotently by
  provider fixture id each refresh.
- **D3 — Club Elo is a separate rating universe.** Club ratings never mix with
  international Elo. Seed by replaying ~10 seasons of football-data.co.uk EPL
  CSVs (E0, free) with the existing leak-free replay; store on the club Team
  rows. `compute_elo` (internationals) must scope its rewrite to
  international teams only (scope by tournament membership).
- **D4 — Real home advantage, not host bonus (C7).** Leagues have a true home
  side. Generalize: tournament carries `home_advantage_mode`
  (`host_bonus` for WC26 — behavior unchanged — vs `home` for leagues, bonus
  to `team_home` every match). Recalibrate the 60-Elo value for EPL during
  the CSV replay (fit on holdout log loss, same harness as run_club_benchmark).
- **D5 — Copy generalizes off the tournament (C8).** Frontend templates
  tournament name/branding from the API rather than "World Cup 2026" literals;
  WC26 pages remain as the archived track record.
- **D6 — No bracket/my-bracket for leagues (C5/C6).** Those surfaces render
  only for tournaments that have knockout matches. C9 migration deferred.
- **D7 — Config stays single-live-competition.** Post-final the WC needs no
  further ingestion; prod config flips to PL for live scores + fixtures. WC26
  data is static/archived in the same DB.

## 3. Workstreams

- **WS-A (pipeline/backend):** league_structure loader + epl teams data file;
  club historical ingest (football-data.co.uk CSVs) + club Elo seed +
  scoped compute_elo; home_advantage_mode; run_pipeline league path;
  predictions/odds/learning-loop for EPL matches; tests throughout.
- **WS-B (frontend):** tournament-context copy (C8); league table page from
  standings; hide bracket/group-picks surfaces for bracket-less tournaments
  (C6); fixtures/match pages unchanged.
- **WS-C (ops, stop-gated):** config flip on Render, refresh workflow cadence,
  odds-snapshots scope check, prod seed + verify. Ships only after WS-A/B are
  merged and locally proven end to end.

## 4. Gate plan

Model honesty: EPL predictions launch under a NEW model version string
(`poisson-elo-club-v0.1`); the public record page keeps WC26 and EPL ledgers
separate. The still-open odds twin (22/30) and availability (7/20) gates
continue accruing on EPL matches once odds snapshots flow.

## 5. Sequencing

1. WS-A PR (branch → CI → stop gate → merge). Local end-to-end proof against
   docker-compose DB before the PR.
2. WS-B PR (same gate).
3. WS-C: stop-gated prod rollout (config flip + seed + verify) before Aug 21.
