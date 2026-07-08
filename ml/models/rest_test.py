"""Tests for the rest-days signal (pure offset math)."""
from ml.models.rest import DEFAULT_REST, rest_offsets

COEF, CAP = DEFAULT_REST["coef"], DEFAULT_REST["cap"]


def test_equal_rest_cancels_exactly():
    assert rest_offsets(4.0, 4.0, COEF, CAP) == (0.0, 0.0)


def test_better_rested_home_side_gains():
    off_h, off_a = rest_offsets(6.0, 3.0, COEF, CAP)
    assert off_h > 0 > off_a
    assert abs(off_h + off_a) < 1e-12  # symmetric: total goals level preserved


def test_cap_bounds_extreme_differentials():
    off_h, _ = rest_offsets(8.0, 2.0, coef=1.0, cap=CAP)  # absurd coef
    assert off_h == CAP / 2.0


def test_window_clips_long_rests():
    # 9 vs 15 days: both past the window's top — no marginal difference.
    assert rest_offsets(9.0, 15.0, COEF, CAP) == (0.0, 0.0)


def test_openers_have_no_signal():
    assert rest_offsets(None, 4.0, COEF, CAP) is None
    assert rest_offsets(4.0, None, COEF, CAP) is None
