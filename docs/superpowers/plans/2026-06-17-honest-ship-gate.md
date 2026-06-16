# Honest Ship-Gate (lever #4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the evaluation ship-gate honest — edition-clustered bootstrap CIs, calibration surfaced per-class and per-segment, and a tuner that refuses underpowered windows. No change to served predictions.

**Architecture:** A new `block_bootstrap_ci` resamples whole tournament editions (not IID matches) and replaces both IID resamples in `experiment_model_eval.py`. New equal-count + per-class ECE in `scoreline_metrics.py`. Segment slices added to the eval report. A `MIN_VAL_MATCHES` raise-guard in `tune.py` (and the harness skips windows below it).

**Tech Stack:** Python (NumPy, pytest). Run tests from repo root: `python -m pytest` (config `pytest.ini`).

**Spec:** `docs/superpowers/specs/2026-06-17-honest-ship-gate-design.md`

---

### Task 1: `block_bootstrap_ci` helper + edition-clustered `bootstrap_delta`

**Files:**
- Modify: `pipeline/experiment_model_eval.py` (add helper; tag edition keys in `run`; rewrite `bootstrap_delta`)
- Test: `pipeline/experiment_model_eval_test.py` (create or append)

- [ ] **Step 1: Write the failing test**

Create `pipeline/experiment_model_eval_bootstrap_test.py`:
```python
import numpy as np

from pipeline.experiment_model_eval import block_bootstrap_ci


def test_block_bootstrap_is_wider_than_iid_under_within_edition_correlation():
    # 5 editions x 20 matches; every match in edition e has value e -> strong
    # within-edition correlation. IID resampling of 100 points gives a tight CI;
    # resampling whole editions gives a much wider (honest) CI.
    values, editions = [], []
    for e in range(5):
        values += [float(e)] * 20
        editions += [("CompA", 2000 + e)] * 20
    rng = np.random.default_rng(0)
    blo, bhi = block_bootstrap_ci(values, editions, n_boot=2000, rng=rng)

    rng2 = np.random.default_rng(0)
    v = np.array(values); n = len(v)
    idx = rng2.integers(0, n, size=(2000, n))
    iid = v[idx].mean(axis=1)
    ilo, ihi = float(np.percentile(iid, 2.5)), float(np.percentile(iid, 97.5))

    assert (bhi - blo) > 3 * (ihi - ilo)  # block CI dramatically wider


def test_block_bootstrap_resamples_whole_editions():
    # Single edition -> every resample is that whole edition -> mean is constant.
    values = [1.0, 2.0, 3.0, 4.0]
    editions = [("X", 1)] * 4
    rng = np.random.default_rng(1)
    lo, hi = block_bootstrap_ci(values, editions, n_boot=500, rng=rng)
    assert lo == hi == 2.5  # mean of the only edition, every draw
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q`
Expected: FAIL — `cannot import name 'block_bootstrap_ci'`.

- [ ] **Step 3: Implement the helper**

In `pipeline/experiment_model_eval.py`, add near the top-level helpers (after the imports / before `run`):
```python
from collections import defaultdict


def block_bootstrap_ci(values, edition_keys, n_boot, rng, pct=(2.5, 97.5)):
    """Percentile CI of the mean of `values`, resampling whole tournament
    EDITIONS with replacement (cluster/block bootstrap). values[i] belongs to
    edition_keys[i]. Matches within an edition share context, so this gives an
    honest (wider) CI than IID match resampling. Returns (lo, hi)."""
    vals = np.asarray(values, dtype=float)
    groups: dict = defaultdict(list)
    for i, k in enumerate(edition_keys):
        groups[k].append(i)
    blocks = [np.asarray(ix) for ix in groups.values()]
    n_ed = len(blocks)
    if n_ed == 0:
        return (0.0, 0.0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        chosen = rng.integers(0, n_ed, size=n_ed)
        idx = np.concatenate([blocks[c] for c in chosen])
        means[b] = vals[idx].mean()
    lo, hi = pct
    return float(np.percentile(means, lo)), float(np.percentile(means, hi))
```

- [ ] **Step 4: Tag edition keys per match in `run`, and use the block bootstrap**

In `run` (lines 165-253): add an `edition_keys` accumulator parallel to the pooled per-match arrays.

After `match_count = 0` (line 174), add:
```python
    edition_keys: list[tuple] = []  # (comp, year) per pooled match, index-aligned
```
Inside the `for r in target:` loop (after line 185 `label = ...`), append once per match (NOT per candidate):
```python
            edition_keys.append((comp, year))
```
(Place it inside `for r in target:` but outside the `for name, scorer ...` inner loop, so it's appended once per match.)

Rewrite `bootstrap_delta` (lines 224-246) to use `block_bootstrap_ci` instead of the IID `idx`:
```python
    def bootstrap_delta(name: str) -> dict:
        # Paired per-match delta (candidate - v0.1); negative = candidate better
        # for losses (ll/rps/esnll), positive = better for hit-rates (top5).
        cand_ll = np.array(pooled[name]["ll"]); cand_rps = np.array(pooled[name]["rps"])
        cand_es = np.array(pooled[name]["esnll"]); cand_t5 = np.array(pooled[name]["top5"])
        d_ll = cand_ll - base_ll; d_rps = cand_rps - base_rps
        d_es = cand_es - base_esnll; d_t5 = cand_t5 - base_top5
        n = len(d_ll)
        if n == 0:
            return {}
        return {
            "d_log_loss": float(d_ll.mean()),
            "ll_ci": block_bootstrap_ci(d_ll, edition_keys, n_boot, rng),
            "d_rps": float(d_rps.mean()),
            "rps_ci": block_bootstrap_ci(d_rps, edition_keys, n_boot, rng),
            "d_exact_nll": float(d_es.mean()),
            "es_ci": block_bootstrap_ci(d_es, edition_keys, n_boot, rng),
            "d_top5": float(d_t5.mean()),
            "t5_ci": block_bootstrap_ci(d_t5, edition_keys, n_boot, rng),
        }
```
(The old `idx = rng.integers(...)` line and the `bll/brps/bes/bt5` lines are removed.)

- [ ] **Step 5: Run to verify it passes + regression**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q && python -m pytest pipeline/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_bootstrap_test.py
git commit -m "feat(ml): edition-clustered block bootstrap for the ship-gate CI"
```

---

### Task 2: Cluster `run_global_split`'s bootstrap too

**Files:**
- Modify: `pipeline/experiment_model_eval.py` (`run_global_split` lines 256-304)
- Test: append to `pipeline/experiment_model_eval_bootstrap_test.py`

- [ ] **Step 1: Write the failing test**

Append:
```python
def test_global_split_ci_uses_edition_clustering(monkeypatch):
    # The global-split ci() must resample editions, not IID matches. We assert the
    # rec carries edition keys and ci() routes through block_bootstrap_ci.
    import pipeline.experiment_model_eval as ev
    calls = {"n": 0}
    real = ev.block_bootstrap_ci

    def spy(values, edition_keys, n_boot, rng, pct=(2.5, 97.5)):
        calls["n"] += 1
        assert len(edition_keys) == len(values)  # tagged per test row
        return real(values, edition_keys, n_boot, rng, pct)

    monkeypatch.setattr(ev, "block_bootstrap_ci", spy)
    # Minimal synthetic 'major final' rows across 2 test-year editions.
    from datetime import datetime
    def row(year, ph, pa, sh, sa):
        return {"competition": "FIFA World Cup", "date": datetime(year, 6, 1),
                "pre_home": ph, "pre_away": pa, "is_neutral": True,
                "score_home": sh, "score_away": sa}
    rows = [row(2014, 1600, 1500, 2, 1), row(2014, 1500, 1600, 0, 1),
            row(2018, 1700, 1400, 3, 0), row(2018, 1450, 1450, 1, 1)] * 60
    res = ev.run_global_split(rows, train_lo=2014, train_hi=2014, test_since=2014, n_boot=200)
    assert calls["n"] >= 4  # one per delta metric (log_loss, rps, exact_nll, top5)
    assert "delta" in res
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q -k global_split`
Expected: FAIL — `block_bootstrap_ci` not called (current `ci` uses IID `idx`); `assert calls["n"] >= 4` fails.

- [ ] **Step 3: Implement**

In `run_global_split`'s `metrics_for` (lines 269-284), tag edition keys per test row. Change the `rec` dict to include `"ed"` and append it in the loop:
```python
    def metrics_for(scorer) -> tuple[dict, dict]:
        rec = {"ll": [], "rps": [], "esnll": [], "top5": [], "wdl": [], "labels": [], "ed": []}
        for r in test:
            label = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
            wdl, grid = scorer(r)
            rec["ll"].append(-math.log(max(_EPS, min(1 - _EPS, wdl[label]))))
            rec["rps"].append(ranked_probability_score(wdl, label))
            rec["esnll"].append(exact_score_nll(grid, r["score_home"], r["score_away"]))
            rec["top5"].append(1.0 if top_k_scoreline_hit(grid, r["score_home"], r["score_away"], 5) else 0.0)
            rec["wdl"].append(wdl); rec["labels"].append(label)
            rec["ed"].append((r["competition"], r["date"].year))
        summ = {
            "log_loss": float(np.mean(rec["ll"])), "rps": float(np.mean(rec["rps"])),
            "exact_nll": float(np.mean(rec["esnll"])), "top5": float(np.mean(rec["top5"])),
            "ece": expected_calibration_error(rec["wdl"], rec["labels"], bins=10),
        }
        return summ, rec
```
Replace the IID bootstrap (lines 289-297) with the block version:
```python
    rng = np.random.default_rng(7)
    _REC_KEY = {"log_loss": "ll", "rps": "rps", "exact_nll": "esnll", "top5": "top5"}

    def ci(metric):
        rk = _REC_KEY[metric]
        d = np.array(v2_r[rk]) - np.array(v1_r[rk])
        return float(d.mean()), block_bootstrap_ci(d, v1_r["ed"], n_boot, rng)
```
(The `n = len(...); idx = rng.integers(...)` line is removed.)

- [ ] **Step 4: Run to verify it passes + regression**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q && python -m pytest pipeline/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_bootstrap_test.py
git commit -m "feat(ml): cluster the global-split bootstrap by edition"
```

---

### Task 3: Equal-count + per-class ECE in `scoreline_metrics`

**Files:**
- Modify: `ml/evaluation/scoreline_metrics.py` (add two functions after `expected_calibration_error`, line 104-130)
- Test: `ml/evaluation/calibration_ece_test.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `ml/evaluation/calibration_ece_test.py`:
```python
from ml.evaluation.scoreline_metrics import (
    expected_calibration_error_equal_count, per_class_calibration_error,
)


def _perfectly_calibrated():
    # 3 buckets of probs whose home-win frequency matches the predicted prob.
    probs, labels = [], []
    for p, n_pos, n_tot in [(0.2, 2, 10), (0.5, 5, 10), (0.8, 8, 10)]:
        for i in range(n_tot):
            probs.append((p, (1 - p) / 2, (1 - p) / 2))
            labels.append(0 if i < n_pos else 1)
    return probs, labels


def test_equal_count_ece_zero_for_calibrated():
    probs, labels = _perfectly_calibrated()
    assert expected_calibration_error_equal_count(probs, labels, bins=3) < 0.05


def test_equal_count_bins_have_roughly_equal_counts():
    # 90 predictions, 3 bins -> ~30 each. (Verified indirectly: a heavily skewed
    # prob distribution still produces non-empty balanced bins.)
    probs = [(0.1 + 0.001 * i, 0.45, 0.45) for i in range(90)]
    labels = [0] * 90
    # Should not raise and should return a finite number.
    val = expected_calibration_error_equal_count(probs, labels, bins=3)
    assert val == val and val >= 0.0


def test_per_class_isolates_draw_miscalibration():
    # Draw class systematically under-predicted: predict 0.1 draw, actual ~0.4.
    probs, labels = [], []
    for i in range(100):
        probs.append((0.45, 0.10, 0.45))
        labels.append(1 if i < 40 else (0 if i % 2 else 2))
    out = per_class_calibration_error(probs, labels, bins=5)
    assert set(out) == {"home", "draw", "away"}
    assert out["draw"] > 0.2  # the draw class is badly miscalibrated
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/evaluation/calibration_ece_test.py -q`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement**

In `ml/evaluation/scoreline_metrics.py`, after `expected_calibration_error` (line ~130), add:
```python
def _equal_count_ece(pairs: list[tuple[float, int]], bins: int) -> float:
    """ECE over quantile (equal-count) bins of (predicted_prob, hit) pairs."""
    n = len(pairs)
    if n == 0:
        return 0.0
    pairs = sorted(pairs)
    bins = max(1, min(bins, n))
    ece = 0.0
    for b in range(bins):
        lo = (b * n) // bins
        hi = ((b + 1) * n) // bins
        chunk = pairs[lo:hi]
        if not chunk:
            continue
        mean_pred = sum(p for p, _ in chunk) / len(chunk)
        freq = sum(h for _, h in chunk) / len(chunk)
        ece += (len(chunk) / n) * abs(mean_pred - freq)
    return ece


def expected_calibration_error_equal_count(probs_list, labels, bins: int = 10) -> float:
    """Like expected_calibration_error but with equal-COUNT (quantile) bins, so
    sparse high-probability bins (where draws are under-predicted) aren't washed
    out by equal-width pooling. Pools every class probability vs its hit (0/1)."""
    pairs = [(probs[c], 1 if labels[i] == c else 0)
             for i, probs in enumerate(probs_list) for c in range(3)]
    return _equal_count_ece(pairs, bins)


def per_class_calibration_error(probs_list, labels, bins: int = 10) -> dict:
    """Equal-count ECE computed separately per outcome class. Returns
    {"home": .., "draw": .., "away": ..}. Surfaces the draw-class pathology that
    pooled ECE hides."""
    names = {0: "home", 1: "draw", 2: "away"}
    out = {}
    for c, name in names.items():
        pairs = [(probs[c], 1 if labels[i] == c else 0) for i, probs in enumerate(probs_list)]
        out[name] = _equal_count_ece(pairs, bins)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ml/evaluation/calibration_ece_test.py -q && python -m pytest ml/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ml/evaluation/scoreline_metrics.py ml/evaluation/calibration_ece_test.py
git commit -m "feat(ml): equal-count + per-class ECE (surface draw miscalibration)"
```

---

### Task 4: Segment slices in the eval report

**Files:**
- Modify: `pipeline/experiment_model_eval.py` (`run` — record per-match elo gap; add `segment_report`; include in return)
- Test: append to `pipeline/experiment_model_eval_bootstrap_test.py`

- [ ] **Step 1: Write the failing test**

Append:
```python
def test_run_output_has_segment_tables():
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
    seg = res["segments"]
    assert set(seg) == {"by_edition", "by_favorite_gap", "draw_vs_decisive"}
    # draw_vs_decisive splits into the two buckets
    assert set(seg["draw_vs_decisive"]) == {"draw", "decisive"}
    for table in seg.values():
        for cell in table.values():
            assert {"n", "log_loss", "ece"} <= set(cell)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q -k segment`
Expected: FAIL — `res["segments"]` KeyError.

- [ ] **Step 3: Implement**

In `run`, record the per-match favorite Elo gap alongside `edition_keys`. After the `edition_keys` accumulator line, add:
```python
    elo_gaps: list[float] = []  # |pre_home - pre_away| per pooled match
```
Inside `for r in target:` (next to the `edition_keys.append(...)`), add:
```python
            elo_gaps.append(abs(r["pre_home"] - r["pre_away"]))
```
Add a `segment_report` helper inside `run` (after `bootstrap_delta`), diagnosing the SERVED model (`v0.1 (served)`):
```python
    def segment_report() -> dict:
        served = pooled["v0.1 (served)"]
        ll = served["ll"]; wdl = served["wdl"]; labels = served["labels"]

        def cell(idxs: list[int]) -> dict:
            if not idxs:
                return {"n": 0, "log_loss": 0.0, "ece": 0.0}
            return {
                "n": len(idxs),
                "log_loss": float(np.mean([ll[i] for i in idxs])),
                "ece": expected_calibration_error_equal_count(
                    [wdl[i] for i in idxs], [labels[i] for i in idxs], bins=5),
            }

        by_edition: dict = defaultdict(list)
        for i, k in enumerate(edition_keys):
            by_edition[k].append(i)

        gap_buckets = {"0-50": [], "50-150": [], "150-300": [], "300+": []}
        for i, g in enumerate(elo_gaps):
            key = "0-50" if g < 50 else "50-150" if g < 150 else "150-300" if g < 300 else "300+"
            gap_buckets[key].append(i)

        dvd = {"draw": [], "decisive": []}
        for i, lab in enumerate(labels):
            dvd["draw" if lab == 1 else "decisive"].append(i)

        return {
            "by_edition": {f"{c} {y}": cell(ix) for (c, y), ix in by_edition.items()},
            "by_favorite_gap": {k: cell(ix) for k, ix in gap_buckets.items()},
            "draw_vs_decisive": {k: cell(ix) for k, ix in dvd.items()},
        }
```
Add `"segments": segment_report(),` to the `return {...}` dict (line 248-253). Also add the import for the new metric at the top of the file:
```python
from ml.evaluation.scoreline_metrics import expected_calibration_error_equal_count
```
(alongside the existing `expected_calibration_error` import).

In `main()` (after the existing prints), add this concrete block so the CLI surfaces the segments:
```python
    print("\nCalibration by segment (served v0.1 — n / log_loss / ece):")
    for group, table in res["segments"].items():
        print(f"  {group}:")
        for seg, cell in table.items():
            print(f"    {seg:<14} n={cell['n']:<5} ll={cell['log_loss']:.4f} ece={cell['ece']:.4f}")
```

- [ ] **Step 4: Run to verify it passes + regression**

Run: `python -m pytest pipeline/experiment_model_eval_bootstrap_test.py -q && python -m pytest pipeline/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_bootstrap_test.py
git commit -m "feat(ml): per-edition / favorite-gap / draw-vs-decisive calibration segments"
```

---

### Task 5: Min-sample guard in the tuner

**Files:**
- Modify: `ml/evaluation/tune.py` (`MIN_VAL_MATCHES` + raise in `tune_params`)
- Modify: `pipeline/experiment_model_eval.py` (`run` skip threshold uses `MIN_VAL_MATCHES`)
- Test: `ml/evaluation/tune_guard_test.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ml/evaluation/tune_guard_test.py`:
```python
import pytest
from datetime import datetime

from ml.evaluation.tune import tune_params, MIN_VAL_MATCHES


def _row(sh, sa):
    return {"competition": "FIFA World Cup", "date": datetime(2018, 6, 1),
            "pre_home": 1600, "pre_away": 1500, "is_neutral": True,
            "score_home": sh, "score_away": sa}


def test_underpowered_window_raises():
    with pytest.raises(ValueError):
        tune_params([_row(2, 1)] * (MIN_VAL_MATCHES - 1))


def test_at_threshold_tunes():
    params = tune_params([_row(2, 1), _row(0, 1), _row(1, 1)] * MIN_VAL_MATCHES)
    assert params.base > 0 and 0.0 <= params.temperature
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ml/evaluation/tune_guard_test.py -q`
Expected: FAIL — `cannot import name 'MIN_VAL_MATCHES'`.

- [ ] **Step 3: Implement**

In `ml/evaluation/tune.py`, add a module constant near the top (after imports):
```python
# A tuning/validation window below this many matches is underpowered — fitting on
# it returns grid-corner params shaped by noise, so we fail loudly instead.
MIN_VAL_MATCHES = 100
```
At the start of `tune_params` (line 52, before `base, beta, ... = ...`):
```python
    if len(val_rows) < MIN_VAL_MATCHES:
        raise ValueError(
            f"validation window has {len(val_rows)} matches (< MIN_VAL_MATCHES="
            f"{MIN_VAL_MATCHES}); too underpowered to tune.")
```

In `pipeline/experiment_model_eval.py`, the per-edition `run` loop currently skips windows with `< 50` rows (line 179). Bump it to the shared constant so an underpowered window is skipped BEFORE a candidate calls `tune_params` (which would now raise). Add the import:
```python
from ml.evaluation.tune import MIN_VAL_MATCHES, tune_params  # tune_params already used indirectly
```
and change line 179:
```python
        if len(val) < MIN_VAL_MATCHES:  # underpowered window; skip (matches tune guard)
            continue
```
(If `tune_params` is not already imported there, only import `MIN_VAL_MATCHES`.)

- [ ] **Step 4: Run to verify it passes + full suite**

Run: `python -m pytest ml/evaluation/tune_guard_test.py -q && python -m pytest -q`
Expected: PASS. If `run_global_split`'s `tune_params(train)` now raises because a synthetic/small train set is under the threshold, fix only the affected TEST inputs to provide ≥ `MIN_VAL_MATCHES` rows (do not weaken the guard).

- [ ] **Step 5: Commit**
```bash
git add ml/evaluation/tune.py pipeline/experiment_model_eval.py ml/evaluation/tune_guard_test.py
git commit -m "feat(ml): fail loudly on underpowered tuning windows (MIN_VAL_MATCHES)"
```

---

### Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `python -m pytest -q`
Expected: ALL PASS.

- [ ] **Step 2: Smoke-run the eval harness on real data**

Run: `PYTHONPATH=backend:. python -m pipeline.experiment_model_eval --since 2004 --boot 500 2>&1 | tail -30`
Expected: runs without error; prints the bootstrap CIs (now wider/edition-clustered) and the new segment tables. Confirm no NaN and that the report includes per-edition / favorite-gap / draw-vs-decisive sections.

- [ ] **Step 3: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Note in the summary: CIs are now edition-clustered (wider) — some prior "significant" verdicts may flip to not-significant, which is the intended honest outcome.

---

## Notes for the implementer
- **Run all commands from the repo root.**
- This lever changes ONLY evaluation/reporting + the tuner guard — it must NOT change `model_params.json`, the simulators, or any served prediction.
- The block bootstrap resamples WHOLE editions; never resample individual matches IID again in these code paths.
- Keep the existing equal-width `expected_calibration_error` — the new equal-count/per-class functions are additive.
