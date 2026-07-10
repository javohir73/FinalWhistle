# Model Quality: Shadow Promotions + v0.6 Challenger Ladder — Design

**Date:** 2026-07-10
**Status:** Approved by user (brainstorming session)
**Trigger:** France–Morocco QF post-mortem (model 54.6% France vs market ~61%,
France won 2–0; market benchmark reads "MARKET BEATS MODEL" at n=1; the three
biggest tournament misses are all underpriced low-scoring draws).

## Problem

Production serves `poisson-elo-v0.5`. Post-mortem evidence:

- The model underrated the favorite where the market didn't — and the existing
  odds-blend shadow can't fix that class of miss: it anchors only the lambda
  **total** (`odds_blend.py` blends the sum, preserves the Elo split), while
  France–Morocco was a **split** error.
- Tournament record: 65% winner accuracy, avg log loss 0.861, avg Brier 0.504
  over 97 matches. Biggest misses are all draws priced 4–13%.
- Five shadow twins already exist with graded live comparisons (14
  `PredictionResult` pairs) that nobody has looked at: `v0.3-shadow`
  (odds-total blend), `v0.3+xg`, `v0.3+avail`, `v0.5+bans`, `v0.5+rest`. The
  summary is token-gated behind `GET /api/internal/shadow-record`.
- Knockout micro-parameters are placeholders: penalties `pk_beta=0` (coin
  flip), `et_tempo=1.0`.
- Version-string drift: `model_params.json` says v0.5, `render.yaml` says
  v0.4, CLAUDE.md says v0.1.

## Decision (user-approved)

Two tracks, approach "evidence-first, shadow-first":

- **Phase 1 (now, before the semis):** review and — with the user's go/no-go
  per twin — promote existing shadow twins through the repo's own gates.
  Nothing that has never run as a shadow gets promoted mid-tournament.
- **Phase 2 (post-final, v0.6):** five challenger candidates through the
  existing walk-forward harness; winners assemble into `poisson-elo-v0.6`.

Evidence bar (user choice): each promotion/ship needs the repo's existing
acceptance gates PLUS a per-twin/per-candidate user go/no-go. Prod changes go
through the stop gate.

Only 4 WC26 fixtures remain (2 SF, third place, final) — Phase 1's live
surface is small; the model also serves future tournaments, so Phase 2 is
judged on walk-forward evidence, not the remaining fixtures.

## Phase 1 — promotion review (days)

1. **`.github/workflows/shadow-record.yml`** (new, manual dispatch only,
   read-only): GET `${API_URL}/api/internal/shadow-record` with the existing
   `RECOMPUTE_TOKEN` secret (same pattern as `ops-flag-internal.yml`); print
   the per-twin record over the graded live pairs. No new secrets, no DB
   access, no writes.
2. **Local walk-forward gates** for each promotable flag using the existing
   harness: `experiment_model_eval.py` run (odds-total blend candidates) and
   `run_team_offsets_gate()` (xG offsets), plus the availability twin's gate
   path. Acceptance = the repo's own criteria: paired log-loss delta CI
   excluding 0, do-no-harm tolerances (`_LL_TOL`, `_RPS_TOL`).
3. **Evidence card** per twin: walk-forward verdict + live-pair record +
   recommendation → user says go/no-go per twin. Only three twins have
   promotion flags today (`w_odds`, `team_offsets`, `use_availability`);
   `v0.5+bans` and `v0.5+rest` appear on the card for information but are
   promotable in Phase 1 only if a params flag already exists — no new
   serving code ships mid-tournament.
4. **Promotion** for approved twins via the existing `promote_blend.py` owner
   gate (`w_odds` ≤ 0.5 cap, `team_offsets`, `use_availability` flags in
   `model_params.json`). Predictions regenerate for the 4 remaining fixtures
   only — frozen pre-kickoff predictions for past matches are untouched by
   the existing status guard. The flag flip reaching prod is **stop-gated**.

## Phase 2 — v0.6 challenger ladder (post-July 19)

Each candidate is added to `experiment_model_eval.py`'s CANDIDATES and
evaluated per-edition walk-forward (majors 2004+, 730-day validation windows,
block-bootstrap CIs):

| Candidate | Mechanism | Gate |
|---|---|---|
| `split-anchor` | `p = (1−w)·p_model + w·p_market` on de-vigged 1X2; new `w_1x2` param capped at 0.5; applied after calibration, before pick policy. Sources: bookmaker consensus first, `market_odds_snapshots` exchange mids fallback. | LL CI down on the odds-covered subset; harness reports coverage per edition and refuses to gate when fewer than 70% of an edition's validation matches have odds (editions below the floor are excluded from the gate, and the report says so). |
| `draw-fix` | Joint refit of Dixon-Coles `rho` (per Elo-gap bucket) and per-bucket `b_draw` boosts; dead-rubber flag as group-stage draw feature. | LL/RPS CI down; draw-class ECE improves; no top-1 regression. |
| `atk-def-xg` | Enable per-team attack/defence offsets with the xG kappa-blend (`team_offsets_xg.json`, already built). | Existing team-offsets gate: top-1 hit CI up OR exact-score NLL CI down without top-1 regression. |
| `ko-micro` | Fit `pk_beta` (Elo edge → shootout win prob, currently 0) and `et_tempo` (currently 1.0) on historical ET periods/shootouts; serve from params. | KO-subset LL/NLL improvement CI; regulation-time outputs unchanged. |
| `xgb-stack` | XGBoost stacking layer over Poisson-Elo outputs + elo gap, form, H2H, rest, market odds (when present) → 1X2 probs on the same folds. If shipped: XGB serves 1X2, Poisson grid conditioned on it serves scorelines/goal markets. | Must beat the best simpler candidate combination on LL CI, same folds — otherwise it dies in the harness. |

**Assembly:** combine winners greedily (largest individual gain first),
re-gating each combination — candidates that win alone may cancel jointly.
Then calibrator refit (`fit_calibrator --ship`), version bump to
`poisson-elo-v0.6` in `model_params.json`, and version-string drift fixed
(`render.yaml`, CLAUDE.md). Ship on gate evidence; there is no live football
to shadow-soak until September, and walk-forward is the strongest available
evidence. NRL's model is untouched throughout.

## Data flow

```
bookmaker odds (Odds table, pre-kickoff)   ─┐
exchange mids (market_odds_snapshots)      ─┼─► split-anchor / xgb-stack features
historical archives (football_data_odds)  ─┘        │
Elo + form + H2H + offsets ─► poisson.py grid ─► calibrate() ─► [w_1x2 blend] ─► serving
                                   ▲                                  ▲
                     draw-fix (rho, b_draw)             xgb-stack (1X2 layer, if gated)
```

Historical 1X2 odds for the walk-forward come through the existing
`football_data_odds` ingest path extended to archived internationals where
available; coverage is measured and reported per edition, never assumed.

## Components (one responsibility each)

- `.github/workflows/shadow-record.yml` — Phase 1 evidence, read-only.
- `promote_blend.py` — existing owner gate for flag flips (unchanged).
- `ml/models/odds_blend.py` — gains `split_anchor()` (probability-simplex
  blend; identity when odds absent or `w_1x2=0`).
- `ml/models/poisson.py` — `rho` becomes per-bucket, from params.
- `ml/models/knockout.py` — `pk_beta`/`et_tempo` read from params instead of
  constants.
- `ml/models/xgb_stack.py` (new) + `pipeline/fit_xgb_stack.py` (new).
- `pipeline/experiment_model_eval.py` — five new candidates + odds-coverage
  reporting.
- `ml/models/model_params.json` — carries every new knob; serving changes are
  always a params flip, never a code fork.

## Error handling

| Situation | Behavior |
|---|---|
| No odds for a match | `w_1x2` blend degrades to pure model (identity), same contract as `w_odds` |
| xgb-stack missing features at serve time | Fall back to Poisson probabilities |
| Candidate's odds coverage below floor | Harness refuses to gate it — no hollow wins |
| Past matches | Frozen-prediction guard prevents regeneration (existing) |

## Testing & governance

- Unit tests per new function: blend math (including identity cases), rho
  bucketing, KO param loading, xgb feature assembly.
- The harness IS the acceptance test: every candidate's walk-forward output
  is written to a committed experiment report so verdicts are auditable.
- `make test` green throughout; frozen predictions and NRL paths untouched.
- Stop gates: Phase 1 promotion flag-flip reaching prod; v0.6 ship. Each gets
  a plain-English evidence summary and waits for explicit "go".
