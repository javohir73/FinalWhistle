"""Tests for the explanation generator (task 3.6)."""
from ml.explain.reasons import confidence_level, generate_reasons, top_features
from ml.features.build_features import MatchFeatures


def _features(**overrides) -> MatchFeatures:
    base = dict(
        elo_home=2000.0, elo_away=1700.0, elo_diff=300.0,
        strength_source_home="elo", strength_source_away="elo",
        fifa_rank_diff=10, form_home=20.0, form_away=8.0, form_diff=12.0,
        goals_for_avg_home=2.2, goals_for_avg_away=1.0, is_home_host=False,
        h2h={"matches": 5, "a_wins": 4, "draws": 0, "b_wins": 1},
        data_points_home=10, data_points_away=10,
    )
    base.update(overrides)
    return MatchFeatures(**base)


def test_confidence_high_when_decisive_and_data_rich():
    assert confidence_level(0.7, 0.2, 0.1, 10, 10, cold_start=False) == "High"


def test_confidence_downgraded_on_cold_start():
    assert confidence_level(0.7, 0.2, 0.1, 10, 10, cold_start=True) == "Medium"


def test_confidence_low_when_close():
    assert confidence_level(0.4, 0.33, 0.27, 10, 10, cold_start=False) == "Low"


def test_confidence_downgraded_on_thin_data():
    assert confidence_level(0.7, 0.2, 0.1, 1, 10, cold_start=False) == "Medium"


def test_generate_reasons_returns_at_least_three():
    reasons = generate_reasons(_features(), "Brazil", "Serbia", 0.62, 0.24, 0.14)
    assert len(reasons) >= 3
    assert any("Elo" in r for r in reasons)


def test_reasons_mention_host_when_applicable():
    reasons = generate_reasons(
        _features(is_home_host=True), "Mexico", "Croatia", 0.5, 0.3, 0.2
    )
    assert any("host" in r.lower() for r in reasons)


def test_top_features_weights_sum_to_one():
    feats = top_features(_features())
    assert abs(sum(x["weight"] for x in feats) - 1.0) < 0.05
    assert feats[0]["name"] == "elo_gap"  # biggest driver here
