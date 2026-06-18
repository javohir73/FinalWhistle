"""Tests for the canonical W/D/L booster feature schema."""
from ml.features.wdl_features import (
    FEATURE_NAMES,
    assemble_features,
    to_vector,
    window_stats,
    DEFAULT_GOALS_AVG,
)


def _inputs(**over):
    base = dict(
        elo_home=1700.0, elo_away=1500.0, is_neutral=True,
        form_home=18.0, form_away=9.0,
        gf_avg_home=2.0, gf_avg_away=1.0, ga_avg_home=0.8, ga_avg_away=1.5,
        h2h_home_wins=3, h2h_matches=5,
        data_points_home=10, data_points_away=10,
    )
    base.update(over)
    return base


def test_assemble_has_every_feature_name():
    feats = assemble_features(**_inputs())
    assert set(feats.keys()) == set(FEATURE_NAMES)


def test_derived_fields():
    feats = assemble_features(**_inputs())
    assert feats["elo_diff"] == 200.0
    assert feats["form_diff"] == 9.0
    assert feats["is_neutral"] == 1.0
    assert feats["h2h_home_winrate"] == 3 / 5


def test_h2h_winrate_defaults_to_half_when_no_history():
    feats = assemble_features(**_inputs(h2h_home_wins=0, h2h_matches=0))
    assert feats["h2h_home_winrate"] == 0.5


def test_to_vector_follows_feature_names_order():
    feats = assemble_features(**_inputs())
    vec = to_vector(feats)
    assert vec == [feats[name] for name in FEATURE_NAMES]
    assert len(vec) == len(FEATURE_NAMES)


def test_window_stats_empty_uses_defaults():
    form, gf, ga, n = window_stats([])
    assert (form, gf, ga, n) == (0.0, DEFAULT_GOALS_AVG, DEFAULT_GOALS_AVG, 0)


def test_window_stats_counts_points_and_averages():
    # (gf, ga): a win (2-0), a draw (1-1), a loss (0-3)
    form, gf, ga, n = window_stats([(2, 0), (1, 1), (0, 3)])
    assert form == 4.0           # 3 + 1 + 0
    assert gf == 1.0             # (2+1+0)/3
    assert ga == 4 / 3           # (0+1+3)/3
    assert n == 3


def test_window_stats_all_losses_have_zero_form():
    form, gf, ga, n = window_stats([(0, 1), (0, 2)])
    assert form == 0.0
    assert n == 2


def test_non_neutral_is_encoded_as_zero():
    feats = assemble_features(**_inputs(is_neutral=False))
    assert feats["is_neutral"] == 0.0
