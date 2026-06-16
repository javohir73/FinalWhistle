from app.models import Match, Team
from app.serializers import match_to_summary
from pipeline.ingest.wc26_structure import load_structure


def test_match_to_summary_includes_goal_events(db_session):
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.status = "in_play"
    m.score_home, m.score_away = 1, 0
    m.goal_events = [{"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
    db_session.commit()

    out = match_to_summary(db_session, m)
    assert len(out.goal_events) == 1
    assert out.goal_events[0].player == "R. Jimenez"
    assert out.goal_events[0].side == "home"
    assert out.goal_events[0].minute == 30


def test_match_to_summary_goal_events_defaults_empty(db_session):
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    out = match_to_summary(db_session, m)
    assert out.goal_events == []
