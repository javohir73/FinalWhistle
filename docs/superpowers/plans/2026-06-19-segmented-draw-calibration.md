# Segment-Conditional Draw Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a draw-aware calibrator that fits a separate vector-scaling `(t, b_draw, b_away)` per *effective-Elo-gap* bucket, gated against shipped v0.2, shipping only if it beats v0.2 out-of-sample (log-loss CI excludes 0 and no RPS regression).

**Architecture:** Extend the existing single calibrator helper (`ml/evaluation/calibration.py`) with two pure helpers (`effective_gap`, `gap_bucket`), a segmented blob format dispatched inside `calibrate()`, and a per-bucket fitter. Thread the effective gap into the two calibrate call sites (serving `predict_match` and eval `wdl_and_grid`). Add an honest gate (`run_draw_cal_gate`) mirroring the booster gate. Production stays `calibrator: null` unless the gate clears.

**Tech Stack:** Python 3.12, pytest, numpy. No new packages. Run tests with `PYTHONPATH=backend:. .venv/bin/python -m pytest <path> -q`.

**Spec:** `docs/superpowers/specs/2026-06-19-segmented-draw-calibration-design.md`

---

## File Structure

- `ml/evaluation/calibration.py` — **modify.** Add `effective_gap()`, `gap_bucket()`, `fit_segmented_vector_scaling()`; extend `calibrate()` with a keyword-only `eff_gap` and segmented dispatch. Responsibility: all calibration math, one source of truth for bucketing.
- `ml/evaluation/calibration_test.py` — **modify.** Tests for the new helpers, segmented dispatch, backward-compat, and the fitter.
- `ml/models/poisson.py` — **modify.** `predict_match()` threads `eff_gap` into its `calibrate()` call (serving path).
- `ml/models/poisson_test.py` — **modify (or create test fn).** Serving threads the bucket.
- `pipeline/experiment_model_eval.py` — **modify.** Add `_eval_adv()` helper; thread `eff_gap` into `wdl_and_grid`'s `calibrate()`; add `run_draw_cal_gate()`; wire it into `main()`.
- `pipeline/experiment_model_eval_gate_test.py` — **modify.** Smoke test for `run_draw_cal_gate`.
- `ml/models/params_test.py` — **modify.** Round-trip a segmented calibrator blob.

---

## Task 1: Shared bucketing helpers

**Files:**
- Modify: `ml/evaluation/calibration.py`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `ml/evaluation/calibration_test.py` (and add `effective_gap, gap_bucket` to the existing import block at the top of the file):

```python
def test_effective_gap_uses_home_adv():
    # The engine responds to (elo_home + home_adv) - elo_away, so the gap must too.
    from ml.evaluation.calibration import effective_gap
    # Home 50 below away, but +60 home_adv -> effectively +10, a *close* match.
    assert effective_gap(1450.0, 1500.0, 60.0) == 10.0
    # Neutral (adv 0) -> raw gap.
    assert effective_gap(1450.0, 1500.0, 0.0) == 50.0
    # Away is host (signed -adv) widens an already-away-favored gap.
    assert effective_gap(1500.0, 1450.0, -60.0) == 10.0


def test_gap_bucket_boundaries():
    from ml.evaluation.calibration import gap_bucket
    assert gap_bucket(0.0) == "0-50"
    assert gap_bucket(50.0) == "50-150"      # lower edge is exclusive of prior bucket
    assert gap_bucket(149.9) == "50-150"
    assert gap_bucket(150.0) == "150-300"
    assert gap_bucket(299.9) == "150-300"
    assert gap_bucket(300.0) == "300+"
    assert gap_bucket(9999.0) == "300+"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py::test_effective_gap_uses_home_adv ml/evaluation/calibration_test.py::test_gap_bucket_boundaries -q`
Expected: FAIL with `ImportError: cannot import name 'effective_gap'`.

- [ ] **Step 3: Implement the helpers**

Add near the top of `ml/evaluation/calibration.py` (after the `_EPS` line, before `apply_temperature`):

```python
# Effective-Elo-gap segmentation for draw-aware calibration. The probability
# engine responds to (elo_home + home_adv) - elo_away (see poisson.py
# expected_goals_from_elo), so the calibrator buckets on that, NOT the raw gap —
# otherwise a host-boosted close match is mis-bucketed. Both the gate (fit) and
# the serving path bucket through these two helpers, so they cannot drift.
_GAP_EDGES = (50.0, 150.0, 300.0)
_GAP_BUCKETS = ("0-50", "50-150", "150-300", "300+")


def effective_gap(elo_home: float, elo_away: float, home_adv: float) -> float:
    """Absolute effective Elo gap the engine actually responds to."""
    return abs((elo_home + home_adv) - elo_away)


def gap_bucket(eff_gap: float) -> str:
    """Map an effective gap to one of the four coarse buckets."""
    for edge, name in zip(_GAP_EDGES, _GAP_BUCKETS):
        if eff_gap < edge:
            return name
    return _GAP_BUCKETS[-1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py -q`
Expected: PASS (all calibration tests).

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): effective-gap bucketing helpers for draw calibration"
```

---

## Task 2: Segmented dispatch in `calibrate()` (backward-compatible)

**Files:**
- Modify: `ml/evaluation/calibration.py:calibrate`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `ml/evaluation/calibration_test.py`:

```python
def _segmented_blob():
    # Big draw lift in close matches, identity in blowouts.
    return {
        "method": "vector_scaling_segmented",
        "by": "effective_elo_gap",
        "buckets": {
            "0-50":   {"t": 1.0, "b": [0.0, 1.0, 0.0]},   # lift draw strongly
            "300+":   {"t": 1.0, "b": [0.0, 0.0, 0.0]},   # identity
        },
        "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},      # identity
    }


def test_segmented_picks_bucket_by_eff_gap():
    p = (0.45, 0.20, 0.35)
    close = calibrate(p, _segmented_blob(), eff_gap=10.0)    # -> 0-50 bucket
    blowout = calibrate(p, _segmented_blob(), eff_gap=500.0)  # -> 300+ (identity)
    assert close[1] > p[1]                       # draw lifted in close match
    assert all(abs(a - b) < 1e-9 for a, b in zip(blowout, p))  # identity in blowout


def test_segmented_falls_back_to_default():
    p = (0.45, 0.20, 0.35)
    # Bucket "50-150" is absent from the blob -> use default (identity).
    mid = calibrate(p, _segmented_blob(), eff_gap=100.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(mid, p))
    # eff_gap omitted entirely -> also default.
    none_gap = calibrate(p, _segmented_blob())
    assert all(abs(a - b) < 1e-9 for a, b in zip(none_gap, p))


def test_global_and_none_ignore_eff_gap():
    # Backward-compat: passing eff_gap must not change global/None behavior.
    p = (0.6, 0.25, 0.15)
    glob = {"method": "vector_scaling", "t": 1.2, "b": [0.0, 0.3, -0.1]}
    assert calibrate(p, glob) == calibrate(p, glob, eff_gap=10.0)
    assert calibrate(p, None) == calibrate(p, None, eff_gap=10.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py::test_segmented_picks_bucket_by_eff_gap -q`
Expected: FAIL with `TypeError: calibrate() got an unexpected keyword argument 'eff_gap'`.

- [ ] **Step 3: Extend `calibrate()`**

Replace the existing `calibrate()` function in `ml/evaluation/calibration.py` with:

```python
def calibrate(probs: Probs, calibrator: dict | None, temperature: float = 1.0,
              *, eff_gap: float | None = None) -> Probs:
    """Apply the shipped calibrator to a W/D/L triple — the one shared helper for
    the card path. `calibrator` is one of:
      - None: scalar `temperature` fallback (t=1 is the identity);
      - {"method": "vector_scaling", "t", "b"}: one global vector scaling;
      - {"method": "vector_scaling_segmented", "buckets": {bucket: {t,b}}, "default": {t,b}}:
        per effective-Elo-gap bucket. `eff_gap` selects the bucket via gap_bucket();
        a missing bucket or a None eff_gap falls back to "default".
    The global and None paths ignore `eff_gap`, so existing callers are unchanged."""
    if calibrator and calibrator.get("method") == "vector_scaling_segmented":
        key = gap_bucket(eff_gap) if eff_gap is not None else None
        cell = calibrator["buckets"].get(key) if key is not None else None
        if cell is None:
            cell = calibrator["default"]
        return apply_vector_scaling(probs, cell["t"], tuple(cell["b"]))
    if calibrator and calibrator.get("method") == "vector_scaling":
        return apply_vector_scaling(probs, calibrator["t"], tuple(calibrator["b"]))
    return apply_temperature(probs, temperature)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): segmented vector-scaling dispatch in calibrate()"
```

---

## Task 3: Per-bucket fitter `fit_segmented_vector_scaling()`

**Files:**
- Modify: `ml/evaluation/calibration.py`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `ml/evaluation/calibration_test.py`:

```python
def _draw_varying_dataset():
    """Synthetic: close matches (gap ~10) draw far more often than blowouts
    (gap ~400). Uncalibrated probs under-state the draw in close matches."""
    probs, labels, gaps = [], [], []
    for _ in range(600):
        probs.append((0.40, 0.20, 0.40)); labels.append(1); gaps.append(10.0)   # close -> draw
    for _ in range(600):
        probs.append((0.40, 0.20, 0.40)); labels.append(0); gaps.append(10.0)   # close -> home
    for _ in range(600):
        probs.append((0.80, 0.12, 0.08)); labels.append(0); gaps.append(400.0)  # blowout -> home
    return probs, labels, gaps


def test_fit_segmented_beats_global_logloss():
    from ml.evaluation.calibration import fit_segmented_vector_scaling, _log_loss
    probs, labels, gaps = _draw_varying_dataset()
    blob = fit_segmented_vector_scaling(probs, labels, gaps, min_bucket=200)
    assert blob["method"] == "vector_scaling_segmented"
    seg = [calibrate(p, blob, eff_gap=g) for p, g in zip(probs, gaps)]
    t, b = fit_vector_scaling(probs, labels)
    glob_blob = {"method": "vector_scaling", "t": t, "b": list(b)}
    glob = [calibrate(p, glob_blob) for p in probs]
    assert _log_loss(seg, labels) < _log_loss(glob, labels)


def test_fit_segmented_sparse_bucket_uses_default():
    from ml.evaluation.calibration import fit_segmented_vector_scaling
    probs, labels, gaps = _draw_varying_dataset()
    # Add 5 mid-gap rows -> "50-150" is below min_bucket and must equal default.
    probs += [(0.5, 0.2, 0.3)] * 5
    labels += [1] * 5
    gaps += [100.0] * 5
    blob = fit_segmented_vector_scaling(probs, labels, gaps, min_bucket=200)
    assert blob["buckets"].get("50-150", blob["default"]) == blob["default"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py::test_fit_segmented_beats_global_logloss -q`
Expected: FAIL with `ImportError: cannot import name 'fit_segmented_vector_scaling'`.

- [ ] **Step 3: Implement the fitter**

Add to `ml/evaluation/calibration.py` (after `fit_vector_scaling`):

```python
def fit_segmented_vector_scaling(
    probs_list: list[Probs],
    labels: list[int],
    eff_gaps: list[float],
    min_bucket: int = 200,
) -> dict:
    """Fit one vector-scaling (t, b_draw, b_away) per effective-gap bucket.

    A global fit over all rows is always computed and stored as "default"; any
    bucket with fewer than `min_bucket` rows inherits it (sparse buckets degrade
    gracefully instead of over-fitting). Returns a vector_scaling_segmented blob."""
    gt, gb = fit_vector_scaling(probs_list, labels)
    default = {"t": gt, "b": list(gb)}

    by_bucket: dict[str, list[int]] = {}
    for i, g in enumerate(eff_gaps):
        by_bucket.setdefault(gap_bucket(g), []).append(i)

    buckets: dict[str, dict] = {}
    for name in _GAP_BUCKETS:
        ix = by_bucket.get(name, [])
        if len(ix) >= min_bucket:
            t, b = fit_vector_scaling([probs_list[i] for i in ix], [labels[i] for i in ix])
            buckets[name] = {"t": t, "b": list(b)}
        else:
            buckets[name] = default
    return {
        "method": "vector_scaling_segmented",
        "by": "effective_elo_gap",
        "buckets": buckets,
        "default": default,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/evaluation/calibration_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): per-bucket segmented vector-scaling fitter"
```

---

## Task 4: Thread `eff_gap` into the serving path (`predict_match`)

**Files:**
- Modify: `ml/models/poisson.py:predict_match`
- Test: `ml/models/poisson_test.py`

- [ ] **Step 1: Write the failing test**

Add to `ml/models/poisson_test.py` (match the file's existing import style for `predict_match`):

```python
def test_predict_match_threads_eff_gap_to_segmented_calibrator():
    from ml.models.poisson import predict_match
    # Segmented blob: lift draw only in the 0-50 bucket, identity elsewhere.
    blob = {
        "method": "vector_scaling_segmented", "by": "effective_elo_gap",
        "buckets": {"0-50": {"t": 1.0, "b": [0.0, 1.0, 0.0]}},
        "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},
    }
    # Same raw ratings; home_adv pulls the effective gap into the 0-50 bucket.
    close = predict_match(1450.0, 1500.0, home_adv=60.0, calibrator=blob)   # eff gap 10
    far = predict_match(1450.0, 1500.0, home_adv=0.0, calibrator=blob)      # eff gap 50 -> not 0-50
    assert close.prob_draw > far.prob_draw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/models/poisson_test.py::test_predict_match_threads_eff_gap_to_segmented_calibrator -q`
Expected: FAIL — both draws equal (eff_gap not threaded; segmented falls back to default for both).

- [ ] **Step 3: Thread the gap**

In `ml/models/poisson.py`, in `predict_match`, change the calibrate line. Find:

```python
    p_home, p_draw, p_away = calibrate((p_home, p_draw, p_away), calibrator, temperature)
```

Replace with:

```python
    eff_gap = effective_gap(elo_home, elo_away, home_adv)
    p_home, p_draw, p_away = calibrate((p_home, p_draw, p_away), calibrator, temperature, eff_gap=eff_gap)
```

And update the import at the top of `ml/models/poisson.py`. Find:

```python
from ml.evaluation.calibration import apply_temperature, calibrate
```

Replace with:

```python
from ml.evaluation.calibration import apply_temperature, calibrate, effective_gap
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/models/poisson_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/models/poisson.py ml/models/poisson_test.py
git commit -m "feat(ml): thread effective gap into served calibration"
```

---

## Task 5: Thread `eff_gap` into the eval path (`wdl_and_grid`) + `_eval_adv` helper

**Files:**
- Modify: `pipeline/experiment_model_eval.py:wdl_and_grid`
- Test: `pipeline/experiment_model_eval_gate_test.py`

- [ ] **Step 1: Write the failing test**

Add to `pipeline/experiment_model_eval_gate_test.py`:

```python
def test_wdl_and_grid_threads_eff_gap():
    from dataclasses import replace
    from pipeline.experiment_model_eval import wdl_and_grid
    from ml.models.params import load_params
    blob = {
        "method": "vector_scaling_segmented", "by": "effective_elo_gap",
        "buckets": {"0-50": {"t": 1.0, "b": [0.0, 1.0, 0.0]}},
        "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},
    }
    params = replace(load_params(), calibrator=blob)
    # Non-neutral so home_adv applies: 1450 vs 1500 + adv pulls eff gap into 0-50.
    close, _ = wdl_and_grid(1450.0, 1500.0, False, params)
    # Neutral (adv 0): eff gap 50 -> outside 0-50 -> default identity.
    far, _ = wdl_and_grid(1450.0, 1500.0, True, params)
    assert close[1] > far[1]   # draw lifted only when effectively close
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py::test_wdl_and_grid_threads_eff_gap -q`
Expected: FAIL — draws equal (eff_gap not threaded).

- [ ] **Step 3: Add `_eval_adv` and thread the gap**

In `pipeline/experiment_model_eval.py`, update the calibration import. Find:

```python
from ml.evaluation.calibration import calibrate, fit_temperature, fit_vector_scaling
```

Replace with:

```python
from ml.evaluation.calibration import (
    calibrate, effective_gap, fit_segmented_vector_scaling, fit_temperature,
    fit_vector_scaling, gap_bucket,
)
```

Add this helper immediately before `def wdl_and_grid(`:

```python
def _eval_adv(is_neutral, params: ModelParams) -> float:
    """The home advantage the eval engine applies — 0 at a neutral site, else the
    params' home_adv. Single source so bucketing matches the engine exactly."""
    return 0.0 if is_neutral else params.home_adv
```

In `wdl_and_grid`, replace the body's advantage + calibrate lines. Find:

```python
    adv = 0.0 if is_neutral else params.home_adv
    lam_h, lam_a = expected_goals_from_elo(pre_home, pre_away, adv, params.base, params.beta)
```

Replace with:

```python
    adv = _eval_adv(is_neutral, params)
    lam_h, lam_a = expected_goals_from_elo(pre_home, pre_away, adv, params.base, params.beta)
```

Then find:

```python
    wdl = outcome_probabilities(grid)
    wdl = calibrate(wdl, params.calibrator, params.temperature)
    return wdl, grid
```

Replace with:

```python
    wdl = outcome_probabilities(grid)
    eff_gap = effective_gap(pre_home, pre_away, adv)
    wdl = calibrate(wdl, params.calibrator, params.temperature, eff_gap=eff_gap)
    return wdl, grid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_gate_test.py
git commit -m "feat(ml): thread effective gap into eval calibration path"
```

---

## Task 6: The gate `run_draw_cal_gate()`

**Files:**
- Modify: `pipeline/experiment_model_eval.py`
- Test: `pipeline/experiment_model_eval_gate_test.py`

- [ ] **Step 1: Write the failing smoke test**

Add to `pipeline/experiment_model_eval_gate_test.py` (reuses the `_rows()` builder already in that file):

```python
def test_draw_cal_gate_runs_and_reports_a_verdict():
    from pipeline.experiment_model_eval import run_draw_cal_gate
    res = run_draw_cal_gate(_rows(), tail_years=2, test_since=2018, n_boot=50, min_bucket=20)
    assert res["served_version"] == "poisson-elo-v0.2"
    assert "base_log_loss" in res and "cal_log_loss" in res
    assert "delta_log_loss" in res and "ll_ci" in res and len(res["ll_ci"]) == 2
    assert "delta_rps" in res
    assert "bucket_counts" in res and set(res["bucket_counts"]) <= {"0-50", "50-150", "150-300", "300+"}
    assert res["test_n"] > 0
    assert res["verdict"] in ("SHIP", "do-not-ship")
    # Mechanical ship rule: SHIP iff log-loss CI upper < 0 AND rps not worse than tol.
    expect_ship = res["ll_ci"][1] < 0 and res["delta_rps"] <= res["rps_tol"]
    assert (res["verdict"] == "SHIP") == expect_ship
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py::test_draw_cal_gate_runs_and_reports_a_verdict -q`
Expected: FAIL with `ImportError: cannot import name 'run_draw_cal_gate'`.

- [ ] **Step 3: Implement the gate**

Add to `pipeline/experiment_model_eval.py`, immediately after `run_blend_gate`. Prerequisites to confirm/add to the top-of-file imports: `gap_bucket` (added in Task 5's calibration import block); `ranked_probability_score` (add to the `from ml.evaluation.scoreline_metrics import (...)` block if absent); and `from dataclasses import replace`.

```python
_RPS_TOL = 1e-4  # RPS may not get worse than this on the point estimate (do-no-harm guardrail)


def run_draw_cal_gate(rows: list[dict], tail_years: int = 2, test_since: int = 2018,
                      n_boot: int = 2000, min_bucket: int = 200,
                      served_params: ModelParams | None = None) -> dict:
    """Honest ship test for the segment-conditional draw calibrator.

    Fit per-effective-gap vector scaling on the held-out tail (all competitions,
    uncalibrated v0.2 triples — no calibrator stacking), then score the
    segmented-calibrated engine vs v0.2-alone on test_since+ major finals with the
    edition-clustered bootstrap. SHIP only if the log-loss CI excludes 0 (better)
    AND RPS does not regress beyond _RPS_TOL.
    """
    served = served_params if served_params is not None else load_params()
    base_params = replace(served, calibrator=None)   # uncalibrated triples for FITTING

    test_start = date(test_since, 1, 1)
    tail_start = date(test_since - tail_years, 1, 1)
    tail = [r for r in rows if tail_start <= r["date"] < test_start]
    test = [r for r in rows
            if r["date"].year >= test_since and is_major_final(r["competition"])]

    # Fit on uncalibrated tail triples, bucketed by the same effective gap the
    # engine uses (via _eval_adv -> effective_gap), so fit and serve agree.
    tail_probs, tail_labels, tail_gaps = [], [], []
    bucket_counts: dict[str, int] = {b: 0 for b in ("0-50", "50-150", "150-300", "300+")}
    for r in tail:
        wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], base_params)
        g = effective_gap(r["pre_home"], r["pre_away"], _eval_adv(r["is_neutral"], base_params))
        tail_probs.append(wdl)
        tail_labels.append(_LABEL_INDEX[result_label(r["score_home"], r["score_away"])])
        tail_gaps.append(g)
        bucket_counts[gap_bucket(g)] += 1

    blob = (fit_segmented_vector_scaling(tail_probs, tail_labels, tail_gaps, min_bucket=min_bucket)
            if tail_probs else None)
    cand_params = replace(served, calibrator=blob)

    base_ll, cal_ll, base_rps, cal_rps, ed_keys = [], [], [], [], []
    for r in test:
        idx = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
        b_wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], served)
        c_wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], cand_params)
        base_ll.append(-math.log(max(_EPS, min(1 - _EPS, b_wdl[idx]))))
        cal_ll.append(-math.log(max(_EPS, min(1 - _EPS, c_wdl[idx]))))
        base_rps.append(ranked_probability_score(b_wdl, idx))
        cal_rps.append(ranked_probability_score(c_wdl, idx))
        ed_keys.append((r["competition"], r["date"].year))

    rng = np.random.default_rng(2026)
    d_ll = np.array(cal_ll) - np.array(base_ll)
    ci = block_bootstrap_ci(d_ll, ed_keys, n_boot, rng) if len(d_ll) else (0.0, 0.0)
    d_rps = float(np.mean(cal_rps) - np.mean(base_rps)) if cal_rps else 0.0

    ship = bool(len(d_ll) and ci[1] < 0 and d_rps <= _RPS_TOL)
    return {
        "served_version": served.version,
        "calibrator": blob,
        "tail_n": len(tail), "test_n": len(test),
        "bucket_counts": bucket_counts,
        "base_log_loss": float(np.mean(base_ll)) if base_ll else 0.0,
        "cal_log_loss": float(np.mean(cal_ll)) if cal_ll else 0.0,
        "delta_log_loss": float(d_ll.mean()) if len(d_ll) else 0.0,
        "ll_ci": ci,
        "delta_rps": d_rps,
        "rps_tol": _RPS_TOL,
        "verdict": "SHIP" if ship else "do-not-ship",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_gate_test.py
git commit -m "feat(ml): honest gate for segment-conditional draw calibration"
```

---

## Task 7: Params round-trip + wire gate into `main()`

**Files:**
- Modify: `ml/models/params_test.py`
- Modify: `pipeline/experiment_model_eval.py:main`

- [ ] **Step 1: Write the failing params round-trip test**

Add to `ml/models/params_test.py` (match the file's existing import/style):

```python
def test_segmented_calibrator_round_trips(tmp_path, monkeypatch):
    import ml.models.params as P
    from ml.models.params import ModelParams, save_params, load_params
    monkeypatch.setattr(P, "_PARAMS_FILE", tmp_path / "model_params.json")
    blob = {
        "method": "vector_scaling_segmented", "by": "effective_elo_gap",
        "buckets": {"0-50": {"t": 1.1, "b": [0.0, 0.4, -0.1]}},
        "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},
    }
    params = ModelParams(version="t", base=1.2, beta=0.0021, home_adv=60.0,
                         rho=-0.06, temperature=1.0, calibrator=blob)
    save_params(params)
    assert load_params().calibrator == blob
```

- [ ] **Step 2: Run test to verify it passes (or fails meaningfully)**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest ml/models/params_test.py::test_segmented_calibrator_round_trips -q`
Expected: PASS (the `calibrator` field already round-trips arbitrary dicts; this test locks that contract for the segmented blob). If the monkeypatch attribute name differs, align it with how `params.py` names the file constant (`_PARAMS_FILE`).

- [ ] **Step 3: Wire the gate into `main()`**

In `pipeline/experiment_model_eval.py`, in `main()`, find the booster-gate print block (ends with the SHIP-blob print) and add immediately after it:

```python
    print("\n==== Segmented draw-calibration gate ====")
    dg = run_draw_cal_gate(rows, n_boot=args.boot)
    print(f"  served={dg['served_version']}  tail_n={dg['tail_n']} test_n={dg['test_n']}")
    print(f"  bucket_counts={dg['bucket_counts']}")
    print(f"  base_logloss={dg['base_log_loss']:.4f}  cal_logloss={dg['cal_log_loss']:.4f}")
    print(f"  d_logloss={dg['delta_log_loss']:+.4f}  CI[{dg['ll_ci'][0]:+.4f},{dg['ll_ci'][1]:+.4f}]"
          f"  d_rps={dg['delta_rps']:+.5f} (tol {dg['rps_tol']})  -> {dg['verdict']}")
    if dg["verdict"] == "SHIP":
        blob = json.dumps(dg["calibrator"])
        print(f"  SHIP blob (paste into model_params.json -> calibrator): {blob}")
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest -q`
Expected: PASS (all tests, e.g. `353+ passed`).

- [ ] **Step 5: Commit**

```bash
git add ml/models/params_test.py pipeline/experiment_model_eval.py
git commit -m "feat(ml): params round-trip + main() wiring for draw-cal gate"
```

---

## Task 8: Run the gate on real data and record the verdict

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-segmented-draw-calibration-design.md` (append a Gate result section)

- [ ] **Step 1: Run the gate end-to-end on the historical dataset**

Create `/tmp/run_draw_cal_gate.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
import app.models  # noqa: F401
import json
from pipeline.backtest_data import build_enriched_rows
from pipeline.ingest.historical_results import download_results_df, load_historical
from pipeline.experiment_model_eval import run_draw_cal_gate

engine = create_engine("sqlite://", future=True)
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine, future=True)()
load_historical(db, download_results_df())
rows = build_enriched_rows(db)
print(f"rows={len(rows)}")
res = run_draw_cal_gate(rows, n_boot=2000)
print(json.dumps(res, indent=2, default=str))
```

Run: `PYTHONPATH=backend:. .venv/bin/python /tmp/run_draw_cal_gate.py`
Expected: prints `served_version=poisson-elo-v0.2`, per-bucket counts, base/cal log-loss, delta + CI, delta_rps, and a verdict. (Requires network to download the results CSV.)

- [ ] **Step 2: Record the verdict honestly**

Append a `## Gate result (YYYY-MM-DD)` section to the spec with the printed numbers, mirroring the booster verdict doc: bucket counts/composition, base vs cal log-loss, Δlog-loss + CI, Δrps vs tol, and the SHIP/do-not-ship decision. If `do-not-ship`, state that `model_params.json` keeps `calibrator: null` and the infrastructure stays in place. If `SHIP`, note the blob is ready to paste but **do not modify `model_params.json` without explicit user sign-off** (it changes served probabilities).

- [ ] **Step 3: Clean up and commit the verdict**

```bash
rm -f /tmp/run_draw_cal_gate.py
git add docs/superpowers/specs/2026-06-19-segmented-draw-calibration-design.md
git commit -m "docs(ml): record segmented draw-calibration gate verdict"
```

---

## Self-Review Notes (author)

- **Spec coverage:** helpers (T1), segmented dispatch + backward-compat (T2), fitter + sparse fallback (T3), serving thread (T4), eval thread + parity helper (T5), gate with no-stacking/RPS-guardrail/bucket diagnostics (T6), params round-trip + main wiring (T7), real-data run + verdict (T8). Draw-ECE "watch" is reported via base/cal draw behavior in the run output; if a numeric draw-ECE field is wanted, add it to the gate dict in T6 using the existing `per_class_calibration_error` (check its signature first).
- **No `model_params.json` write** is included by design — shipping is a separate, user-approved step.
- **Type consistency:** blob shape `{"method","by","buckets":{name:{"t","b"}},"default":{"t","b"}}` is identical across T2/T3/T6/T7; `calibrate(probs, calibrator, temperature=1.0, *, eff_gap=None)` used consistently; `gap_bucket`/`effective_gap`/`fit_segmented_vector_scaling` names match across tasks.
