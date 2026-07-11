"""Origin frozen shadow predictions + grading (mirrors nrl_predict_test's
fixtures, sport="origin")."""
from datetime import datetime, timezone

import pytest

from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam
from ml.sports.origin.venues import is_neutral, model_is_neutral
from pipeline.sports.origin_predict import SPORT, generate, grade


@pytest.fixture
def teams(db_session):
    nsw = SportTeam(sport=SPORT, name="NSW Blues")
    qld = SportTeam(sport=SPORT, name="QLD Maroons")
    db_session.add_all([nsw, qld])
    db_session.flush()
    return nsw, qld


def _match(db, teams, season, rnd, status="scheduled", sh=None, sa=None,
           venue="Suncorp Stadium", kickoff=None):
    nsw, qld = teams
    m = SportMatch(sport=SPORT, season=season, round=rnd, match_no=rnd,
                   kickoff_utc=kickoff or datetime(season, 5, 20 + rnd, 9, tzinfo=timezone.utc),
                   venue=venue, home_team_id=qld.id, away_team_id=nsw.id,
                   score_home=sh, score_away=sa, status=status)
    db.add(m)
    db.flush()
    return m


def test_generate_writes_shadow_prediction_for_scheduled_only(db_session, teams):
    _match(db_session, teams, 2027, 1, status="finished", sh=20, sa=10)
    scheduled = _match(db_session, teams, 2027, 2)
    db_session.commit()

    assert generate(db_session) == 1
    pred = db_session.query(SportPrediction).one()
    assert pred.match_id == scheduled.id
    assert pred.is_shadow is True
    assert pred.model_version == "origin-elo-v0.1"
    assert 0 < pred.p_home < 1 and pred.p_home + pred.p_draw + pred.p_away == pytest.approx(1.0)


def test_generate_is_idempotent(db_session, teams):
    _match(db_session, teams, 2027, 1)
    db_session.commit()
    assert generate(db_session) == 1
    assert generate(db_session) == 0  # unchanged Elo state -> no new row


def test_model_neutral_set_is_empty_so_home_edge_applies_everywhere(db_session, teams):
    # Task 4's backtest REFUTED zeroing home_adv at neutral venues (log loss
    # 0.7456 with zeroing vs 0.7216 without), so MODEL_NEUTRAL_VENUES is empty
    # and the model path (model_is_neutral) applies home_adv everywhere, even
    # at a venue that is display-flagged neutral (is_neutral). See
    # ml/sports/origin/venues.py.
    home_ground = _match(db_session, teams, 2027, 1, venue="Suncorp Stadium")
    mcg = _match(db_session, teams, 2027, 2, venue="Melbourne Cricket Ground")
    db_session.commit()
    generate(db_session)

    p_home_ground = db_session.query(SportPrediction).filter_by(match_id=home_ground.id).one()
    p_mcg = db_session.query(SportPrediction).filter_by(match_id=mcg.id).one()
    # Equal fresh Elos: home edge still applies at the MCG since the model
    # path never zeroes it (MODEL_NEUTRAL_VENUES is empty).
    assert p_home_ground.p_home > p_home_ground.p_away
    assert p_mcg.p_home > p_mcg.p_away

    assert model_is_neutral("Melbourne Cricket Ground") is False
    assert is_neutral("Melbourne Cricket Ground") is True


def test_grade_scores_pre_kickoff_prediction_once(db_session, teams):
    kickoff = datetime(2027, 5, 21, 9, tzinfo=timezone.utc)
    m = _match(db_session, teams, 2027, 1, kickoff=kickoff)
    db_session.add(SportPrediction(
        match_id=m.id, model_version="origin-elo-v0.1",
        created_at=datetime(2027, 5, 20, 9, tzinfo=timezone.utc),
        p_home=0.6, p_draw=0.02, p_away=0.38, expected_margin=4.0))
    db_session.commit()
    m.status = "finished"
    m.score_home, m.score_away = 22, 12
    db_session.commit()

    assert grade(db_session) == 1
    r = db_session.query(SportPredictionResult).one()
    assert r.outcome == "home" and r.winner_correct is True
    assert grade(db_session) == 0  # never re-grades
