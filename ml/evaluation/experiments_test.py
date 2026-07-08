"""Tests for the variant/ablation runner (model v2 design doc §5).

A variant is a plain dict — {name, params, form_channels, calibrator} — so new
ablations are config, not code. score_variant scores one variant on a set of
target rows; run_experiments does the walk-forward train/val/target split (like
ml.evaluation.backtest.walk_forward) and scores every named variant on the
held-out tournament, returning one metrics table.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ml.evaluation.experiments import (
    build_variant,
    run_experiments,
    score_variant,
)
from ml.models.params import DEFAULT_PARAMS


def _row(pre_home, pre_away, sh, sa, date, is_neutral=True, competition="Friendly",
         ledger_home=None, ledger_away=None, home_id=None, away_id=None):
    # tune_form walks a per-team running ledger, so rows need stable team ids
    # (real enriched rows carry them from backtest_data). The synthetic fixtures
    # reuse the same strong/weak pair everywhere, so "one id per rating" is a
    # faithful default.
    return {
        "pre_home": pre_home, "pre_away": pre_away, "is_neutral": is_neutral,
        "score_home": sh, "score_away": sa, "date": date, "competition": competition,
        "ledger_home": ledger_home or [], "ledger_away": ledger_away or [],
        "home_id": home_id if home_id is not None else int(pre_home),
        "away_id": away_id if away_id is not None else int(pre_away),
    }


def _synthetic_rows(n_train=520, wc_year=2018):
    """Training rows span the six years BEFORE `wc_year`, spread so the two
    years immediately preceding it (the tuner's default 730-day validation
    window) alone clear MIN_VAL_MATCHES=100."""
    rows = []
    for i in range(n_train):
        strong_home = i % 2 == 0
        pre_home, pre_away = (1900, 1500) if strong_home else (1500, 1900)
        sh, sa = (3, 0) if strong_home else (0, 3)
        if i % 6 == 0:
            sh, sa = 1, 1
        year = (wc_year - 6) + i % 6  # wc_year-6 .. wc_year-1, last 2 in-window
        month = 1 + (i // 6) % 12
        day = 1 + i % 27
        rows.append(_row(pre_home, pre_away, sh, sa,
                          datetime(year, month, day, tzinfo=timezone.utc)))
    for j in range(20):
        rows.append(_row(1950, 1450, 2, 0, datetime(wc_year, 6, 1 + j % 27, tzinfo=timezone.utc),
                          competition="FIFA World Cup"))
    return rows


# ---------------------------------------------------------------------------
# score_variant
# ---------------------------------------------------------------------------

def test_score_variant_v01_raw_matches_default_params():
    """The 'v0.1-raw' built-in must reduce to the DEFAULT_PARAMS engine
    (bit-identical to model_probs with no overrides)."""
    from ml.evaluation.backtest import model_probs

    rows = _synthetic_rows()
    target = [r for r in rows if r["competition"] == "FIFA World Cup"]
    variant = {"name": "v0.1-raw", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": None}
    result = score_variant(target, variant)

    expected_probs = [
        model_probs(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target
    ]
    assert result["n"] == len(target)
    # log_loss should match compute_metrics on the same raw probs exactly.
    from ml.evaluation.backtest import compute_metrics
    from ml.models.baseline_logistic import result_label
    labels = [result_label(r["score_home"], r["score_away"]) for r in target]
    expected = compute_metrics(expected_probs, labels)
    assert result["log_loss"] == pytest.approx(expected["log_loss"])
    assert result["brier"] == pytest.approx(expected["brier"])
    assert result["accuracy"] == pytest.approx(expected["accuracy"])


def test_score_variant_returns_ece():
    rows = _synthetic_rows()
    target = [r for r in rows if r["competition"] == "FIFA World Cup"]
    variant = {"name": "v0.1-raw", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": None}
    result = score_variant(target, variant)
    assert "ece" in result
    assert 0.0 <= result["ece"] <= 1.0


def test_score_variant_applies_custom_params():
    """A variant with a different base/beta must diverge from v0.1-raw."""
    rows = _synthetic_rows()
    target = [r for r in rows if r["competition"] == "FIFA World Cup"]
    v01 = {"name": "v0.1-raw", "params": DEFAULT_PARAMS.to_dict(),
           "form_channels": None, "calibrator": None}
    custom_params = DEFAULT_PARAMS.to_dict()
    custom_params["beta"] = 0.0026
    v_custom = {"name": "custom", "params": custom_params,
                "form_channels": None, "calibrator": None}

    r1 = score_variant(target, v01)
    r2 = score_variant(target, v_custom)
    assert r1["log_loss"] != pytest.approx(r2["log_loss"])


def test_score_variant_with_form_channels_changes_result():
    """When form_channels is set and rows carry non-trivial ledgers, the
    scored probabilities must differ from the no-form variant. Uses a
    locally-built FormConfig-shaped dict; guards the ml.ratings.form import."""
    pytest.importorskip("ml.ratings.form", reason="form module not yet merged")

    rows = _synthetic_rows()
    target = [
        _row(1950, 1450, 2, 0, datetime(2018, 6, 1 + j % 27, tzinfo=timezone.utc),
             competition="FIFA World Cup",
             ledger_home=[(1.2, -0.5), (0.8, -0.3), (1.5, 0.1)],
             ledger_away=[(-0.4, 0.6), (-0.2, 0.3)])
        for j in range(20)
    ]
    no_form = {"name": "no-form", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": None}
    with_form = {
        "name": "with-form", "params": DEFAULT_PARAMS.to_dict(),
        "form_channels": {"c_atk": 0.05, "c_def": 0.05, "cap": 0.2, "half_life": 5.0},
        "calibrator": None,
    }
    r1 = score_variant(target, no_form)
    r2 = score_variant(target, with_form)
    assert r1["log_loss"] != pytest.approx(r2["log_loss"])


def test_score_variant_form_channels_none_is_bit_identical_to_no_form_key():
    """form_channels=None must be a true no-op even when ledgers are present
    on the rows (disabled by default = unaffected by ledger content)."""
    rows = [
        _row(1950, 1450, 2, 0, datetime(2018, 6, 1, tzinfo=timezone.utc),
             competition="FIFA World Cup",
             ledger_home=[(1.2, -0.5)], ledger_away=[(-0.4, 0.6)]),
    ]
    variant = {"name": "v0.1-raw", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": None}
    r1 = score_variant(rows, variant)

    rows_no_ledger = [
        _row(1950, 1450, 2, 0, datetime(2018, 6, 1, tzinfo=timezone.utc),
             competition="FIFA World Cup"),
    ]
    r2 = score_variant(rows_no_ledger, variant)
    assert r1["log_loss"] == pytest.approx(r2["log_loss"])


def test_score_variant_with_calibrator_fit_on_validation():
    """calibrator='fit_on_validation' fits a segmented vector-scaling blob on
    the validation rows passed in, then applies it to the target."""
    rows = _synthetic_rows()
    val = [r for r in rows if r["competition"] != "FIFA World Cup"]
    target = [r for r in rows if r["competition"] == "FIFA World Cup"]
    variant = {"name": "v0.2+cal", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": "fit_on_validation"}
    result = score_variant(target, variant, val_rows=val)
    assert result["n"] == len(target)
    assert "log_loss" in result


def test_score_variant_calibrator_requires_val_rows():
    rows = _synthetic_rows()
    target = [r for r in rows if r["competition"] == "FIFA World Cup"]
    variant = {"name": "v0.2+cal", "params": DEFAULT_PARAMS.to_dict(),
               "form_channels": None, "calibrator": "fit_on_validation"}
    with pytest.raises(ValueError):
        score_variant(target, variant)  # no val_rows supplied


# ---------------------------------------------------------------------------
# build_variant (named built-ins)
# ---------------------------------------------------------------------------

def test_build_variant_v01_raw():
    v = build_variant("v0.1-raw", val_rows=_synthetic_rows()[:150])
    assert v["name"] == "v0.1-raw"
    assert v["params"]["version"] == "poisson-elo-v0.1"
    assert v["form_channels"] is None
    assert v["calibrator"] is None


def test_build_variant_v02_tuned_tunes_on_validation_window():
    val = _synthetic_rows()[:150]
    v = build_variant("v0.2-tuned", val_rows=val)
    assert v["name"] == "v0.2-tuned"
    assert v["params"]["version"] == "poisson-elo-v0.2"
    # tuned params should differ from raw v0.1 defaults on this skewed synthetic set
    assert v["params"]["base"] != DEFAULT_PARAMS.base or v["params"]["beta"] != DEFAULT_PARAMS.beta


def test_build_variant_unknown_name_raises():
    with pytest.raises(ValueError):
        build_variant("not-a-real-variant", val_rows=_synthetic_rows()[:150])


def test_build_variant_v02_plus_cal_sets_calibrator():
    val = _synthetic_rows()[:150]
    v = build_variant("v0.2+cal", val_rows=val)
    assert v["calibrator"] == "fit_on_validation"


def test_build_variant_v02_plus_form_requires_form_module_or_notes_absence():
    val = _synthetic_rows()[:150]
    try:
        v = build_variant("v0.2+form", val_rows=val)
    except ImportError:
        pytest.skip("ml.ratings.form not merged yet — acceptable per scope")
    else:
        assert v["form_channels"] is not None


# ---------------------------------------------------------------------------
# run_experiments (full walk-forward table)
# ---------------------------------------------------------------------------

def test_run_experiments_basic_table_shape():
    rows = _synthetic_rows(wc_year=2018)
    table = run_experiments(rows, 2018, variant_names=["v0.1-raw", "v0.2-tuned"])
    assert table["year"] == 2018
    assert table["n_matches"] == 20
    assert set(table["variants"].keys()) == {"v0.1-raw", "v0.2-tuned"}
    for name, metrics in table["variants"].items():
        assert metrics["n"] == 20
        assert "log_loss" in metrics
        assert "brier" in metrics
        assert "accuracy" in metrics
        assert "ece" in metrics


def test_run_experiments_raises_for_missing_year():
    rows = _synthetic_rows(wc_year=2018)
    with pytest.raises(ValueError):
        run_experiments(rows, 1990, variant_names=["v0.1-raw"])


def test_run_experiments_default_variants_include_core_four_when_available():
    rows = _synthetic_rows(wc_year=2018)
    table = run_experiments(rows, 2018)
    names = set(table["variants"].keys())
    assert "v0.1-raw" in names
    assert "v0.2-tuned" in names
    # form/cal variants included only if their dependency module is present;
    # never silently stubbed with fake numbers.
    for optional in ("v0.2+form", "v0.2+cal"):
        if optional in names:
            assert "log_loss" in table["variants"][optional]
