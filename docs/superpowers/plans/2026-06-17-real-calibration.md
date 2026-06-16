# Real Calibration (roadmap lever #2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a low-parameter vector-scaling calibrator on the W/D/L card path that can lift the under-predicted draw class, shipped only behind the #4 edition-clustered gate (temperature fallback otherwise — no regression).

**Architecture:** A pure log-space vector-scaling transform (`apply_vector_scaling`) plus a coordinate-descent fitter (`fit_vector_scaling`) live in `ml/evaluation/calibration.py`. A single shared dispatcher `calibrate(probs, calibrator, temperature)` applies the vector-scaling blob when present and falls back to scalar temperature otherwise. `predict_match` (the card path) routes its W/D/L triple through `calibrate`; the scoreline sampler and Monte-Carlo sims are untouched. `ModelParams` + `model_params.json` carry a nullable `calibrator` blob. The eval harness gains a `candidate_vector_scaling` and a per-class ECE column so the gate can be run.

**Tech Stack:** Python 3, `pytest` (tests live alongside code as `*_test.py`; `pytest.ini` sets `pythonpath = backend .` and `testpaths = backend ml pipeline`). No new dependencies.

**Import-cycle note (read before Task 3/5):** `ml/models/params.py` imports `ml/models/poisson.py` (for `BASE_GOALS`/`ELO_TO_GOALS_BETA`), so `poisson.py` must **not** import `params.py`. Therefore the shared helper is `calibrate(probs, calibrator, temperature)` taking **primitives** (the blob + a temperature fallback), living in `calibration.py` (which imports nothing internal). This is a deliberate refinement of the spec's `calibrate(probs, params)` signature — same single helper, same temperature-fallback semantics, primitive args to dodge the `poisson ↔ params` cycle. `build_payload` already holds a `ModelParams`, so it passes `params.calibrator` and `params.temperature` through to `predict_match`.

---

### Task 1: `apply_vector_scaling` — pure log-space transform

**Files:**
- Modify: `ml/evaluation/calibration.py`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `ml/evaluation/calibration_test.py` (extend the existing import line and append the tests):

```python
from ml.evaluation.calibration import (
    apply_temperature,
    apply_vector_scaling,
    fit_temperature,
    reliability_curve,
)


def test_vector_scaling_identity_at_t1_b0():
    p = (0.6, 0.3, 0.1)
    out = apply_vector_scaling(p, 1.0, (0.0, 0.0, 0.0))
    assert all(abs(a - b) < 1e-9 for a, b in zip(out, p))
    assert abs(sum(out) - 1.0) < 1e-9


def test_vector_scaling_b_draw_lifts_draw():
    p = (0.6, 0.1, 0.3)
    out = apply_vector_scaling(p, 1.0, (0.0, 1.0, 0.0))
    assert out[1] > p[1]          # draw class lifted
    assert out[0] < p[0]          # mass pulled from the others
    assert abs(sum(out) - 1.0) < 1e-9


def test_vector_scaling_handles_zero_probability():
    # log(0) must not blow up — eps-clamped.
    out = apply_vector_scaling((1.0, 0.0, 0.0), 1.0, (0.0, 0.5, 0.0))
    assert abs(sum(out) - 1.0) < 1e-9
    assert all(x >= 0.0 for x in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: FAIL with `ImportError: cannot import name 'apply_vector_scaling'`

- [ ] **Step 3: Implement `apply_vector_scaling`**

In `ml/evaluation/calibration.py`, add after `apply_temperature` (after line 22):

```python
def apply_vector_scaling(probs: Probs, t: float, b: Probs) -> Probs:
    """Vector-scale a W/D/L triple in log-space.

        z_c  = log(max(eps, p_c)) / t + b_c
        p'_c = softmax(z)

    `t` is a shared temperature; `b = (b_home, b_draw, b_away)` are per-class
    biases (fix b_home = 0 as the softmax reference). Unlike scalar temperature
    this can reshape the triple — e.g. b_draw > 0 lifts the under-predicted draw
    class. At t = 1 and b = (0, 0, 0) it is the identity (softmax of logs of a
    normalized triple returns the triple).
    """
    z = [math.log(max(_EPS, p)) / t + bc for p, bc in zip(probs, b)]
    m = max(z)  # shift for numerical stability; softmax is shift-invariant
    exps = [math.exp(zc - m) for zc in z]
    total = sum(exps)
    return (exps[0] / total, exps[1] / total, exps[2] / total)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: PASS (8 tests: 5 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): vector-scaling calibration transform (log-space, per-class bias)"
```

---

### Task 2: `fit_vector_scaling` — coordinate-descent fitter

**Files:**
- Modify: `ml/evaluation/calibration.py`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `ml/evaluation/calibration_test.py` (and extend the import to include `fit_vector_scaling` and the private `_log_loss`):

```python
from ml.evaluation.calibration import (
    _log_loss,
    apply_temperature,
    apply_vector_scaling,
    fit_temperature,
    fit_vector_scaling,
    reliability_curve,
)
from ml.evaluation.scoreline_metrics import per_class_calibration_error


def _wdl_log_loss(probs, labels):
    return _log_loss(probs, labels)


def test_fit_vector_scaling_lifts_underpredicted_draw():
    # Constant prediction home>away>draw, but the TRUTH has draw the 2nd-most
    # common class (draw > away). Scalar temperature can't reorder classes;
    # vector scaling can. 80 home / 70 draw / 50 away on a constant (0.6,0.1,0.3).
    probs = [(0.6, 0.1, 0.3)] * 200
    labels = [0] * 80 + [1] * 70 + [2] * 50

    t, b = fit_vector_scaling(probs, labels)
    assert b[0] == 0.0            # home is the fixed reference
    assert b[1] > 0.0             # draw bias is positive (draw was under-predicted)

    vec = [apply_vector_scaling(p, t, b) for p in probs]
    base_ll = _wdl_log_loss(probs, labels)
    vec_ll = _wdl_log_loss(vec, labels)
    assert vec_ll < base_ll       # beats the uncalibrated input

    # ...and beats the best scalar temperature (which cannot reorder draw>away).
    t_only = fit_temperature(probs, labels)
    temp = [apply_temperature(p, t_only) for p in probs]
    assert vec_ll < _wdl_log_loss(temp, labels)

    # draw-class calibration error drops.
    base_draw = per_class_calibration_error(probs, labels, bins=5)["draw"]
    vec_draw = per_class_calibration_error(vec, labels, bins=5)["draw"]
    assert vec_draw < base_draw


def test_fit_vector_scaling_is_near_identity_on_calibrated_data():
    # Already-calibrated data -> no strong correction needed.
    probs = ([(0.5, 0.3, 0.2)] * 50) + ([(0.2, 0.3, 0.5)] * 50)
    labels = ([0] * 25 + [1] * 15 + [2] * 10) + ([2] * 25 + [1] * 15 + [0] * 10)
    t, b = fit_vector_scaling(probs, labels)
    assert 0.5 <= t <= 3.0
    assert abs(b[1]) <= 0.5 and abs(b[2]) <= 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: FAIL with `ImportError: cannot import name 'fit_vector_scaling'`

- [ ] **Step 3: Implement `fit_vector_scaling`**

In `ml/evaluation/calibration.py`, add after `fit_temperature` (after line 48):

```python
def fit_vector_scaling(
    probs_list: list[Probs],
    labels: list[int],
    t_lo: float = 0.5,
    t_hi: float = 3.0,
    t_steps: int = 26,
    b_lo: float = -1.5,
    b_hi: float = 1.5,
    b_steps: int = 31,
    passes: int = 3,
) -> tuple[float, Probs]:
    """Fit (T, b_draw, b_away) minimizing validation log-loss by coordinate
    descent over bounded grids. b_home is fixed at 0 (softmax reference). A few
    passes converge the three coordinates. Returns (t, (0.0, b_draw, b_away))."""
    t, b_draw, b_away = 1.0, 0.0, 0.0

    def ll(tt: float, bd: float, ba: float) -> float:
        scaled = [apply_vector_scaling(p, tt, (0.0, bd, ba)) for p in probs_list]
        return _log_loss(scaled, labels)

    def grid(lo: float, hi: float, steps: int) -> list[float]:
        return [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]

    for _ in range(passes):
        t = min(grid(t_lo, t_hi, t_steps), key=lambda x: ll(x, b_draw, b_away))
        b_draw = min(grid(b_lo, b_hi, b_steps), key=lambda x: ll(t, x, b_away))
        b_away = min(grid(b_lo, b_hi, b_steps), key=lambda x: ll(t, b_draw, x))
    return round(t, 3), (0.0, round(b_draw, 3), round(b_away, 3))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): fit vector-scaling calibrator (coordinate descent, draw-aware)"
```

---

### Task 3: `calibrate` — single shared dispatcher (vector-scaling or temperature fallback)

**Files:**
- Modify: `ml/evaluation/calibration.py`
- Test: `ml/evaluation/calibration_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `ml/evaluation/calibration_test.py` (extend the import to include `calibrate`):

```python
from ml.evaluation.calibration import (
    _log_loss,
    apply_temperature,
    apply_vector_scaling,
    calibrate,
    fit_temperature,
    fit_vector_scaling,
    reliability_curve,
)


def test_calibrate_applies_vector_scaling_blob():
    p = (0.6, 0.1, 0.3)
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 1.0, 0.0]}
    out = calibrate(p, blob, temperature=1.0)
    assert out == apply_vector_scaling(p, 1.0, (0.0, 1.0, 0.0))
    assert out[1] > p[1]


def test_calibrate_none_falls_back_to_temperature():
    p = (0.8, 0.15, 0.05)
    assert calibrate(p, None, temperature=1.4) == apply_temperature(p, 1.4)


def test_calibrate_none_t1_is_identity():
    p = (0.5, 0.3, 0.2)
    out = calibrate(p, None, temperature=1.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(out, p))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: FAIL with `ImportError: cannot import name 'calibrate'`

- [ ] **Step 3: Implement `calibrate`**

In `ml/evaluation/calibration.py`, add after `apply_vector_scaling` (so the dispatcher sits next to the transforms it dispatches to):

```python
def calibrate(probs: Probs, calibrator: dict | None, temperature: float = 1.0) -> Probs:
    """Apply the shipped calibrator to a W/D/L triple — the one shared helper for
    the card path. `calibrator` is a vector-scaling blob
    {"method": "vector_scaling", "t": float, "b": [b_home, b_draw, b_away]} or
    None. When it is a vector-scaling blob we apply it; otherwise we fall back to
    scalar `temperature` (so an un-shipped calibrator is a guaranteed no-regression
    temperature path, and t=1 is the identity)."""
    if calibrator and calibrator.get("method") == "vector_scaling":
        return apply_vector_scaling(probs, calibrator["t"], tuple(calibrator["b"]))
    return apply_temperature(probs, temperature)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest ml/evaluation/calibration_test.py -q`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add ml/evaluation/calibration.py ml/evaluation/calibration_test.py
git commit -m "feat(ml): shared calibrate() dispatcher (vector-scaling or temperature)"
```

---

### Task 4: `ModelParams.calibrator` blob + JSON round-trip

**Files:**
- Modify: `ml/models/params.py`
- Modify: `ml/models/model_params.json`
- Test: `ml/models/params_test.py` (Create)

- [ ] **Step 1: Write the failing tests**

Create `ml/models/params_test.py`:

```python
"""Tests for ModelParams (calibrator round-trip)."""
import json

from ml.models.params import DEFAULT_PARAMS, ModelParams, load_params, save_params
import ml.models.params as params_mod


def test_default_params_have_no_calibrator():
    assert DEFAULT_PARAMS.calibrator is None


def test_calibrator_round_trips_through_save_load(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    blob = {"method": "vector_scaling", "t": 1.2, "b": [0.0, 0.4, -0.1]}
    p = ModelParams(version="v0.2+cal", base=1.2, beta=0.0021, home_adv=60.0,
                    rho=-0.06, temperature=1.0, pk_beta=0.0, calibrator=blob)
    save_params(p)
    loaded = load_params()
    assert loaded.calibrator == blob


def test_json_without_calibrator_loads_as_none(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    f.write_text(json.dumps({
        "version": "v0.2", "base": 1.2, "beta": 0.0021, "home_adv": 60.0,
        "rho": -0.06, "temperature": 1.0, "pk_beta": 0.0,
    }))
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_params().calibrator is None


def test_to_dict_includes_calibrator():
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 0.5, 0.0]}
    p = ModelParams(version="v", base=1.2, beta=0.002, home_adv=60.0, rho=0.0,
                    temperature=1.0, calibrator=blob)
    assert p.to_dict()["calibrator"] == blob
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest ml/models/params_test.py -q`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'calibrator'`

- [ ] **Step 3: Add the `calibrator` field and round-trip it**

In `ml/models/params.py`, add the field to the dataclass (after line 31, the `pk_beta` field):

```python
@dataclass(frozen=True)
class ModelParams:
    version: str
    base: float
    beta: float
    home_adv: float
    rho: float
    temperature: float
    pk_beta: float = 0.0
    calibrator: dict | None = None  # vector-scaling blob or None (temperature-only)

    def to_dict(self) -> dict:
        return asdict(self)
```

In `load_params()`, add the calibrator read to the returned `ModelParams(...)` (after the `pk_beta=...` line, line 62):

```python
    return ModelParams(
        version=data.get("version", "poisson-elo-v0.2"),
        base=float(data["base"]),
        beta=float(data["beta"]),
        home_adv=float(data["home_adv"]),
        rho=float(data["rho"]),
        temperature=float(data["temperature"]),
        pk_beta=float(data.get("pk_beta", 0.0)),
        calibrator=data.get("calibrator"),
    )
```

(`save_params` already serializes the whole dataclass via `to_dict()`/`asdict`, so it round-trips the new field with no change.)

- [ ] **Step 4: Make the production JSON carry an explicit (inert) calibrator**

Replace the contents of `ml/models/model_params.json` with (adds the explicit `null` so the field is documented; production stays calibrator-free until the gate passes):

```json
{
  "version": "poisson-elo-v0.2",
  "base": 1.2,
  "beta": 0.0021,
  "home_adv": 60.0,
  "rho": -0.06,
  "temperature": 1.0,
  "pk_beta": 0.0,
  "calibrator": null
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest ml/models/params_test.py -q`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add ml/models/params.py ml/models/params_test.py ml/models/model_params.json
git commit -m "feat(ml): nullable calibrator blob on ModelParams + model_params.json"
```

---

### Task 5: `predict_match` applies the calibrator on the card path

**Files:**
- Modify: `ml/models/poisson.py:165-201`
- Modify: `pipeline/generate_predictions.py:60-63`
- Test: `ml/models/poisson_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `ml/models/poisson_test.py`:

```python
def test_predict_match_calibrator_lifts_draw():
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 1.0, 0.0]}
    base = predict_match(1700, 1700, home_adv=0)
    cal = predict_match(1700, 1700, home_adv=0, calibrator=blob)
    assert cal.prob_draw > base.prob_draw
    assert abs(cal.prob_home_win + cal.prob_draw + cal.prob_away_win - 1.0) < 1e-9


def test_predict_match_none_calibrator_matches_temperature_path():
    # calibrator=None must reproduce the existing temperature behavior exactly.
    soft_blob = predict_match(2100, 1500, temperature=1.4, calibrator=None)
    soft_temp = predict_match(2100, 1500, temperature=1.4)
    assert soft_blob.prob_home_win == soft_temp.prob_home_win
    assert soft_blob.prob_draw == soft_temp.prob_draw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest ml/models/poisson_test.py -q`
Expected: FAIL with `TypeError: predict_match() got an unexpected keyword argument 'calibrator'`

- [ ] **Step 3: Route `predict_match` through `calibrate`**

In `ml/models/poisson.py`, add the import near the top (after the `import numpy as np` block, ~line 18):

```python
from ml.evaluation.calibration import calibrate
```

Replace the `predict_match` function (lines 165-201) with:

```python
def predict_match(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    rho: float = 0.0,
    temperature: float = 1.0,
    calibrator: dict | None = None,
) -> MatchPrediction:
    """Full Poisson prediction for one match from the two Elo ratings.

    `rho` applies the Dixon–Coles low-score correction. The W/D/L triple is then
    calibrated via `calibrate`: a vector-scaling `calibrator` blob if present
    (which CAN reshape the triple — e.g. lift the under-predicted draw class),
    otherwise scalar `temperature` (a monotone softening). The predicted
    scoreline is chosen consistent with the CALIBRATED argmax outcome, so the
    displayed winner and score never contradict each other even when calibration
    reorders the classes.
    """
    lam_home, lam_away = expected_goals_from_elo(elo_home, elo_away, home_adv, base, beta)
    matrix = score_matrix(lam_home, lam_away, rho=rho)
    p_home, p_draw, p_away = outcome_probabilities(matrix)
    p_home, p_draw, p_away = calibrate((p_home, p_draw, p_away), calibrator, temperature)
    # Scoreline consistent with the predicted result (argmax W/D/L), so the
    # displayed winner and scoreline never contradict each other.
    outcome = max(
        (("home", p_home), ("draw", p_draw), ("away", p_away)), key=lambda kv: kv[1]
    )[0]
    sh, sa, sp = most_likely_score(matrix, outcome)
    return MatchPrediction(
        prob_home_win=p_home,
        prob_draw=p_draw,
        prob_away_win=p_away,
        score_home=sh,
        score_away=sa,
        score_prob=sp,
        lambda_home=lam_home,
        lambda_away=lam_away,
    )
```

(Leave the module-level `_apply_temperature` in place — `pipeline/experiment_model_eval.py` imports it. `calibrate(..., None, 1.0)` is the identity, so the previous `if temperature != 1.0` short-circuit is no longer needed.)

- [ ] **Step 4: Pass the calibrator through `build_payload`**

In `pipeline/generate_predictions.py`, update the `predict_match` call (lines 60-63) to forward the loaded calibrator:

```python
    pred = predict_match(
        elo_home, elo_away, home_adv=host_adv,
        base=params.base, beta=params.beta, rho=params.rho,
        temperature=params.temperature, calibrator=params.calibrator,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest ml/models/poisson_test.py pipeline/generate_predictions_test.py -q`
Expected: PASS (existing poisson + generate-predictions tests plus the 2 new ones)

- [ ] **Step 6: Commit**

```bash
git add ml/models/poisson.py pipeline/generate_predictions.py ml/models/poisson_test.py
git commit -m "feat(ml): apply calibrator on the W/D/L card path (predict_match)"
```

---

### Task 6: Per-class ECE column in the eval report

**Files:**
- Modify: `pipeline/experiment_model_eval.py:30-45` (imports), `:229-243` (`summarize`), `:382-408` (report printing)
- Test: `pipeline/experiment_model_eval_bootstrap_test.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/experiment_model_eval_bootstrap_test.py`:

```python
def test_summary_includes_per_class_calibration():
    import pipeline.experiment_model_eval as ev
    from datetime import datetime

    def row(year, ph, pa, sh, sa):
        return {"competition": "FIFA World Cup", "date": datetime(year, 6, 1),
                "pre_home": ph, "pre_away": pa, "is_neutral": True,
                "score_home": sh, "score_away": sa}
    rows = []
    for yr in (2014, 2018):
        for _ in range(120):
            rows += [row(yr, 1700, 1400, 2, 0), row(yr, 1500, 1500, 1, 1)]
    res = ev.run(rows, since_year=2010, n_boot=100, val_days=3650)
    served = res["summary"]["v0.1 (served)"]
    assert set(served["per_class"]) == {"home", "draw", "away"}
    assert all(isinstance(served["per_class"][k], float) for k in served["per_class"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest pipeline/experiment_model_eval_bootstrap_test.py::test_summary_includes_per_class_calibration -q`
Expected: FAIL with `KeyError: 'per_class'`

- [ ] **Step 3: Import `per_class_calibration_error`**

In `pipeline/experiment_model_eval.py`, add to the `ml.evaluation.scoreline_metrics` import block (lines 30-36):

```python
from ml.evaluation.scoreline_metrics import (
    exact_score_nll,
    expected_calibration_error,
    expected_calibration_error_equal_count,
    per_class_calibration_error,
    ranked_probability_score,
    top_k_scoreline_hit,
)
```

- [ ] **Step 4: Add per-class ECE to `summarize`**

In `pipeline/experiment_model_eval.py`, in `summarize` (the `out = {...}` dict, lines 232-242), add the `per_class` key:

```python
        out = {
            "n": len(p["ll"]),
            "log_loss": float(ll.mean()),
            "rps": float(rps.mean()),
            "brier": float(np.mean(p["brier"])),
            "exact_nll": float(np.mean(p["esnll"])),
            "top1": float(np.mean(p["top1"])),
            "top3": float(np.mean(p["top3"])),
            "top5": float(np.mean(p["top5"])),
            "ece": expected_calibration_error(p["wdl"], p["labels"], bins=10),
            "per_class": per_class_calibration_error(p["wdl"], p["labels"], bins=10),
        }
```

- [ ] **Step 5: Print the per-class draw ECE in `main`**

In `pipeline/experiment_model_eval.py` `main`, after the summary table loop (after line 386, the `for name, m in res["summary"].items()` block), add a per-class draw-ECE line so the gate signal is visible:

```python
    print("\nPer-class ECE (home / draw / away) — draw is the known pathology:")
    for name, m in res["summary"].items():
        pc = m["per_class"]
        print(f"  {name:22s} home={pc['home']:.4f} draw={pc['draw']:.4f} away={pc['away']:.4f}")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest pipeline/experiment_model_eval_bootstrap_test.py -q`
Expected: PASS (existing 4 + 1 new)

- [ ] **Step 7: Commit**

```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_bootstrap_test.py
git commit -m "feat(ml): per-class ECE column in eval report (surface draw miscalibration)"
```

---

### Task 7: `candidate_vector_scaling` in the gate harness

**Files:**
- Modify: `pipeline/experiment_model_eval.py:29` (import), `:106-127` (`wdl_and_grid`), `:155-183` (candidates + `CANDIDATES`)
- Test: `pipeline/experiment_model_eval_bootstrap_test.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/experiment_model_eval_bootstrap_test.py`:

```python
def test_vector_scaling_candidate_is_scored_and_bootstrapped():
    import pipeline.experiment_model_eval as ev
    from datetime import datetime

    def row(year, ph, pa, sh, sa):
        return {"competition": "FIFA World Cup", "date": datetime(year, 6, 1),
                "pre_home": ph, "pre_away": pa, "is_neutral": True,
                "score_home": sh, "score_away": sa}
    rows = []
    for yr in (2014, 2018):
        for _ in range(120):
            rows += [row(yr, 1700, 1400, 2, 0), row(yr, 1500, 1500, 1, 1),
                     row(yr, 1500, 1500, 0, 0)]
    res = ev.run(rows, since_year=2010, n_boot=100, val_days=3650)
    name = "v0.1+vector-scaling"
    assert name in res["summary"]
    assert "per_class" in res["summary"][name]
    # gate inputs present: a clustered-CI delta vs v0.1 for log-loss.
    assert "ll_ci" in res["bootstrap"][name]
    lo, hi = res["bootstrap"][name]["ll_ci"]
    assert lo <= hi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest pipeline/experiment_model_eval_bootstrap_test.py::test_vector_scaling_candidate_is_scored_and_bootstrapped -q`
Expected: FAIL with `KeyError: 'v0.1+vector-scaling'`

- [ ] **Step 3: Import `fit_vector_scaling`**

In `pipeline/experiment_model_eval.py`, update the calibration import (line 29):

```python
from ml.evaluation.calibration import calibrate, fit_temperature, fit_vector_scaling
```

- [ ] **Step 4: Make `wdl_and_grid` apply the calibrator (not just temperature)**

In `pipeline/experiment_model_eval.py`, replace the calibration tail of `wdl_and_grid` (lines 124-127) so it routes through the shared `calibrate` helper:

```python
    wdl = outcome_probabilities(grid)
    wdl = calibrate(wdl, params.calibrator, params.temperature)
    return wdl, grid
```

(For every existing candidate `params.calibrator` is `None`, so this is identical to the old `if params.temperature != 1.0: _apply_temperature(...)` behavior — no regression.)

- [ ] **Step 5: Add the candidate and register it**

In `pipeline/experiment_model_eval.py`, add after `candidate_temperature_only` (after line 165):

```python
def candidate_vector_scaling(val):
    # Keep v0.1 goals params; fit a vector-scaling calibrator (T + per-class bias)
    # on the window — the lever that can lift the under-predicted draw class.
    if val:
        probs = [wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS)[0] for r in val]
        labels = [_LABEL_INDEX[result_label(r["score_home"], r["score_away"])] for r in val]
        t, b = fit_vector_scaling(probs, labels)
        calibrator = {"method": "vector_scaling", "t": t, "b": list(b)}
    else:
        calibrator = None
    params = ModelParams(version="v1+vecscale", base=DEFAULT_PARAMS.base, beta=DEFAULT_PARAMS.beta,
                         home_adv=DEFAULT_PARAMS.home_adv, rho=DEFAULT_PARAMS.rho,
                         temperature=1.0, calibrator=calibrator)
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], params)
```

Then add it to the `CANDIDATES` dict (lines 178-183):

```python
CANDIDATES = {
    "v0.1 (served)": candidate_v1,
    "v0.2 (full tune)": candidate_v2_full_tune,
    "v0.1+temperature": candidate_temperature_only,
    "v0.1+draw-inflation": candidate_draw_inflation,
    "v0.1+vector-scaling": candidate_vector_scaling,
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest pipeline/experiment_model_eval_bootstrap_test.py -q`
Expected: PASS (existing + new candidate test)

- [ ] **Step 7: Run the full ML/pipeline suite (regression check)**

Run: `.venv/bin/pytest ml pipeline -q`
Expected: PASS, no regressions (the full suite was green at 300+ on main before this branch)

- [ ] **Step 8: Commit**

```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_bootstrap_test.py
git commit -m "feat(ml): vector-scaling candidate in the edition-clustered gate harness"
```

---

## After implementation: running the gate (operational, not a code commit)

The code above ships **inert** — `model_params.json` has `"calibrator": null`, so production behavior is unchanged. To decide whether to ship a real calibrator, run the harness and read the gate the spec defines:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_model_eval --since 2004 --boot 2000
```

**Ship the calibrator only if** `v0.1+vector-scaling`:
1. has a **log-loss delta vs v0.1 whose clustered CI excludes 0 (better)**, AND
2. its **draw-class per-class ECE drops** vs v0.1, AND
3. W/D/L log-loss / RPS do **not** regress.

If it clears, fit the production calibrator on the **served (v0.2) engine's** holdout triples and paste the resulting blob into `model_params.json` (`{"method":"vector_scaling","t":...,"b":[0.0,...,...]}`). If it does not clear, leave `"calibrator": null` — temperature-only, guaranteed no regression. Either way, refresh the methodology page's calibration section if the served W/D/L probabilities change.

---

## Self-Review

**Spec coverage:**
- Vector-scaling calibrator (`apply_vector_scaling` + `fit_vector_scaling`, 3 free params, b_home=0) → Tasks 1, 2. ✓
- One shared `calibrate()` helper with temperature fallback, on the card path → Task 3 (helper), Task 5 (predict_match + build_payload). ✓ (signature refined to primitives to avoid the poisson↔params cycle — documented in header.)
- `calibrator` blob in ModelParams + model_params.json, load/save round-trip, default None → Task 4. ✓
- Sampler / simulators untouched → confirmed: only `predict_match`'s triple changes; `score_cdf`/`sample_scoreline_from_cdf`/`simulate_*` are not modified. ✓
- Fit on the regime it serves incl. group-stage rows → operational gate note + Task 7 candidate fits on the walk-forward window (the harness already pools all major-final editions). ✓
- Gate via the #4 clustered bootstrap, ship only if log-loss CI excludes 0 AND draw ECE drops → Task 6 (per-class ECE), Task 7 (candidate + clustered `ll_ci`), operational note (decision rule). ✓
- Isotonic out of scope → not implemented. ✓
- Testing items (identity, draw lift, fit beats temperature + draw ECE drop, calibrate fallback parity, ModelParams round-trip incl. missing key, gate wiring) → Tasks 1-7 tests. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test shows assertions. ✓

**Type consistency:** `calibrate(probs, calibrator, temperature)` signature identical in Task 3 (def), Task 5 (poisson call), Task 7 (`wdl_and_grid` call). Blob shape `{"method":"vector_scaling","t":float,"b":[bh,bd,ba]}` identical in Tasks 3, 4, 5, 7 and the JSON. `fit_vector_scaling` returns `(t, (b_home, b_draw, b_away))`; consumers use `list(b)` for the blob. `ModelParams.calibrator: dict | None = None` consistent across Tasks 4, 5, 7. ✓
