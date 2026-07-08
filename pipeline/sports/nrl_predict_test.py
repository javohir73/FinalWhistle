"""Tests for NRL frozen shadow prediction generation + grading (task 5).

generate/grade operate purely on sport="nrl" rows, so tests build small
in-memory fixtures via db_session (conftest.py's SQLite fixture) rather than
touching the football tables. Elo state is always derived by replaying
FINISHED matches in kickoff order (with regress_season at season boundaries)
-- never stored on SportTeam -- so "changed state" tests finish an extra
match rather than mutating a team row directly.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam
from ml.sports.nrl.model import NrlParams, predict
from pipeline.sports.nrl_predict import generate, grade

SPORT = "nrl"


def _team(db, name, season_hint=None):
    t = SportTeam(sport=SPORT, name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, home, away, season, match_no, kickoff, status="scheduled",
           score_home=None, score_away=None, round_=1):
    m = SportMatch(
        sport=SPORT, season=season, round=round_, match_no=match_no,
        kickoff_utc=kickoff, venue="Test Stadium",
        home_team_id=home.id, away_team_id=away.id,
        score_home=score_home, score_away=score_away, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _kickoff(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


PARAMS = NrlParams()


# ---- generate: freeze guard ----

def test_generate_writes_nothing_for_finished_match_with_no_prior_row(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
           status="finished", score_home=20, score_away=16)

    n = generate(db_session, PARAMS)

    assert n == 0
    assert db_session.query(SportPrediction).count() == 0


def test_generate_writes_for_scheduled_match(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1), status="scheduled")

    n = generate(db_session, PARAMS)

    assert n == 1
    row = db_session.query(SportPrediction).one()
    assert row.is_shadow is True
    assert abs((row.p_home + row.p_draw + row.p_away) - 1.0) < 1e-9


# ---- generate: dedup ----

def test_generate_is_idempotent_when_state_unchanged(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1), status="scheduled")

    first = generate(db_session, PARAMS)
    second = generate(db_session, PARAMS)

    assert first == 1
    assert second == 0
    assert db_session.query(SportPrediction).count() == 1


def test_generate_appends_new_row_when_elo_state_changes(db_session):
    broncos = _team(db_session, "Broncos")
    storm = _team(db_session, "Storm")
    cowboys = _team(db_session, "Cowboys")

    # The scheduled match we'll re-predict as Broncos' state shifts.
    scheduled = _match(db_session, broncos, storm, 2026, 2, _kickoff(2026, 4, 1),
                        status="scheduled")

    first = generate(db_session, PARAMS)
    assert first == 1
    first_row = db_session.query(SportPrediction).filter_by(match_id=scheduled.id).one()

    # Finish an earlier match involving Broncos -- shifts their Elo, so a
    # re-generate must predict differently for the still-scheduled fixture.
    _match(db_session, broncos, cowboys, 2026, 1, _kickoff(2026, 3, 1),
           status="finished", score_home=40, score_away=6)

    second = generate(db_session, PARAMS)
    assert second == 1

    rows = (
        db_session.query(SportPrediction)
        .filter_by(match_id=scheduled.id)
        .order_by(SportPrediction.id)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].id == first_row.id
    assert abs(rows[1].p_home - rows[0].p_home) > 1e-9


# ---- generate: hard guard ----

def test_generate_never_writes_for_non_scheduled_status(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
           status="postponed")  # not "scheduled", not "finished"

    n = generate(db_session, PARAMS)

    assert n == 0
    assert db_session.query(SportPrediction).count() == 0


def test_generate_season_regression_applied_at_boundary(db_session):
    # Two seasons: a blowout in 2025 should have LESS influence on a 2026
    # prediction than it would within the same season, because regress_season
    # pulls ratings back toward the mean at the boundary. We just assert the
    # replay runs across seasons without error and produces a valid triple --
    # the exact math is covered by ml.sports.nrl.backtest's replay_seasons tests.
    broncos = _team(db_session, "Broncos")
    storm = _team(db_session, "Storm")
    _match(db_session, broncos, storm, 2025, 1, _kickoff(2025, 3, 1),
           status="finished", score_home=50, score_away=0)
    scheduled = _match(db_session, broncos, storm, 2026, 1, _kickoff(2026, 3, 1),
                        status="scheduled")

    n = generate(db_session, PARAMS)
    assert n == 1
    row = db_session.query(SportPrediction).filter_by(match_id=scheduled.id).one()
    assert abs((row.p_home + row.p_draw + row.p_away) - 1.0) < 1e-9


# ---- grade: exactness ----

def test_grade_computes_exact_log_loss_and_brier_for_known_triple(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
                    status="finished", score_home=20, score_away=16)

    p_home, p_draw, p_away = 0.55, 0.02, 0.43
    pred = SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=p_home, p_draw=p_draw, p_away=p_away,
        expected_margin=5.0, is_shadow=True,
    )
    db_session.add(pred)
    db_session.commit()

    n = grade(db_session)
    assert n == 1

    result = db_session.query(SportPredictionResult).one()
    assert result.outcome == "home"
    assert result.winner_correct is True
    assert abs(result.prob_assigned - p_home) < 1e-9
    assert abs(result.log_loss - (-math.log(p_home))) < 1e-9
    expected_brier = (p_home - 1.0) ** 2 + (p_draw - 0.0) ** 2 + (p_away - 0.0) ** 2
    assert abs(result.brier - expected_brier) < 1e-9
    assert abs(result.margin_error - abs(5.0 - (20 - 16))) < 1e-9


def test_grade_draw_outcome_winner_correct_false_when_argmax_is_a_side(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
                    status="finished", score_home=18, score_away=18)

    pred = SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.52, p_draw=0.02, p_away=0.46,
        expected_margin=1.0, is_shadow=True,
    )
    db_session.add(pred)
    db_session.commit()

    grade(db_session)

    result = db_session.query(SportPredictionResult).one()
    assert result.outcome == "draw"
    assert result.winner_correct is False  # argmax is "home", not "draw"
    assert abs(result.prob_assigned - 0.02) < 1e-9


# ---- grade: never re-grade ----

def test_grade_never_re_grades_an_already_graded_match(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
                    status="finished", score_home=20, score_away=16)
    pred = SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.55, p_draw=0.02, p_away=0.43,
        expected_margin=5.0, is_shadow=True,
    )
    db_session.add(pred)
    db_session.commit()

    first = grade(db_session)
    second = grade(db_session)

    assert first == 1
    assert second == 0
    assert db_session.query(SportPredictionResult).count() == 1


def test_grade_uses_latest_prediction_row(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
                    status="finished", score_home=20, score_away=16)
    db_session.add(SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.40, p_draw=0.02, p_away=0.58, expected_margin=-2.0, is_shadow=True,
    ))
    db_session.commit()
    latest = SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.60, p_draw=0.02, p_away=0.38, expected_margin=6.0, is_shadow=True,
    )
    db_session.add(latest)
    db_session.commit()

    grade(db_session)

    result = db_session.query(SportPredictionResult).one()
    assert result.prediction_id == latest.id
    assert abs(result.prob_assigned - 0.60) < 1e-9


def test_grade_skips_finished_match_with_no_prediction(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
           status="finished", score_home=20, score_away=16)

    n = grade(db_session)

    assert n == 0
    assert db_session.query(SportPredictionResult).count() == 0


def test_grade_skips_scheduled_match_even_with_prediction(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1), status="scheduled")
    db_session.add(SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.5, p_draw=0.02, p_away=0.48, expected_margin=0.5, is_shadow=True,
    ))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    assert db_session.query(SportPredictionResult).count() == 0


def test_grade_away_win_outcome(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    match = _match(db_session, home, away, 2026, 1, _kickoff(2026, 3, 1),
                   status="finished", score_home=10, score_away=24)
    db_session.add(SportPrediction(
        match_id=match.id, model_version="nrl-elo-v0.1",
        p_home=0.45, p_draw=0.02, p_away=0.53, expected_margin=-3.0, is_shadow=True,
    ))
    db_session.commit()

    grade(db_session)

    result = db_session.query(SportPredictionResult).one()
    assert result.outcome == "away"
    assert result.winner_correct is True
    assert abs(result.prob_assigned - 0.53) < 1e-9
