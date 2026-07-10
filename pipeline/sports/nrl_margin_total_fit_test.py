"""Tests for pipeline/sports/nrl_margin_total_fit.py -- the least-squares
margin~elo_diff+home_advantage fit and the recency-weighted total mean."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_margin_total_fit import (
    collect_training_rows,
    fit_expected_total,
    fit_margin,
)


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t); db.flush()
    return t


def _match(db, home, away, season, no, kickoff, score_home, score_away):
    m = SportMatch(sport="nrl", season=season, round=1, match_no=no,
                   kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                   score_home=score_home, score_away=score_away, status="finished")
    db.add(m); db.flush()
    return m


def test_fit_margin_recovers_a_known_linear_relationship():
    """Construct (elo_diff, margin) pairs that exactly satisfy
    margin = 0.04 * elo_diff + 3.0, then check OLS recovers those coefficients."""
    rows = [(d, 0.04 * d + 3.0) for d in (-200.0, -100.0, 0.0, 100.0, 200.0, 300.0)]
    coef, intercept = fit_margin(rows)
    assert abs(coef - 0.04) < 1e-9
    assert abs(intercept - 3.0) < 1e-9


def test_fit_margin_empty_input_returns_zeros():
    assert fit_margin([]) == (0.0, 0.0)


def test_collect_training_rows_uses_pre_match_elo_not_post_match(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    k1 = datetime(2017, 3, 1, tzinfo=timezone.utc)
    k2 = datetime(2017, 3, 8, tzinfo=timezone.utc)
    _match(db_session, home, away, 2017, 1, k1, 30, 10)   # home blowout win
    _match(db_session, home, away, 2017, 2, k2, 10, 30)   # away blowout win
    db_session.commit()

    matches = db_session.query(SportMatch).all()
    rows = collect_training_rows(matches)

    assert len(rows) == 2
    # Both teams start at 1500 -> the FIRST match's elo_diff must be 0
    # regardless of that match's own (leaked) result.
    assert rows[0][0] == 0.0
    assert rows[0][1] == 20.0  # 30 - 10
    # The second match's elo_diff reflects the FIRST match's outcome only.
    assert rows[1][0] != 0.0
    assert rows[1][1] == -20.0  # 10 - 30


def test_fit_expected_total_weights_latest_season_2to1():
    by_season = {
        2024: [SimpleNamespace(score_home=20, score_away=20)],  # total 40
        2025: [SimpleNamespace(score_home=25, score_away=25)],  # total 50
    }
    total = fit_expected_total(by_season)
    assert abs(total - ((2 * 50 + 40) / 3)) < 1e-9


def test_fit_expected_total_single_season_uses_its_mean():
    by_season = {2025: [SimpleNamespace(score_home=20, score_away=24)]}
    assert fit_expected_total(by_season) == 44.0


def test_fit_expected_total_no_data_falls_back_to_default():
    from ml.models.nrl_margin_total import NrlMarginTotalParams
    assert fit_expected_total({}) == NrlMarginTotalParams().expected_total
