"""Tests for the logistic baseline (task 3.5)."""
from ml.models.baseline_logistic import LogisticBaseline, result_label


def test_result_label():
    assert result_label(2, 1) == "H"
    assert result_label(1, 1) == "D"
    assert result_label(0, 3) == "A"


def _synthetic_rows():
    """Stronger home Elo -> home wins; reversed -> away wins; equal -> draw."""
    rows = []
    for _ in range(60):
        rows.append({"pre_home": 1900, "pre_away": 1500, "is_neutral": True,
                     "score_home": 3, "score_away": 0})
        rows.append({"pre_home": 1500, "pre_away": 1900, "is_neutral": True,
                     "score_home": 0, "score_away": 2})
        rows.append({"pre_home": 1700, "pre_away": 1700, "is_neutral": True,
                     "score_home": 1, "score_away": 1})
    return rows


def test_fit_and_predict_probabilities_sum_to_one():
    model = LogisticBaseline().fit(_synthetic_rows())
    probs = model.predict_proba(400)
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert set(probs.keys()) == {"H", "D", "A"}


def test_stronger_home_predicted_to_win():
    model = LogisticBaseline().fit(_synthetic_rows())
    probs = model.predict_proba(400)  # big home edge
    assert probs["H"] > probs["A"]
    # mirror: big away edge favors away
    probs_away = model.predict_proba(-400)
    assert probs_away["A"] > probs_away["H"]


def test_unfitted_raises():
    import pytest

    with pytest.raises(RuntimeError):
        LogisticBaseline().predict_proba(0)
