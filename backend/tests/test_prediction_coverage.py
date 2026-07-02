"""Prediction-coverage query (FR-1.2/FR-1.3): a scheduled match with both
teams assigned but no frozen prediction row is a guaranteed zero in the model
record — the query is the read-only detector shared by /api/health and the
daily pipeline's coverage step. Lives in backend/app (imports app.models only)
so the health endpoint never pulls ml/pipeline into the request path."""
from datetime import datetime, timedelta, timezone

from app.models import Match, Prediction
from app.prediction_coverage import matches_missing_prediction


def _now():
    return datetime.now(timezone.utc)


def _scheduled(hours_ahead: float = 12, **kw):
    return Match(
        tournament_id=1, stage="R32", status="scheduled",
        team_home_id=kw.pop("team_home_id", 1),
        team_away_id=kw.pop("team_away_id", 2),
        kickoff_utc=_now() + timedelta(hours=hours_ahead),
        **kw,
    )


def _prediction_for(match_id: int) -> Prediction:
    return Prediction(
        match_id=match_id, model_version="poisson-elo-test",
        prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2,
        predicted_score_home=1, predicted_score_away=0,
    )


def test_scheduled_match_with_teams_and_no_prediction_is_missing(db_session):
    m = _scheduled()
    db_session.add(m)
    db_session.commit()

    missing = matches_missing_prediction(db_session)
    assert [x.id for x in missing] == [m.id]


def test_match_with_prediction_is_not_missing(db_session):
    m = _scheduled()
    db_session.add(m)
    db_session.commit()
    db_session.add(_prediction_for(m.id))
    db_session.commit()

    assert matches_missing_prediction(db_session) == []


def test_unassigned_or_started_matches_are_not_missing(db_session):
    db_session.add(Match(tournament_id=1, stage="R16", status="scheduled",
                         team_home_id=None, team_away_id=None))  # placeholder
    db_session.add(Match(tournament_id=1, stage="R32", status="in_play",
                         team_home_id=3, team_away_id=4))
    db_session.add(Match(tournament_id=1, stage="R32", status="finished",
                         team_home_id=5, team_away_id=6, score_home=1, score_away=0))
    db_session.commit()

    assert matches_missing_prediction(db_session) == []


def test_within_hours_window_filters_far_kickoffs(db_session):
    soon = _scheduled(hours_ahead=12)
    far = _scheduled(hours_ahead=100, team_home_id=3, team_away_id=4)
    unknown = Match(tournament_id=1, stage="R16", status="scheduled",
                    team_home_id=5, team_away_id=6, kickoff_utc=None)
    db_session.add_all([soon, far, unknown])
    db_session.commit()

    within = matches_missing_prediction(db_session, within_hours=48)
    # A NULL kickoff can't be proven far away — treated as due (defensive).
    assert {x.id for x in within} == {soon.id, unknown.id}
    # No window => everything missing is reported.
    assert {x.id for x in matches_missing_prediction(db_session)} == {soon.id, far.id, unknown.id}
