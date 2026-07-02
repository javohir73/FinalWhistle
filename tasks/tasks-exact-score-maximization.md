# Tasks: Exact-Score Maximization Program

**Source PRD:** `tasks/prd-exact-score-maximization.md`
**Design spec:** `docs/superpowers/specs/2026-07-02-exact-score-maximization-design.md`

## Relevant Files

- `pipeline/generate_predictions.py` - Prediction generation; gains a single-match generation entry point (1.0) and the shadow-prediction path (4.0).
- `pipeline/generate_predictions_test.py` - Tests for generation, regeneration-on-assignment, and shadow tagging.
- `pipeline/ingest/live_scores.py` - `assign_knockout_teams` (regeneration trigger, 1.0) and period tracking (90-minute score capture, 2.0).
- `pipeline/ingest/live_scores_test.py` - Tests for team-assignment trigger and 90-minute capture on ET/no-ET/shootout paths.
- `pipeline/run_pipeline.py` - New `prediction_coverage` step (1.0) and shadow generation step (4.0).
- `pipeline/run_pipeline_test.py` - Pipeline step tests.
- `backend/app/main.py` - `/api/health` gains `prediction_coverage` (1.0).
- `backend/tests/test_health.py` - Health payload tests.
- `backend/app/models/__init__.py` - New `Match.score_home_90/score_away_90` columns (2.0), `Prediction.is_shadow` flag (4.0).
- `backend/alembic/versions/` - Two new migrations: 90-minute score columns (2.0), is_shadow flag (4.0).
- `ml/ratings/tournament.py` - Residual mis-specification fix at line ~145 (2.0).
- `ml/ratings/tournament_test.py` - Regression test pinning served-params residuals.
- `ml/evaluation/match_metrics.py` - Exact-score evaluation on the 90-minute basis (2.0).
- `ml/evaluation/match_metrics_test.py` - Evaluation basis tests.
- `pipeline/learning_loop.py` - Passes 90-minute basis to evaluation (2.0); shadow scoring + frozen-selection exclusion (4.0).
- `pipeline/learning_loop_test.py` - Learning-loop tests for both.
- `ml/evaluation/scoreline_metrics.py` - Production-pick-rule scorer for the harness (2.0).
- `ml/evaluation/scoreline_metrics_test.py` - Parity tests against `predict_match`.
- `pipeline/experiment_model_eval.py` - Parity `top1` metric (2.0); pick-policy candidates (3.0); knockout-multiplier candidate (4.0); attack/defence candidate (5.0).
- `ml/evaluation/empirical_prior.py` - NEW: gap-conditional historical scoreline-frequency table (3.0).
- `ml/evaluation/empirical_prior_test.py` - No-leakage and bucket tests.
- `pipeline/ingest/odds.py` - NEW: API-Football `/odds` fetch + `Odds` row writer (4.0).
- `pipeline/ingest/odds_test.py` - Fetch/parse/best-effort tests.
- `ml/models/odds_blend.py` - NEW: odds→implied-λ-total inversion (margin removal) and blend math (4.0).
- `ml/models/odds_blend_test.py` - Inversion and blend unit tests.
- `ml/models/poisson.py` - Choke point: pick-rule changes (3.0), attack/defence multipliers (5.0).
- `ml/models/poisson_test.py` - Grid/pick-rule tests.
- `ml/models/model_params.json` - `w_odds`, knockout multiplier, offsets reference, version bumps.
- `pipeline/fit_attack_defence.py` - NEW: offline time-decayed MLE fit over `historical_matches` (5.0).
- `pipeline/fit_attack_defence_test.py` - Seeded reproducibility, shrinkage/cap bounds.
- `backend/app/api/model_record.py` - Shadow exclusion from the public record + internal production-vs-shadow comparison (4.0).
- `backend/tests/test_model_record.py` - Exclusion and comparison tests.
- `docs/LEARNING-LOOP.md` - Production baseline pin (1.0).
- `docs/MODEL-EXPERIMENTS.md` - NEW: running experiment log — every gate result, win or lose (3.0/6.0).
- `frontend/app/methodology/page.tsx` (or equivalent) - Model-change notes (6.0).

### Notes

- Each phase (1.0–5.0) ships as its own branch + PR; phases are sequenced by expected value per effort but 3.0–5.0 may proceed in parallel once 2.0 lands (2.5's parity metric gates them all).
- **TDD is mandatory** (PRD FR-6.3): write the failing test, watch it fail, then implement. Python suite: `python3 -m pytest` from the repo root (currently 527 passing). Frontend: `npm test` in `frontend/`.
- Every model-behavior change must clear the edition-clustered bootstrap gate in `pipeline/experiment_model_eval.py` (PRD FR-3.2/FR-5.3). A change that fails the gate is recorded in `docs/MODEL-EXPERIMENTS.md` and NOT shipped.
- New pipeline steps use the `step()` pattern in `run_pipeline` (log + re-raise); anything running in the web process inherits the post-results chain's never-raise + heartbeat contract (PRD FR-6.2).
- Production accuracy claims always reference `/api/model/record` snapshots, never the local dev DB (PRD FR-1.4). Run alembic migrations locally before any local record analysis (dev DB is missing `match_no`).

## Instructions for Completing Tasks

**IMPORTANT:** As you complete each task, check it off in this markdown file by changing `- [ ]` to `- [x]`. Update the file after completing each sub-task, not just after completing an entire parent task.

## Tasks

- [x] 0.0 Create feature branch
  - [x] 0.1 Create and checkout the Phase 1 branch: `git checkout -b feat/prediction-coverage` (from up-to-date `main`; repeat this pattern per phase: `feat/90min-basis`, `feat/pick-policy`, `feat/odds-shadow`, `feat/attack-defence`)

- [x] 1.0 Phase 1 — Ops integrity: guarantee every match has a frozen pre-kickoff prediction (FR-1.1–FR-1.4)
  - [x] 1.1 Write a failing test: after `assign_knockout_teams` assigns both teams to a scheduled KO match with no `Prediction` row for that pairing, a prediction row exists for the match (test in `pipeline/ingest/live_scores_test.py` or `backend/tests/test_live_refresh.py`, wherever the trigger lands)
  - [x] 1.2 Extract/confirm a cheap single-match generation function in `pipeline/generate_predictions.py` (analytic `predict_match` payload only — no Monte-Carlo; reuse `build_payload`), callable with a `db` session and a `Match`
  - [x] 1.3 Hook the trigger: where `assign_knockout_teams` (pipeline/ingest/live_scores.py) newly assigns both teams, collect those match ids and generate predictions for them in the same pass, inside the post-results-chain error contract (never raises into the response; failures logged and retried by the next pass)
  - [x] 1.4 Write a failing test for the coverage counter: scheduled match + both teams + kickoff within 48h + no frozen prediction row ⇒ counted; then implement a `prediction_coverage(db)` helper (suggest `backend/app/chain_status.py` or a small new module) returning `{missing: N, match_ids: [...]}`
  - [x] 1.5 Add a `prediction_coverage` step to `run_pipeline` (after `predictions`) that runs the helper and fails loudly in the summary when `missing > 0` (log + summary, not an exception)
  - [x] 1.6 Surface it in `GET /api/health` as `prediction_coverage: {missing, checked_at}` (DB-guarded like `learning_chain` — health must answer without a DB); test in `backend/tests/test_health.py`
  - [x] 1.7 Pin the baseline in `docs/LEARNING-LOOP.md`: production snapshot 2026-07-02 (82 evaluated / 9 exact / 62.2% winner), the rule that all comparisons use production `/api/model/record`, and the gap-mix caveat (offline holdout ≈14.8% raw ≈13–14% WC-mix-adjusted)
  - [x] 1.8 Full suite green; open PR "feat(predictions): regenerate on KO team assignment + coverage guarantee"; after merge, trigger the `refresh-data` workflow and verify `prediction_coverage.missing == 0` on production `/api/health`

- [ ] 2.0 Phase 2 — Measurement correctness (FR-2.1–FR-2.5)
  - [x] 2.1 Migration + model: add nullable `score_home_90`/`score_away_90` to `Match` (`backend/app/models/__init__.py` + new alembic revision chained on current head); test table round-trip
  - [x] 2.2 Write failing tests for 90-minute capture in `pipeline/ingest/live_scores_test.py`: (a) match enters extra time ⇒ 90' score frozen at the regulation score, (b) match finishes without ET ⇒ 90' score = final score, (c) shootout after ET ⇒ 90' score stays the regulation score, (d) re-ingest after finish never overwrites a captured 90' score
  - [x] 2.3 Implement capture in `update_live_scores` (pipeline/ingest/live_scores.py) using the existing period/duration tracking
  - [x] 2.4 Evaluation basis: failing test in `ml/evaluation/match_metrics_test.py` — exact-score compares against 90' columns when present, falls back to final score otherwise; pens-tie still evaluates as a draw; implement in `evaluate_match` + pass-through in `pipeline/learning_loop.py`
  - [x] 2.5 Backfill: one-off, idempotent pipeline step or script deriving 90' scores for already-finished KO matches from `Match.goal_events` minute data (goals ≤ 90' + injury time count; document matches where events are incomplete — they keep the after-ET score per FR-2.3)
  - [x] 2.6 Residual bug fix (FR-2.4): failing regression test in `ml/ratings/tournament_test.py` pinning that `replay_tournament` computes expected goals with the SERVED params (from `ml/models/params.py`), not v0.1 defaults; then fix `ml/ratings/tournament.py:~145` (thread params through, keep signature backward-compatible)
  - [x] 2.7 Harness parity (FR-2.5): add a `production_pick(matrix, p_home, p_away)` scorer to `ml/evaluation/scoreline_metrics.py` that replicates `predict_match`'s DRAW_HEADLINE_BAND + outcome-restricted argmax exactly (parity test: feed both the same grids, assert identical picks); switch `experiment_model_eval.py`'s `top1` to use it (keep the unrestricted metric as `top1_unrestricted` for comparison)
  - [ ] 2.8 Full suite green; PR "fix(model): 90-minute scoring basis + served-params residuals + harness parity"; after merge run `refresh-data`, then record the re-based production record in `docs/MODEL-EXPERIMENTS.md`

- [ ] 3.0 Phase 3 — Pick-policy offline experiment (FR-3.1–FR-3.3)
  - [x] 3.1 Create `docs/MODEL-EXPERIMENTS.md` with the experiment-log format (date, candidate, holdout, metric deltas, bootstrap CI, verdict) and back-enter the two design-time refutations (unrestricted argmax; base/rho re-tune)
  - [ ] 3.2 Build `ml/evaluation/empirical_prior.py` (TDD): fit a scoreline-frequency table conditioned on Elo-gap bucket from historical matches **strictly before a given date** (no-leakage test: table fitted at date D contains no matches ≥ D); start with buckets 0–50/50–150/150+ and make boundaries a parameter (PRD open question 4)
  - [ ] 3.3 Add harness candidates to `pipeline/experiment_model_eval.py` `CANDIDATES`: control (production rule), unrestricted argmax, band = 0.15/0.20/0.25, empirical blend `(1−w)·P_grid + w·F_empirical` for w ∈ {0.1, 0.2, 0.3}, and stage-conditional (group vs KO) tables
  - [ ] 3.4 Run the walk-forward evaluation (`--since 2004`, ~1,843 matches), record every candidate's parity-top1 delta + bootstrap CI in `docs/MODEL-EXPERIMENTS.md`
  - [ ] 3.5 If a candidate clears the gate: implement it in `predict_match` behind `model_params.json` config (TDD), bump the model version, update the methodology note (task 6.1), PR + deploy + `refresh-data`. If none clears: record the negative result and close the phase (that outcome is likely and fine)

- [ ] 4.0 Phase 4 — Market-odds anchoring in shadow mode (FR-4.1–FR-4.8)
  - [ ] 4.1 Verify API-Football `/odds` coverage for upcoming international fixtures FIRST (PRD open question 2) — a small read-only probe script; if coverage is poor, stop and record in `docs/MODEL-EXPERIMENTS.md` (blend weight stays 0, phase re-scoped)
  - [ ] 4.2 Build `pipeline/ingest/odds.py` (TDD): fetch 1X2 + over/under-2.5 for scheduled matches inside a pre-kickoff window, write `Odds` rows (median across bookmakers; store `captured_at`); best-effort contract test — fetch failure/empty response leaves DB unchanged and never raises into callers (FR-4.2)
  - [ ] 4.3 Build `ml/models/odds_blend.py` (TDD): margin removal (normalize implied probs), invert O/U-2.5 + 1X2 into a market λ-total (Poisson-grid search or closed-form approximation — document choice), and `blend_lambda_total(lam_h, lam_a, market_total, w_odds)` preserving the Elo split; property tests (w=0 identity, w=1 sum=market, split invariant)
  - [ ] 4.4 Shadow storage: `Prediction.is_shadow` boolean (default false) + migration; shadow generation step (daily pipeline + post-chain) producing `poisson-elo-v0.3-shadow` rows with the odds blend when odds exist, pure-Elo otherwise
  - [ ] 4.5 Shadow isolation (FR-4.5), one failing test per exclusion BEFORE wiring: serving endpoints, `learning_loop._frozen_prediction`, bracket scoring, public `/api/model/record`
  - [ ] 4.6 Shadow scoring: learning loop evaluates shadow rows into `PredictionResult` tagged with the shadow version; internal comparison endpoint (e.g. `GET /api/model/record?version=` or `/api/internal/shadow-record`) returning production vs shadow: n, exact hits, winner acc, Brier (FR-4.6)
  - [ ] 4.7 Knockout λ-multiplier candidate (FR-4.7): add to the harness (backtestable on historical 90' KO scores via the 2.7 parity metric), gate per FR-3.2, log the result; ships independently of shadow mode if it clears
  - [ ] 4.8 PR + deploy shadow mode; let it accumulate. Promotion (FR-4.8) is a separate, later, owner-approved one-line version switch — never automatic
  - [ ] 4.9 Wire the production-vs-shadow comparison into the monitoring routine so the owner sees it without asking (e.g. include in the health-check summary the monitoring loop reports)

- [ ] 5.0 Phase 5 — Per-team attack/defence upgrade, gated (FR-5.1–FR-5.4)
  - [ ] 5.1 Build `pipeline/fit_attack_defence.py` (TDD): time-decayed Poisson MLE over `historical_matches` (~49k rows) producing per-team attack/defence offsets; decay half-life a parameter (default in the 2–4-year range); seeded + reproducible; runs offline/CI only, writes `ml/models/team_offsets.json`
  - [ ] 5.2 Shrinkage + caps (TDD): teams under N matches shrink toward 0; hard cap on |offset| mirroring the form-layer policy; property tests for both bounds
  - [ ] 5.3 Choke-point integration behind config: `expected_goals_from_elo`/`predict_match` applies `exp(atk_home + def_away)` multipliers only when `model_params.json` enables offsets; off by default; identity test when disabled
  - [ ] 5.4 Walk-forward harness candidate with the parity metric; edition-bootstrap gate decides (FR-5.3); record the result either way in `docs/MODEL-EXPERIMENTS.md`
  - [ ] 5.5 If the gate clears: enable via params + version bump, PR + deploy + `refresh-data` + methodology note. If not: leave the code path disabled and documented
  - [ ] 5.6 (Optional, FR-5.4 — only after 2.6) capped asymmetric in-tournament residual candidate through the same gate; expected to fail at n=3–4 matches/team; record and move on

- [ ] 6.0 Cross-cutting — visibility and hygiene (FR-6.1, FR-3.3)
  - [ ] 6.1 Methodology page: add a short "model changelog" section (version, date, one-line change description); update it in the same PR as every shipped model change — never as an afterthought
  - [ ] 6.2 Keep `docs/MODEL-EXPERIMENTS.md` the single source of truth for every gate run (wins AND losses) so refuted ideas are never retried
  - [ ] 6.3 After each phase's production deploy: verify via `/api/health` (chain + coverage green) and snapshot `/api/model/record` into the experiment log as the phase's closing baseline
