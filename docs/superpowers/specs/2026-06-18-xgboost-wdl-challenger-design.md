# Gradient-boosted W/D/L challenger (HistGradientBoosting) — design

**Date:** 2026-06-18
**Status:** Approved (design)
**Source:** user request — "implement xgboost model to our model as well." Original ask was a
*live / in-play* booster (current minute, score, shots, SoT, live xG, possession, corners,
dangerous attacks, cards, subs, odds). That track is **data-blocked** (see Non-goals): a
supervised in-play model needs historical in-play snapshots labelled with final outcomes,
which neither the codebase nor `martj42/international_results` has, and ~3 of the 12 features
(dangerous attacks, reliable international live xG, live odds) aren't reachable from the
existing api-sports feed. The feasible, zero-new-data increment chosen with the user is a
**pre-match** boosted W/D/L challenger on the data we already replay.

## Problem

The served engine is hand-coded Poisson + Elo. We have never tested whether a gradient-boosted
classifier — given richer leak-free features (form, head-to-head, rolling goals, host,
competition tier) on top of Elo — predicts match outcome (W/D/L) better than the Poisson
engine. We want to find out, and to ship the booster **only if it actually wins**, with the
same honesty bar the calibrator had to clear (it didn't, and shipped as `calibrator: null`).

## Goal

A gradient-boosted W/D/L classifier that is **trained and gated offline**, and **auto-promoted
to a production blend with the Poisson engine only if it beats Poisson out-of-sample** under
the existing edition-clustered bootstrap. If it doesn't clear the gate it stays a documented
benchmark and production is byte-identical to today (`wdl_blend: null`).

Decisions locked with the user:
- **Role:** challenger → auto-promote to a blend if it passes the gate (not always-blend, not
  benchmark-only).
- **Library:** `sklearn.ensemble.HistGradientBoostingClassifier` (histogram gradient boosting —
  same technique as XGBoost), **not** the `xgboost` package. scikit-learn 1.6.0 is already a
  dependency; this adds **zero** new packages, no `libomp` native dep, and no Render free-tier
  image/memory risk. Native multiclass `log_loss` and missing-value handling.

## Design

### 1. Scope & boundary

- The booster outputs **only a W/D/L triple** — it refines the headline outcome
  probabilities + confidence on the match card.
- **Untouched, all stay pure Poisson:** the predicted scoreline, the group/bracket
  Monte-Carlo simulators, and the live win-probability bar. The booster produces no scoreline
  distribution, so it cannot and does not feed any of these.
- **Default = off.** `wdl_blend: null` ⇒ `generate_predictions` runs exactly as today.

### 2. Leak-free training features — `ml/features/training_rows.py`

`build_match_features()` (`ml/features/build_features.py`) reads *today's* `TeamStats`
snapshot, so it would leak the future if used to label past matches. Add a dedicated
chronological-replay builder:

```
build_training_rows(ordered_matches) -> list[dict]
```

A single oldest→newest sweep that, at each match, emits features computed **only from earlier
matches**, plus the label. Reuses `ml.ratings.elo.replay_with_prematch` for the (already
leak-free) Elo, and maintains rolling per-team / per-pair state in the same pass:

| Feature | As-of source |
| --- | --- |
| `elo_home`, `elo_away`, `elo_diff` | `replay_with_prematch` pre-match ratings |
| `is_neutral`, `is_home_host` | match row |
| `form_home`, `form_away`, `form_diff` | rolling last-10 points (3/1/0), per team |
| `gf_avg_home/away`, `ga_avg_home/away` | rolling goals for/against (last-10) |
| `h2h_home_winrate`, `h2h_matches` | pair history strictly before this match |
| `competition_tier` | bucketed: WC/major final · qualifier · friendly · other |
| `data_points_home`, `data_points_away` | match counts so far (confidence signal) |

Label: `result_label(score_home, score_away)` → `"H"|"D"|"A"` (reuse from
`ml/models/baseline_logistic.py`).

**Dropped on purpose:** FIFA rank. No historical FIFA-rank table exists, so it can't be
reconstructed leak-free; it already feeds Elo cold-start upstream (`estimate_strength`), so
its signal is not lost. Train/serve parity: at serve time the same builder computes features
from current-as-of data, which is correct because the upcoming match is in the future.

### 3. Model wrapper — `ml/models/wdl_boost.py`

Mirrors `baseline_logistic.py`'s shape:

```
class WdlBoost:
    def fit(self, rows: list[dict]) -> "WdlBoost"          # rows from build_training_rows
    def predict_proba(self, feats: dict) -> dict[str,float] # {"H","D","A"} summing to 1
```

- Wraps `HistGradientBoostingClassifier(loss="log_loss", random_state=<fixed>, ...)`.
- **Recency weighting:** `sample_weight` with an exponential half-life (~8 years) + a date
  floor (e.g. drop pre-1990) so it trains in seconds and is dominated by the modern regime.
- Class-order safety: map `model.classes_` → `{"H","D","A"}` exactly as the logistic baseline
  does (never assume column order).
- Deterministic under the fixed seed (asserted in tests).

### 4. The gate — extend `pipeline/experiment_model_eval.py`

The ship decision uses the existing **`run_global_split`** path (the honest "can we ship one
fixed model that beats v0.1 out-of-sample?" test), which already builds explicit `train`
(2004–2017 major finals) and `test` (2018+) sets.

- Train `WdlBoost` on the **full pre-test leak-free history** (not the 730-day tune window — a
  booster needs tens of thousands of rows, unlike the 4-knob Poisson tune).
- **Fit the blend weight `w` and a blend calibrator on a held-out tail of train** (e.g. the
  last 2 years before the test cutoff), never on test: `blend = w·HGB + (1−w)·Poisson`, where
  `Poisson` is the engine at the **served params** (currently the v0.2 `model_params.json`);
  pick `w` minimizing log-loss, then fit a vector-scaling/temperature calibrator
  (`ml/evaluation/calibration.py`) on the blended probs.
- On `test`: score `blend` against **Poisson alone at the same served params (no blend)** with
  the paired **edition-clustered bootstrap** (`block_bootstrap_ci`), reporting log-loss / RPS /
  Brier / per-class ECE. This paired delta isolates the booster's actual contribution over the
  engine it would augment (rather than against the older v0.1 label).
- Scoreline-only columns (exact-NLL, top-k) for the booster **borrow the Poisson grid** (the
  booster has none) — consistent with §1; these columns just won't differ for the booster.
- Optionally surface a `wdl_boost` / `blend` candidate in the per-edition walk-forward table
  for diagnostics; the **ship decision is `run_global_split`'s bootstrap CI**.

**Ship criterion (same bar as the calibrator):** promote to a blend **only if** the paired
log-loss delta `(blend − Poisson-alone)` CI **excludes 0 on the better side**, with **no RPS
regression**. Otherwise write `wdl_blend: null`.

### 5. Serving & blend — `generate_predictions.py` + `ml/models/params.py`

Add one nullable field to `ModelParams` + `model_params.json`, mirroring `calibrator`:

```jsonc
"wdl_blend": null
// shipped form:
"wdl_blend": { "weight": 0.35, "calibrator": { "method": "vector_scaling", "t": ..., "b": [...] } }
```

`load_params`/`save_params` round-trip it (absent key ⇒ `null`).

In `generate_predictions`, when `wdl_blend` is non-null:
1. Train `WdlBoost` **in-process** on the leak-free rows the refresh already replays.
2. For each upcoming match, compute the §2 feature vector and the booster's W/D/L.
3. `blend = weight·HGB + (1−weight)·Poisson` (the served-params W/D/L), then apply
   `wdl_blend.calibrator` via the shared `calibrate()` helper.
4. Write the blended W/D/L to the card / payload.

When `wdl_blend` is `null`, none of the above runs — **zero added cost, zero behavior change.**

### 6. Persistence — train-on-refresh, no committed artifact

The booster is **retrained in-process on each refresh** from the same leak-free replay rows
the pipeline already builds. No model binary is committed: joblib pickles are brittle across
sklearn versions and bloat the repo, and refitting `HistGradientBoosting` on ~tens-of-thousands
× ~12 features is seconds. The only persisted state is the gate's verdict in
`model_params.json` (`wdl_blend` weight + calibrator, or `null`).

## Out of scope / Non-goals (YAGNI)

- **The live / in-play booster and its 12 features** (minute, score, shots, SoT, live xG,
  possession, corners, dangerous attacks, red/yellow cards, subs, live odds). Data-blocked as
  above; a separate track if/when an in-play snapshot training set is sourced or logged.
- **Betting odds** as a feature — also conflicts with PRD Decision #1 (odds never user-facing),
  and live odds would dominate/leak.
- **Scorelines, simulators, live win-prob** — unchanged; the booster never feeds them.
- **The `xgboost` package** — rejected in favor of the already-installed sklearn equivalent.
- **Committed model artifacts** — train-on-refresh instead.

## Testing (TDD)

1. **Leakage guard** — `build_training_rows`: the feature row for match *i* is unchanged when
   matches ≥ *i* are mutated/removed (it depends only on earlier matches).
2. **`WdlBoost` fit/predict** — output is a valid 3-simplex (sums to 1, all ≥ 0), deterministic
   under the fixed seed, and beats `BaseRateBaseline` log-loss on a chronological holdout.
3. **No-regression** — with `wdl_blend: null`, `generate_predictions` output is identical to
   the current pipeline (golden comparison).
4. **Blend math** — with a stub weight, the served W/D/L moves monotonically toward the booster
   as `weight → 1`, sums to 1, and the calibrator is applied.
5. **Params round-trip** — `ModelParams`/`model_params.json` round-trips `wdl_blend` through
   `save_params`/`load_params`; a JSON without the key loads as `null`.
6. **Gate wiring** — the booster/blend candidate runs end-to-end in `run_global_split` and
   produces an edition-clustered CI vs v0.1.

## Re-baseline note

If the blend ships, served W/D/L probabilities shift. Predicted-score and tournament sims are
unaffected (the booster never feeds the sampler/sims). Refresh the methodology page's model
section to describe the blend.

## Gate result (TBD)

To be appended after running `pipeline.experiment_model_eval` over the major-tournament
holdout — recording the bootstrap CI and the **ship / do-not-ship** decision, exactly like the
calibrator spec. If it does not clear, `model_params.json` keeps `"wdl_blend": null` and this
section documents why; the infrastructure stays in place for a future regime that clears.
