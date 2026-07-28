"""Tests for the T1.6 club calibrator recut — holdout guard first."""
from __future__ import annotations

import pytest

from ml.evaluation.calibration import _GAP_EDGES, apply_vector_scaling
from ml.evaluation.club_calibration import (
    CANDIDATES,
    CONFIRM_SEASON,
    REFIT_FAMILY,
    HoldoutViolation,
    apply_blob,
    assert_holdout_absent,
    brier_one,
    bucket_names,
    bucket_of,
    ece,
    fit_segmented,
    log_loss_one,
    occupancy,
    quantile_edges,
    rps_one,
)

# ---------------------------------------------------------------------------
# Holdout guard. The 2025-26 season was consumed by the #202 confirmation run;
# reading it again would invalidate every number T1.6 produces.
# ---------------------------------------------------------------------------


def test_guard_raises_when_the_consumed_holdout_appears():
    with pytest.raises(HoldoutViolation, match=CONFIRM_SEASON):
        assert_holdout_absent(["2324", "2425", CONFIRM_SEASON], "unit-test")


def test_guard_raises_even_for_a_single_holdout_row_among_many():
    seasons = ["1920"] * 5000 + [CONFIRM_SEASON]
    with pytest.raises(HoldoutViolation):
        assert_holdout_absent(seasons, "unit-test")


def test_guard_passes_on_pre_confirmation_seasons():
    assert_holdout_absent(["1617", "1718", "1819", "1920", "2021",
                           "2122", "2223", "2324", "2425"], "unit-test") is None


def test_guard_names_the_offending_context():
    with pytest.raises(HoldoutViolation, match="outer-train"):
        assert_holdout_absent([CONFIRM_SEASON], "outer-train")


def test_fit_candidate_refuses_to_fit_on_the_holdout():
    from pipeline.experiment_club_calibration import fit_candidate

    train = [{"season": CONFIRM_SEASON, "raw": (0.5, 0.25, 0.25),
              "gap": 10.0, "label": 0}]
    with pytest.raises(HoldoutViolation):
        fit_candidate("refit_q3", train)


def test_the_experiment_loader_drops_the_holdout_before_the_guard_ever_runs(tmp_path):
    """Primary defence is exclusion at load; the guard is only a backstop."""
    import pandas as pd

    from pipeline.experiment_club_calibration import load_league

    rows = lambda n, d: pd.DataFrame({  # noqa: E731
        "Date": [d] * n, "HomeTeam": [f"H{i}" for i in range(n)],
        "AwayTeam": [f"A{i}" for i in range(n)], "FTHG": [1] * n, "FTAG": [0] * n,
    })
    rows(4, "13/08/16").to_csv(tmp_path / "E0_1617.csv", index=False)
    rows(4, "13/08/25").to_csv(tmp_path / f"E0_{CONFIRM_SEASON}.csv", index=False)

    df, _ = load_league("E0", tmp_path)
    assert CONFIRM_SEASON not in set(df.season_code)
    assert set(df.season_code) == {"1617"}


# ---------------------------------------------------------------------------
# Bucketing with edges carried in the blob (the serving path's edges are a
# module constant and are deliberately not mutated).
# ---------------------------------------------------------------------------


def test_bucket_names_and_membership_are_consistent():
    edges = [50.0, 150.0]
    assert bucket_names(edges) == ["0-50", "50-150", "150+"]
    assert bucket_of(0.0, edges) == "0-50"
    assert bucket_of(49.9, edges) == "0-50"
    assert bucket_of(50.0, edges) == "50-150"
    assert bucket_of(149.9, edges) == "50-150"
    assert bucket_of(150.0, edges) == "150+"
    assert bucket_of(9999.0, edges) == "150+"


def test_served_edges_reproduce_the_production_bucket_labels():
    assert bucket_names(list(_GAP_EDGES)) == ["0-50", "50-150", "150-300", "300+"]


def test_quantile_edges_split_the_sample_roughly_evenly():
    gaps = list(range(1000))
    edges = quantile_edges(gaps, 4)
    assert len(edges) == 3
    occ = occupancy(gaps, edges)
    assert len(occ) == 4
    assert max(occ.values()) - min(occ.values()) <= 2


def test_quantile_edges_rejects_a_degenerate_bucket_count():
    with pytest.raises(ValueError):
        quantile_edges([1.0, 2.0], 1)


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def _synthetic(n=800):
    """Draw-heavy truth the raw triple under-predicts, so a fit has work to do."""
    probs, labels, gaps = [], [], []
    for i in range(n):
        probs.append((0.50, 0.20, 0.30))
        labels.append(1 if i % 2 == 0 else (0 if i % 4 == 1 else 2))
        gaps.append(float(i % 400))
    return probs, labels, gaps


def test_fit_records_its_edges_and_training_size():
    p, lab, g = _synthetic()
    blob = fit_segmented(p, lab, g, [100.0, 200.0], min_bucket=50)
    assert blob["edges"] == [100.0, 200.0]
    assert blob["n_train"] == len(lab)
    assert set(blob["buckets"]) == {"0-100", "100-200", "200+"}


def test_a_thin_bucket_inherits_the_global_fit_instead_of_overfitting():
    p, lab, g = _synthetic()
    g = [0.0] * (len(g) - 3) + [900.0, 901.0, 902.0]  # 3 rows in the top bucket
    blob = fit_segmented(p, lab, g, [100.0, 800.0], min_bucket=200)
    assert "800+" in blob["thin_buckets"]
    assert blob["buckets"]["800+"] == blob["default"]


def test_fitting_reduces_training_log_loss_versus_the_raw_triple():
    p, lab, g = _synthetic()
    blob = fit_segmented(p, lab, g, [200.0], min_bucket=50)
    raw = sum(log_loss_one(x, y) for x, y in zip(p, lab)) / len(lab)
    cal = sum(log_loss_one(apply_blob(x, blob, gg), y)
              for x, y, gg in zip(p, lab, g)) / len(lab)
    assert cal < raw


def test_apply_blob_is_the_identity_for_none():
    assert apply_blob((0.5, 0.3, 0.2), None, 10.0) == (0.5, 0.3, 0.2)


def test_apply_blob_matches_the_shared_vector_scaling_primitive():
    blob = {"edges": [100.0],
            "buckets": {"0-100": {"t": 1.3, "b": [0.0, 0.2, -0.1]},
                        "100+": {"t": 0.9, "b": [0.0, -0.3, 0.4]}},
            "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]}}
    p = (0.5, 0.25, 0.25)
    assert apply_blob(p, blob, 10.0) == apply_vector_scaling(p, 1.3, (0.0, 0.2, -0.1))
    assert apply_blob(p, blob, 500.0) == apply_vector_scaling(p, 0.9, (0.0, -0.3, 0.4))


def test_an_unknown_bucket_falls_back_to_default_rather_than_raising():
    blob = {"edges": [100.0], "buckets": {},
            "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]}}
    assert apply_blob((0.5, 0.25, 0.25), blob, 10.0) == pytest.approx((0.5, 0.25, 0.25))


# ---------------------------------------------------------------------------
# Family declaration + metrics
# ---------------------------------------------------------------------------


def test_the_candidate_family_is_fixed_and_contains_both_fixed_references():
    assert CANDIDATES["prod_calibrator"]["kind"] == "served"
    assert CANDIDATES["no_calibrator"]["kind"] == "none"
    assert len(REFIT_FAMILY) == 4
    assert all(CANDIDATES[k]["kind"] == "refit" for k in REFIT_FAMILY)
    # The two fixed references are NOT part of the searched family.
    assert "prod_calibrator" not in REFIT_FAMILY
    assert "no_calibrator" not in REFIT_FAMILY


def test_metrics_behave_on_a_confident_correct_versus_wrong_prediction():
    right, wrong = (0.9, 0.05, 0.05), (0.05, 0.05, 0.9)
    assert log_loss_one(right, 0) < log_loss_one(wrong, 0)
    assert brier_one(right, 0) < brier_one(wrong, 0)
    assert rps_one(right, 0) < rps_one(wrong, 0)


def test_rps_penalises_a_near_miss_less_than_a_far_miss():
    """Ordered scale: predicting Draw when Home happened beats predicting Away."""
    near, far = (0.1, 0.8, 0.1), (0.1, 0.1, 0.8)
    assert rps_one(near, 0) < rps_one(far, 0)


def test_ece_is_zero_for_a_perfectly_calibrated_set_and_positive_otherwise():
    assert ece([(0.5, 1.0), (0.5, 0.0)] * 50) == pytest.approx(0.0, abs=1e-9)
    assert ece([(0.9, 0.0)] * 50) > 0.5


def test_ece_handles_an_empty_sample():
    import math

    assert math.isnan(ece([]))
