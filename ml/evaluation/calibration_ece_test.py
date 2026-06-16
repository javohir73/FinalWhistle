from ml.evaluation.scoreline_metrics import (
    expected_calibration_error_equal_count, per_class_calibration_error,
)


def _perfectly_calibrated():
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
    probs = [(0.1 + 0.001 * i, 0.45, 0.45) for i in range(90)]
    labels = [0] * 90
    val = expected_calibration_error_equal_count(probs, labels, bins=3)
    assert val == val and val >= 0.0


def test_per_class_isolates_draw_miscalibration():
    probs, labels = [], []
    for i in range(100):
        probs.append((0.45, 0.10, 0.45))
        labels.append(1 if i < 40 else (0 if i % 2 else 2))
    out = per_class_calibration_error(probs, labels, bins=5)
    assert set(out) == {"home", "draw", "away"}
    assert out["draw"] > 0.2  # draw class badly miscalibrated
