# Model v2 — Design & Validation Plan

Owner: ML engineering. Status: in progress on `feat/model-v2`.
Trigger: Norway–Brazil misprediction post-mortem (July 2026) + full pipeline audit.

## 1. Root cause of the Norway–Brazil miss

Reproduced with production code + the post-group-stage DB state (the exact inputs a
knockout prediction was generated from). Production (`poisson-elo-v0.2`) served:

```
P(Brazil) = 0.510   P(draw) = 0.270   P(Norway) = 0.220    headline: Brazil 1-0
effective gap = +121.1 Elo  =  +82.0 historical prior  +39.1 in-tournament adjustment
```

Three mechanisms produced the +121:

1. **The prior dominates and nothing modern counterweights it.** The production
   triple is a function of exactly two inputs: effective Elo and neutral-venue
   flag. The +82 historical gap is decades of reputation; Elo's K-factor moves
   it slowly regardless of how sharp a team's current run is.
2. **The single live form channel netted to ~zero for Norway and +29 for Brazil.**
   `form_adjustment` collapses attack and defence residuals into one scalar:
   Norway's attack overperformance (+1.22 goals/match above model expectation —
   the Haaland run) was arithmetically cancelled by one defensive collapse
   against France (+1.23 conceded above expectation). Brazil's mild, broad
   overperformance against the group's weakest opponents compounded to +29.15
   (near the ±35 cap). The channel also starts from zero at the tournament
   boundary: Norway's last-10 pre-tournament form (21/30 points, GF 31, GA 8 —
   better than Brazil's 19/30, GF 25, GA 11) sat unused in `team_stats`.
3. **Every signal that would have helped was built but disconnected.**
   `model_params.json` ships `calibrator: null`, `wdl_blend: null` (the 15-feature
   form-aware booster), `w_odds: 0.0` (market anchor), `team_offsets: null` (xG),
   and the announced-XI/injury availability adjustment writes shadow rows only.

Honesty note: a 22% event is not by itself proof of model error. The error is
systematic — the model would emit the same triple even when form, availability
and the market all point the other way, because those inputs are not connected.

## 2. Baseline (what v2 must beat)

| Dataset | Model | Log loss | Brier | Winner acc |
|---|---|---|---|---|
| WC2018 (64) | v0.1 raw | 0.9670 | 0.5739 | 0.562 |
| WC2018 (64) | favorite baseline | 0.9912 | 0.5891 | 0.562 |
| WC2022 (64) | v0.1 raw | **1.0693** | 0.6236 | 0.531 |
| WC2022 (64) | favorite baseline | **1.0208** | 0.6110 | 0.531 |
| WC26 groups (59) | v0.2 production ledger | 0.8937 | 0.5246 | 0.610 |

The model *lost to the naive favorite baseline on WC2022*. That is the clearest
offline evidence that Elo-only is leaving signal on the table.

## 3. v2 changes (each gated on measurable improvement)

### C1. Split, decayed, boundary-free form channels (root-cause fix)
Replace the single cancelling `form_adjustment` scalar with two log-lambda
offsets computed from a **unified residual ledger** that spans pre-tournament
history and tournament matches with exponential recency decay (half-life `h`
in matches, tuned):

```
atk_form = clamp(c_atk * decayed_mean(gf_residuals), ±cap_form)
def_form = clamp(c_def * decayed_mean(ga_residuals), ±cap_form)
lam_team ×= exp(atk_form_team + def_form_opponent)
```

Residuals stay measured against the model's own pre-match expectation (so they
are already opponent-quality-adjusted); pre-tournament residuals come from
`replay_with_prematch()` over `historical_matches`. The zero-sum `elo_delta`
channel is unchanged. `c_atk`, `c_def`, `cap_form`, `h` are tuned by the
existing walk-forward coordinate-descent tuner — never hand-set.
Why it fixes the miss class: attack and defence stop cancelling; one bad match
no longer erases a run of good ones; pre-tournament form carries in instead of
resetting to zero at the group-stage boundary.

### C2. Ship an actual calibrator
`fit_segmented_vector_scaling` exists and is validated by tests but production
ships `calibrator: null`. Fit on the walk-forward validation window; ship the
blob in `model_params.json`. Fixes draw under-prediction and favorite
overconfidence at the probability level.

### C3. Blend the W/D/L booster (form → outcome probabilities)
The 15-feature logistic booster (`wdl_features.py`: form, GF/GA averages, h2h,
data volume) exists with a blend leg already deployed (default off). Train on
leak-free enriched history, pick the blend weight on the validation window,
gate on walk-forward log loss. This is the direct channel for
`form_points_last10` into the served triple.

### C4. Market-odds anchor (additional signal, never primary)
The odds-anchored shadow twin and the W/D/L odds-blend leg exist (`w_odds`,
blend leg shipped 2026-07-07, default off). Promotion criterion: shadow ledger
must show the blended twin beating production on log loss over ≥30 scored WC26
matches. Weight hard-capped at 0.5 so the model stays primary. **Gated on the
prod shadow-ledger readout** (read access currently blocked from this
environment — see §6).

### C5. Availability into production (injuries / announced XI)
Code exists end-to-end (`availability_offset`, clamp [−0.25, +0.10] log-lambda);
production currently renders it as a UI note while the adjusted prediction goes
to a shadow row. No historical lineup data exists to backtest it, so promotion
uses the same shadow-ledger gate as C4.

## 4. Explicitly rejected / deferred (no data ⇒ no feature)

Fatigue & rest days, travel distance, tactical matchup, coach performance,
tournament pressure, referee, weather: no ingested data source in this repo can
support them today, so they cannot clear the "measurable predictive value"
bar. They are ingestion projects, not model features, and are deferred.
Head-to-head stays out of the core math (tiny samples, mostly ancient) — it
already surfaces in the explanation layer, and enters C3 only as a weak
booster feature where the regression can learn to ignore it.

## 5. Validation protocol

- Walk-forward backtests on WC2018 + WC2022 (existing harness, extended with a
  variant/ablation runner). Tuning only ever sees the pre-tournament validation
  window; the tournament itself is held out.
- WC26 group-stage replay: re-predict the 71 finished group matches using only
  information available pre-kickoff of each match; score against the stored
  v0.2 production ledger on identical matches.
- Per-change ablations: each of C1–C3 toggled independently; a change ships
  only if it improves held-out log loss without degrading Brier or calibration
  (reliability curve / ECE).
- Case replay: Norway–Brazil rerun under v2. Success = materially
  better-calibrated upset probability with the same inputs; flipping the pick
  is not the target (that would be fitting one match).
- Leakage guards: all feature computation as-of pre-kickoff; tests assert no
  post-match information enters `build_match_features` / residual ledgers.

## 5b. Validation results & ship decisions (2026-07-08)

Walk-forward ablations (form hyperparams + calibrator fit on each tournament's
pre-tournament validation window only):

| Variant | WC2018 LL | WC2022 LL | WC26 replay LL (n=71) |
|---|---|---|---|
| v0.1-raw | 0.9670 | **1.0693** | 0.9264 |
| v0.2-tuned | 0.9813 | 1.0943 | 0.9053 |
| v0.2+form (C1) | 0.9713 | 1.1071 | 0.9100 |
| v0.2+cal (C2) | 0.9791 | 1.0942 | **0.8974** |
| v0.2+form+cal | 0.9732 | 1.1178 | 0.9005 |

(Numbers above are from the post-review rerun after unifying every residual
ledger onto the served goals scale and fixing the replay's host-as-away sign —
the original ablation had a tuner/scorer scale mismatch, caught in review. The
C1 verdict was re-decided on these clean numbers and did not change.)

Shipped-file check (v0.2 goals constants as served, on the same 71 WC26
matches): goals-only 0.9160 → with calibrator **0.9119**; fit-window (n=2084)
log loss 0.8611 → 0.8564, ECE 0.0092 → 0.0055.

**Decisions:**
- **C2 ships** (`poisson-elo-v0.4` = v0.2 goals + segmented vector-scaling
  calibrator): the only lever that improved or held log loss on every holdout,
  with the best calibration error. Fit by `pipeline/fit_calibrator.py`;
  refit-able any time.
- **C1 does NOT ship as default** (`form_channels: null`): better than v0.2 on
  WC2018, worse on WC2022 and the WC26 replay — inconsistent ⇒ off, per the
  "remove features that add noise" gate. Code, tuner, ledger, migration and
  tests stay in (dark), so the harness can keep evaluating it as more WC26
  matches finish; ablation is one config away.
- **Goals params NOT re-tuned**: window-tuned goals beat the shipped constants
  on the WC26 replay but lose on 2018/2022 — era-fragile, and the shipped
  values were fit on a ~1,800-match tournament sample for exact-score quality.
- **Case replay (Norway–Brazil)**: v0.4 gives 52.1/27.6/20.3 vs v0.2's
  51.0/27.0/22.0 — the calibrator slightly *lowers* this upset's probability,
  because two years of evidence says 50–150-gap underdogs win less often than
  raw Poisson claims. Aggregate calibration and single-case vindication are
  different objectives; the honest lever for Norway-type cases is C4 (market
  prior) + C5 (availability), both gated on the prod shadow ledger. This
  matches the repo's own earlier conclusion (pipeline/tune_model.py): "W/D/L
  is still at its Elo-only ceiling; the next real outcome lever is a market
  (odds) prior."

## 6. Open items requiring owner action

- **Prod shadow-ledger readout** (gates C4/C5 promotion): read-only queries
  against `PROD_READ_DATABASE_URL` are blocked by the permission classifier in
  this environment. Either add a settings allowlist rule for read-only psql, or
  run the readout manually.
- Norway–Brazil actual stored prediction row (forensics only; reproduction is
  already conclusive) — same access gate.
