# Model Experiment Log

Single source of truth for every offline experiment against the walk-forward
harness (`pipeline/experiment_model_eval.py`). Every gate run is recorded —
wins AND losses — so refuted ideas are never retried. Rules:

- The gate: edition-clustered bootstrap CI on the metric delta vs control; a
  change ships only when the CI excludes zero in the right direction.
- `top1` = exact-scoreline hit with the PRODUCTION pick rule (harness parity,
  FR-2.5). Production accuracy claims cite `/api/model/record` snapshots only.
- Holdout hit rates are inflated vs World-Cup play by blowout-heavy editions:
  ~14.8% raw ≈ 13–14% at a WC-like Elo-gap mix. That gap-mix adjustment applies to ABSOLUTE accuracy claims; gate
  decisions compare the delta vs the same control on the same holdout —
  which is gap-mix-invariant — so the rows below report raw deltas.

Phases 1–2 were measurement/correctness work with no gated model-behavior
candidates, so they have no experiment rows here (they appear only in the
Production baseline section below).

| Date | Candidate | Holdout | Metric deltas (vs control) | Bootstrap CI / uncertainty | Verdict |
|---|---|---|---|---|---|
| 2026-07-02 | Unrestricted grid argmax (drop DRAW_HEADLINE_BAND outcome restriction) | 1,843 major-finals matches, 2004+, v0.2 params | top1 14.70% vs 14.76% (−0.05pp) | [−1.66, +1.53] | **REFUTED** — no gain; restriction is not costing hits |
| 2026-07-02 | Re-tune base/beta/rho on top-1 (base 1.00–1.35 × rho −0.25–0.0 sweep) | same | best in-sample +0.22pp (base=1.0, rho=−0.25) | Exploratory in-sample screen; no bootstrap CI; within ±0.8pp binomial SE | **REFUTED** — in-sample upper bound below noise; v0.2 params stand |
| 2026-07-02 | KO lambda multiplier 0.85× (`run_ko_multiplier_gate`, FR-4.7) | 480 knockout matches / 53 editions, 2004+, v0.2 params (KO inferred structurally; base top1 13.96%) | exactNLL +0.0336, top1 −0.63pp, logloss +0.0047 | exactNLL [+0.0050, +0.0626] (worse, significant) | **REFUTED** — grids get significantly worse |
| 2026-07-02 | KO lambda multiplier 0.90× | same | exactNLL +0.0147, top1 −1.04pp, logloss +0.0025 | exactNLL [−0.0032, +0.0338]; top1 [−2.29pp, +0.00pp] | **REFUTED** — no gain anywhere, top1 borderline-worse |
| 2026-07-02 | KO lambda multiplier 0.95× | same | exactNLL +0.0038, top1 −0.83pp, logloss +0.0009 | top1 [−1.75pp, −0.19pp] (worse, significant) | **REFUTED** — production pick loses hits with CI excluding 0 |
| 2026-07-02 | FR-3.1b unrestricted grid argmax (pick-policy gate, `--pick-only`) | 1,843 major-finals matches / 53 editions, 2004+, v0.2 engine, KO share 28.0% | top1 14.70% vs 14.76% (−0.05pp) | [−1.61, +1.66] pp | **REFUTED** — reconfirms the earlier one-off run under the committed gate |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.15 (production band 0.08) | same | top1 14.98% (+0.22pp) | [−0.57, +1.06] pp | **NOT SHIPPED** — small positive point estimate, CI spans 0 |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.20 | same | top1 15.03% (+0.27pp) | [−0.73, +1.35] pp | **NOT SHIPPED** — CI spans 0 |
| 2026-07-02 | FR-3.1c DRAW_HEADLINE_BAND 0.25 | same | top1 15.14% (+0.38pp) | [−0.95, +1.69] pp | **NOT SHIPPED** — best band point estimate, still not significant |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.1 (gap buckets 0–50/50–150/150+, fit strictly pre-edition) | same | top1 14.65% (−0.11pp) | [−1.79, +1.55] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.2 | same | top1 14.54% (−0.22pp) | [−1.92, +1.59] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1d empirical prior blend w=0.3 | same | top1 14.92% (+0.16pp) | [−1.47, +1.95] pp | **REFUTED** — noise in both directions across w grid |
| 2026-07-02 | FR-3.1e stage-conditional (group/KO) empirical blend w=0.1 | same | top1 14.49% (−0.27pp) | [−1.82, +1.52] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1e stage-conditional empirical blend w=0.2 | same | top1 14.60% (−0.16pp) | [−1.85, +1.65] pp | **REFUTED** — no gain |
| 2026-07-02 | FR-3.1e stage-conditional empirical blend w=0.3 | same | top1 15.19% (+0.43pp) | [−1.33, +2.28] pp | **NOT SHIPPED** — largest point estimate of Phase 3, CI still spans 0 |
| 2026-07-02 | Per-team attack/defence offsets, half-life 1095d — PRIMARY (FR-5.1–5.3): time-decayed Poisson MLE on 49,403 historical matches (`pipeline/fit_attack_defence.py`), √(n_eff/30) shrinkage, ±0.075 log-λ cap (≈ FORM_CAP_ELO×β); walk-forward refit strictly before each edition (`run_team_offsets_gate`) | 750 matches / 18 major-finals editions 2018+, v0.2 served params | top1 16.13%→14.67% (−1.47pp); exact NLL +0.0020; log-loss +0.0028 | top1 [−2.66pp, +0.00pp]; NLL [−0.0080, +0.0114]; LL [−0.0024, +0.0084] | **REFUTED** — offsets hurt the modal pick and buy nothing on grid NLL (top1 CI touches zero: directionally negative, not conclusively significant); `"team_offsets"` stays null, code path disabled |
| 2026-07-02 | Per-team attack/defence offsets, half-life sensitivity 730d / 1460d | same | top1 −1.33pp / −1.60pp; exact NLL +0.0017 both; log-loss +0.0039 / +0.0021 | top1 [−2.43, −0.25] / [−2.73, −0.39] — significantly WORSE at both | **REFUTED** — the harm is robust to the decay choice, not a half-life artifact |
| 2026-07-02 | In-tournament asymmetric residual λ-adjust (FR-5.4): λ ×= exp(κ·(own gf-residual + opp ga-residual)), √(n/4) ramp, ±0.075 cap, κ ∈ {0.05, 0.10, 0.20} (`run_residual_form_gate`) | same | top1 −0.53 / −1.07 / −1.33pp; exact NLL −0.0019 / −0.0019 / −0.0014 (ns); log-loss ≈0 | κ=0.05 top1 [−1.37, +0.29]; κ=0.10 [−2.18, +0.00]; κ=0.20 [−2.49, −0.28] | **REFUTED** — as predicted at n=3–4 matches/team: tiny ns NLL gain, top1 degrades monotonically with κ |

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

FR-3.1e rows record the re-run after the stage-label truncation fix (review
finding on `knockout_flags`): history stage flags are now computed on COMPLETE
editions before date-truncation, so a concurrent summer edition still underway
at an edition's kickoff (Euro/Copa 2016, 2021, 2024; the 2019 Copa/Gold
Cup/AFCON triple) no longer gets trailing group matches counted into the KO
frequency table. Only w=0.2 moved (14.54% → 14.60%); every verdict stands.

Phase 3 (pick policy) verdict: **no candidate clears the FR-3.2 gate; the
production pick rule stands.** The wider-band and stage-w=0.3 point estimates
land inside the design spec's expected +0 to +0.5pp — real-if-any effect too
small to prove on ~1.8k matches. Candidates stay in `PICK_CANDIDATES`
(`--pick-only`) for cheap re-runs as more editions accrue.

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
- Post-Phase-2 re-base (2026-07-02 08:36Z, after the 90'-basis deploy): 82
  evaluated / 51 winners (62.2%) / 9 exact (11.0%) — unchanged, as expected:
  evaluation is append-only and existing rows keep their after-ET basis; the
  90' basis applies from the next finished match onward.
- Program closing state (Phases 1–5 shipped): served model remains
  poisson-elo-v0.2 — every gated upgrade candidate (pick policies, KO
  multiplier, attack/defence offsets, residual form) was refuted; shadow mode
  is live with w_odds=0 awaiting an odds key + coverage probe (Phase 4 blocked
  note above). The honest expectation band for live exact-score remains
  13–14% on WC-like matches; hits above that are luck, not model change.
