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
