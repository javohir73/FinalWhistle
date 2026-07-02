# PRD: Exact-Score Maximization Program

**Source design spec:** `docs/superpowers/specs/2026-07-02-exact-score-maximization-design.md`
**Priority:** Standard (no deadline)
**Owner approval required for:** model-version promotion (see FR-4.8)

## 1. Introduction / Overview

The platform predicts one exact scoreline per match (e.g. "USA 1–0 Bosnia"). Over the first 82 World Cup matches the model hit the exact score 11.0% of the time (9 of 82). Analysis showed the model is already close to its own mathematical ceiling (~12.7% expected), and that football's information ceiling for a single-scoreline prediction is roughly 13–15% — no bookmaker or academic model does better.

This program raises the exact-score hit rate as high as it can honestly go, through five phases: (1) stop losing guaranteed hits to operational gaps, (2) fix what we measure, (3) test a smarter scoreline-picking policy, (4) blend bookmaker-odds information into the goal expectations, and (5) teach the model per-team attacking/defensive tendencies. Every model change must prove itself against the project's existing offline experiment harness before it ships.

**Goal:** raise per-match expected exact-hit probability by +1 to +3 percentage points (to ~14–15% on World-Cup-like matches) while never degrading winner accuracy, and eliminate all operational causes of lost hits.

## 2. Goals

1. **Zero missed evaluations:** every finished match has a frozen pre-kickoff prediction that gets scored. (Today, a knockout match whose prediction wasn't regenerated after its teams became known is silently skipped — a guaranteed zero.)
2. **Correct measurement:** knockout matches are scored on the 90-minute score the model actually predicts, not the after-extra-time score; offline experiments measure the exact pick rule production uses.
3. **Validated pick policy:** the scoreline-selection rule is the best one measurable on historical data.
4. **Market information in the model:** goal expectations are anchored to bookmaker totals where available, proven safe via a shadow model before going live.
5. **Structural upgrade evaluated:** per-team attack/defence modeling is built, backtested, and shipped only if it beats the current model with statistical confidence.

## 3. User Stories

- As a **platform user**, I want the predicted scoreline to be as accurate as possible, so the "Model predicted" panel is credible and interesting.
- As the **platform owner**, I want no match to be silently excluded from the model record, so accuracy numbers are trustworthy and complete.
- As the **platform owner**, I want every model change validated offline before it ships, so the public record never gets worse because of an unproven idea.
- As the **platform owner**, I want to see a shadow model's record next to production's and decide myself when to switch, so promotions are deliberate.
- As a **platform user reading the methodology page**, I want a note when the model version changes, so I understand what's behind the predictions.

## 4. Functional Requirements

### Phase 1 — Ops integrity (protect the record)

- **FR-1.1** When live ingestion assigns both teams to a scheduled knockout match (in `assign_knockout_teams`), the system must generate and store a prediction for that match in the same processing pass if no prediction exists for the current team pairing.
- **FR-1.2** The daily pipeline must include a coverage check step that counts scheduled matches which (a) have both teams assigned, (b) kick off within 48 hours, and (c) have no frozen prediction row. The step's result must appear in the pipeline summary.
- **FR-1.3** `GET /api/health` must expose that count as `prediction_coverage.missing` (0 = healthy) so external monitors can alert on it.
- **FR-1.4** The production baseline (82 evaluated / 9 exact hits at 2026-07-02) must be recorded in `docs/LEARNING-LOOP.md`, and all future accuracy comparisons must reference production `/api/model/record` snapshots, never the local development database.

### Phase 2 — Measurement correctness

- **FR-2.1** The system must capture the 90-minute (regulation time) score of every match into new columns `Match.score_home_90` / `Match.score_away_90` (with an alembic migration). Live ingestion already tracks match periods; the capture happens when a match leaves regulation time (enters extra time) or finishes without it.
- **FR-2.2** Exact-score evaluation must compare the predicted scoreline against the 90-minute score when it is present, and fall back to the stored final score otherwise. Penalty-shootout ties must continue to evaluate as draws (existing behavior).
- **FR-2.3** For already-finished knockout matches, the system must backfill the 90-minute score where it can be derived from stored goal-event timings; matches where it cannot be derived keep the after-extra-time score, and this limitation is documented.
- **FR-2.4** `ml/ratings/tournament.py` (line ~145) must compute goal residuals using the currently served model parameters from `model_params.json`, not the hardcoded v0.1 defaults. (Bug fix.)
- **FR-2.5** The offline experiment harness (`pipeline/experiment_model_eval.py`) must score its `top1` metric using the same scoreline-pick rule production uses (`DRAW_HEADLINE_BAND` + outcome-restricted argmax in `ml/models/poisson.py::predict_match`), so offline numbers predict production behavior.

### Phase 3 — Pick-policy experiment (offline)

- **FR-3.1** The harness must gain experiment candidates for: (a) the current production rule (control), (b) unrestricted grid argmax, (c) `DRAW_HEADLINE_BAND` values of 0.15, 0.20, and 0.25, (d) an "empirical prior blend" that picks the scoreline maximizing `(1−w)·P_grid + w·F_empirical(gap bucket)`, where `F_empirical` is a historical scoreline-frequency table conditioned on Elo-gap bucket (fitted only on data before each test window — no leakage), and (e) stage-conditional (group vs knockout) frequency tables.
- **FR-3.2** A pick-policy change ships to production only if it beats the control with the harness's existing edition-clustered bootstrap confidence gate.
- **FR-3.3** Experiment results (winners and losers) must be recorded in the repository (experiment log or docs) so refuted ideas are not retried.

### Phase 4 — Market-odds anchoring (shadow mode)

- **FR-4.1** The system must fetch pre-match odds (1X2 and over/under 2.5 goals) for upcoming matches from the API-Football `/odds` endpoint and store them in the existing (currently unpopulated) `Odds` table.
- **FR-4.2** Odds fetching must be best-effort: a failed or empty fetch must never block or fail prediction generation.
- **FR-4.3** The system must convert stored odds into a market-implied expected-goals total (removing the bookmaker margin), and rescale the model's two expected-goals values so their **sum** moves toward the market total by a configurable blend weight (`w_odds` in `model_params.json`), keeping the Elo-based **split** between the teams.
- **FR-4.4** Odds-anchored predictions must be generated as **shadow predictions**: stored alongside production predictions, tagged with a distinct model version (e.g. `poisson-elo-v0.3-shadow`).
- **FR-4.5** Shadow predictions must be excluded from: serving endpoints, frozen-prediction selection at evaluation time, bracket scoring, and the public model record. Each exclusion must have a test.
- **FR-4.6** The learning loop must score shadow predictions into a separate record queryable via an internal endpoint or admin view showing production vs shadow: matches scored, exact hits, winner accuracy, Brier score.
- **FR-4.7** A stage-conditional expected-goals multiplier for knockout matches (literature: ~0.85–0.95×) must be added as a harness candidate (it IS backtestable on historical 90-minute knockout scores) and ships via the FR-3.2 gate, not shadow mode.
- **FR-4.8** Promotion of the shadow model to the live headline is a **manual owner decision**. The system must not auto-promote. The comparison data from FR-4.6 is the input to that decision.

### Phase 5 — Per-team attack/defence upgrade (gated)

- **FR-5.1** The system must fit static per-team attack and defence strength offsets on the ~49k-match `historical_matches` dataset using a time-decayed maximum-likelihood fit (decay half-life ~2–4 years), run offline (never in the web process).
- **FR-5.2** The fitted offsets must enter prediction as multiplicative adjustments to the expected goals at the single existing choke point (`expected_goals_from_elo` / `predict_match`), with shrinkage and caps so a team with few matches gets a near-zero adjustment.
- **FR-5.3** The upgrade must be evaluated walk-forward in the harness (with the FR-2.5 parity rule) and ships only if it clears the bootstrap gate; a failed gate is documented per FR-3.3 and the code path stays disabled.
- **FR-5.4** (Optional, only after FR-2.4) A capped in-tournament asymmetric residual adjustment may be added as a harness candidate under the same gate.

### Cross-cutting

- **FR-6.1** When any model change ships (pick rule, odds blend promotion, attack/defence), the public methodology page must be updated with a short note describing the change and the new model version. No other user-facing UI changes.
- **FR-6.2** All new pipeline work follows the existing `step()` pattern in `run_pipeline` and the post-results chain's never-raise + heartbeat contract.
- **FR-6.3** All work follows TDD (failing test first), matching project convention.

## 5. Non-Goals (Out of Scope)

1. **A 30% exact-score hit rate.** Mathematically unreachable for single-scoreline prediction; the honest ceiling is ~13–15%.
2. **Product-metric alternatives** (top-3 scorelines display, ±1-goal "close prediction" stat) — offered and declined; may become a separate PRD later.
3. **Lineup-aware prediction adjustments** — analyzed and rejected: too little effect on the modal scoreline for the infrastructure required.
4. **New count-model families** (bivariate Poisson, Weibull, copulas) — no evidence of exact-score gains anywhere in the literature.
5. **Re-tuning base/beta/rho for exact score** — already tested during design; no significant gain.
6. **Auto-promotion of shadow models** — promotion is manual (FR-4.8).
7. **New user-facing UI** beyond the methodology note (FR-6.1).
8. **Betting features or odds display to users** — odds are a model input only.

## 6. Design Considerations

- UI surface is limited to a methodology-page note per shipped change (FR-6.1). The existing frontend already handles a level ("1–1") headline scoreline gracefully ("Too close to call"), so pick-policy changes need no frontend work.
- The internal production-vs-shadow comparison (FR-4.6) can be a JSON endpoint only; no styled page required.

## 7. Technical Considerations

- **Single choke point:** all expected-goals changes go through `ml/models/poisson.py` (`expected_goals_from_elo` / `predict_match`); pick-rule changes only in `predict_match`; evaluation changes in `ml/evaluation/match_metrics.py` + `pipeline/learning_loop.py`.
- **Model versioning:** served parameters and version live in `ml/models/model_params.json`; a version bump is a one-file change that propagates everywhere.
- **Shadow isolation:** frozen-prediction selection (`learning_loop._frozen_prediction`) picks the latest prediction with `created_at <= kickoff` — shadow rows must be excluded from this query or they would corrupt the production record (FR-4.5).
- **No historical international odds exist** in any accessible dataset — hence shadow mode instead of backtesting for the odds blend (FR-4.4), while the knockout multiplier (FR-4.7) is backtestable and gated normally.
- **Compute:** Render free tier constrains the web process; single-match prediction regeneration (FR-1.1) is trivial (analytic grid, no Monte-Carlo), the MLE fit (FR-5.1) runs offline/CI only.
- **Local dev DB** is stale and missing the `match_no` column; run migrations before local record analysis (FR-1.4 mandates production snapshots for claims).
- Existing test suite: 527 passing; keep it green.

## 8. Success Metrics

1. **Primary:** production exact-score hit rate (`/api/model/record`) trending toward ~14–15% on World-Cup-like matches; offline parity-rule top-1 hit rate improvement confirmed by bootstrap gate for each shipped change.
2. **Coverage:** `prediction_coverage.missing` stays 0; zero finished matches skipped by evaluation from this point on.
3. **Guardrails:** winner accuracy (currently 62.2%) and Brier/log-loss do not degrade after any shipped change.
4. **Process:** every shipped model change has a corresponding harness experiment result recorded; every refuted idea is documented.

## 9. Open Questions

1. **Shadow sample size:** the World Cup ends July 19 (~22 matches); the shadow-vs-production comparison may need post-tournament internationals (per `ROADMAP-POST-WORLDCUP.md`) to reach a decision-grade sample. How long is the owner willing to run shadow mode before deciding?
2. **Odds provider coverage:** API-Football's odds coverage for international fixtures needs verification early in Phase 4 — if coverage is poor for the matches we care about, the blend weight stays 0 and Phase 4's value drops.
3. **90-minute backfill quality (FR-2.3):** how many already-finished knockout matches have goal-event timings complete enough to reconstruct the 90-minute score? Determine during implementation; affects only historical record accuracy, not future matches.
4. **Empirical prior table granularity (FR-3.1d):** Elo-gap bucket boundaries (e.g. 0–50/50–150/150+) to be chosen during the experiment, subject to the no-leakage constraint.
