"""Tests for naive baselines (task 4.7)."""
from ml.evaluation.naive_baseline import BaseRateBaseline, FavoriteBaseline


def _rows():
    # 6 home-favorite wins, 2 draws, 2 away (favorite-loss) -> known frequencies.
    rows = []
    for _ in range(6):
        rows.append({"pre_home": 1900, "pre_away": 1500, "is_neutral": True,
                     "score_home": 2, "score_away": 0})
    for _ in range(2):
        rows.append({"pre_home": 1900, "pre_away": 1500, "is_neutral": True,
                     "score_home": 1, "score_away": 1})
    for _ in range(2):
        rows.append({"pre_home": 1900, "pre_away": 1500, "is_neutral": True,
                     "score_home": 0, "score_away": 1})
    return rows


def test_base_rate_probs_sum_to_one():
    b = BaseRateBaseline().fit(_rows())
    p = b.predict_proba(1900, 1500, True)
    assert abs(sum(p) - 1.0) < 1e-9


def test_favorite_baseline_learns_favorite_win_rate():
    f = FavoriteBaseline().fit(_rows())
    # 6 favorite wins, 2 draws, 2 favorite losses out of 10
    assert abs(f.p_fav_win - 0.6) < 1e-9
    assert abs(f.p_draw - 0.2) < 1e-9
    assert abs(f.p_fav_loss - 0.2) < 1e-9


def test_favorite_baseline_orients_by_who_is_favorite():
    f = FavoriteBaseline().fit(_rows())
    home_fav = f.predict_proba(1900, 1500, True)   # home favored
    away_fav = f.predict_proba(1500, 1900, True)   # away favored
    assert home_fav[0] > home_fav[2]   # home win prob highest
    assert away_fav[2] > away_fav[0]   # away win prob highest
    assert abs(sum(home_fav) - 1.0) < 1e-9
