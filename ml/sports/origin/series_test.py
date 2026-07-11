"""series_odds — exact enumeration over the remaining games of a 3-game series."""
import pytest

from ml.sports.origin.series import series_odds
from ml.sports.origin.venues import is_neutral


def test_decided_series_no_remaining():
    assert series_odds(2, 0, []) == {"p_a": 1.0, "p_b": 0.0, "p_drawn": 0.0}
    assert series_odds(1, 1, []) == {"p_a": 0.0, "p_b": 0.0, "p_drawn": 1.0}


def test_single_remaining_game_at_one_all():
    out = series_odds(1, 1, [(0.6, 0.1, 0.3)])
    assert out == pytest.approx({"p_a": 0.6, "p_b": 0.3, "p_drawn": 0.1})


def test_full_series_sums_to_one_and_symmetric():
    g = (0.45, 0.1, 0.45)
    out = series_odds(0, 0, [g, g, g])
    assert out["p_a"] + out["p_b"] + out["p_drawn"] == pytest.approx(1.0)
    assert out["p_a"] == pytest.approx(out["p_b"])


def test_drawn_games_count_toward_drawn_series():
    # 1-0 up with two remaining; opponent wins one, other drawn -> 1-1-1 drawn.
    out = series_odds(1, 0, [(0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])
    assert out == pytest.approx({"p_a": 0.0, "p_b": 0.0, "p_drawn": 1.0})


def test_is_neutral_known_venues_case_insensitive():
    assert is_neutral("Melbourne Cricket Ground")
    assert is_neutral("optus stadium")
    assert not is_neutral("Suncorp Stadium")
    assert not is_neutral(None)
    assert not is_neutral("")
