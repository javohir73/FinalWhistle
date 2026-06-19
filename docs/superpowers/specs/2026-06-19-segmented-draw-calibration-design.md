# Segment-conditional draw calibration — design

**Date:** 2026-06-19
**Status:** Approved (design) — pending spec review
**Source:** ML review follow-up. External review (Codex) flagged draws as the model's weakest
segment and suggested "draw-aware calibration by Elo-gap bucket, tournament type, and
neutral/host context." Global temperature/vector-scaling was already tried and shelved
(`calibrator: null` in v0.2). This is the **segmented** refinement of the calibrator we already
have — **not a new predictor.**

## Problem

The served Poisson+Elo engine under-predicts draws, and it does so **unevenly**: draws are far
more likely in close matchups than in mismatches. The existing calibrator
(`apply_vector_scaling`, with a per-class draw bias `b_draw`) can only apply **one global**
draw-lift, so it cannot lift draws where they're actually under-predicted without over-lifting
them where they aren't. Fit globally, it didn't beat the engine out-of-sample, so v0.2 ships
`calibrator: null`.

## Goal

A **segment-conditional** vector-scaling calibrator: the same `(t, b_draw, b_away)` machinery,
but with a separate fit per **effective-Elo-gap** bucket, so the draw-lift is strongest in close
matches and near-identity in blowouts. Fit offline, gated against shipped **v0.2** under the
existing edition-clustered bootstrap, and **promoted only if it beats v0.2 out-of-sample**. If it
doesn't clear the gate, `calibrator` stays `null` and production is byte-identical to today.

This is **calibration, not prediction** — it reshapes the W/D/L triple the engine already
produces. It adds no model, no new data source, and no new package.

## Design

### 1. Scope & boundary

- Acts **only on the served W/D/L triple** on the match card (the existing `calibrate()` step).
- **Untouched:** the scoreline grid, exact-score distribution, the group/bracket Monte-Carlo
  simulators, and the live win-probability bar — identical scope discipline to the booster.
- **Default = off.** `calibrator: null` ⇒ serving is byte-identical to today.

### 2. The segmentation key — *effective* Elo gap (not raw)

Bucket on the **effective** gap, i.e. the quantity the probability engine actually responds to:

```
diff = (elo_home + home_adv) - elo_away          # exactly poisson.py:51
eff_gap = abs(diff)
```

Raw `abs(pre_home - pre_away)` would mis-bucket host/home matches — a host-boosted "close"
matchup could be bucketed as not-close (or vice-versa), which is precisely the case (US/CA/MX
host matches) that matters for WC26.

**Parity rule (critical):** compute `eff_gap` from the **same `home_adv` the engine applied for
that match**, at the point of calibration ([poisson.py:200](../../../ml/models/poisson.py), where
`elo_home`, `elo_away`, and `home_adv` are all in scope). Do **not** recompute `home_adv`
independently. This makes train (gate) and serve use the identical bucket by construction:
- neutral match → `home_adv = 0`;
- normal home advantage → `home_adv = params.home_adv`;
- host match at serve → `home_adv = ±params.home_adv` (signed by `_host_adv`).

A train/serve parity test locks this (see Testing #6).

**Buckets:** reuse the existing four — `0-50`, `50-150`, `150-300`, `300+`
([experiment_model_eval.py:311](../../../pipeline/experiment_model_eval.py)). **Elo-gap only — no
cross with match-type**, to keep enough matches per cell (the test set is small; segmentation is
overfit-tempting territory).

**Shared helpers (single source of truth — prevents train/serve drift):** add two pure functions
to `ml/evaluation/calibration.py`, imported by *both* the gate (fit) and the engine (serve):

```python
def effective_gap(elo_home: float, elo_away: float, home_adv: float) -> float:
    return abs((elo_home + home_adv) - elo_away)

def gap_bucket(eff_gap: float) -> str:        # -> "0-50" | "50-150" | "150-300" | "300+"
    ...
```

Neither the gate nor the serving path may inline this logic; both call the helpers. The host
parity test (#6) asserts the two call sites land in the same bucket for the same inputs — which is
trivially true once both go through `gap_bucket(effective_gap(...))`.

### 3. Calibrator blob — backward-compatible extension

Reuse the `ModelParams.calibrator` field (already a nullable dict that `load/save_params`
round-trips). Add **one** new `method` value:

```jsonc
{
  "method": "vector_scaling_segmented",
  "by": "effective_elo_gap",
  "buckets": {
    "0-50":    {"t": .., "b": [0.0, b_draw, b_away]},
    "50-150":  {"t": .., "b": [0.0, b_draw, b_away]},
    "150-300": {"t": .., "b": [0.0, b_draw, b_away]},
    "300+":    {"t": .., "b": [0.0, b_draw, b_away]}
  },
  "default": {"t": .., "b": [0.0, b_draw, b_away]}   // fallback: sparse/unknown bucket, or eff_gap absent
}
```

`method: "vector_scaling"` (global) and `null` are **untouched** ⇒ existing behavior is provably
unchanged.

### 4. Serving wiring — one shared helper

Extend the single shared helper:

```python
calibrate(probs, calibrator, temperature=1.0, *, eff_gap: float | None = None) -> Probs
```

- `method == "vector_scaling_segmented"`: pick the bucket via `gap_bucket(eff_gap)`; if
  `eff_gap is None` **or** the resulting key is absent from `buckets`, use `"default"`. Apply
  `apply_vector_scaling` with that bucket's `(t, b)`.
- `method == "vector_scaling"` and `None`: **exactly today's behavior**; the new `eff_gap` arg is
  ignored. All existing call sites that don't pass `eff_gap` are unaffected.

Thread `eff_gap` from [poisson.py:200](../../../ml/models/poisson.py) using the in-scope
`elo_home + home_adv - elo_away`. The blend path
([generate_predictions.py:123](../../../pipeline/generate_predictions.py)) passes the same
`eff_gap` so a future shipped blend re-calibrates on the correct bucket too.

### 5. Fitting (offline, inside the gate)

- Build on the **served v0.2** engine (`load_params()`), not v0.1 — consistent with the booster
  gate fix.
- **No calibrator stacking.** Fit the segmented calibrator on the engine's **uncalibrated** v0.2
  triples — i.e. derive the base params as `replace(load_params(), calibrator=None)` so an
  existing (or future) shipped calibrator is *not* applied underneath the candidate. The candidate
  engine is `replace(v0.2, calibrator=<segmented blob>)` (calibrator **replaced, never stacked**),
  and the baseline is v0.2 exactly as shipped. Today v0.2 is `calibrator: null`, so base ==
  uncalibrated already; the `replace(..., calibrator=None)` makes that invariant explicit and
  future-proof.
- Fit on the held-out **tail** — the same tail/test split the booster gate uses (the years before
  the 2018 test cutoff), **all competitions** (calibration of the W/D/L mapping is general, not
  finals-only), and **never** overlapping the test set.
- **Domain-mismatch guard (the biggest subtle risk).** The tail is all-competitions but the test
  target is major finals. Emit diagnostics that (a) report per-bucket **counts and competition-tier
  composition** of the tail vs the test, and (b) if the finals-only tail clears `MIN_BUCKET` per
  bucket, **also** report the fit/performance restricted to finals as a sensitivity check. If the
  all-competitions and finals-only fits disagree sharply, prefer the more conservative outcome and
  flag it in the verdict rather than silently shipping the broader fit.
- Compute each tail row's `eff_gap` (reusing the engine's `home_adv`), partition into the four
  buckets.
- **Per bucket:** if it has `>= MIN_BUCKET` rows, fit `(t, b_draw, b_away)` with the existing
  `fit_vector_scaling` (fixed coordinate-descent grids, deterministic). Otherwise inherit the
  **global** fit (one `fit_vector_scaling` over all tail rows). The global fit is also written as
  `"default"`.
- `MIN_BUCKET = 200`. (Start conservative: the tail set is small and per-segment fitting is the
  main overfit risk; sparse buckets degrade gracefully to the global fit.)

### 6. The gate / ship decision

Add a gate candidate `"v0.2 + segmented-draw-cal"` that scores **segmented-cal-on-v0.2** against
**v0.2-alone** on 2018+ major finals with the existing **edition-clustered bootstrap**
(`block_bootstrap_ci`).

**Ship rule (mechanically gateable).** All deltas are `Δ = calibrated − v0.2-alone`, lower is
better for both metrics; both computed on the same paired test set with the edition-clustered
bootstrap.
- **Primary (must pass):** `logloss_delta_ci_upper < 0` — the 95% CI for Δlog-loss lies entirely
  below 0 (significantly better).
- **RPS guardrail (must pass):** `rps_delta <= RPS_TOL` with **`RPS_TOL = 1e-4`** — the RPS **point
  estimate** must not get meaningfully worse. (RPS is a do-no-harm guardrail, not a second
  objective; we don't require it to *improve*, only to not regress beyond float noise.) The RPS
  delta **CI is reported** for transparency but the gate is the point estimate vs `RPS_TOL`.
- Verdict is `SHIP` only if **both** pass; otherwise `do-not-ship` and `calibrator` stays `null`.

**Secondary (watch, not gate):** draw per-class ECE — report it so we can confirm the close-match
draw-lift behaves as intended, but it does **not** decide the ship.

If the rule isn't met → `calibrator` stays `null`, do-not-ship, production unchanged. Same
discipline as the calibrator and booster before it.

### 7. Diagnostics

- The gate prints, per bucket: `n`, fitted `(t, b_draw, b_away)` (or "→ global fallback"),
  base vs calibrated log-loss, and draw ECE.
- The chosen bucket name is surfaced in **eval/debug output only** (gate logs, the offline eval
  row) so we can inspect that close matches actually receive the larger draw-lift. **It does NOT
  change any API payload, DB schema, or the prediction card contract** — those are untouched unless
  we later decide, as a separate explicit task, to ship the bucket as public metadata.

### 8. Overfitting guards (the real risk)

- Coarse: 4 effective-gap buckets, **no** match-type cross.
- `MIN_BUCKET = 200` → global fallback for sparse buckets.
- Fixed grids + deterministic fit (inherited from `fit_vector_scaling`).
- Fit on the held-out tail, **never** on the test set; gate on test via the clustered bootstrap.

## Testing (TDD)

1. **Segmented dispatch** — `calibrate()` with a `vector_scaling_segmented` blob returns the
   bucket-specific result for a given `eff_gap`, and the **`default`** result when the bucket key
   is absent or `eff_gap is None`.
2. **Backward-compat golden** — with `method: "vector_scaling"` and with `None`, `calibrate()`
   output is identical to today, with and without the new `eff_gap` kwarg passed.
3. **Per-bucket fit beats global** — on a synthetic set where the draw rate varies by gap, the
   segmented fit achieves lower validation log-loss than a single global fit.
4. **Sparse fallback** — a bucket with `< MIN_BUCKET` rows inherits the global/`default` fit.
5. **Gate wiring** — the `v0.2 + segmented-draw-cal` candidate runs end-to-end, produces an
   edition-clustered CI, and yields `SHIP` only when the CI excludes 0 **and** RPS doesn't regress.
6. **Train/serve parity** — both the gate and the serving path bucket via the shared
   `gap_bucket(effective_gap(...))`; for a host match (non-neutral, `host_team` set) they land in
   the same bucket for the same `(elo_home, elo_away, home_adv)`, and a raw-`abs(elo_home -
   elo_away)` bucketing would pick a *different* bucket (guard test proving the host correction
   matters).
7. **No-regression** — with `calibrator: null`, `generate_predictions` output is byte-identical
   (reuse the existing golden comparison).
8. **No calibrator stacking** — the candidate built from a v0.2 that *already* carries a (global)
   calibrator fits on the **uncalibrated** triples (`replace(..., calibrator=None)`) and replaces
   the calibrator; the fitted blob is identical to the one fit from a `calibrator: null` v0.2
   (i.e. the existing calibrator is not applied underneath).

## Non-goals (YAGNI)

- **Segmented calibration inside `wdl_blend.calibrator`.** This project fits & gates a segmented
  calibrator for **`ModelParams.calibrator` only** — the pre-blend W/D/L path. The booster's own
  `wdl_blend.calibrator` stays **global-only** and is out of scope (production is `wdl_blend: null`
  anyway, so the blend path is dormant). The shared `calibrate()` helper is generic, so the blend
  path *can* pass `eff_gap` and a future segmented blend-calibrator could be fit later — but we do
  **not** fit or gate one here. Stacking order is unchanged: `ModelParams.calibrator` (now possibly
  segmented) applies to the Poisson triple; the blend, when enabled, applies its own calibrator
  afterward as today.
- **Match-type / neutral-host as additional segmentation axes** — Elo-gap only for v1 (data
  budget per cell). Effective-gap already folds in the host effect via `home_adv`.
- **Grid-level draw-inflation** (per-segment `gamma`) and a **standalone draw-residual model** —
  considered and rejected (touch scorelines/sims, or reintroduce a new predictor to gate).
- **Scorelines, simulators, live win-prob** — unchanged; calibration never feeds them.
- **New data or packages** — none.

## Re-baseline note

If the segmented calibrator ships, served W/D/L probabilities shift (mostly draws in close
matches). Predicted scorelines and tournament sims are unaffected (calibration never feeds the
sampler/sims). Refresh the methodology page's calibration section to describe the segmented
calibrator and show the per-bucket reliability.
