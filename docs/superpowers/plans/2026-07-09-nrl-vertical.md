# NRL Vertical (Universal Model, Instance #2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NRL predictions running shadow-first on the platform — Elo + margin model, season-based walk-forward validation, frozen pre-kickoff predictions, and a graded ledger — with zero changes to any football file.

**Architecture:** A parallel sport vertical: generic `sport_*` tables (sport-scoped, so NFL/NBA reuse them without new schema), a self-contained `ml/sports/nrl/` model (margin-based Elo → win prob + expected margin, tiny empirical draw mass for golden-point survivals), a fixturedownload.com ingest adapter, CLI-driven prediction generation with the same append-only/frozen-at-kickoff rule as football, and read-only API endpoints. **Deliberate spec §5.2 deviation, approved direction:** the sport-agnostic `core/` extraction is deferred until after the WC26 final (Jul 19) — football is live mid-tournament and is not touched; consolidation happens when two sports exist to generalize from.

**Tech Stack:** Existing stack (FastAPI, SQLAlchemy + alembic, pytest). Data: `https://fixturedownload.com/feed/json/nrl-{year}` (verified live: JSON array of {MatchNumber, RoundNumber, DateUtc, Location, HomeTeam, AwayTeam, HomeTeamScore, AwayTeamScore, Winner}; requires a browser User-Agent header). Deep-history fallback if ever needed: uselessnrlstats (rugbyleagueproject.org extracts).

## Global Constraints

- **Do not modify any football file.** No edits under `ml/models/`, `ml/ratings/`, `ml/evaluation/`, `pipeline/` top-level football scripts, or football API routers. New code lives in `ml/sports/nrl/`, `pipeline/sports/`, `backend/app/api/sports.py`, plus one additive migration. (Reusing football modules by IMPORT is allowed where signatures fit; copying-and-adapting small pure functions is allowed with a provenance comment.)
- **This plan contains a migration** (`sport_*` tables). Repo rule applies: migration must reach the prod DB via `refresh.yml` dispatch before/with the code deploy; the PR body must carry the sequencing checklist. Tables are additive; football paths never read them, so the blast radius of a mis-ordered deploy is the new NRL endpoints only.
- **Shadow-first, gated:** every NRL prediction row ships `is_shadow=True`. Going public is a separate later decision requiring: (a) walk-forward gate — beat the favorite baseline on 3-way log loss on ≥2 of the 3 most recent held-out seasons; (b) ≥2 live shadow rounds graded clean. That flip is a stop-gate action.
- Frozen-at-kickoff, append-only predictions: identical rule to football — no row may be written or amended once a match leaves "scheduled".
- Test gates before any "done": `.venv/bin/python -m pytest backend ml pipeline` green. Python via `.venv/bin/python`, pipeline modules with `PYTHONPATH=backend:.` from repo root.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Never merge; PR + stop gate. External fetches: fixturedownload only, with `User-Agent: Mozilla/5.0` header, never-raises contract (failed fetch leaves DB unchanged).
- NRL domain constants (fit, don't hand-wave): matches per season ~200 (27 rounds, 17 teams, byes) + 9 finals; golden-point era draws are rare but real — outcome space stays {home, draw, away}.

---

### Task 1: `sport_*` schema + migration

**Files:**
- Modify: `backend/app/models/__init__.py` (append new models; follow the file's existing column style)
- Create: `backend/alembic/versions/<gen>_add_sport_tables.py` (autogenerate revision id; down_revision = current head — verify with `alembic heads`)
- Test: `backend/tests/test_sport_models.py`

**Interfaces:**
- Produces (exact names, later tasks import these): `SportTeam(id, sport, name, elo_rating, meta)` unique on (sport, name); `SportMatch(id, sport, season, round, match_no, kickoff_utc, venue, home_team_id, away_team_id, score_home, score_away, status)` with status in {"scheduled","finished"} default "scheduled", unique on (sport, season, match_no); `SportPrediction(id, match_id FK sport_matches, model_version, created_at, p_home, p_draw, p_away, expected_margin, is_shadow default True)`; `SportPredictionResult(id, match_id, prediction_id, model_version, outcome, winner_correct, prob_assigned, log_loss, brier, margin_error, evaluated_at)`.

- [ ] **Step 1: Write the failing test**

```python
"""backend/tests/test_sport_models.py"""
from datetime import datetime, timezone


def test_sport_tables_round_trip(client):
    _, TestingSession = client
    db = TestingSession()
    from app.models import SportMatch, SportPrediction, SportTeam

    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db.add_all([a, b])
    db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=3,
                   kickoff_utc=datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
                   venue="AAMI Park", home_team_id=a.id, away_team_id=b.id,
                   score_home=52, score_away=4, status="finished")
    db.add(m)
    db.flush()
    p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                        p_home=0.71, p_draw=0.01, p_away=0.28,
                        expected_margin=8.5)
    db.add(p)
    db.commit()
    assert db.get(SportPrediction, p.id).is_shadow is True
    assert db.get(SportMatch, m.id).status == "finished"


def test_sport_team_unique_per_sport(client):
    _, TestingSession = client
    db = TestingSession()
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.models import SportTeam

    db.add_all([SportTeam(sport="nrl", name="Storm"),
                SportTeam(sport="nfl", name="Storm")])
    db.commit()  # same name, different sport: fine
    db.add(SportTeam(sport="nrl", name="Storm"))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest backend/tests/test_sport_models.py -q` → FAIL (ImportError: SportTeam).
- [ ] **Step 3: Implement models** (append to `backend/app/models/__init__.py`, mirroring existing declarative style; UniqueConstraint on (sport, name) and (sport, season, match_no); `is_shadow` server-side default true; all new-table columns nullable except keys/sport/name/status/is_shadow). Then write the alembic migration by hand following the July migrations' style (additive `op.create_table` × 4, exact inverse `op.drop_table` × 4 in downgrade; nullable per model). DO NOT run alembic against any DB except the local dev one (`cd backend && ../.venv/bin/python -m alembic upgrade head` is allowed and needed for local runs).
- [ ] **Step 4: Verify** — targeted test passes; then `.venv/bin/python -m pytest backend -q` all green.
- [ ] **Step 5: Commit** — `feat(sports): sport-scoped tables for the multi-sport vertical`

---

### Task 2: fixturedownload ingest adapter + season backfill CLI

**Files:**
- Create: `pipeline/sports/__init__.py`, `pipeline/sports/nrl_ingest.py`
- Test: `pipeline/sports/nrl_ingest_test.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces: `fetch_season(year) -> list[dict]` (raw feed rows; requests.get with `headers={"User-Agent": "Mozilla/5.0"}`, timeout 20, returns [] and logs on any error); `parse_row(row) -> dict | None` (pure; None for malformed rows — missing team names or unparseable DateUtc; scores None when either is null → status "scheduled", both present → "finished"); `upsert_season(db, year, rows) -> dict` idempotent counts `{"created": n, "updated": m}` keyed on (sport="nrl", season, match_no=MatchNumber), creating SportTeams on first sight by (sport, name); CLI `python -m pipeline.sports.nrl_ingest --seasons 2016 2026` looping inclusive.

- [ ] **Step 1: Failing tests** — pure-parse cases (finished row from the verified live shape incl. `"DateUtc": "2026-03-01 02:15:00Z"` parsing; scheduled row with null scores; malformed row → None) and an upsert test against the DB fixture (insert twice → second run `created==0`; a score arriving later flips status to finished and fills scores — but NEVER when the stored row is already finished, mirroring the freshness-guard spirit). Use the exact live sample from the feed as the test fixture:

```python
SAMPLE = {"MatchNumber": 1, "RoundNumber": 1, "DateUtc": "2026-03-01 02:15:00Z",
          "Location": "Allegiant Stadium", "HomeTeam": "Knights",
          "AwayTeam": "Cowboys", "Group": None,
          "HomeTeamScore": 28, "AwayTeamScore": 18, "Winner": "Knights"}
```

- [ ] **Step 2: RED**, **Step 3: implement** (mirror `pipeline/ingest/injuries.py`'s never-raises structure and logging idiom), **Step 4: GREEN + pipeline suite**, **Step 5: commit** — `feat(sports): NRL ingest from fixturedownload (idempotent, never-raises)`.
- [ ] **Step 6: Real backfill against local DB** — `PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_ingest --seasons 2016 2026`; paste the per-season counts into the report. If a season 404s (feed doesn't go back that far), the CLI logs and continues — record the earliest available season; ≥6 seasons of history is the acceptance bar (else STOP and report BLOCKED: the model tasks need history).

---

### Task 3: NRL Elo + margin model (pure math)

**Files:**
- Create: `ml/sports/__init__.py`, `ml/sports/nrl/__init__.py`, `ml/sports/nrl/model.py`
- Test: `ml/sports/nrl/model_test.py`

**Interfaces (exact — Tasks 4/5 import these):**

```python
@dataclass(frozen=True)
class NrlParams:
    version: str = "nrl-elo-v0.1"
    k: float = 36.0                 # per-match Elo K
    home_adv: float = 45.0          # Elo points
    margin_mult_cap: float = 2.2    # cap on the margin multiplier
    season_regress: float = 0.25    # off-season regression toward the mean
    margin_slope: float = 0.045     # expected points margin per Elo diff point
    margin_sigma: float = 15.0      # residual std dev of margins
    p_draw: float = 0.012           # empirical golden-point-era draw mass

def expected_home_prob(elo_home, elo_away, home_adv) -> float   # 1/(1+10^(-(diff+adv)/400))
def margin_multiplier(margin, cap) -> float                     # ln(|margin|+1), capped
def update(elo_home, elo_away, score_home, score_away, p: NrlParams) -> tuple[float, float]
def regress_season(elos: dict[int, float], p: NrlParams, mean: float = 1500.0) -> dict[int, float]
def predict(elo_home, elo_away, p: NrlParams, neutral: bool = False) -> dict
# predict returns {"p_home","p_draw","p_away","expected_margin"}:
#   raw = expected_home_prob(...); p_draw fixed from params;
#   p_home = raw*(1-p_draw), p_away = (1-raw)*(1-p_draw)  (sums to 1 exactly)
#   expected_margin = (diff + adv_if_not_neutral) * margin_slope
```

- [ ] **Step 1: Failing tests** — symmetry (`predict(a,b)` home/away mirror of `predict(b,a)` on neutral); triple sums to 1.0 within 1e-9; home edge positive when elos equal and not neutral; `update` is zero-sum and a blowout moves more than a 1-point win but respects `margin_mult_cap`; a draw at equal Elo moves nothing; `regress_season` pulls every team `season_regress` of the way to the mean; `expected_margin` sign follows the favourite.
- [ ] **Step 2: RED → Step 3: implement → Step 4: GREEN**, whole `ml` suite green.
- [ ] **Step 5: Commit** — `feat(sports): NRL margin-Elo model (pure math)`.

---

### Task 4: season walk-forward backtest + tuner CLI

**Files:**
- Create: `ml/sports/nrl/backtest.py`, `pipeline/sports/nrl_backtest.py` (CLI)
- Test: `ml/sports/nrl/backtest_test.py`

**Interfaces:**
- Consumes: Task 3's `NrlParams/update/regress_season/predict`; Task 2's ingested rows (CLI reads SportMatch for sport="nrl").
- Produces: `replay_seasons(matches_by_season, params) -> dict[int, dict[int, float]]` (end-of-season Elo per team, regressed between seasons, leak-free order by kickoff); `evaluate_season(matches, elos_in, params) -> dict` (walk-forward within the season: predict each match from current state THEN update; returns log_loss, brier, winner_acc, n, and the same metrics for a favorite baseline (picks higher pre-match Elo, probabilities = training-window class frequencies) and home baseline); `tune(train_seasons, val_season, grid) -> NrlParams` (coordinate descent over k/home_adv/margin_slope/margin_sigma/p_draw/season_regress on val log loss — mirror `ml/evaluation/tune.py`'s style); CLI prints a per-season table for the 3 most recent completed seasons, each tuned only on data strictly before it.
- [ ] **Step 1: Failing tests** with a small synthetic two-season fixture (deterministic: strong team beats weak → walk-forward accuracy > 0.5; leak-freedom: evaluating season N must not change elos_in that season N+1 receives except via replay; predict-before-update order pinned by asserting the first match's prediction uses the seed Elo exactly).
- [ ] **Step 2: RED → Step 3: implement → Step 4: GREEN.**
- [ ] **Step 5: Real run + gate readout** — `PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_backtest` over the ingested seasons; paste the table. **Gate (Global Constraints): model beats the favorite baseline on log loss in ≥2 of the 3 held-out seasons.** If the gate fails, STOP — report the table and mark the plan blocked at Task 4 (tuning iteration is a controller decision, not silent grid-widening).
- [ ] **Step 6: Commit** — `feat(sports): NRL season walk-forward backtest + tuner`.

---

### Task 5: prediction generation + grading (frozen, append-only, shadow)

**Files:**
- Create: `pipeline/sports/nrl_predict.py` (CLI: generate + grade)
- Create: `ml/sports/nrl/params.json` (written by Task 4's tuner via `--ship`; loader with in-code defaults fallback, mirroring `ml/models/params.py` load pattern)
- Test: `pipeline/sports/nrl_predict_test.py`

**Interfaces:**
- Produces: `generate(db, params) -> int` — for every SportMatch sport="nrl", status="scheduled": compute current Elo state by replaying ALL finished nrl matches (with season regression at boundaries) then `predict`; append a SportPrediction (is_shadow=True) ONLY if the newest existing row for that match differs in (p_home, p_draw, p_away) by >1e-9 or none exists; hard guard: never write when status != "scheduled". `grade(db) -> int` — for finished matches with a prediction and no SportPredictionResult: outcome from final score, winner_correct vs argmax, prob_assigned, 3-way log loss, brier, margin_error = |expected_margin − actual_margin|; append-only. CLI: `--generate`, `--grade`, both idempotent.
- [ ] **Step 1: Failing tests** — freeze guard (finished match: generate writes nothing even with no prior row); dedup (unchanged state → second generate adds no row); grade computes the exact log loss for a hand-computed case and never re-grades; draw outcome grades argmax≠draw as incorrect.
- [ ] **Step 2: RED → Step 3: implement → Step 4: GREEN + full Python suite.**
- [ ] **Step 5: Real run** — generate + grade against the local backfilled DB (2026 season is mid-season: past rounds grade immediately — paste the ledger counts and the season-to-date shadow accuracy/log loss).
- [ ] **Step 6: Commit** — `feat(sports): NRL frozen shadow predictions + graded ledger`.

---

### Task 6: read-only API + record endpoint

**Files:**
- Create: `backend/app/api/sports.py` (router prefix `/api/nrl`)
- Modify: `backend/app/main.py` (register router — additive single line)
- Test: `backend/tests/test_sports_api.py`

**Interfaces:**
- Produces: `GET /api/nrl/matches?round=` → rounds of matches with any latest prediction attached (shadow rows ARE returned here — the endpoint itself is the shadow surface; nothing links to it publicly yet); `GET /api/nrl/model/record` → same shape family as football's record (evaluated_matches, winner_accuracy + wilson_ci95 (import from `app.api.model_record`), avg_log_loss, avg_brier, best_streak in kickoff order, model_version, disclaimer). No write endpoints.
- [ ] **Step 1: Failing tests** — record aggregates a seeded ledger correctly (reuse Task 1's fixture style); matches endpoint returns predictions and 404s cleanly on unknown round; empty record is honest (nulls/zeros).
- [ ] **Step 2: RED → Step 3: implement → Step 4: GREEN + backend suite.**
- [ ] **Step 5: Commit** — `feat(sports): NRL read-only API (matches + graded record)`.

---

### Task 7: launch runbook + controller verification

**Files:**
- Create: `docs/RUNBOOK-NRL-LAUNCH.md`

- [ ] **Step 1: Write the runbook** — sections: (1) Prod backfill & cadence (dispatch `refresh.yml` for the migration FIRST; then one-off `nrl_ingest --seasons <earliest> 2026` + `nrl_predict --generate --grade` — note these are manual/cron-candidate, NOT wired into the football pipeline); (2) Shadow gate (backtest table criteria + ≥2 live rounds graded clean via `/api/nrl/model/record`); (3) Go-public flip (separate PR: is_shadow=False default + frontend plan — stop gate); (4) Post-deploy verification (endpoints + a spot-check match). Exact commands throughout.
- [ ] **Step 2: Controller verification** — full `make test`; confirm zero football files in `git diff --name-only` against the branch base except `backend/app/main.py` (one additive line) and `backend/app/models/__init__.py` (append-only block).
- [ ] **Step 3: Commit** — `docs(runbook): NRL launch — backfill, shadow gate, go-public flip`.

---

## Execution order
1 → 2 → 3 → 4 (GATE: may stop the plan) → 5 → 6 → 7. One PR; migration sequencing per Global Constraints; stop gate before merge.

## Self-review notes
- Spec §5 coverage: outcome space (margin model, near-zero draw mass) ✓; Elo family with per-sport params ✓; data adapters ✓; walk-forward + shadow governance from day one ✓ (spec's calibration layer is deliberately deferred to the go-public plan — a calibrator fit on backtest seasons rides the flip PR, noted in runbook §3).
- The §5.2 extract-core-first deviation is stated in the header and requires no football edits — enforced by Task 7's diff check.
- Type consistency: SportTeam/SportMatch/SportPrediction/SportPredictionResult names and NrlParams fields consistent across Tasks 1-6; `nrl-elo-v0.1` version string everywhere.
- No placeholders: every task carries real code/values; the two runtime unknowns (earliest feed season; gate outcome) have explicit STOP semantics rather than TBDs.
