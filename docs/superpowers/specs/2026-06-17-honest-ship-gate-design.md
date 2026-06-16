# Honest Ship-Gate (roadmap lever #4) — design

**Date:** 2026-06-17
**Status:** Approved (design)
**Source:** multi-agent model audit (workflow `wf_da0a67c7-89d`), recommendation #4.

## Problem

The model's ship decisions ride on a paired bootstrap CI ("CI excludes 0 ⇒ significant"). But the bootstrap resamples **matches IID** ([experiment_model_eval.py:234](pipeline/experiment_model_eval.py) in `bootstrap_delta`, and again at line 290 in `run_global_split`). Matches within a tournament edition share era/host/opponent context, so IID resampling **understates variance** → the CI is too narrow → the gate green-lights noise. The calibration report pools equal-**width** ECE bins, which hides the known draw-class miscalibration. And the tuner can fit grid-corner params on an underpowered validation window with no guard.

This lever makes the measuring instrument honest **before** we use it to judge later levers (#3 odds prior, #2 calibration). It is pure eval/stats + reporting — **no change to served predictions**.

## Goal

Edition-clustered bootstrap CIs, a calibration report that surfaces draw-class miscalibration, and a tuner that refuses underpowered windows. Success = the same data yields **wider, honest CIs** (clustered ≥ IID), per-class/segment calibration is visible, and an underpowered window fails loudly.

## Design

### 1. Edition-clustered (block) bootstrap

`tournament_editions(rows, since_year)` ([experiment_model_eval.py:70](pipeline/experiment_model_eval.py)) already yields `(competition, year, rows)` editions. Use that grouping.

- Tag each per-match metric record with its **edition key** `(competition, year)` so the bootstrap can resample by edition.
- Add a helper `block_bootstrap_ci(per_match_values, edition_keys, n_boot, rng, pct=(2.5, 97.5))`: each of the `n_boot` iterations **resamples the set of editions with replacement**, pools the per-match values of the sampled editions, takes the mean, and the CI is the percentiles of those bootstrap means. (A whole-cluster block bootstrap — every sampled edition contributes *all* its matches; no partial editions.)
- Replace the IID resample in `bootstrap_delta` and in `run_global_split`'s `ci(metric)` with `block_bootstrap_ci`. The paired per-match delta (candidate − v0.1) is unchanged; only the resampling unit changes from match → edition.

### 2. Calibration report: equal-count bins + per-class ECE + segments

In `ml/evaluation/scoreline_metrics.py` (alongside the existing equal-width `expected_calibration_error`, line 104):
- `expected_calibration_error_equal_count(probs_list, labels, bins=10)` — **quantile bins** (each bin holds ~`n/bins` predictions) so sparse high-probability bins (where draws are systematically under-predicted) aren't washed out by equal-width pooling.
- `per_class_calibration_error(probs_list, labels, bins=10)` — ECE computed **per outcome class** (home / draw / away) and returned as a dict, since the draw class is the known pathology. Reuses the equal-count binning.
- Keep the existing equal-width `expected_calibration_error` unchanged (methodology-page continuity).

In the eval report (`run`/`main` in `experiment_model_eval.py`), add **segment slices** to the printed/returned output:
- **per-edition** (metric per `(competition, year)`),
- **by favorite-Elo-gap bucket** (e.g. 0-50 / 50-150 / 150-300 / 300+),
- **draw-vs-decisive** (actual draws vs decisive results).

### 3. Min-sample guard in the tuner

In `ml/evaluation/tune.py`: a named constant `MIN_VAL_MATCHES = 100`. `tune_params` (or `validation_window`) **raises `ValueError`** when its window has fewer than `MIN_VAL_MATCHES` rows — an underpowered window must fail loudly rather than return grid-corner params fit on noise. The threshold is a single tunable constant.

## Out of scope (YAGNI)

- No change to the served model, the simulators, or `model_params.json` values.
- No new metrics beyond equal-count/per-class ECE and the three segment slices.
- No change to the bootstrap percentile levels or `n_boot` defaults.

## Testing (TDD)

- **block bootstrap widens CIs:** on synthetic data with strong within-edition correlation, `block_bootstrap_ci` produces a **wider** interval than an IID resample of the same values; construct a case where the IID CI excludes 0 but the clustered CI covers 0.
- **whole-edition resampling:** every bootstrap draw is a union of complete editions (no partial-edition leakage); a single-edition dataset degenerates sanely.
- **equal-count ECE:** bins hold ~equal counts; a perfectly-calibrated input → ECE 0; `per_class_calibration_error` returns three classes and isolates an injected draw-class miscalibration that the pooled equal-width ECE misses.
- **min-sample guard:** a window with `< MIN_VAL_MATCHES` rows raises `ValueError`; at/above the threshold tuning proceeds.
- **report segments:** `run(...)` output contains the per-edition, favorite-gap, and draw-vs-decisive tables.

## Re-baseline note

CIs will get **wider** — some previously "significant" candidates may flip to not-significant. That is the correct, intended outcome (it protects against shipping noise). The methodology page / any doc quoting CI widths should be refreshed.
