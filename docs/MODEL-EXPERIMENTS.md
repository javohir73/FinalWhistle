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

---

# Club program — PRE-REGISTRATION (2026-07-28)

Written **before any selection run**, per the overfitting-control decision
below. Nothing in this section may be edited after the first gate run except to
append results; a candidate discovered mid-flight gets a new row explicitly
marked post-hoc.

## Why this program exists

League predictions are stamped `poisson-elo-club-v0.1`
(`pipeline/run_pipeline.py`), but `generate_predictions` loads a single global
`model_params.json` — `poisson-elo-v0.5`, fitted on **international tournament
football**. There is no per-league params file. The only per-league quantity is
`home_advantage`, carried on the Tournament row. So EPL/La Liga/Bundesliga are
priced with internationals-fitted `base`/`beta`/`rho`/`temperature`, an
internationals-cut calibrator, and an internationals `k_factor`.

## Protocol

- **Data.** football-data.co.uk, ten seasons 2016-17…2025-26 per division:
  E0 n=3,800 · SP1 n=3,800 · D1 n=3,060.
- **Offline↔live parity — VERIFIED 2026-07-28.** The CSV replay path used for
  fitting (`replay_with_prematch`, local ids) and the DB path used in
  production (`load_club_results` → `compute_and_store_club_elo` → `run_elo`,
  real Team ids, deduped) produce **identical match counts, team counts and
  ratings** (within the DB path's 1-dp rounding) for all three leagues:
  E0 3800/34, SP1 3800/31, D1 3060/30, zero divergences. Offline selection
  therefore transfers to production. Re-run this check before trusting any
  future offline fit.
- **Selection.** Walk-forward over 2016-17…2024-25: each season scored by a
  model fitted only on seasons strictly before it. Bootstrap CI (2,000
  resamples) on pooled per-match deltas, **clustered by season** — the honest
  resampling unit, since matches within a season share ratings.
- **Confirmation.** 2025-26 is **quarantined**. It is touched exactly once, at
  the end, on the final chosen config *per track* — never per candidate.
- **Contamination, declared.** 2025-26 was previously used to select
  `home_advantage` from {40, 60, 80} (La Liga 80, Bundesliga 60). That
  selection is **voided**; `home_advantage` is re-fitted inside the
  walk-forward block (T1.5) so the confirmation season is genuinely untouched.
- **Known defect in the voided fit.** `compute_club_elo._evaluate_holdout`
  calls `model_probs(...)` passing only `home_adv`, so `base`/`beta`/`rho`/
  `temperature` silently fell back to `model_probs`'s **v0.1** defaults
  (`base=1.35, beta=0.0019, rho=0.0`) rather than the served v0.5 values —
  i.e. the fit ran with Dixon–Coles disabled. Measured 1X2 impact is small
  (~0.002 nats), so the 80/60 values are not badly wrong; what it invalidates
  is their provenance. Fix lands with T1.5.

## Gate assignment

λ_home = base·exp(+β·diff), λ_away = base·exp(−β·diff). 1X2 depends almost
entirely on the **ratio** (β·diff); totals markets depend entirely on the
**sum** (base). The two are near-orthogonal, so each parameter is gated on the
market it actually moves:

| Metric | Parameters gated on it |
|---|---|
| **1X2 log loss** ~~vs de-vigged closing line (vs actuals where odds absent)~~ — see correction below | `beta`, `rho`, `temperature`, `home_adv`, calibrator, `k_factor`, season shrinkage, `rest_days`, promoted prior, `w_odds` |

> **CORRECTION (2026-07-28 audit).** The struck wording overstates what was
> run. Every one of the 27 gates below scored 1X2 log loss **against realized
> outcomes only**. No de-vigged closing-line comparator was computed at any
> point in the original program — the club CSV cache was built with
> `usecols=[Date,HomeTeam,AwayTeam,FTHG,FTAG]`, so the odds columns never
> reached disk. Read every "1X2 log loss" figure in the #202 tables as
> *vs outcomes*, never *vs market*. The market baseline was first computed in
> the post-merge audit, and is reported there and in T1.6 as a **benchmark
> only** — it is never a label and never a feature.
| **O/U totals log loss** | `base` |

## Pre-registered candidates

### Track 1 — per-league core refit (all per league; defect-fix bar, see ship rules)

| ID | Candidate | Grid | Metric |
|---|---|---|---|
| T1.1 | `base` | 1.10–1.80 step 0.02 | totals |
| T1.2 | `beta` | 0.0010–0.0035 step 0.0001 | 1X2 |
| T1.3 | `rho` | −0.20–0.00 step 0.01 | 1X2 |
| T1.4 | `temperature` | 0.80–1.40 step 0.05 | 1X2 |
| T1.5 | `home_adv` (re-fit, voiding the contaminated selection) | 20–120 step 10 | 1X2 |
| T1.6 | calibrator recut — bucket edges at club effective-gap quartiles, `t`/`b` refit per bucket | edges from data; `t` 0.8–1.4 step 0.05 | 1X2 |
| T1.7 | `k_factor` for club competitions | 10–50 step 5 | 1X2 |

T1.7 note: `k_factor()` has no branch for club competitions, so every club
match falls through to the catch-all **30.0** — a value inherited from the
internationals convention and never fitted. Requires a code change (K override
threaded through `update_ratings`/`run_elo`/`replay_with_prematch`), not just a
grid sweep.

Deferred, no grid pre-registered: `goal_diff_multiplier` curve — needs a
functional-form decision before a grid is meaningful.

### Track 3 — free signals (standard gate)

| ID | Candidate | Grid | Metric |
|---|---|---|---|
| T3.1 | Season-boundary Elo shrinkage toward league mean | λ 0.00–0.50 step 0.05 | 1X2 |
| T3.2 | `rest_days` | coef 0.000–0.020 step 0.002 × cap {0.05, 0.075, 0.10} | 1X2 |
| T3.3 | Promoted-club cold-start prior — fitted from realized first-season performance of every promoted club in window, replacing `BASE_RATING`=1500 | fitted mean + spread | 1X2 |

### Track 2 — market anchor (post-kickoff; standard gate)

| ID | Candidate | Grid | Metric |
|---|---|---|---|
| T2.1 | `w_odds` per league | 0.00–0.60 step 0.05 | 1X2 vs close |

Requires a schema migration (`historical_matches` has no odds columns) plus
backfill from the CSVs already downloaded. Migration must reach the prod DB via
`refresh.yml` before dependent code serves.

### Track 4 — conditional (standard gate)

| ID | Candidate | Gate |
|---|---|---|
| T4.1 | Club xG coverage probe (`pipeline/probe_club_xg.py`) | ≥3,000 covered matches across ≥6 league-seasons. Diagnostic only, no writes |
| T4.2 | xG features → GBM-on-λ shadow challenger | Chartered **only if T4.1 clears**. Shadow-only; never serves until it beats the fitted champion on held-out club data |

## Ship rules

- **Standard gate** (Tracks 2, 3, 4): CI excludes zero in the candidate's
  favour → ship. Straddles zero → not shipped, loss recorded.
- **Defect-fix bar** (Track 1 only, and only because these correct the
  application of internationals-fitted constants to club football): bar is
  *not credibly worse*. CI in favour → ship. CI straddles zero → ship on
  principle and record it as **shipped on principle, not on gate**. CI
  credibly worse → **do not ship, investigate for leakage** — that outranks
  the params.
- Season freeze: params are frozen at kickoff. Elo continues updating online
  (specified rule, part of the model). One gated refit opportunity at the
  winter break, shipped as v0.3.

## Exploratory scoping — IN-SAMPLE, NOT GATE RUNS

Run 2026-07-28 to scope the program. **No ship decision may cite these
numbers**; they exist to justify which candidates were pre-registered.

Served-params behaviour over all ten seasons, per league:

| League | actual mean total | implied mean total | bias | 1X2 LL | O/U 2.5 LL | constant-rate O/U LL |
|---|---|---|---|---|---|---|
| Premier League | 2.835 | 2.618 | −0.217 (−7.6%) | 0.9770 | 0.6955 | **0.6893** |
| La Liga | 2.618 | 2.602 | −0.017 (−0.6%) | 0.9931 | **0.6886** | 0.6924 |
| Bundesliga | 3.096 | 2.579 | −0.517 (−16.7%) | 1.0044 | 0.7001 | **0.6738** |

**On O/U 2.5 the served model is beaten by a constant in EPL and Bundesliga.**
That is the finding that put T1.1 in scope and drove the split-gate decision.

In-sample `base` search (β fixed), showing the orthogonality directly:

| League | best `base` | Δ 1X2 LL | Δ O/U LL |
|---|---|---|---|
| Premier League | 1.32 | +0.0013 (worse) | −0.0073 (better) |
| La Liga | 1.20 (unchanged) | 0.0000 | 0.0000 |
| Bundesliga | 1.44 | +0.0057 (worse) | −0.0311 (better) |

Calibrator bucket occupancy under the served international cut — recorded
because it **refutes** a pre-scoping assumption that club gaps would collapse
into `0-50`; the cut is not degenerate, which lowers T1.6's expected value:

| League | 0-50 | 50-150 | 150-300 | 300+ |
|---|---|---|---|---|
| Premier League | 21.7% | 34.2% | 30.4% | 13.7% |
| La Liga | 20.7% | 37.1% | 30.0% | 12.2% |
| Bundesliga | 23.3% | 37.3% | 29.4% | 10.0% |

## Results — SELECTION phase (2026-07-28)

Walk-forward over 2016-17…2024-25, 8 scored seasons per league (the opening
season can never be scored — nothing precedes it to fit on). Season-clustered
bootstrap, 2,000 resamples. Confirmation season **not yet consumed**.
Runner: `pipeline/experiment_club_eval.py`. Raw: `--emit-json`.

Negative delta = candidate better. n: EPL 3,040 · La Liga 3,040 · Bundesliga 2,448.

| Candidate | League | Final pick | Mean Δ | CI95 | Verdict |
|---|---|---|---|---|---|
| T1.1 `base` | Bundesliga | **1.44** | −0.0299 | [−0.0388, −0.0204] | **BETTER (credible)** |
| T1.1 `base` | EPL | **1.30** | −0.0050 | [−0.0112, +0.0001] | not credible (favourable) |
| T1.1 `base` | La Liga | 1.20 | +0.0043 | [+0.0015, +0.0076] | **WORSE (credible)** |
| T1.2 `beta` | Bundesliga | 0.0018 | −0.0028 | [−0.0057, +0.0000] | not credible |
| T1.2 `beta` | EPL | 0.0019 | +0.0020 | [−0.0015, +0.0076] | not credible |
| T1.2 `beta` | La Liga | 0.0018 | +0.0006 | [−0.0046, +0.0080] | not credible |
| T1.3 `rho` | EPL | **0.00** | −0.0025 | [−0.0036, −0.0014] | **BETTER (credible)** |
| T1.3 `rho` | Bundesliga | **0.00** | −0.0017 | [−0.0025, −0.0007] | **BETTER (credible)** |
| T1.3 `rho` | La Liga | −0.02 | +0.0001 | [−0.0008, +0.0010] | not credible |
| T1.4 `temperature` | all three | — | +0.0000 | [+0.0000, +0.0000] | **VACUOUS — see below** |
| T1.5 `home_adv` | La Liga | **60** | −0.0026 | [−0.0038, −0.0013] | **BETTER (credible)** |
| T1.5 `home_adv` | EPL | 50 | +0.0004 | [−0.0019, +0.0027] | not credible |
| T1.5 `home_adv` | Bundesliga | 50 | +0.0002 | [−0.0020, +0.0026] | not credible |
| T1.7 `k_factor` | Bundesliga | 20 | −0.0027 | [−0.0068, +0.0022] | not credible |
| T1.7 `k_factor` | La Liga | 15 | −0.0008 | [−0.0048, +0.0034] | not credible |
| T1.7 `k_factor` | EPL | 25 | +0.0009 | [−0.0010, +0.0037] | not credible |
| T3.1 season shrinkage | La Liga | 0.20 | −0.0033 | [−0.0080, +0.0002] | **REFUTED** |
| T3.1 season shrinkage | Bundesliga | 0.10 | +0.0001 | [−0.0016, +0.0020] | **REFUTED** |
| T3.1 season shrinkage | EPL | 0.00 | +0.0005 | [+0.0000, +0.0012] | **REFUTED** |
| T3.2 `rest_days` | EPL | (0.002, 0.05) | +0.0003 | [−0.0002, +0.0009] | **REFUTED** |
| T3.2 `rest_days` | Bundesliga | (0.000, 0.05) | +0.0003 | [−0.0002, +0.0010] | **REFUTED** |
| T3.2 `rest_days` | La Liga | (0.020, 0.05) | +0.0005 | [−0.0006, +0.0018] | **REFUTED** |
| T3.3 promoted prior | EPL | 1400 | −0.0006 | [−0.0022, +0.0013] | **REFUTED** |
| T3.3 promoted prior | Bundesliga | 1375 | +0.0016 | [−0.0017, +0.0061] | **REFUTED** |
| T3.3 promoted prior | La Liga | 1450 | +0.0029 | [−0.0008, +0.0092] | **REFUTED** |

### T1.4 is vacuous, and that is a latent trap

`temperature` has **no effect whatsoever** under the served calibrator.
`calibrate()` uses the scalar temperature only when `calibrator is None`; with
`vector_scaling_segmented` set — which is what `model_params.json` ships — the
bucket's own `t` wins and the scalar is discarded. Verified directly: t=0.8,
1.0 and 1.4 return byte-identical triples. The exact +0.0000 / [+0.0000,
+0.0000] result across all three leagues is not a coincidence, it is a no-op.

Recorded because anyone tuning `temperature` in future would be tuning
nothing, and would read the flat response surface as "already optimal."

### Why La Liga's `base` refit is credibly WORSE (investigated, not leakage)

The pre-committed rule says a credibly-worse defect-fix candidate must not ship
and must be investigated. Per-season picks: 1.40 → 1.32 → 1.28 → 1.24 → 1.22 →
1.20 → 1.20 → 1.20. The walk-forward converges *onto the served value*. The
harm is entirely in the early seasons, where 1–2 seasons of training data pick
too high. So: La Liga's served `base` = 1.20 is already correct (the scoping
pass independently found 1.20 optimal in-sample), and refitting it on short
history adds selection variance with no signal to trade for it. Not a leak —
the gate correctly refusing a fit that has nothing to fit.

### Post-hoc refinement of the defect-fix bar — declared

The pre-registration set a "not credibly worse" bar for all of Track 1. Applied
literally, that would ship `beta`/`k_factor`/`home_adv` refits whose CIs
straddle zero with *unfavourable* point estimates in some leagues — i.e. refits
that add selection variance rather than correcting anything.

**Refined, post-hoc:** the defect-fix bar applies only where a defect was
demonstrated *independently and before* the gate ran. That is **T1.1 alone**
(the O/U-2.5 market beaten by a constant in EPL and Bundesliga — scoping table
above). Every other Track-1 candidate is an ordinary challenger and faces the
standard gate.

This is recorded as post-hoc per the pre-registration's own rule. It makes the
ship list strictly *smaller* than the literal reading would have.

### Ship list from selection (pending confirmation)

| League | Change | Basis |
|---|---|---|
| Bundesliga | `base` 1.20 → **1.44** | credible win on totals, −0.0299 |
| Bundesliga | `rho` −0.06 → **0.00** | credible win on 1X2, −0.0017 |
| EPL | `base` 1.20 → **1.30** | defect-fix bar; favourable, CI touches 0 |
| EPL | `rho` −0.06 → **0.00** | credible win on 1X2, −0.0025 |
| La Liga | `home_adv` 80 → **60** | credible win on 1X2, −0.0026 |
| La Liga | `base` | **unchanged at 1.20** — refit credibly worse |

Everything else — `beta`, `k_factor`, `temperature`, season shrinkage, rest
days, promoted-club priors — **does not ship**. Three free-signal hypotheses
(T3.1/T3.2/T3.3) are refuted across all three leagues.

Note that `rho` → 0.00 means the Dixon–Coles low-score correction is being
switched *off* for club football in both leagues where it cleared. The
internationals-fitted −0.06 is actively costing 1X2 accuracy on club matches.

## Results — CONFIRMATION phase (2026-07-28)

The one-shot on the quarantined 2025-26 season. **The season is now consumed.**
Config came from `experiment_club_eval.FINAL_CONFIG` — frozen from the
selection ship list, not re-fitted. Both metrics reported, because Track 1
spans them.

Resampling unit is the **matchweek**, not the season: one held-out season is a
single season-cluster, so a season bootstrap would resample the same cluster
every draw and return a zero-width CI — an interval that looks certain
precisely because it measured nothing. Calendar week gives 33–37 clusters per
league and respects the short-range correlation between matches sharing a
rating snapshot.

| League | Config | Metric | Mean Δ | CI95 | Verdict |
|---|---|---|---|---|---|
| Bundesliga | `base` 1.44, `rho` 0.00 | **O/U 2.5** | **−0.0447** | **[−0.0756, −0.0126]** | **CONFIRMED — credibly better** |
| Bundesliga | same | 1X2 | +0.0047 | [−0.0053, +0.0156] | not credible |
| EPL | `base` 1.30, `rho` 0.00 | O/U 2.5 | −0.0094 | [−0.0202, +0.0013] | not credible (favourable) |
| EPL | same | 1X2 | +0.0043 | [−0.0034, +0.0124] | not credible |
| La Liga | `home_adv` 60 | 1X2 | +0.0002 | [−0.0056, +0.0057] | not credible |
| La Liga | same | O/U 2.5 | +0.0014 | [−0.0008, +0.0037] | not credible |

### What confirmed, and what did not

**Confirmed:** Bundesliga's `base` refit. The held-out effect (−0.0447) is
*larger* than the selection estimate (−0.0299), on 306 matches it never saw.

**Did not replicate:** all three of the credible 1X2 wins from selection.
`rho`→0.00 (EPL −0.0025, Bundesliga −0.0017) and `home_adv`→60 (La Liga
−0.0026) each come back with a *positive* point estimate and a CI straddling
zero on held-out data.

This is exactly what the multiplicity control was built to catch. 27 gates were
run against one selection block; at a 95% CI, one or two clearing by chance is
the expectation, not a surprise. Without the quarantined season all three would
have shipped as validated wins and entered the public ledger as such.

### Limitation, declared: the 1X2 numbers cannot be decomposed

The confirmation scored each league's **combined** config, so Bundesliga's and
EPL's 1X2 deltas mix the `base` change (known to cost a little 1X2 — `base` is
tuned for the λ sum, 1X2 keys off the ratio) with the `rho` change. Bundesliga
decomposes plausibly: in-sample base-only was +0.0057 and selection rho-only
−0.0017, summing to ≈+0.0040 against the observed +0.0047 — i.e. the 1X2 cost
is the `base` move, and `rho` is roughly neutral. EPL does not decompose that
cleanly (+0.0013 and −0.0025 sum to −0.0012 against an observed +0.0043), so
`rho` genuinely failed to replicate there.

Separating them properly would mean scoring more configs against a season that
is now burnt — multiple testing against a consumed holdout, which is weak
evidence and would not be recorded as a gate result. **The fresh holdout is the
live 2026-27 season.** `rho` stays at the served −0.06 until then.

### FINAL ship list (post-confirmation)

| League | Change | Basis |
|---|---|---|
| **Bundesliga** | `base` 1.20 → **1.44** | Confirmed on held-out data, −0.0447 O/U, CI [−0.0756, −0.0126] |
| **EPL** | `base` 1.20 → **1.30** | Defect-fix bar (O/U beaten by a constant, demonstrated pre-gate); held-out direction favourable, not credible |
| La Liga | **nothing** | `base` refit credibly worse in selection; `home_adv` 60 did not replicate. Stays at `base` 1.20 / `home_adv` 80 |

Not shipping: `rho` (did not replicate), `beta`, `k_factor`, `temperature`
(vacuous), season shrinkage, rest days, promoted-club priors.

`home_adv` note: La Liga's served 80 retains weak provenance — it came from the
fit with the v0.1-fallback defect, on a season now consumed. The walk-forward
preferred 60 but it did not replicate, and the two are empirically
indistinguishable (+0.0002). No evidence to change it, so it does not change.

## T4.1 — club xG coverage probe (2026-07-28)

Run against the live API-Football Pro plan (active, expires 2026-08-18;
6/7,500 requests used at start). Diagnostic only, no writes.

**Finding: xG coverage begins at season 2023 and is absent before it.** Every
league sampled 0/20 for 2018–2022 and 20/20 for 2023 — a clean provider
cutover, not patchy coverage.

As pre-registered, the probe **FAILED**: ~1,754 covered matches across 5
league-seasons, against a gate of ≥3,000 and ≥6.

### Post-hoc correction, declared: the probe asked a stale question

`probe_club_xg.SEASONS` is hardcoded `[2018…2023]` — written years before
2024 and 2025 existed. Given the observed cutover, the decision-relevant
question is whether the two completed seasons the probe never looked at are
covered. **The gate thresholds were not touched**; only the stale window was
corrected. Recorded here as post-hoc because the extension was run after
seeing the original fail.

| League | 2023 | 2024 | 2025 |
|---|---|---|---|
| Premier League | 380 | 380 | 380 |
| La Liga | 380 | 380 | 380 |
| Serie A | 380 | 380 | 380 |
| Bundesliga | 307 | 308 | 307 |
| Ligue 1 | 307 | 307 | 308 |

All 15 cells sampled 20/20.

- Top-5 leagues: **~5,264 matches across 15 league-seasons**
- The three served leagues alone: **~3,202 matches across 9 league-seasons**

**GATE PASSES on the served three alone** (≥3,000 matches, ≥6 cells), before
counting Serie A or Ligue 1. **T4.2 (GBM-on-λ) is chartered**, and the
2026-08-18 Pro renewal is now an evidence-backed spend rather than a guess.

Two constraints that shape T4.2:

1. **Depth, not breadth, is the binding limit.** xG exists for 3 seasons, not
   the 10 the Elo replay uses. An xG-featured challenger trains on ~3,200
   matches (served leagues) or ~5,264 (top-5), against ~10,700 for the
   goal-based engine. Walk-forward folds drop from 9 to ~2.
2. **These are sample-based estimates.** 20 fixtures per cell, all 20/20;
   coverage is extrapolated as uniform within a season. Sound given the
   observed cutover, but a full backfill should verify rather than assume.

## The live receipt: `+baseline` twin

The two shipped changes rest on **one** confirmation season — n=306 for
Bundesliga, n=380 for EPL. Three of the five selection-phase candidates died
on that same season, which is a fair warning about how much a single held-out
sample can carry.

So the promotion logs its own live A/B. Every league match now writes a
`<version>+baseline` `is_shadow` row: the same engine run with the parameters
production served *before* the refit (`poisson-elo-club-v0.1`, the global
internationals values). Rebuilt through `build_payload` rather than scaled off
the production payload, because `base` and `rho` are not expressible as a
lambda multiplier the way the `+bans`/`+rest` offsets are.

- Opt-in: `generate_predictions(..., baseline_params=...)`. None (the default)
  writes nothing, so WC26 and every pre-existing call site is unchanged, and a
  promotion with no meaningful predecessor logs no pointless copy of itself.
- Scored by `pipeline/run_baseline_benchmark.py`. **Note the inverted sign
  convention**: for the feature twins a negative diff favours the twin; here
  the twin is the OLD model, so a negative diff means the promotion was right.
  There is a test locking exactly that, because getting it backwards would
  invert every verdict.
- Grouped by production model version, so two families never pool into one
  comparison — the same leak the shadow and availability ledgers each had to
  close.

Expected state until 2026-08-15: `insufficient`, no pairs. That is correct,
not a failure.

## POST-MERGE AUDIT of #202 (2026-07-28) — corrections

Read-only audit after #202 merged. Nothing here was tuned on the consumed
2025-26 season. Two findings materially qualify the shipped result.

### What held up

- **No leakage.** Empirically probed, not argued: tampering with the
  confirmation season's results, dropping it entirely, and tampering with each
  scored season's own results all leave selection picks bit-identical. Selection
  is provably prior-only.
- **Data integrity clean.** 3,800 / 3,800 / 3,060 rows, zero dropped in
  cleaning, zero duplicate `(date, home, away)`, zero unparsed dates, file
  order already chronological in all 30 season files, 2–3 promotions/season.
- **Offline↔live Elo parity** re-verified against `main` (including #199's
  alias remapping), all three leagues, zero divergence.

### Finding 1 (P1) — the market baseline was never computed

Every #202 gate scored against realized outcomes only. No de-vigged
closing-line comparator was ever run, despite ten seasons of closing odds
being present in the same football-data.co.uk files and
`pipeline/ingest/football_data.py` already parsing them. The club cache was
built with `usecols=[Date,HomeTeam,AwayTeam,FTHG,FTAG]`, so the odds columns
never reached disk.

Computed now (`AvgC` closing, proportional de-vig, ~70% of matches carry odds):

| League | control − market | shipped − market | n with odds |
|---|---|---|---|
| Premier League | +0.0312 | +0.0316 | 2,660 |
| La Liga | +0.0279 | +0.0279 | 2,660 |
| Bundesliga | +0.0326 | **+0.0369** | 2,142 |

**The model is behind the closing line in all three leagues**, and #202 moved
Bundesliga *further* behind on 1X2. Against the metric this program was
chartered on — paired Δ log-loss vs de-vigged closing odds — the shipped
Bundesliga change is a 1X2 regression. It remains a large totals win.

### Finding 2 (P1) — `base` was changed without refitting the calibrator

The segmented calibrator's per-bucket `(t, b)` were fitted for a lambda scale
of `base=1.2`. #202 raised `base` without refitting it, moving the model
outside the calibrator's fitted regime.

| Config | 1X2 LL | ECE | sharpness |
|---|---|---|---|
| Bundesliga control 1.20 | 1.0074 | **0.0147** | 0.525 |
| Bundesliga shipped 1.44 | 1.0101 | **0.0437** | 0.554 |

**Calibration degraded ~3× on Bundesliga 1X2** while sharpness rose — the
model became more confident and less correct. Not measured in #202, which
reported only log loss.

Related, and larger: the internationals calibrator *costs* club 1X2 log loss
in 3 of 4 configurations tested (EPL control +0.0042, EPL shipped +0.0028,
Bundesliga control +0.0030 vs calibrator-off). Pre-registered candidate T1.6
(calibrator recut) was never run — it was deprioritised after bucket occupancy
turned out non-degenerate. That was the wrong call: occupancy is not fit.

### Finding 3 (P2) — effect stability differs sharply by league

Per-season deltas (shipped − control), 9 pre-confirmation seasons:

| League | metric | mean | season SD | read |
|---|---|---|---|---|
| Bundesliga | O/U 2.5 | −0.0296 | 0.0169 | robust; 9/10 seasons improve |
| Bundesliga | 1X2 | **+0.0026** | 0.0041 | consistently worse, 7/10 seasons |
| Premier League | O/U 2.5 | −0.0069 | 0.0089 | **SD 1.3× the mean — weak** |
| Premier League | 1X2 | −0.0009 | 0.0022 | noise |

Bundesliga's totals gain is real. **EPL's `base` change is not well
supported**: its season-to-season SD exceeds its mean effect, and it shipped
under the defect-fix bar on a CI that touched zero.

### Finding 4 (P2) — the confirmation CI is anti-conservative

The confirmation clustered by **matchweek** (33–37 clusters) because one
held-out season gives a single season-cluster. Matchweek clustering ignores
season-level correlation, so those intervals are narrower than a season-level
analysis would give. They are conditional on that season and carry no
season-to-season uncertainty. The per-season tables above are the honest
sensitivity: read them, not the confirmation CI alone, when judging effect size.

Multiplicity: 27 selection gates at nominal 95% imply ≈1.35 expected false
positives under a global null. Four cleared; three failed confirmation. That
is consistent with roughly one real effect plus noise, which is what the
per-season tables show (Bundesliga totals real, the rest not).

### Finding 5 (P3) — served `home_advantage` retains contaminated provenance

La Liga 80 / Bundesliga 60 were selected on the 2025-26 season with v0.1
params (Dixon–Coles disabled). #202 voided that selection and refit inside the
walk-forward, but T1.5 did not replicate, so the **original contaminated
values still serve**. They are not wrong — selection and confirmation agree
they are indistinguishable from the alternatives — but their provenance is the
now-burnt holdout, and that should not be cited as validation.

### Not changed here

No parameter was retuned. Correcting Findings 1–3 requires a fresh holdout —
the 2025-26 season is consumed — and the live 2026-27 season is that holdout.
The `+baseline` twin already logs the live A/B needed to adjudicate Bundesliga
1X2 vs totals.

### Reproduction

```
PYTHONPATH=backend:. .venv/bin/python -m pipeline.club_data_manifest --dir <captures>
```

Raw inputs are pinned in `pipeline/data/club_data_manifest.json` (sha256 for
all 30 season files, captured 2026-07-28). football-data.co.uk revises files in
place, so verify before citing any number above as reproduced.

**Two verification scopes.** This audit and the #202 reproduction use the full
30-file set — that program consumed the 2025-26 season, so re-reading it
changes nothing. Any POST-confirmation experiment must instead use
`--pre-confirmation-only` (27 files), because hashing a capture opens it and
that would itself be a holdout read. T1.6 uses the 27-file scope.

## T1.6 — club calibrator recut (2026-07-28). SHADOW-ONLY, nothing promoted

The pre-registered candidate that #202 skipped. Run after the audit showed the
internationals calibrator costing club 1X2 log loss, and #202's `base` change
degrading Bundesliga calibration ~3×.

### Protocol

- **Data** — nine PRE-confirmation seasons, 2016-17…2024-25. The consumed
  2025-26 holdout is dropped **at load**; `assert_holdout_absent` is a backstop
  that raises if one row of it reaches any fit/score path. Six regression tests
  pin this, including one proving the loader drops it before the guard runs.
- **Manifest scope — the holdout is never opened.** Verification *hashes*
  files, i.e. opens and reads them, so this is a distinct exposure from the
  season filter above. Two scopes exist and must not be confused:

  | Scope | Files | Used by |
  |---|---|---|
  | `expected_keys()` | **30** (2016-17…2025-26) | #202 reproduction — may read the holdout, that program consumed it |
  | `pre_confirmation_keys()` | **27** (2016-17…2024-25) | **T1.6** — the three `*_2526` captures are never opened |

  Found in mentor review of the first cut of this branch, where the T1.6
  runner verified all 30 keys and therefore hashed the holdout bytes at its
  entry point, *before* the season filter ran. Now scoped, and pinned by a
  regression test that replaces each `*_2526` capture with a directory (so any
  `read_bytes()` raises regardless of permissions or test user), proves the
  27-file path completes cleanly, asserts `expected == matched == 27`, and
  separately proves the poison is real by showing the unscoped call still
  raises. Correcting the manifest scope changed **no result**: the re-run is
  byte-identical to the pre-fix output.
- **Outer** — for each scored season S, the training block is every season
  strictly before S. Every candidate's bucket **edges** and per-bucket `(t, b)`
  are fitted on that block alone, then scored on S. Calibration is never fitted
  on the outcomes it scores.
- **Abstention** — `--min-train-seasons 3`. Seasons 2016-17/2017-18/2018-19 are
  **abstained, not scored**, and never pooled with later data to cover the
  shortfall. Six seasons are scored per league: n=2,280 (EPL, La Liga),
  n=1,836 (Bundesliga).
- **Family** — six candidates declared before the run: two fixed references
  (`prod_calibrator`, `no_calibrator`) and a four-member recut family
  (`refit_served_edges`, `refit_q3`, `refit_q4`, `refit_q4_thin`). CIs are
  season-clustered bootstrap, reported nominal **and** Bonferroni-corrected at
  k=4 over the recut family.
- **Market** — de-vigged closing odds reported as a benchmark. Not a label, not
  a feature; no candidate reads them.

### Result — Δ log loss vs the production calibrator (negative = better)

Bundesliga, **shipped base=1.44 — the configuration production actually serves**:

| candidate | Δ vs prod | CI95 | CI95 Bonferroni (k=4) | ECE |
|---|---|---|---|---|
| prod_calibrator | — | — | — | **0.0645** |
| no_calibrator | −0.0009 | [−0.0073, +0.0038] | — | 0.0733 |
| refit_served_edges | −0.0073 | [−0.0131, −0.0021] | [−0.0144, −0.0008] | 0.0366 |
| **refit_q3** | **−0.0104** | **[−0.0168, −0.0046]** | **[−0.0188, −0.0036]** | 0.0340 |
| refit_q4 | −0.0078 | [−0.0131, −0.0030] | [−0.0148, −0.0021] | **0.0312** |

**All four recut variants survive Bonferroni.** The recut recovers ≈0.010 nats
and roughly halves ECE (0.0645 → 0.031–0.034) in exactly the configuration
#202 damaged. Market benchmark on the same matches: LL 0.9779 vs the recut's
1.0061 — still behind.

Bundesliga control (base=1.20): only `refit_q3` survives Bonferroni
(−0.0071, [−0.0142, −0.0007]).

| League / config | best candidate | nominal | Bonferroni | verdict |
|---|---|---|---|---|
| Bundesliga shipped | refit_q3 | −0.0104 ✓ | ✓ | **survives** |
| Bundesliga control | refit_q3 | −0.0071 ✓ | ✓ | **survives** |
| Premier League shipped | refit_q3 | −0.0050 ✓ | ✗ | nominal only |
| Premier League control | refit_q3 | −0.0046 ✓ | ✗ | nominal only |
| La Liga (control=shipped) | refit_q4 | −0.0017 | ✗ | no effect |

### Reading

1. **The recut is a repair for #202's `base` change, not a general win.** Its
   effect tracks the damage: largest where ECE was worst (Bundesliga shipped),
   absent where `base` never moved (La Liga).
2. **"Remove the calibrator" is refuted.** `no_calibrator` is nowhere credible
   and makes Bundesliga-shipped ECE *worse* (0.0733 vs 0.0645). The problem is
   a calibrator fitted for the wrong lambda scale, not calibration itself.
3. **The audit's descriptive estimate was optimistic.** It suggested the
   internationals calibrator costs log loss broadly; under proper nesting the
   effect is smaller and only Bundesliga clears. Nested estimates beat
   full-sample descriptive ones — as expected.
4. **Equal-count edges beat the served edges.** `refit_q3` wins in five of five
   configurations, consistent with club gaps being lower and tighter than the
   international matchups the 50/150/300 cuts were drawn for.
5. **Still behind the market everywhere.** The best recut leaves Bundesliga at
   1.0061 vs the closing line's 0.9779.

### Not promoted

Nothing here changes serving. A shipped recut would additionally require
`calibration.calibrate` to read `edges` from the blob — the served path's
edges are a module constant — which is deliberately out of scope. The next
clean holdout is the live 2026-27 season.

### Scoreboard

Two parameter changes ship, in one and a bit leagues, out of 27 gates and 9
candidate families. Three apparent wins were killed by the held-out season.
That is the process working: the internationals program shipped nothing across
~15 candidates, and this one ships the one thing that had an independently
demonstrated defect behind it.
