# Gradient-boosted W/D/L Challenger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a HistGradientBoosting W/D/L classifier as a gated challenger to the Poisson engine, auto-promoted to a calibrated blend in production only if it beats Poisson out-of-sample.

**Architecture:** A self-contained, leak-free feature pipeline (chronological replay → rolling form/goals/h2h features) feeds a `HistGradientBoostingClassifier`. An offline gate (extending `pipeline/experiment_model_eval.py`) decides ship/shelve. When shipped (`model_params.json` → `wdl_blend` non-null), `generate_predictions` trains the booster in-process each refresh and blends its W/D/L with Poisson's, then calibrates. The booster never touches scorelines, simulators, or the live win-prob bar.

**Tech Stack:** Python 3, scikit-learn 1.6.0 (`HistGradientBoostingClassifier` — already a dependency; **no new packages**), numpy, SQLAlchemy, pytest.

**Spec:** [docs/superpowers/specs/2026-06-18-xgboost-wdl-challenger-design.md](../specs/2026-06-18-xgboost-wdl-challenger-design.md)

> **Commit convention:** this repo uses `type(scope): subject` (e.g. `feat(ml):`, `test(ml):`). End every commit message body with the trailer:
> `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
> All work happens on branch `feat/wdl-boost-challenger` (already created).

---

## File Structure

**Create:**
- `ml/features/wdl_features.py` — canonical feature schema: `FEATURE_NAMES`, `assemble_features(...)`, `to_vector(...)`, `window_stats(...)`. Pure (no DB). The single source of truth both training and serving call, guaranteeing train/serve parity.
- `ml/features/wdl_features_test.py` — tests for the assembler + window helper.
- `ml/features/training_rows.py` — `build_training_rows(enriched_rows)` (leak-free chronological feature+label builder) and `training_weight(row, ref_date)` (recency + competition-tier sample weight).
- `ml/features/training_rows_test.py` — leakage guard + rolling-feature correctness + weight tests.
- `ml/models/wdl_boost.py` — `WdlBoost` (HistGradientBoosting wrapper, `fit`/`predict_proba`) and `blend_triples(a, b, w)`.
- `ml/models/wdl_boost_test.py` — model fit/predict/determinism/blend tests.

**Modify:**
- `ml/models/params.py` — add nullable `wdl_blend` field to `ModelParams` + `load_params`/`save_params` round-trip.
- `ml/models/params_test.py` — `wdl_blend` round-trip tests (mirror the calibrator tests).
- `pipeline/generate_predictions.py` — `build_payload` gains an optional `booster`; assembles booster features, blends + calibrates when `params.wdl_blend` is set; `generate_predictions` trains the booster once per run when enabled and threads it in.
- `pipeline/generate_predictions_test.py` — no-regression (blend off ⇒ identical) + blend-shift tests.
- `pipeline/experiment_model_eval.py` — add `run_blend_gate(...)` and wire its verdict into `main()`.
- `pipeline/experiment_model_eval_gate_test.py` (create) — smoke test that the gate runs end-to-end on synthetic rows.
- `ml/models/model_params.json` — set/keep `"wdl_blend": null` (Task 4); flipped to the fitted blob only if Task 7's gate passes.

---

## Task 1: Canonical feature schema (`ml/features/wdl_features.py`)

**Files:**
- Create: `ml/features/wdl_features.py`
- Test: `ml/features/wdl_features_test.py`

- [ ] **Step 1: Write the failing test**

```python
# ml/features/wdl_features_test.py
"""Tests for the canonical W/D/L booster feature schema."""
from ml.features.wdl_features import (
    FEATURE_NAMES,
    assemble_features,
    to_vector,
    window_stats,
    DEFAULT_GOALS_AVG,
)


def _inputs(**over):
    base = dict(
        elo_home=1700.0, elo_away=1500.0, is_neutral=True,
        form_home=18.0, form_away=9.0,
        gf_avg_home=2.0, gf_avg_away=1.0, ga_avg_home=0.8, ga_avg_away=1.5,
        h2h_home_wins=3, h2h_matches=5,
        data_points_home=10, data_points_away=10,
    )
    base.update(over)
    return base


def test_assemble_has_every_feature_name():
    feats = assemble_features(**_inputs())
    assert set(feats.keys()) == set(FEATURE_NAMES)


def test_derived_fields():
    feats = assemble_features(**_inputs())
    assert feats["elo_diff"] == 200.0
    assert feats["form_diff"] == 9.0
    assert feats["is_neutral"] == 1.0
    assert feats["h2h_home_winrate"] == 3 / 5


def test_h2h_winrate_defaults_to_half_when_no_history():
    feats = assemble_features(**_inputs(h2h_home_wins=0, h2h_matches=0))
    assert feats["h2h_home_winrate"] == 0.5


def test_to_vector_follows_feature_names_order():
    feats = assemble_features(**_inputs())
    vec = to_vector(feats)
    assert vec == [feats[name] for name in FEATURE_NAMES]
    assert len(vec) == len(FEATURE_NAMES)


def test_window_stats_empty_uses_defaults():
    form, gf, ga, n = window_stats([])
    assert (form, gf, ga, n) == (0.0, DEFAULT_GOALS_AVG, DEFAULT_GOALS_AVG, 0)


def test_window_stats_counts_points_and_averages():
    # (gf, ga): a win (2-0), a draw (1-1), a loss (0-3)
    form, gf, ga, n = window_stats([(2, 0), (1, 1), (0, 3)])
    assert form == 4.0           # 3 + 1 + 0
    assert gf == 1.0             # (2+1+0)/3
    assert ga == 4 / 3           # (0+1+3)/3
    assert n == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest ml/features/wdl_features_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ml.features.wdl_features'`

- [ ] **Step 3: Write minimal implementation**

```python
# ml/features/wdl_features.py
"""Canonical feature schema for the gradient-boosted W/D/L challenger.

This module is PURE (no DB, no model imports) and is the single source of truth
for the booster's feature vector. Both the training-row builder
(ml/features/training_rows.py) and the serving path (pipeline/generate_predictions.py)
assemble features through `assemble_features`/`to_vector`, so train/serve parity is
guaranteed by construction. `window_stats` is the shared last-N rolling reducer used
by both sides.

Deliberately excluded (see spec §2): FIFA rank (no leak-free history), is_home_host
(host advantage already lives in Elo home_adv; ~constant in training), and competition
tier (constant for WC matches at serve — it is used as a training sample weight in
training_rows.py instead of as a feature).
"""
from __future__ import annotations

# Average international goals per team per match — the cold-start fallback for a
# team with no recent history. Matches the spirit of poisson.BASE_GOALS.
DEFAULT_GOALS_AVG = 1.3

# Fixed feature order. NEVER reorder without retraining — fit and predict both
# rely on this order via to_vector().
FEATURE_NAMES = [
    "elo_diff", "elo_home", "elo_away", "is_neutral",
    "form_home", "form_away", "form_diff",
    "gf_avg_home", "gf_avg_away", "ga_avg_home", "ga_avg_away",
    "h2h_home_winrate", "h2h_matches",
    "data_points_home", "data_points_away",
]


def assemble_features(
    *, elo_home: float, elo_away: float, is_neutral: bool,
    form_home: float, form_away: float,
    gf_avg_home: float, gf_avg_away: float, ga_avg_home: float, ga_avg_away: float,
    h2h_home_wins: int, h2h_matches: int,
    data_points_home: int, data_points_away: int,
) -> dict:
    """Build the ordered feature dict from raw, leak-free inputs."""
    winrate = h2h_home_wins / h2h_matches if h2h_matches else 0.5
    return {
        "elo_diff": elo_home - elo_away,
        "elo_home": elo_home,
        "elo_away": elo_away,
        "is_neutral": 1.0 if is_neutral else 0.0,
        "form_home": form_home,
        "form_away": form_away,
        "form_diff": form_home - form_away,
        "gf_avg_home": gf_avg_home,
        "gf_avg_away": gf_avg_away,
        "ga_avg_home": ga_avg_home,
        "ga_avg_away": ga_avg_away,
        "h2h_home_winrate": winrate,
        "h2h_matches": float(h2h_matches),
        "data_points_home": float(data_points_home),
        "data_points_away": float(data_points_away),
    }


def to_vector(feats: dict) -> list[float]:
    """Flatten a feature dict into the model's fixed-order vector."""
    return [feats[name] for name in FEATURE_NAMES]


def window_stats(appearances: list[tuple[int, int]]) -> tuple[float, float, float, int]:
    """Reduce a team's recent (goals_for, goals_against) appearances to
    (form_points, gf_avg, ga_avg, n). Empty history → (0, DEFAULT, DEFAULT, 0).

    form_points = sum of 3/1/0 per match (win/draw/loss). The SAME reducer is used
    by training (deque sweep) and serving (DB query), so the two paths cannot drift.
    """
    n = len(appearances)
    if n == 0:
        return 0.0, DEFAULT_GOALS_AVG, DEFAULT_GOALS_AVG, 0
    form = gf_sum = ga_sum = 0
    for gf, ga in appearances:
        gf_sum += gf
        ga_sum += ga
        form += 3 if gf > ga else (1 if gf == ga else 0)
    return float(form), gf_sum / n, ga_sum / n, n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest ml/features/wdl_features_test.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ml/features/wdl_features.py ml/features/wdl_features_test.py
git commit -m "feat(ml): canonical W/D/L booster feature schema"
```

---

## Task 2: Leak-free training rows (`ml/features/training_rows.py`)

**Files:**
- Create: `ml/features/training_rows.py`
- Test: `ml/features/training_rows_test.py`

Input = the enriched leak-free Elo rows produced by `pipeline/backtest_data.build_enriched_rows` (each: `home_id`, `away_id`, `pre_home`, `pre_away`, `is_neutral`, `competition`, `score_home`, `score_away`, `date`). `build_training_rows` does ONE more chronological sweep, maintaining rolling per-team and per-pair state, emitting one feature row (features + `label` + `date` + `competition`) per input.

- [ ] **Step 1: Write the failing test**

```python
# ml/features/training_rows_test.py
"""Tests for the leak-free training-row builder."""
from datetime import date

from ml.features.training_rows import (
    build_training_rows,
    training_weight,
    DATE_FLOOR,
)
from ml.features.wdl_features import FEATURE_NAMES


def _row(home_id, away_id, sh, sa, d, comp="Friendly", pre_h=1500.0, pre_a=1500.0, neutral=False):
    return {
        "home_id": home_id, "away_id": away_id,
        "pre_home": pre_h, "pre_away": pre_a, "is_neutral": neutral,
        "competition": comp, "score_home": sh, "score_away": sa,
        "date": d,
    }


def test_emits_one_row_per_input_with_features_and_label():
    rows = [
        _row(1, 2, 2, 0, date(2020, 1, 1)),
        _row(1, 2, 1, 1, date(2020, 2, 1)),
    ]
    out = build_training_rows(rows)
    assert len(out) == 2
    assert out[0]["label"] == "H"
    assert out[1]["label"] == "D"
    for name in FEATURE_NAMES:
        assert name in out[0]
    assert out[0]["date"] == date(2020, 1, 1)


def test_first_match_has_no_prior_form():
    out = build_training_rows([_row(1, 2, 3, 0, date(2020, 1, 1))])
    # Neither team has earlier matches → zero form, zero data points.
    assert out[0]["form_home"] == 0.0
    assert out[0]["data_points_home"] == 0.0
    assert out[0]["data_points_away"] == 0.0


def test_form_reflects_only_earlier_matches():
    rows = [
        _row(1, 2, 3, 0, date(2020, 1, 1)),   # team 1 wins
        _row(1, 3, 2, 0, date(2020, 2, 1)),   # team 1 wins again
        _row(1, 4, 0, 0, date(2020, 3, 1)),   # by now team 1 has 2 prior wins
    ]
    out = build_training_rows(rows)
    # Third match: team 1 has 2 prior matches, both wins → form 6, 2 data points.
    assert out[2]["form_home"] == 6.0
    assert out[2]["data_points_home"] == 2.0


def test_leakage_guard_later_matches_do_not_affect_earlier_features():
    early = [_row(1, 2, 2, 0, date(2020, 1, 1)), _row(1, 2, 1, 0, date(2020, 2, 1))]
    later = early + [_row(1, 2, 5, 0, date(2020, 3, 1))]
    out_early = build_training_rows(early)
    out_later = build_training_rows(later)
    # The feature rows for the first two matches must be byte-identical whether or
    # not a later match exists — proves no future data leaks backward.
    assert out_early[0] == out_later[0]
    assert out_early[1] == out_later[1]


def test_h2h_winrate_accumulates_from_home_perspective():
    rows = [
        _row(1, 2, 1, 0, date(2020, 1, 1)),   # 1 beats 2
        _row(2, 1, 0, 0, date(2020, 2, 1)),   # draw
        _row(1, 2, 0, 1, date(2020, 3, 1)),   # 2 beats 1
    ]
    out = build_training_rows(rows)
    # Third match home=1: prior meetings = [1 won, draw] from team 1's view →
    # 1 win in 2 matches → winrate 0.5.
    assert out[2]["h2h_matches"] == 2.0
    assert out[2]["h2h_home_winrate"] == 0.5


def test_training_weight_decays_with_age_and_downweights_friendlies():
    ref = date(2024, 1, 1)
    recent = {"date": date(2023, 1, 1), "competition": "FIFA World Cup"}
    old = {"date": date(2008, 1, 1), "competition": "FIFA World Cup"}
    friendly = {"date": date(2023, 1, 1), "competition": "Friendly"}
    assert training_weight(recent, ref) > training_weight(old, ref)
    assert training_weight(friendly, ref) < training_weight(recent, ref)


def test_rows_before_date_floor_are_dropped():
    rows = [
        _row(1, 2, 1, 0, date(1980, 1, 1)),       # before floor
        _row(1, 2, 1, 0, date(DATE_FLOOR.year + 1, 1, 1)),
    ]
    out = build_training_rows(rows)
    assert all(r["date"] >= DATE_FLOOR for r in out)
    assert len(out) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest ml/features/training_rows_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ml.features.training_rows'`

- [ ] **Step 3: Write minimal implementation**

```python
# ml/features/training_rows.py
"""Leak-free training rows for the gradient-boosted W/D/L challenger.

Takes the enriched leak-free Elo rows (pipeline.backtest_data.build_enriched_rows)
and runs ONE chronological sweep, emitting per match a feature row whose rolling
features (form, goals for/against, head-to-head) reflect ONLY earlier matches.
Same windowing reducer as serving (ml.features.wdl_features.window_stats), so the
training and serving feature distributions match.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date

from ml.features.wdl_features import assemble_features, window_stats
from ml.models.baseline_logistic import result_label

# Modern-era floor: pre-1994 international football is a different regime and dilutes
# the booster. Rows older than this are dropped from training.
DATE_FLOOR = date(1994, 1, 1)

WINDOW = 10        # rolling form / goals window (matches pipeline/team_stats.py intent)
H2H_WINDOW = 5     # head-to-head window (matches build_features.head_to_head default)
_HALF_LIFE_DAYS = 8 * 365.25   # recency half-life ~8 years


def _result_points(gf: int, ga: int) -> int:
    return 3 if gf > ga else (1 if gf == ga else 0)


def build_training_rows(enriched_rows: list[dict]) -> list[dict]:
    """Chronological sweep → list of {**features, label, date, competition,
    pre_home, pre_away}.

    `enriched_rows` MUST be oldest-first (build_enriched_rows orders by date, id).
    Rolling state is read BEFORE each match is folded in, so features never see the
    match's own result or any later match. Each row also carries pre_home/pre_away
    (the gate's Poisson side reuses them) plus date/competition — none of these are
    in FEATURE_NAMES, so the booster never sees them.
    """
    recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=WINDOW))   # team_id -> (gf, ga)
    counts: dict[int, int] = defaultdict(int)                              # team_id -> matches seen
    h2h: dict[frozenset, deque] = defaultdict(lambda: deque(maxlen=H2H_WINDOW))  # pair -> winner_id|None

    out: list[dict] = []
    for r in enriched_rows:
        if r["date"] < DATE_FLOOR:
            continue
        h, a = r["home_id"], r["away_id"]
        sh, sa = r["score_home"], r["score_away"]

        form_h, gf_h, ga_h, _ = window_stats(list(recent[h]))
        form_a, gf_a, ga_a, _ = window_stats(list(recent[a]))

        pair = frozenset((h, a))
        meetings = list(h2h[pair])
        home_wins = sum(1 for w in meetings if w == h)

        feats = assemble_features(
            elo_home=r["pre_home"], elo_away=r["pre_away"], is_neutral=r["is_neutral"],
            form_home=form_h, form_away=form_a,
            gf_avg_home=gf_h, gf_avg_away=gf_a, ga_avg_home=ga_h, ga_avg_away=ga_a,
            h2h_home_wins=home_wins, h2h_matches=len(meetings),
            data_points_home=counts[h], data_points_away=counts[a],
        )
        out.append({**feats, "label": result_label(sh, sa),
                    "date": r["date"], "competition": r["competition"],
                    "pre_home": r["pre_home"], "pre_away": r["pre_away"]})

        # Fold this match into the rolling state AFTER emitting (leak-free).
        recent[h].append((sh, sa))
        recent[a].append((sa, sh))
        counts[h] += 1
        counts[a] += 1
        winner = h if sh > sa else (a if sa > sh else None)
        h2h[pair].append(winner)
    return out


def training_weight(row: dict, ref_date: date) -> float:
    """Sample weight: exponential recency decay (~8yr half-life) × competition tier.
    Friendlies carry half weight (noisier, weaker line-ups)."""
    age_days = max(0, (ref_date - row["date"]).days)
    recency = 0.5 ** (age_days / _HALF_LIFE_DAYS)
    comp = (row.get("competition") or "").lower()
    tier = 0.5 if "friendly" in comp else 1.0
    return recency * tier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest ml/features/training_rows_test.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add ml/features/training_rows.py ml/features/training_rows_test.py
git commit -m "feat(ml): leak-free training-row builder for the W/D/L booster"
```

---

## Task 3: The booster model (`ml/models/wdl_boost.py`)

**Files:**
- Create: `ml/models/wdl_boost.py`
- Test: `ml/models/wdl_boost_test.py`

- [ ] **Step 1: Write the failing test**

```python
# ml/models/wdl_boost_test.py
"""Tests for the HistGradientBoosting W/D/L challenger + blend helper."""
import pytest

from ml.features.wdl_features import assemble_features
from ml.models.wdl_boost import WdlBoost, blend_triples


def _feat(elo_home, elo_away):
    return assemble_features(
        elo_home=elo_home, elo_away=elo_away, is_neutral=True,
        form_home=15.0, form_away=15.0,
        gf_avg_home=1.4, gf_avg_away=1.4, ga_avg_home=1.2, ga_avg_away=1.2,
        h2h_home_wins=0, h2h_matches=0,
        data_points_home=10, data_points_away=10,
    )


def _training_rows():
    """Strong home edge → home win; strong away edge → away win; level → draw."""
    rows = []
    for _ in range(80):
        rows.append({**_feat(1900, 1500), "label": "H"})
        rows.append({**_feat(1500, 1900), "label": "A"})
        rows.append({**_feat(1700, 1700), "label": "D"})
    return rows


def test_predict_proba_is_a_simplex():
    model = WdlBoost().fit(_training_rows())
    probs = model.predict_proba(_feat(1850, 1500))
    assert set(probs.keys()) == {"H", "D", "A"}
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in probs.values())


def test_learns_home_edge():
    model = WdlBoost().fit(_training_rows())
    assert model.predict_proba(_feat(1900, 1500))["H"] > model.predict_proba(_feat(1500, 1900))["H"]


def test_deterministic_under_fixed_seed():
    a = WdlBoost().fit(_training_rows()).predict_proba(_feat(1800, 1550))
    b = WdlBoost().fit(_training_rows()).predict_proba(_feat(1800, 1550))
    assert a == b


def test_unfitted_raises():
    with pytest.raises(RuntimeError):
        WdlBoost().predict_proba(_feat(1700, 1700))


def test_blend_triples_weights_and_normalizes():
    poisson = (0.5, 0.3, 0.2)
    boost = (0.1, 0.1, 0.8)
    assert blend_triples(poisson, boost, 0.0) == pytest.approx(poisson)
    assert blend_triples(poisson, boost, 1.0) == pytest.approx(boost)
    mid = blend_triples(poisson, boost, 0.5)
    assert sum(mid) == pytest.approx(1.0)
    assert mid[2] == pytest.approx(0.5)   # (0.2 + 0.8) / 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/wdl_boost_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ml.models.wdl_boost'`

- [ ] **Step 3: Write minimal implementation**

```python
# ml/models/wdl_boost.py
"""Gradient-boosted W/D/L challenger (spec 2026-06-18).

A thin wrapper over scikit-learn's HistGradientBoostingClassifier (histogram
gradient boosting — the same technique as XGBoost, but already a dependency, no
native libs, free-tier-Render-safe). It outputs ONLY a W/D/L triple; it never
produces scorelines. Trained on leak-free rows from
ml.features.training_rows.build_training_rows.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.features.wdl_features import to_vector

CLASSES = ("H", "D", "A")
_SEED = 2026


class WdlBoost:
    def __init__(self, **kwargs):
        # Conservative, fast defaults; international football is low-signal so we
        # keep the model shallow to avoid overfitting.
        params = dict(
            loss="log_loss", learning_rate=0.05, max_iter=300,
            max_leaf_nodes=15, min_samples_leaf=50, l2_regularization=1.0,
            early_stopping=True, random_state=_SEED,
        )
        params.update(kwargs)
        self._clf = HistGradientBoostingClassifier(**params)
        self._fitted = False

    def fit(self, rows: list[dict], sample_weight: list[float] | None = None) -> "WdlBoost":
        """Train on rows that each carry the FEATURE_NAMES keys plus a 'label'."""
        X = np.array([to_vector(r) for r in rows], dtype=float)
        y = np.array([r["label"] for r in rows])
        sw = np.array(sample_weight, dtype=float) if sample_weight is not None else None
        self._clf.fit(X, y, sample_weight=sw)
        self._fitted = True
        return self

    def predict_proba(self, feats: dict) -> dict[str, float]:
        """Return {'H','D','A': prob}. Classes absent from training map to 0.0."""
        if not self._fitted:
            raise RuntimeError("model not fitted")
        row = np.array([to_vector(feats)], dtype=float)
        probs = self._clf.predict_proba(row)[0]
        by_class = {cls: float(probs[i]) for i, cls in enumerate(self._clf.classes_)}
        return {c: by_class.get(c, 0.0) for c in CLASSES}


def blend_triples(
    a: tuple[float, float, float], b: tuple[float, float, float], weight: float
) -> tuple[float, float, float]:
    """Convex blend (1-weight)*a + weight*b over a W/D/L triple, renormalized."""
    mixed = [(1.0 - weight) * ai + weight * bi for ai, bi in zip(a, b)]
    total = sum(mixed) or 1.0
    return (mixed[0] / total, mixed[1] / total, mixed[2] / total)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/wdl_boost_test.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add ml/models/wdl_boost.py ml/models/wdl_boost_test.py
git commit -m "feat(ml): HistGradientBoosting W/D/L challenger + blend helper"
```

---

## Task 4: `wdl_blend` param (`ml/models/params.py`)

**Files:**
- Modify: `ml/models/params.py` (dataclass field + `load_params`)
- Modify: `ml/models/params_test.py` (add round-trip tests)
- Modify: `ml/models/model_params.json` (add explicit `"wdl_blend": null`)

- [ ] **Step 1: Write the failing test** — append to `ml/models/params_test.py`

```python
def test_default_params_have_no_wdl_blend():
    assert DEFAULT_PARAMS.wdl_blend is None


def test_wdl_blend_round_trips_through_save_load(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    blend = {"weight": 0.35, "calibrator": {"method": "vector_scaling", "t": 1.1, "b": [0.0, 0.2, 0.0]}}
    p = ModelParams(version="v0.2+blend", base=1.2, beta=0.0021, home_adv=60.0,
                    rho=-0.06, temperature=1.0, pk_beta=0.0, wdl_blend=blend)
    save_params(p)
    assert load_params().wdl_blend == blend


def test_json_without_wdl_blend_loads_as_none(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    f.write_text(json.dumps({
        "version": "v0.2", "base": 1.2, "beta": 0.0021, "home_adv": 60.0,
        "rho": -0.06, "temperature": 1.0, "pk_beta": 0.0,
    }))
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_params().wdl_blend is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest ml/models/params_test.py -v`
Expected: FAIL with `TypeError: ModelParams.__init__() got an unexpected keyword argument 'wdl_blend'`

- [ ] **Step 3: Write minimal implementation**

In `ml/models/params.py`, add the field to the dataclass (after `calibrator`):

```python
    calibrator: dict | None = None  # vector-scaling blob or None (temperature-only)
    wdl_blend: dict | None = None    # {"weight": float, "calibrator": dict|None} or None
```

In `load_params()`, add to the returned `ModelParams(...)`:

```python
        calibrator=data.get("calibrator"),
        wdl_blend=data.get("wdl_blend"),
    )
```

`save_params` and `to_dict` need no change (they use `asdict`). Then set the shipped default in `ml/models/model_params.json` — add the key:

```json
{
  "version": "poisson-elo-v0.2",
  "base": 1.2,
  "beta": 0.0021,
  "home_adv": 60.0,
  "rho": -0.06,
  "temperature": 1.0,
  "pk_beta": 0.0,
  "calibrator": null,
  "wdl_blend": null
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest ml/models/params_test.py -v`
Expected: PASS (all params tests, including the 3 new)

- [ ] **Step 5: Commit**

```bash
git add ml/models/params.py ml/models/params_test.py ml/models/model_params.json
git commit -m "feat(ml): add nullable wdl_blend param (default null, shelved)"
```

---

## Task 5: Serving — blend in `build_payload` (`pipeline/generate_predictions.py`)

**Files:**
- Modify: `pipeline/generate_predictions.py` (`build_payload` signature + blend; `generate_predictions` trains booster once; new `_boost_features` helper)
- Modify: `pipeline/generate_predictions_test.py` (no-regression + blend-shift + parity tests)

The booster's serving features are computed from `HistoricalMatch` (each team's last-10, the pair's last-5 via the existing `head_to_head`) through the SAME `window_stats`/`assemble_features` used in training — so no train/serve skew and no dependency on `team_stats.py`.

- [ ] **Step 1: Write the failing tests** — append to `pipeline/generate_predictions_test.py`

```python
def test_blend_off_is_identical_to_poisson(db_session):
    """wdl_blend=None (and no booster) ⇒ probabilities are exactly the Poisson card."""
    from dataclasses import replace
    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (db_session.query(Match)
             .filter(Match.stage == "group", Match.team_home_id.isnot(None)).first())
    params = replace(DEFAULT_PARAMS, wdl_blend=None)

    base = build_payload(db_session, match, "v", params=params)
    again = build_payload(db_session, match, "v", params=params, booster=None)
    assert base["probabilities"] == again["probabilities"]


class _StubBooster:
    """Returns a fixed, strongly-home triple regardless of features."""
    def predict_proba(self, feats):
        return {"H": 0.90, "D": 0.06, "A": 0.04}


def test_blend_shifts_probabilities_toward_booster(db_session):
    from dataclasses import replace
    from ml.models.params import DEFAULT_PARAMS

    load_structure(db_session)
    _set_elos(db_session)
    match = (db_session.query(Match)
             .filter(Match.stage == "group", Match.team_home_id.isnot(None)).first())

    off = build_payload(db_session, match, "v",
                        params=replace(DEFAULT_PARAMS, wdl_blend=None))
    # weight=1.0 ⇒ served triple becomes the booster's (then calibrated; calibrator None).
    on = build_payload(db_session, match, "v",
                       params=replace(DEFAULT_PARAMS, wdl_blend={"weight": 1.0, "calibrator": None}),
                       booster=_StubBooster())

    assert on["probabilities"]["home_win"] > off["probabilities"]["home_win"]
    p = on["probabilities"]
    assert abs(p["home_win"] + p["draw"] + p["away_win"] - 1.0) < 0.01
    # Predicted SCORE stays Poisson's — the booster never touches it.
    assert on["predicted_score"] == off["predicted_score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py -v -k "blend"`
Expected: FAIL with `TypeError: build_payload() got an unexpected keyword argument 'booster'`

- [ ] **Step 3: Write minimal implementation** in `pipeline/generate_predictions.py`

Add imports near the top:

```python
from app.models import Group, GroupTeam, HistoricalMatch, Match, Prediction, Standing, Team, TournamentOdds
from ml.evaluation.calibration import calibrate
from ml.features.build_features import build_match_features, estimate_strength, head_to_head
from ml.features.wdl_features import assemble_features, window_stats
from ml.models.wdl_boost import WdlBoost, blend_triples
```

(`HistoricalMatch`, `calibrate`, `head_to_head`, `assemble_features`, `window_stats`, `WdlBoost`, `blend_triples` are the additions; keep the existing imports.)

Add the serving feature helper (module-level):

```python
def _recent_appearances(db: Session, team_id: int, limit: int = 10) -> list[tuple[int, int]]:
    """A team's most-recent (goals_for, goals_against) from played history."""
    rows = (
        db.query(HistoricalMatch)
        .filter(
            (HistoricalMatch.team_a_id == team_id) | (HistoricalMatch.team_b_id == team_id),
            HistoricalMatch.score_a.isnot(None), HistoricalMatch.score_b.isnot(None),
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(limit)
        .all()
    )
    out: list[tuple[int, int]] = []
    for m in rows:
        if m.team_a_id == team_id:
            out.append((m.score_a, m.score_b))
        else:
            out.append((m.score_b, m.score_a))
    return out


def _boost_features(db: Session, home: Team, away: Team,
                    elo_home: float, elo_away: float, is_neutral: bool) -> dict:
    """Assemble the booster's feature dict for an upcoming match — same schema and
    reducer as training (leak-free: all of history precedes a scheduled fixture)."""
    form_h, gf_h, ga_h, n_h = window_stats(_recent_appearances(db, home.id))
    form_a, gf_a, ga_a, n_a = window_stats(_recent_appearances(db, away.id))
    h2h = head_to_head(db, home.id, away.id)   # last-5, home perspective: a_wins/matches
    return assemble_features(
        elo_home=elo_home, elo_away=elo_away, is_neutral=is_neutral,
        form_home=form_h, form_away=form_a,
        gf_avg_home=gf_h, gf_avg_away=gf_a, ga_avg_home=ga_h, ga_avg_away=ga_a,
        h2h_home_wins=h2h["a_wins"], h2h_matches=h2h["matches"],
        data_points_home=n_h, data_points_away=n_a,
    )
```

Change `build_payload`'s signature to accept the booster:

```python
def build_payload(
    db: Session, match: Match, model_version: str,
    strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
    booster: "WdlBoost | None" = None,
) -> dict | None:
```

After the `pred = predict_match(...)` call (currently lines ~60-64), insert the blend. Replace the block that currently reads `pred.prob_home_win` etc. into `confidence`/`reasons`/payload with blended values:

```python
    # Poisson W/D/L is the base. If a booster blend is shipped (and a trained
    # booster is supplied), blend toward it and re-calibrate. The SCORELINE stays
    # Poisson's — the booster only refines the W/D/L triple (spec §1).
    p_home, p_draw, p_away = pred.prob_home_win, pred.prob_draw, pred.prob_away_win
    if params.wdl_blend and booster is not None:
        feats_v = _boost_features(db, home, away, elo_home, elo_away, match.is_neutral)
        b = booster.predict_proba(feats_v)
        p_home, p_draw, p_away = blend_triples(
            (p_home, p_draw, p_away), (b["H"], b["D"], b["A"]), params.wdl_blend["weight"]
        )
        p_home, p_draw, p_away = calibrate(
            (p_home, p_draw, p_away), params.wdl_blend.get("calibrator")
        )
```

Then change the downstream uses of the probabilities to the blended locals: `confidence_level(p_home, p_draw, p_away, ...)`, `generate_reasons(..., p_home, p_draw, p_away)`, and the payload's `"probabilities"` block:

```python
        "probabilities": {
            "home_win": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away_win": round(p_away, 4),
        },
```

(Leave `predicted_score`, `lambda_home/away`, `rho` sourced from `pred`/`params` unchanged.)

Finally, in `generate_predictions`, train the booster once when the blend is shipped, and thread it into `build_payload`:

```python
    params = load_params()
    active_model_version = model_version or params.version
    strengths = effective_elos(db)

    booster = None
    if params.wdl_blend:
        from datetime import date
        from pipeline.backtest_data import build_enriched_rows
        from ml.features.training_rows import build_training_rows, training_weight

        train_rows = build_training_rows(build_enriched_rows(db))
        if train_rows:
            ref = max(r["date"] for r in train_rows)
            weights = [training_weight(r, ref) for r in train_rows]
            booster = WdlBoost().fit(train_rows, sample_weight=weights)
```

and pass it in the loop:

```python
        payload = build_payload(db, match, active_model_version,
                                strengths=strengths, params=params, booster=booster)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py -v`
Expected: PASS (existing tests + the 2 new blend tests; `test_blend_off_is_identical_to_poisson` proves no regression)

- [ ] **Step 5: Commit**

```bash
git add pipeline/generate_predictions.py pipeline/generate_predictions_test.py
git commit -m "feat(ml): blend booster W/D/L into served predictions when shipped"
```

---

## Task 6: Train/serve parity test

**Files:**
- Modify: `pipeline/generate_predictions_test.py` (add one parity test)

Guards the highest-risk property: that `_boost_features` (serving) and `build_training_rows` (training) produce the same vector for the same history.

- [ ] **Step 1: Write the failing test** — append to `pipeline/generate_predictions_test.py`

```python
def test_serving_features_match_training_features(db_session):
    """For the same match history, the serving feature vector equals the training
    feature row — proving no train/serve skew."""
    from datetime import date
    from app.models import HistoricalMatch, Team
    from ml.features.training_rows import build_training_rows
    from ml.features.wdl_features import FEATURE_NAMES
    from pipeline.generate_predictions import _boost_features

    home = Team(name="Alpha"); away = Team(name="Beta"); other = Team(name="Gamma")
    db_session.add_all([home, away, other]); db_session.commit()

    # Three prior played matches, oldest first.
    hist = [
        HistoricalMatch(team_a_id=home.id, team_b_id=other.id, score_a=2, score_b=0,
                        competition="Friendly", is_neutral=False, date=date(2023, 1, 1)),
        HistoricalMatch(team_a_id=away.id, team_b_id=other.id, score_a=1, score_b=1,
                        competition="Friendly", is_neutral=False, date=date(2023, 2, 1)),
        HistoricalMatch(team_a_id=home.id, team_b_id=away.id, score_a=0, score_b=1,
                        competition="Friendly", is_neutral=True, date=date(2023, 3, 1)),
    ]
    db_session.add_all(hist); db_session.commit()

    # The "upcoming" match is home vs away — a 4th meeting. Serving features use all
    # history (every played match precedes a scheduled fixture).
    serving = _boost_features(db_session, home, away,
                              elo_home=1500.0, elo_away=1500.0, is_neutral=True)

    # Training: append the same upcoming pairing as the LAST enriched row; its
    # feature row must equal the serving vector. (Elo pre-match = 1500 baseline here
    # since we don't replay Elo in this hermetic test — assemble uses what we pass.)
    enriched = [
        {"home_id": home.id, "away_id": other.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": False, "competition": "Friendly", "score_home": 2, "score_away": 0,
         "date": date(2023, 1, 1)},
        {"home_id": away.id, "away_id": other.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": False, "competition": "Friendly", "score_home": 1, "score_away": 1,
         "date": date(2023, 2, 1)},
        {"home_id": home.id, "away_id": away.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": True, "competition": "Friendly", "score_home": 0, "score_away": 1,
         "date": date(2023, 3, 1)},
        {"home_id": home.id, "away_id": away.id, "pre_home": 1500.0, "pre_away": 1500.0,
         "is_neutral": True, "competition": "Friendly", "score_home": 0, "score_away": 0,
         "date": date(2023, 4, 1)},
    ]
    train_row = build_training_rows(enriched)[-1]
    for name in FEATURE_NAMES:
        assert serving[name] == train_row[name], f"skew in {name}"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py::test_serving_features_match_training_features -v`
Expected: PASS if Tasks 1–5 are correct. If it FAILS, the mismatch names the skewed feature — fix `_boost_features` or `build_training_rows` so the windowing matches, then re-run.

- [ ] **Step 3: (only if failing) reconcile** the two paths until the vectors match. No new code if it already passes.

- [ ] **Step 4: Commit**

```bash
git add pipeline/generate_predictions_test.py
git commit -m "test(ml): train/serve feature parity for the W/D/L booster"
```

---

## Task 7: The gate (`pipeline/experiment_model_eval.py`)

**Files:**
- Modify: `pipeline/experiment_model_eval.py` (add `run_blend_gate` + wire into `main`)
- Create: `pipeline/experiment_model_eval_gate_test.py` (smoke test)

Fits ONE booster on all leak-free history before the test cutoff, fits the blend weight on a held-out tail (never on test), then scores `blend` vs `Poisson-alone` on the held-out major-tournament finals with the existing edition-clustered bootstrap.

- [ ] **Step 1: Write the failing test**

```python
# pipeline/experiment_model_eval_gate_test.py
"""Smoke test for the booster blend gate."""
from datetime import date

from pipeline.experiment_model_eval import run_blend_gate


def _rows():
    """Synthetic enriched rows: strong home edge → home win; spread across years so
    there is a pre-2018 train span, a tail, and 2018+ finals to test on."""
    rows = []
    for yr in range(2004, 2024):
        comp = "FIFA World Cup" if yr % 4 == 2 else "Friendly"
        for i in range(30):
            rows.append({
                "home_id": 1 + (i % 8), "away_id": 1 + ((i + 3) % 8),
                "pre_home": 1800.0, "pre_away": 1500.0, "is_neutral": True,
                "competition": comp, "score_home": 2, "score_away": 0,
                "date": date(yr, 6, 1 + (i % 20)),
            })
    return rows


def test_blend_gate_runs_and_reports_a_verdict():
    res = run_blend_gate(_rows(), train_lo=2004, tail_years=2, test_since=2018, n_boot=50)
    assert "delta_log_loss" in res
    assert "ll_ci" in res and len(res["ll_ci"]) == 2
    assert "weight" in res
    assert res["test_n"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_blend_gate'`

- [ ] **Step 3: Write minimal implementation** — add to `pipeline/experiment_model_eval.py`

Add imports at the top (with the existing imports):

```python
from ml.features.training_rows import build_training_rows, training_weight
from ml.models.wdl_boost import WdlBoost, blend_triples
from ml.evaluation.calibration import calibrate, fit_vector_scaling
```

Add the gate function (place near `run_global_split`). It operates directly on the
feature rows from `build_training_rows` — each carries `pre_home`/`pre_away` for the
Poisson side and all `FEATURE_NAMES` keys for the booster, so no join is needed:

```python
def run_blend_gate(rows: list[dict], train_lo: int = 2004, tail_years: int = 2,
                   test_since: int = 2018, n_boot: int = 2000) -> dict:
    """Honest ship test for the booster blend.

    1. Train ONE booster on leak-free history in [train_lo, test_since) minus a
       held-out tail (recency + competition-tier weighted).
    2. Fit the blend weight on the tail (the `tail_years` before the test cutoff),
       minimizing log-loss; fit a vector-scaling calibrator on the blended tail probs.
    3. Score blend vs Poisson-alone (served params) on test_since+ major finals with
       the edition-clustered bootstrap. Promote only if the log-loss CI excludes 0
       (better).
    """
    feat_rows = build_training_rows(rows)
    test_start = date(test_since, 1, 1)
    tail_start = date(test_since - tail_years, 1, 1)

    train = [r for r in feat_rows if train_lo <= r["date"].year and r["date"] < tail_start]
    tail = [r for r in feat_rows if tail_start <= r["date"] < test_start]
    test = [r for r in feat_rows
            if r["date"].year >= test_since and is_major_final(r["competition"])]

    ref = max((r["date"] for r in train), default=test_start)
    weights = [training_weight(r, ref) for r in train]
    booster = WdlBoost().fit(train, sample_weight=weights)

    served = DEFAULT_PARAMS  # blend against the engine we actually serve

    def poisson_triple(fr: dict) -> tuple:
        # is_neutral is the 0.0/1.0 feature; 0.0 is falsy → home_adv applies. Correct.
        return wdl_and_grid(fr["pre_home"], fr["pre_away"], fr["is_neutral"], served)[0]

    def boost_triple(fr: dict) -> tuple:
        b = booster.predict_proba(fr)   # fr has every FEATURE_NAMES key; extras ignored
        return (b["H"], b["D"], b["A"])

    # Precompute (poisson, boost, label_idx) for the tail once, then grid-search w.
    tail_pb = [(poisson_triple(fr), boost_triple(fr), _LABEL_INDEX[fr["label"]]) for fr in tail]

    def ll_for_weight(w: float) -> float:
        if not tail_pb:
            return float("inf")
        s = 0.0
        for pz, bz, idx in tail_pb:
            tri = blend_triples(pz, bz, w)
            s -= math.log(max(_EPS, min(1 - _EPS, tri[idx])))
        return s / len(tail_pb)

    weight = min((i / 20 for i in range(21)), key=ll_for_weight)  # grid 0.0..1.0 step .05

    if tail_pb:
        blended_tail = [blend_triples(pz, bz, weight) for pz, bz, _ in tail_pb]
        labels_tail = [idx for _, _, idx in tail_pb]
        t, b = fit_vector_scaling(blended_tail, labels_tail)
        calibrator = {"method": "vector_scaling", "t": t, "b": list(b)}
    else:
        calibrator = None

    base_ll, blend_ll, ed_keys = [], [], []
    for fr in test:
        idx = _LABEL_INDEX[fr["label"]]
        pz = poisson_triple(fr)
        tri = calibrate(blend_triples(pz, boost_triple(fr), weight), calibrator)
        base_ll.append(-math.log(max(_EPS, min(1 - _EPS, pz[idx]))))
        blend_ll.append(-math.log(max(_EPS, min(1 - _EPS, tri[idx]))))
        ed_keys.append((fr["competition"], fr["date"].year))

    rng = np.random.default_rng(2026)
    d_ll = np.array(blend_ll) - np.array(base_ll)
    ci = block_bootstrap_ci(d_ll, ed_keys, n_boot, rng) if len(d_ll) else (0.0, 0.0)

    return {
        "weight": round(weight, 3),
        "calibrator": calibrator,
        "train_n": len(train), "tail_n": len(tail), "test_n": len(test),
        "delta_log_loss": float(d_ll.mean()) if len(d_ll) else 0.0,
        "ll_ci": ci,
        "verdict": "SHIP" if (ci[1] < 0) else "do-not-ship",
    }
```

Wire the verdict into `main()` after the global-split block:

```python
    print("\n==== Booster blend gate (HistGradientBoosting) ====")
    bg = run_blend_gate(rows, n_boot=args.boot)
    print(f"  weight={bg['weight']}  train_n={bg['train_n']} tail_n={bg['tail_n']} test_n={bg['test_n']}")
    print(f"  d_logloss={bg['delta_log_loss']:+.4f}  CI[{bg['ll_ci'][0]:+.4f},{bg['ll_ci'][1]:+.4f}]  -> {bg['verdict']}")
    if bg["verdict"] == "SHIP":
        print(f"  SHIP blob: {{\"weight\": {bg['weight']}, \"calibrator\": {bg['calibrator']}}}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest pipeline/experiment_model_eval_gate_test.py -v`
Expected: PASS (1 passed). Also run the touched modules: `.venv/bin/python -m pytest pipeline/ ml/ -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add pipeline/experiment_model_eval.py pipeline/experiment_model_eval_gate_test.py
git commit -m "feat(ml): booster blend gate (edition-clustered, ship-or-shelve)"
```

---

## Task 8: Run the gate, record the verdict, set `model_params.json`

**Files:**
- Modify: `docs/superpowers/specs/2026-06-18-xgboost-wdl-challenger-design.md` (fill the "Gate result" section)
- Modify: `ml/models/model_params.json` (flip `wdl_blend` to the fitted blob ONLY if the gate says SHIP; otherwise leave `null`)

This is the decisive ship/shelve step — it needs the real database (run after `make` ingest/Elo so `HistoricalMatch` is populated).

- [ ] **Step 1: Run the full suite (gate must be green first)**

Run: `make test-py`
Expected: all Python tests pass.

- [ ] **Step 2: Run the gate on real data**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_model_eval --since 2004 --boot 2000`
Expected: prints the existing tables plus the new `Booster blend gate` block with `weight`, `d_logloss`, a CI, and a `SHIP`/`do-not-ship` verdict.

- [ ] **Step 3: Record the verdict in the spec**

Append a "Gate result (2026-06-18)" section to the spec mirroring the calibrator spec: the d_logloss, the CI, the per-the-bar pass/fail table, and the decision. Be honest — if it doesn't clear, say so.

- [ ] **Step 4: Set `model_params.json` accordingly**

- If verdict is **do-not-ship**: leave `"wdl_blend": null` (no production change — infra stays in place).
- If verdict is **SHIP**: paste the printed blob, e.g. `"wdl_blend": {"weight": 0.30, "calibrator": {"method": "vector_scaling", "t": 1.05, "b": [0.0, 0.2, 0.0]}}`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-06-18-xgboost-wdl-challenger-design.md ml/models/model_params.json
git commit -m "chore(ml): record W/D/L booster gate verdict; set wdl_blend"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** §1 boundary → Task 5 (scoreline untouched, asserted). §2 leak-free features → Tasks 1–2 (+ parity Task 6). §3 model wrapper → Task 3. §4 gate → Task 7. §5 serving/params → Tasks 4–5. §6 train-on-refresh, no artifact → Task 5 (`generate_predictions` trains in-process; no file written). §7 tests → all of 1–6. Non-goals (live, odds, sims) → untouched. Covered.
- **Placeholder scan:** the only intentional "TBD" is the spec's Gate-result section, filled by Task 8 (its value is the run output, unknowable until executed). No code placeholders — Task 7's gate operates directly on the feature rows with no stubs or join helpers.
- **Type consistency:** `FEATURE_NAMES`/`assemble_features`/`to_vector`/`window_stats` (Task 1) are used identically in Tasks 2, 5, 6. `WdlBoost.fit(rows, sample_weight=)` / `.predict_proba(dict)->{"H","D","A"}` and `blend_triples(a,b,w)` (Task 3) are called the same way in Tasks 5 and 7. `ModelParams.wdl_blend` shape `{"weight", "calibrator"}` (Task 4) matches its reads in Tasks 5 and 7. `_boost_features` ↔ `build_training_rows` parity is enforced by Task 6.
- **Cross-task dependency:** Task 7's gate reads `pre_home`/`pre_away` off each training row — these are emitted by `build_training_rows` in Task 2 (and excluded from `FEATURE_NAMES`, so the booster never sees them). No separate edit needed; it lands with Task 2.
