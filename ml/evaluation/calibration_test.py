"""Tests for calibration (task 4.7)."""
from ml.evaluation.calibration import (
    _log_loss,
    apply_temperature,
    apply_vector_scaling,
    calibrate,
    fit_temperature,
    fit_vector_scaling,
    reliability_curve,
)
from ml.evaluation.scoreline_metrics import per_class_calibration_error


def test_temperature_one_is_identity():
    p = (0.6, 0.3, 0.1)
    out = apply_temperature(p, 1.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(out, p))


def test_temperature_above_one_softens():
    p = (0.8, 0.15, 0.05)
    softened = apply_temperature(p, 2.0)
    assert max(softened) < max(p)  # less confident
    assert abs(sum(softened) - 1.0) < 1e-9


def test_temperature_below_one_sharpens():
    p = (0.5, 0.3, 0.2)
    sharper = apply_temperature(p, 0.5)
    assert max(sharper) > max(p)


def test_fit_temperature_softens_overconfident_predictions():
    # Model says 0.9 home every time but only ~half actually happen -> needs T>1.
    probs = [(0.9, 0.05, 0.05)] * 50
    labels = [0] * 25 + [2] * 25
    t = fit_temperature(probs, labels)
    assert t > 1.0


def test_reliability_curve_shape():
    probs = [(0.7, 0.2, 0.1), (0.3, 0.4, 0.3)]
    labels = [0, 1]
    curve = reliability_curve(probs, labels, bins=10)
    assert all({"mean_predicted", "empirical_freq", "count"} <= set(b) for b in curve)


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
    base_ll = _log_loss(probs, labels)
    vec_ll = _log_loss(vec, labels)
    assert vec_ll < base_ll       # beats the uncalibrated input

    # ...and beats the best scalar temperature (which cannot reorder draw>away).
    t_only = fit_temperature(probs, labels)
    temp = [apply_temperature(p, t_only) for p in probs]
    assert vec_ll < _log_loss(temp, labels)

    # draw-class calibration error drops.
    # bins=2 avoids label-ordering artefacts with constant predictions.
    base_draw = per_class_calibration_error(probs, labels, bins=2)["draw"]
    vec_draw = per_class_calibration_error(vec, labels, bins=2)["draw"]
    assert vec_draw < base_draw


def test_fit_vector_scaling_is_near_identity_on_calibrated_data():
    # Already-calibrated data -> no strong correction needed.
    probs = ([(0.5, 0.3, 0.2)] * 50) + ([(0.2, 0.3, 0.5)] * 50)
    labels = ([0] * 25 + [1] * 15 + [2] * 10) + ([2] * 25 + [1] * 15 + [0] * 10)
    t, b = fit_vector_scaling(probs, labels)
    assert 0.8 <= t <= 1.5        # near-identity temperature (not pinned to a grid edge)
    assert abs(b[1]) < 0.3 and abs(b[2]) < 0.3


def test_fit_vector_scaling_rejects_degenerate_grid():
    import pytest

    with pytest.raises(ValueError):
        fit_vector_scaling([(0.5, 0.3, 0.2)], [0], t_steps=1)
    with pytest.raises(ValueError):
        fit_vector_scaling([(0.5, 0.3, 0.2)], [0], b_steps=1)


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


def test_calibrate_unknown_method_falls_back_to_temperature():
    # A blob with a method we don't recognize is treated as no calibrator.
    p = (0.5, 0.3, 0.2)
    blob = {"method": "future_method"}
    assert calibrate(p, blob, temperature=1.4) == apply_temperature(p, 1.4)
