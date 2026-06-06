"""Tests for historical odds -> implied probabilities (task 2.10)."""
import pandas as pd
import pytest

from pipeline.ingest.football_data_odds import (
    implied_probabilities,
    prepare_calibration_frame,
)


def test_implied_probabilities_sum_to_one():
    p = implied_probabilities(2.0, 3.5, 4.0)
    assert abs(sum(p) - 1.0) < 1e-9
    # shorter odds -> higher probability
    assert p[0] > p[2]


def test_implied_probabilities_rejects_nonpositive():
    with pytest.raises(ValueError):
        implied_probabilities(0, 3.0, 4.0)


def test_prepare_calibration_frame():
    df = pd.DataFrame(
        [
            {"B365H": 1.5, "B365D": 4.0, "B365A": 7.0, "FTR": "H"},
            {"B365H": 3.0, "B365D": 3.2, "B365A": 2.4, "FTR": "A"},
        ]
    )
    out = prepare_calibration_frame(df)
    assert list(out.columns) == ["p_home", "p_draw", "p_away", "result"]
    assert len(out) == 2
    for _, row in out.iterrows():
        assert abs(row.p_home + row.p_draw + row.p_away - 1.0) < 1e-9
