from types import SimpleNamespace

import pytest

from ml.models.nrl_score import (
    NrlExternalScoreSignals,
    NrlScoreParams,
    build_score_state,
    predict_scoreline,
)


def _match(home, away, home_score, away_score):
    return SimpleNamespace(
        home_team_id=home,
        away_team_id=away,
        score_home=home_score,
        score_away=away_score,
    )


def test_fixture_specific_scores_move_with_team_attack_and_opponent_defence():
    history = []
    for _ in range(12):
        history.extend([_match(1, 2, 34, 10), _match(3, 4, 16, 14)])
    state = build_score_state(history)

    strong_vs_weak = predict_scoreline(state, 1, 2)
    quiet_matchup = predict_scoreline(state, 3, 4)

    assert strong_vs_weak.expected_total != quiet_matchup.expected_total
    assert strong_vs_weak.expected_home > quiet_matchup.expected_home
    assert strong_vs_weak.predicted_home + strong_vs_weak.predicted_away == round(
        strong_vs_weak.expected_total
    )


def test_market_total_is_optional_and_blended_without_replacing_team_split():
    state = build_score_state([_match(1, 2, 30, 12)] * 10)
    internal = predict_scoreline(state, 1, 2)
    informed = predict_scoreline(
        state, 1, 2, NrlExternalScoreSignals(market_total=60.0)
    )

    expected = (1 - state.params.market_weight) * internal.expected_total + 60.0 * state.params.market_weight
    assert informed.expected_total == pytest.approx(expected)
    assert informed.expected_home > informed.expected_away


def test_external_adjustments_have_explicit_pre_match_contract():
    state = build_score_state([], NrlScoreParams())
    plain = predict_scoreline(state, 1, 2)
    adjusted = predict_scoreline(
        state,
        1,
        2,
        NrlExternalScoreSignals(
            home_points_adjustment=-2.0,
            away_points_adjustment=1.0,
            total_adjustment=-4.0,
        ),
    )
    assert adjusted.expected_home == plain.expected_home - 4.0
    assert adjusted.expected_away == plain.expected_away - 1.0
