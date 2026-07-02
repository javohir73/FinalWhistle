# Exact-Score Maximization Program — Design

**Date:** 2026-07-02
**Status:** Approved direction (option C — full maximization program)
**Owner goal:** Raise the platform's exact-scoreline hit rate as high as it can honestly go.

## 1. Goal, ceiling, and success criteria

Production record at design time: **82 matches evaluated, 9 exact-score hits (11.0%)**, winner accuracy 62.2% (`/api/model/record`). The model's own mean modal-scoreline probability is **12.7%** (computed over all 82 finished matches), and the offline holdout hit rate is 14.8% — which drops to **~13–14% when re-weighted to a World-Cup-like Elo-gap mix** (the raw holdout is inflated by AFCON/Gold Cup blowouts).

Literature and betting-market evidence agree: a well-calibrated model's top scoreline rarely exceeds 12–15% probability, and observed hit rates for professional models cluster at 9–13%. Our 11% over 82 matches is within one binomial standard error (~3.7pp) of perfect calibration.

**Target:** raise per-match expected exact-hit probability by **+1 to +3pp** (to ~14–15% on WC-like matches), and — equally important — **stop losing hits to operational gaps**, which currently cost more expected value than any modeling change can add.

**Explicit non-goal:** 30% single-scoreline accuracy. That is above the information ceiling of football; no bookmaker or academic model achieves it. (Product-level alternatives — top-3 scorelines, ±1-goal "close" metric — were offered and declined; this program maximizes the honest strict metric.)

**Success metrics:**
- Primary: production `exact_score_hits / evaluated_matches` over remaining matches; offline walk-forward top-1 hit rate **measured with the production pick rule** (see §4.3), gap-mix-adjusted.
- Guardrails: winner accuracy and Brier/log-loss must not degrade; **zero silently-skipped evaluations** (every finished match must have a frozen pre-kickoff prediction row).
- Every model change ships **only if it clears the existing edition-clustered bootstrap gate** in `pipeline/experiment_model_eval.py`. Changes that fail the gate are documented and dropped.

## 2. Evidence base (what was verified before this design)

A four-analyst research pass over the codebase + literature, followed by an adversarial critique that **ran the key experiments** on the repo's 1,843-match major-tournament holdout (49,403 historical matches in local Postgres):

**Refuted (do not build):**
- *Unrestricted grid argmax instead of the outcome-restricted pick* — measured 14.70% vs production rule's 14.76%. No gain; the map's #1 recommendation was wrong.
- *Re-tuning base/beta/rho for exact score* — best sweep result +0.22pp in-sample, far below noise. `base=1.2` being a grid corner does not matter.
- *Lineup-aware lambdas* — a benched starter moves λ by ~0.1–0.2, almost never flips the modal cell; requires new scheduling infra. Rejected on EV.
- *Monte-Carlo mode noise* — moot; `predicted_score` is already the analytic Dixon-Coles grid argmax (`ml/models/poisson.py:244-251`), n_sims never touches it.
- Exotic count families (Weibull/copula/bivariate Poisson) — no demonstrated exact-score hit-rate gains anywhere in the literature.

**Survived (build, in this order):**
1. Ops integrity — missing prediction rows are guaranteed zeros (`pipeline/learning_loop.py:100` silently skips them).
2. Harness parity — the offline harness scores a *different* pick rule than production uses; all past offline evidence measured the wrong rule.
3. Measurement correctness — knockout exact-score currently evaluated on after-extra-time score against a 90-minute model; plus a real bug: `ml/ratings/tournament.py:145` computes residuals with v0.1 default params (base=1.35/beta=0.0019) instead of served v0.2 params (1.2/0.0021).
4. Pick-policy A/B — the one untested pick idea with headroom: blending gap-conditional *empirical* scoreline frequencies into the pick.
5. Market-odds anchoring of λ totals — best-evidenced upgrade in the literature (Egidi 2018; 2023 Soccer Prediction Challenge won by bookmaker consensus). Expected **+0.3 to +1pp**.
6. Per-team attack/defence offsets fit on the 49k-match history — the model currently maps one Elo diff symmetrically to both λs and *cannot represent* "low-scoring team". Expected **+0 to +0.8pp**, genuinely uncertain, gated.

## 3. Architecture context (the choke point)

The entire scoreline path is: effective Elo (historical replay + capped in-tournament delta/form) → `expected_goals_from_elo` (`ml/models/poisson.py:43-54`, `λ = base·exp(±β·(elo_diff+host_adv))`) → 11×11 Dixon-Coles grid (rho=−0.06) → pick rule in `predict_match` (`poisson.py:212-261`): unrestricted argmax when |p_home−p_away| ≤ 0.08 (`DRAW_HEADLINE_BAND`), else argmax restricted to the favored side's win cells.

Served params live in `ml/models/model_params.json` (v0.2: base=1.2, beta=0.0021, home_adv=60, rho=−0.06). A version bump is a one-file change; everything downstream follows.

All λ-level enrichments in this program go through that single choke point. The pick-policy changes go through `predict_match`. Evaluation changes go through `ml/evaluation/match_metrics.py` + `pipeline/learning_loop.py`.

## 4. Phases

Each phase is independently shippable and lands as its own PR(s). Order is by expected value per effort.

### Phase 1 — Protect the record (ops integrity)

**Problem:** A knockout match whose teams are assigned (after feeder results) but whose prediction is not regenerated before kickoff has **no frozen prediction row** — `learning_loop.py:100` silently skips it at evaluation. Observation history documents the post-results chain failing silently on Render's free tier. Every such miss is a guaranteed zero in the record.

**Design:**
- **Regeneration trigger:** when `assign_knockout_teams` (in the live-refresh path) assigns teams to a scheduled KO match that has no prediction for the current team pairing, mark it and generate its prediction in the same post-results chain pass (single-match analytic generation is cheap; no Monte-Carlo needed for the frozen scoreline).
- **Coverage assertion:** daily pipeline step + `/api/health` field `prediction_coverage`: count of scheduled matches with both teams assigned, kickoff within 48h, and **no** frozen prediction row. Alert value > 0.
- **Baseline pin:** document the production baseline (82/9 at 2026-07-02) in `docs/LEARNING-LOOP.md`; all before/after claims use production `/api/model/record` snapshots, never the local dev DB (which is stale — 2/23 — and missing the `match_no` column until migrated).

### Phase 2 — Measure the right thing

**2a. 90-minute scoring basis for knockouts.** The Poisson model predicts 90-minute scores, but KO evaluation uses the feed's after-ET final. Capture the regulation-time score at the 90' boundary during live ingest (`pipeline/ingest/live_scores.py` already tracks periods) into new `Match.score_home_90 / score_away_90` columns (+ alembic migration); `evaluate_match` scores exact hits against the 90' basis when present. Penalty-decided ties already evaluate as draws — this only corrects ties decided by an extra-time goal (~+0.1–0.3 hits over remaining KO matches, plus honest accounting). Backfill for already-finished KO matches where derivable from goal_events timing; otherwise leave after-ET (documented).

**2b. Residual mis-specification fix.** `ml/ratings/tournament.py:145` must call `expected_goals_from_elo` with the **served** params, not v0.1 defaults. ~1 hour + tests. Harmless today (bias cancels in the symmetric form layer) but poisons any future asymmetric use of the stored residuals.

**2c. Harness parity.** `experiment_model_eval.py`'s `top1` uses the unconditional argmax; production uses the band+restriction rule. Add the production pick rule to the harness scorer (~15 lines) so every offline number measures what production ships. **This is a prerequisite for Phases 3–5's gates.**

### Phase 3 — Pick-policy A/B (offline experiment)

Using the parity harness, evaluate against the walk-forward holdout:
- Production rule (control) and unrestricted argmax (known ≈ equal).
- Band-width variants (0.15 / 0.20 / 0.25) — measured +0.2–0.4pp, CI spans 0; re-check under parity.
- **Empirical prior blend (the real candidate):** pick the scoreline maximizing `(1−w)·P_grid + w·F_empirical(gap bucket)`, where `F_empirical` is the historical scoreline frequency table conditioned on Elo-gap bucket (fit pre-2018, tested 2018+), `w` tuned walk-forward.
- Stage-conditional priors (group vs knockout tables).

Ship whichever variant clears the bootstrap gate; if none do, keep the current rule and record the negative results in the experiment log. Expected: **+0 to +0.5pp**.

### Phase 4 — Market-odds anchoring (the real headroom)

**Design:** Ingest pre-match odds for WC matches via API-Football `/odds` (key already configured; the `Odds` table exists at `backend/app/models/__init__.py:374-389` and is populated by nothing today). Invert 1X2 + over/under-2.5 into a market-implied `λ_total`; rescale the Elo-derived λs so their **sum** moves toward the market total (convex blend, weight `w_odds` in `model_params.json`) while keeping the Elo-based **split**. Market totals capture dead rubbers, rotation, and weather that Elo cannot see.

**Validation constraint:** the local DB has **no historical international odds**, so this cannot be walk-forward validated in the harness. It therefore ships in **shadow mode**: shadow predictions are computed and stored alongside production ones (tagged `model_version = poisson-elo-v0.3-shadow`, excluded from serving and from frozen-prediction selection in `learning_loop._frozen_prediction`), scored by the learning loop into a separate record. Promotion to the served headline requires the shadow record to be non-inferior over the accumulated sample (remaining WC matches + post-WC internationals per `ROADMAP-POST-WORLDCUP.md`) — with the explicit acknowledgment that n will be small and the literature prior (+0.3 to +1pp) carries part of the decision.

Includes a **stage-conditional λ multiplier** experiment (knockout ≈ 0.85–0.95× — WC knockout matches are measurably lower-scoring): this one *is* backtestable on historical 90' KO scores, so it goes through the Phase-2c parity gate rather than shadow mode.

### Phase 5 — Attack/defence structural upgrade (gated experiment)

Fit static per-team attack/defence offsets on the 49k-match `historical_matches` table (time-decayed Dixon-Coles-style MLE, decay ~half-life 2–4 years for international squad cycles), and blend into the λs at the choke point: `λ_home = base·exp(β·diff)·exp(atk_home + def_away)` (shrunk, capped). Reuse the enriched-rows/feature plumbing built for the WDL booster (`ml/models/training_rows.py`). Validate walk-forward on exact-NLL + parity top-1 with the edition bootstrap; **ship only if the gate clears** — the flat (base, rho) response surface found in the refutation experiments warns that grid-shape changes may buy little. Expected **+0 to +0.8pp**.

Optional cheap follow-up once 2b lands: capped asymmetric in-tournament residual feedback (`λ *= exp(κ·(gf_res − ga_res_opp))` with √n ramp). Expected to fail the gate at n=3–4 matches/team; try only because it's nearly free after 2b.

## 5. Error handling & operational constraints

- All new pipeline steps follow the existing `step()` pattern (log + re-raise) in `run_pipeline`, and the post-results-chain additions inherit the never-raise-into-response + chain-status heartbeat contract from PR #93.
- Odds ingestion is best-effort: fetch failure leaves `Odds` empty and the blend falls back to pure Elo λs (weight effectively 0) — no prediction may ever fail because a bookmaker feed is down.
- Shadow rows must be invisible to: serving endpoints, frozen-prediction selection, bracket scoring, and the public model record. A dedicated `is_shadow` flag (or version-prefix filter) with tests enforcing each exclusion.
- Render free tier: single-match analytic regeneration (Phase 1) is trivial compute; odds fetch is one API call per match; the heavy MLE fit (Phase 5) runs offline/in CI, never in the web process.

## 6. Testing strategy

- TDD throughout (project convention; suite currently 527 passing).
- Every offline claim reproduced by a committed experiment candidate in `experiment_model_eval.py` `CANDIDATES` — no untracked scratchpad numbers.
- Phase 1: tests for regeneration-on-assignment, coverage assertion, health surfacing.
- Phase 2: migration + 90'-capture tests (including ET and shootout paths), residual-params regression test, harness-parity test pinning the production rule.
- Phase 4: inversion math tests (1X2/OU → λ_total, with margin removal), blend fallback tests, shadow-isolation tests (each exclusion).
- Phase 5: fit reproducibility (seeded), cap/shrinkage bounds, gate integration.

## 7. Expected outcome (honest accounting)

| Phase | Expected exact-score effect |
|---|---|
| 1 — Ops integrity | Protects several matches' worth of hits (largest real EV) |
| 2 — Measurement | +0.1–0.3 hits over remaining KOs; correct baseline for everything else |
| 3 — Pick policy | +0 to +0.5pp |
| 4 — Odds anchoring | +0.3 to +1pp |
| 5 — Attack/defence | +0 to +0.8pp (gated; may be dropped) |

Realistic combined end state: **~14–15% exact-score hit rate on WC-like matches** — at or near the information ceiling of the sport. Anything above that would be evidence of miscounting, not skill.
