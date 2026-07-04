"""Tests for the StatsBomb xG backfill (pipeline/backfill_xg.py).

Phase 2: pure shot-xG parser + cached fetch scaffolding. All offline — hand-built
event/match fixtures, no network, no DB. Only `type.name=="Shot"` events with a
non-null `shot.statsbomb_xg` count, keyed by `team.name`; the penalty shootout
(period == 5) is excluded because `historical_matches.score_a/score_b` is the
after-extra-time score and would otherwise be compared against xG that roughly
doubles a knockout team's true attacking output (see plan's grounding on the
WC2022 final, Argentina 3-3 France: 5.89/5.41 all-periods vs 2.76/2.27 periods 1-4).
"""
import pytest

from pipeline.backfill_xg import match_xg, sum_shot_xg_by_team


def _shot(team, xg, period=1):
    return {"type": {"name": "Shot"}, "team": {"name": team}, "period": period,
            "shot": {"statsbomb_xg": xg}}


def _other(team, period=1):
    return {"type": {"name": "Pass"}, "team": {"name": team}, "period": period}


def test_sum_shot_xg_by_team_sums_only_shots():
    events = [
        _shot("France", 0.10),
        _other("France"),
        _shot("France", 0.35),
        _shot("Argentina", 0.05),
        _other("Argentina"),
    ]
    out = sum_shot_xg_by_team(events)
    assert out == pytest.approx({"France": 0.45, "Argentina": 0.05})


def test_sum_shot_xg_skips_missing_xg():
    events = [
        _shot("France", 0.20),
        {"type": {"name": "Shot"}, "team": {"name": "France"}, "period": 1,
         "shot": {}},  # statsbomb_xg absent -> skipped, not counted as 0
        _shot("Argentina", 0.15),
    ]
    out = sum_shot_xg_by_team(events)
    assert out == {"France": 0.20, "Argentina": 0.15}


def test_match_xg_maps_home_away():
    match = {"home_team": {"home_team_name": "Canada"},
             "away_team": {"away_team_name": "Morocco"}}
    events = [_shot("Canada", 1.096), _shot("Morocco", 0.426)]
    home_xg, away_xg = match_xg(match, events)
    assert home_xg == 1.096
    assert away_xg == 0.426


def test_match_xg_absent_side_is_none():
    match = {"home_team": {"home_team_name": "Canada"},
             "away_team": {"away_team_name": "Morocco"}}
    events = [_shot("Canada", 1.096)]  # Morocco has zero shot-xG entries
    home_xg, away_xg = match_xg(match, events)
    assert home_xg == 1.096
    assert away_xg is None

    # malformed events -> (None, None), no raise
    home_xg2, away_xg2 = match_xg(match, [{"garbage": True}, None])
    assert (home_xg2, away_xg2) == (None, None)


def test_sum_shot_xg_excludes_shootout():
    # WC2022 final grounding: periods 1-4 sum to 2.76/2.27; adding period-5
    # (shootout) inflates to 5.89/5.41. Only periods <= 4 should count.
    events = [
        _shot("Argentina", 1.50, period=1),
        _shot("Argentina", 1.26, period=4),
        _shot("France", 1.20, period=2),
        _shot("France", 1.07, period=4),
        # Shootout (period 5) -- must be excluded.
        _shot("Argentina", 3.13, period=5),
        _shot("France", 3.14, period=5),
    ]
    out = sum_shot_xg_by_team(events)
    assert out["Argentina"] == pytest.approx(2.76)
    assert out["France"] == pytest.approx(2.27)
