# Model Experiment Log

Single source of truth for every offline experiment against the walk-forward
harness (`pipeline/experiment_model_eval.py`). Every gate run is recorded —
wins AND losses — so refuted ideas are never retried. Rules:

- The gate: edition-clustered bootstrap CI on the metric delta vs control; a
  change ships only when the CI excludes zero in the right direction.
- `top1` = exact-scoreline hit with the PRODUCTION pick rule (harness parity,
  FR-2.5). Production accuracy claims cite `/api/model/record` snapshots only.
- Holdout hit rates are inflated vs World-Cup play by blowout-heavy editions:
  ~14.8% raw ≈ 13–14% at a WC-like Elo-gap mix. Compare gap-mix-adjusted.

| Date | Candidate | Holdout | Metric deltas (vs control) | Bootstrap CI | Verdict |
|---|---|---|---|---|---|
| 2026-07-02 | Unrestricted grid argmax (drop DRAW_HEADLINE_BAND outcome restriction) | 1,843 major-finals matches, 2004+, v0.2 params | top1 14.70% vs 14.76% (−0.05pp) | [−1.66, +1.53] | **REFUTED** — no gain; restriction is not costing hits |
| 2026-07-02 | Re-tune base/beta/rho on top-1 (base 1.00–1.35 × rho −0.25–0.0 sweep) | same | best in-sample +0.22pp (base=1.0, rho=−0.25) | within ±0.8pp binomial SE | **REFUTED** — in-sample upper bound below noise; v0.2 params stand |
| 2026-07-02 | Per-team attack/defence offsets, half-life 1095d — PRIMARY (FR-5.1–5.3): time-decayed Poisson MLE on 49,403 historical matches (`pipeline/fit_attack_defence.py`), √(n_eff/30) shrinkage, ±0.075 log-λ cap (≈ FORM_CAP_ELO×β); walk-forward refit strictly before each edition (`run_team_offsets_gate`) | 750 matches / 18 major-finals editions 2018+, v0.2 served params | top1 16.13%→14.67% (−1.47pp); exact NLL +0.0020; log-loss +0.0028 | top1 [−2.66pp, +0.00pp]; NLL [−0.0080, +0.0114]; LL [−0.0024, +0.0084] | **REFUTED** — offsets HURT the modal pick (borderline-significantly) and buy nothing on grid NLL; `"team_offsets"` stays null, code path disabled |
| 2026-07-02 | Per-team attack/defence offsets, half-life sensitivity 730d / 1460d | same | top1 −1.33pp / −1.60pp; exact NLL +0.0017 both; log-loss +0.0039 / +0.0021 | top1 [−2.43, −0.25] / [−2.73, −0.39] — significantly WORSE at both | **REFUTED** — the harm is robust to the decay choice, not a half-life artifact |
| 2026-07-02 | In-tournament asymmetric residual λ-adjust (FR-5.4): λ ×= exp(κ·(own gf-residual + opp ga-residual)), √(n/4) ramp, ±0.075 cap, κ ∈ {0.05, 0.10, 0.20} (`run_residual_form_gate`) | same | top1 −0.53 / −1.07 / −1.33pp; exact NLL −0.0019 / −0.0019 / −0.0014 (ns); log-loss ≈0 | κ=0.05 top1 [−1.37, +0.29]; κ=0.10 [−2.18, +0.00]; κ=0.20 [−2.49, −0.28] | **REFUTED** — as predicted at n=3–4 matches/team: tiny ns NLL gain, top1 degrades monotonically with κ |

## Phase 5 post-mortem (why per-team offsets lost)

The infrastructure works (deterministic fit, leak-free walk-forward, identity
when disabled) but the signal does not survive the anti-overfitting policy on
this holdout: ~44% of teams saturate the tight ±0.075 log-λ cap, and what the
full-history fit mostly encodes is the exp(β·diff) curve's tail curvature at
extreme Elo gaps (minnows get "concede less / score more than the saturated
exponential predicts") — a regime barely present in major-finals matchups.
Meanwhile a small λ multiplier rarely moves the modal grid cell toward the
truth but does flip 1-0/1-1 boundary picks away from football's most common
scorelines, which is exactly the measured effect: NLL ≈ flat, top1 down ~1.5pp.
Do not retry with a looser cap — that direction adds variance, not signal;
the flat (base, rho) response surface from the design-phase refutations
already warned grid-shape changes buy little.

## Production baseline

- 2026-07-02 (pre-program): 82 evaluated / 51 winners (62.2%) / 9 exact (11.0%).
- Post-Phase-2 re-base: recorded after the 90-minute basis deploys (evaluation
  is append-only; existing rows keep their after-ET basis — only new matches
  score on the 90' basis, so the re-base is a going-forward note, not a rewrite).
