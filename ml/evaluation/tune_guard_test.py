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
