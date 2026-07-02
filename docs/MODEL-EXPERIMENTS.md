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
| 2026-07-02 | FR-3.1b unrestricted grid argmax (pick-policy gate, `--pick-only`) | 1,843 major-finals matches / 53 editions, 2004+, v0.2 engine, KO share 28.0% | top1 14.70% vs 14.76% (−0.05pp) | [−1.61, +1.66] pp | **REFUTED** — reconfirms the earlier one-off run under the committed gate |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.15 (production band 0.08) | same | top1 14.98% (+0.22pp) | [−0.57, +1.06] pp | **NOT SHIPPED** — small positive point estimate, CI spans 0 |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.20 | same | top1 15.03% (+0.27pp) | [−0.73, +1.35] pp | **NOT SHIPPED** — CI spans 0 |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.25 | same | top1 15.14% (+0.38pp) | [−0.95, +1.69] pp | **NOT SHIPPED** — best band point estimate, still not significant |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.1 (gap buckets 0–50/50–150/150+, fit strictly pre-edition) | same | top1 14.65% (−0.11pp) | [−1.79, +1.55] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.2 | same | top1 14.54% (−0.22pp) | [−1.92, +1.59] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.3 | same | top1 14.92% (+0.16pp) | [−1.47, +1.95] pp | **REFUTED** — noise in both directions across w grid |
| 2026-07-02 | FR-3.1e stage-conditional (group/KO) empirical blend w=0.1 | same | top1 14.49% (−0.27pp) | [−1.82, +1.52] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1e stage-conditional empirical blend w=0.2 | same | top1 14.54% (−0.22pp) | [−1.91, +1.61] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1e stage-conditional empirical blend w=0.3 | same | top1 15.19% (+0.43pp) | [−1.33, +2.28] pp | **NOT SHIPPED** — largest point estimate of Phase 3, CI still spans 0 |

Phase 3 (pick policy) verdict: **no candidate clears the FR-3.2 gate; the
production pick rule stands.** The wider-band and stage-w=0.3 point estimates
land inside the design spec's expected +0 to +0.5pp — real-if-any effect too
small to prove on ~1.8k matches. Candidates stay in `PICK_CANDIDATES`
(`--pick-only`) for cheap re-runs as more editions accrue.

## Production baseline

- 2026-07-02 (pre-program): 82 evaluated / 51 winners (62.2%) / 9 exact (11.0%).
- Post-Phase-2 re-base: recorded after the 90-minute basis deploys (evaluation
  is append-only; existing rows keep their after-ET basis — only new matches
  score on the 90' basis, so the re-base is a going-forward note, not a rewrite).
