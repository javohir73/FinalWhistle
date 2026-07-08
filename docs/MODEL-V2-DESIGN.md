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

## 6. Open items requiring owner action

- **Prod shadow-ledger readout** (gates C4/C5 promotion): read-only queries
  against `PROD_READ_DATABASE_URL` are blocked by the permission classifier in
  this environment. Either add a settings allowlist rule for read-only psql, or
  run the readout manually.
- Norway–Brazil actual stored prediction row (forensics only; reproduction is
  already conclusive) — same access gate.
