"""Tests for the league score predictions grading pass (League Score
Predictions design doc, 2026-07-24). Mirrors pipeline/sports/
nrl_user_tips_test.py's fixture style: builds tiny Tournament/Team/Match +
TipPlayer/LeagueScorePrediction fixtures directly via db_session (conftest.py's
SQLite fixture), and exercises grade() directly rather than through the API.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import LeagueScorePrediction, Match, Team, TipPlayer, Tournament
from pipeline.league_score_predictions import grade


def _tournament(db, name="Premier League 2026-27"):
    t = Tournament(name=name, year=2026, home_advantage_mode="home")
    db.add(t)
    db.flush()
    return t


def _team(db, name):
    t = Team(name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, tournament, home, away, kickoff, matchweek=1,
           status="finished", score_home=2, score_away=1):
    m = Match(
        tournament_id=tournament.id, team_home_id=home.id, team_away_id=away.id,
        stage="group", matchweek=matchweek, kickoff_utc=kickoff, status=status,
        score_home=score_home, score_away=score_away,
    )
    db.add(m)
    db.flush()
    return m


def _player(db, device_id="3fa85f64-5717-4562-b3fc-2c963f66afa6", handle="TestTipper"):
    p = TipPlayer(device_id=device_id, handle=handle)
    db.add(p)
    db.flush()
    return p


def _prediction(db, tournament, match, player, pred_home, pred_away, updated_at=None):
    p = LeagueScorePrediction(
        tournament_id=tournament.id, match_id=match.id, player_id=player.id,
        predicted_home=pred_home, predicted_away=pred_away,
        updated_at=updated_at or (match.kickoff_utc - timedelta(hours=1)),
    )
    db.add(p)
    db.flush()
    return p


def _kickoff(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


# ---- scoring matrix: exact / result-only / miss, draws, 0-0 ----

def test_grade_exact_score_awards_five_points(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1)
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 5
    assert pred.exact is True
    assert pred.graded_at is not None


def test_grade_correct_result_wrong_score_awards_two_points(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)  # home win
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 3, 0)  # also a home win, wrong scoreline
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 2
    assert pred.exact is False


def test_grade_wrong_result_awards_zero_points(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)  # home win
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 0, 1)  # away win -- wrong side
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 0
    assert pred.exact is False


def test_grade_draw_prediction_and_draw_result_scores_exact(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=1, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 1, 1)
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 5
    assert pred.exact is True


def test_grade_draw_direction_correct_different_scoreline_awards_two(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=1, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 2)  # drew, but wrong exact scoreline
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 2
    assert pred.exact is False


def test_grade_zero_zero_is_a_valid_exact_prediction(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=0, score_away=0)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 0, 0)
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 5
    assert pred.exact is True


# ---- idempotency + regrade-on-correction ----

def test_grade_is_idempotent_on_rerun(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1)
    db_session.commit()

    first = grade(db_session)
    second = grade(db_session)

    assert first == 1
    assert second == 0
    db_session.refresh(pred)
    assert pred.points == 5


def test_grade_recomputes_when_match_result_is_corrected(db_session):
    """Unlike pipeline.learning_loop.evaluate_finished_predictions' once-only
    guard, a corrected score on an already-graded match must flip the stored
    points/exact -- grade() always recomputes from the current score."""
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1)  # exact against 2-1
    db_session.commit()

    grade(db_session)
    db_session.refresh(pred)
    assert pred.points == 5
    first_graded_at = pred.graded_at

    # Score correction flips the result to an away win.
    m.score_home, m.score_away = 1, 2
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 0
    assert pred.exact is False
    assert pred.graded_at >= first_graded_at


def test_grade_recomputes_when_match_result_changes_past_kickoff(db_session):
    """Regression guard mirroring nrl_user_tips_test.py's identically-named
    test: LeagueScorePrediction.updated_at must track ONLY submit_prediction's
    own pick writes (models.LeagueScorePrediction -- no onupdate=func.now()),
    never a grading write, or a past-kickoff correction could never re-land
    once graded -- the belt-and-braces filter below would wrongly exclude it
    forever after the FIRST grade() write, if that write had bumped
    updated_at past kickoff_utc."""
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    kickoff = datetime.now(timezone.utc) - timedelta(days=2)
    m = _match(db_session, t, ars, che, kickoff, score_home=2, score_away=1)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1, updated_at=kickoff - timedelta(hours=1))
    db_session.commit()

    grade(db_session)
    db_session.refresh(pred)
    assert pred.points == 5

    m.score_home, m.score_away = 1, 2
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(pred)
    assert pred.points == 0


# ---- belt-and-braces: post-kickoff / no-kickoff exclusion ----

def test_grade_excludes_prediction_updated_after_kickoff(db_session):
    """Shouldn't exist given submit_prediction's kickoff lock, but a stray
    updated_at > kickoff_utc row must never be scored -- left permanently
    ungraded rather than scored zero."""
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    player = _player(db_session)
    late = _prediction(db_session, t, m, player, 2, 1, updated_at=m.kickoff_utc + timedelta(hours=1))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(late)
    assert late.points is None
    assert late.graded_at is None

    n2 = grade(db_session)  # re-running never picks it up either
    assert n2 == 0


def test_grade_excludes_prediction_on_match_with_no_kickoff_recorded(db_session):
    """Belt-and-braces: not reachable via real ingestion (every real fixture
    has a kickoff_utc), but a finished match missing one has nothing to check
    a prediction's updated_at against, so it must be excluded rather than
    graded on trust."""
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = Match(
        tournament_id=t.id, team_home_id=ars.id, team_away_id=che.id,
        stage="group", matchweek=1, kickoff_utc=None, status="finished",
        score_home=2, score_away=1,
    )
    db_session.add(m)
    db_session.flush()
    player = _player(db_session)
    pred = LeagueScorePrediction(
        tournament_id=t.id, match_id=m.id, player_id=player.id,
        predicted_home=2, predicted_away=1, updated_at=datetime.now(timezone.utc),
    )
    db_session.add(pred)
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(pred)
    assert pred.points is None
    assert pred.graded_at is None


# ---- abandoned / no-score match: grade null ----

def test_grade_leaves_prediction_ungraded_when_match_score_missing(db_session):
    """Abandoned matches: grade null (never scored) -- design doc edge case."""
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    m = _match(db_session, t, ars, che, _kickoff(2026, 8, 22),
               status="finished", score_home=None, score_away=None)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1)
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(pred)
    assert pred.points is None
    assert pred.graded_at is None


# ---- no-ops ----

def test_grade_no_predictions_is_a_noop(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    _match(db_session, t, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    db_session.commit()

    n = grade(db_session)

    assert n == 0


def test_grade_skips_scheduled_match_even_with_predictions(db_session):
    t = _tournament(db_session)
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db_session, t, ars, che, kickoff, status="scheduled",
               score_home=None, score_away=None)
    player = _player(db_session)
    pred = _prediction(db_session, t, m, player, 2, 1, updated_at=kickoff - timedelta(hours=1))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(pred)
    assert pred.points is None
    assert pred.graded_at is None


# ---- multi-tournament in one pass (grade() is global, not per-league) ----

def test_grade_handles_multiple_tournaments_in_one_pass(db_session):
    epl = _tournament(db_session, "Premier League 2026-27")
    laliga = _tournament(db_session, "La Liga 2026-27")
    ars, che = _team(db_session, "Arsenal"), _team(db_session, "Chelsea")
    rma, fcb = _team(db_session, "Real Madrid"), _team(db_session, "Barcelona")
    m1 = _match(db_session, epl, ars, che, _kickoff(2026, 8, 22), score_home=2, score_away=1)
    m2 = _match(db_session, laliga, rma, fcb, _kickoff(2026, 8, 23), score_home=1, score_away=1)
    player = _player(db_session)
    p1 = _prediction(db_session, epl, m1, player, 2, 1)  # exact
    p2 = _prediction(db_session, laliga, m2, player, 0, 0)  # correct result (draw), wrong score
    db_session.commit()

    n = grade(db_session)

    assert n == 2
    db_session.refresh(p1)
    db_session.refresh(p2)
    assert p1.points == 5 and p1.exact is True
    assert p2.points == 2 and p2.exact is False
