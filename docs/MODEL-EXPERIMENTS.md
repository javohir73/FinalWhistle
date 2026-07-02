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
| 2026-07-02 | KO lambda multiplier 0.85× (`run_ko_multiplier_gate`, FR-4.7) | 480 knockout matches / 53 editions, 2004+, v0.2 params (KO inferred structurally; base top1 13.96%) | exactNLL +0.0336, top1 −0.63pp, logloss +0.0047 | exactNLL [+0.0050, +0.0626] (worse, significant) | **REFUTED** — grids get significantly worse |
| 2026-07-02 | KO lambda multiplier 0.90× | same | exactNLL +0.0147, top1 −1.04pp, logloss +0.0025 | exactNLL [−0.0032, +0.0338]; top1 [−2.29pp, +0.00pp] | **REFUTED** — no gain anywhere, top1 borderline-worse |
| 2026-07-02 | KO lambda multiplier 0.95× | same | exactNLL +0.0038, top1 −0.83pp, logloss +0.0009 | top1 [−1.75pp, −0.19pp] (worse, significant) | **REFUTED** — production pick loses hits with CI excluding 0 |

KO-multiplier notes: the literature's 0.85–0.95× KO deflation does NOT hold on
this dataset — the v0.2 lambdas already fit knockout scoring; every deflation
moved probability mass away from realized scorelines. Basis caveat: holdout KO
scores are the dataset's recorded final scores (after extra time where played,
shootout kicks never counted), which biases *against* a <1× multiplier — but
the failure is uniform (exactNLL worse at every multiplier and top1 hits LOST
at 0.95×, the mildest), so the direction is refuted, not just under-powered.
Do not retry without a 90'-only KO score source.

## Phase 4 odds probe (FR-4.1, 2026-07-02)

API-Football `/odds` coverage probe for upcoming international fixtures:
**not possible — no API key configured.** `API_FOOTBALL_API_KEY` is empty in
the deployment env (`.env`), and a keyless request to api-sports v3 returns
HTTP 403. Coverage for international fixtures therefore remains UNVERIFIED
(PRD open question #2). Everything Phase 4 ships regardless is safe by
construction: `w_odds` defaults to 0.0 in `model_params.json`, odds ingestion
is best-effort (an unpriced match falls back to pure Elo lambdas), and the
shadow twins are exact copies of production until odds exist AND a weight is
deliberately set — so the production-vs-shadow comparison starts as a clean
null test. Re-run the probe once a key is provisioned:
`pipeline/ingest/odds.py::fetch_odds` against any scheduled fixture id.

## Production baseline

- 2026-07-02 (pre-program): 82 evaluated / 51 winners (62.2%) / 9 exact (11.0%).
- Post-Phase-2 re-base: recorded after the 90-minute basis deploys (evaluation
  is append-only; existing rows keep their after-ET basis — only new matches
  score on the 90' basis, so the re-base is a going-forward note, not a rewrite).
