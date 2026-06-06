"""Tests for calibration (task 4.7)."""
from ml.evaluation.calibration import (
    apply_temperature,
    fit_temperature,
    reliability_curve,
)


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
