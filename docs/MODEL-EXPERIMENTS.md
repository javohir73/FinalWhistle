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

## Production baseline

- 2026-07-02 (pre-program): 82 evaluated / 51 winners (62.2%) / 9 exact (11.0%).
- Post-Phase-2 re-base: recorded after the 90-minute basis deploys (evaluation
  is append-only; existing rows keep their after-ET basis — only new matches
  score on the 90' basis, so the re-base is a going-forward note, not a rewrite).
