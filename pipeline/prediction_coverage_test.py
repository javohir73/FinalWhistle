"""Tests for ensure_prediction_coverage (FR-1.1): the cheap analytic sweep
that generates a frozen prediction for any scheduled match whose teams are
known but which has no prediction row — closing the gap where knockout teams
are assigned by a live-refresh pass between daily pipeline runs."""
from app.models import Match, Prediction, Team
from pipeline.ingest.wc26_structure import load_structure
from pipeline.prediction_coverage import ensure_prediction_coverage


def _set_elos(db):
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _assign_ko_teams(db, match_no: int) -> Match:
    """Give a knockout placeholder two real teams, as assign_knockout_teams would."""
    m = db.query(Match).filter_by(match_no=match_no).one()
    teams = db.query(Team).order_by(Team.id).limit(2).all()
    m.team_home_id, m.team_away_id = teams[0].id, teams[1].id
    db.commit()
    return m


def test_generates_prediction_for_missing_match(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    m = _assign_ko_teams(db_session, 89)
    # Group matches all lack predictions too in this fixture — restrict the
    # assertion to the KO match by checking it specifically.
    result = ensure_prediction_coverage(db_session)

    assert m.id in result["match_ids"]
    assert result["generated"] == len(result["match_ids"]) > 0
    row = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=False).one()
    assert row.predicted_score_home is not None
    # The sweep keeps the shadow record complete too (FR-4.4): one twin per row.
    shadow = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=True).one()
    assert shadow.model_version == "poisson-elo-v0.3-shadow"


def test_second_sweep_is_a_noop(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _assign_ko_teams(db_session, 89)
    ensure_prediction_coverage(db_session)

    again = ensure_prediction_coverage(db_session)
    assert again["generated"] == 0


def test_changed_pairing_forces_regeneration(db_session):
    """A feed correction can re-pair an already-predicted tie: the stale
    prediction (for the old teams) must be superseded by a fresh row."""
    load_structure(db_session)
    _set_elos(db_session)
    m = _assign_ko_teams(db_session, 89)
    ensure_prediction_coverage(db_session)
    assert db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=False).count() == 1

    # Re-pair (as assign_knockout_teams would after a feed correction).
    teams = db_session.query(Team).order_by(Team.id).limit(4).all()
    m.team_home_id, m.team_away_id = teams[2].id, teams[3].id
    db_session.commit()

    result = ensure_prediction_coverage(db_session, changed_match_ids={m.id})
    assert m.id in result["match_ids"]
    assert db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=False).count() == 2
