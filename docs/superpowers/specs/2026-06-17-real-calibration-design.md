# Real Calibration (roadmap lever #2) — design

**Date:** 2026-06-17
**Status:** Approved (design)
**Source:** multi-agent model audit (`wf_da0a67c7-89d`), recommendation #2. Empirically
motivated by the #4 honest-gate smoke run: **draw-class ECE = 0.41** (vs 0.13 decisive).

## Problem

The calibration step ships **inert**: `model_params.json` has `temperature = 1.0`, so
`predict_match` applies no real calibration. And a single scalar temperature **cannot**
fix the actual pathology — it raises/softens all three W/D/L probabilities uniformly,
while the model's error is *shape*: the draw class is systematically under-predicted
(ECE 0.41). Fixing that needs a calibrator that can lift one class.

## Goal

A low-parameter calibrator on the W/D/L **card** that lifts the draw class, **fit on the
held-out data and shipped only if it clears the #4 edition-clustered gate** — otherwise the
model falls back to scalar temperature (no regression).

## Design

### 1. Vector-scaling calibrator (`ml/evaluation/calibration.py`)

Operate on the probability triple in log-space:

```
z_c  = log(max(eps, p_c))
z'_c = z_c / T + b_c        # shared temperature T, per-class bias b_c
p'_c = softmax(z')
```

- Parameters: shared `T` plus per-class bias `b = (b_home, b_draw, b_away)`. Softmax is
  shift-invariant, so fix `b_home = 0` as reference → **3 free params** (`T`, `b_draw`,
  `b_away`). The `b_draw` term is what lifts the under-predicted draw class.
- `apply_vector_scaling(probs, t, b)` — pure transform (mirrors the existing
  `apply_temperature`).
- `fit_vector_scaling(probs_list, labels)` — minimize validation log-loss by coordinate
  descent over `T` then `b_draw` then `b_away` (a few passes), each on a bounded grid
  (e.g. `T∈[0.5,3.0]`, `b∈[-1.5,1.5]`). Returns `(t, (b_home, b_draw, b_away))` with
  `b_home=0`. Keep `apply_temperature`/`fit_temperature` unchanged as the fallback.

### 2. One shared `calibrate()` helper, applied on the card path

- Extend `ModelParams` (`ml/models/params.py`) + `model_params.json` with a nullable
  `calibrator` blob: `{"method": "vector_scaling", "t": float, "b": [bh, bd, ba]}` or `None`.
  `load_params`/`save_params` round-trip it (default `None`).
- Add `calibrate(probs, params) -> Probs`: if `params.calibrator` is a vector-scaling blob,
  apply it; else fall back to `apply_temperature(probs, params.temperature)`.
- `predict_match` (the W/D/L card path) calls `calibrate(...)` exactly where it currently
  applies temperature. **Scoreline sampler and the Monte-Carlo sims are untouched** —
  calibration is on W/D/L triples, not single scorelines.

### 3. Fit on the regime it serves

Fit the calibrator on the leak-free walk-forward holdout, and **include group-stage rows**
(v0.2's goal params were finals-tuned but the model serves group matches). The calibrator
is fit on the SAME tuned engine the cards use (post-#1).

### 4. Gate before shipping (uses the #4 honest gate)

Add a `candidate_vector_scaling` to `pipeline/experiment_model_eval.py`'s `CANDIDATES`, so
it's scored alongside v0.1 and temperature-only. **Ship the calibrator only if**, under the
edition-clustered bootstrap (#4): its log-loss delta vs v0.1 has a **CI excluding 0
(better)**, AND `per_class_calibration_error` shows the **draw-class ECE drops** without the
overall W/D/L (log-loss/RPS) regressing. If it doesn't clear, write `calibrator = None`
(temperature-only) — guaranteed no regression.

## Out of scope (YAGNI)

- Per-class isotonic regression (overfits sparse high-prob bins — the audit flagged it).
- No change to the scoreline sampler, the simulators, or the served goal params
  (base/beta/rho/pk_beta/home_adv).
- This spec does NOT itself flip `temperature` to a fitted value in production; shipping a
  calibrator (vector scaling, which subsumes temperature) is the calibration we ship. The
  temperature-only path remains the fallback.

## Testing (TDD)

- `apply_vector_scaling`: identity at `T=1, b=0`; raising `b_draw` increases the draw
  probability and renormalizes; output sums to 1.
- `fit_vector_scaling`: on synthetic data where draws are under-predicted, the fit produces
  `b_draw > 0` and lowers log-loss vs the uncalibrated input and vs best scalar temperature;
  `per_class_calibration_error` for the draw class drops.
- `calibrate()`: with a vector-scaling blob applies it; with `calibrator=None` it equals
  `apply_temperature(probs, params.temperature)` (fallback parity).
- `ModelParams` round-trips the `calibrator` blob through `save_params`/`load_params`
  (and a JSON without the key loads as `None`).
- Gate wiring: `candidate_vector_scaling` runs in the eval harness and produces a
  clustered-CI delta vs v0.1.

## Re-baseline note

If the calibrator ships, served W/D/L probabilities shift (draws lift, big-favorite
over-confidence softens). Predicted-score and tournament sims are unaffected (sampler
untouched). The methodology page's calibration section should be refreshed.
