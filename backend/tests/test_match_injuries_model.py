"""Match.injuries JSON column round-trips (model-driven; create_all in conftest)."""
from app.models import Match, Team


def test_match_injuries_column_roundtrips(db_session):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db_session.add_all([h, a]); db_session.commit()
    m = Match(tournament_id=1, stage="group", team_home_id=h.id, team_away_id=a.id,
              injuries=[{"provider_player_id": 1, "name": "Neymar", "type": "out",
                         "reason": "Calf Injury", "side": "home"}])
    db_session.add(m); db_session.commit()
    got = db_session.get(Match, m.id)
    assert got.injuries[0]["name"] == "Neymar"
    assert got.injuries[0]["type"] == "out"
    assert got.injuries[0]["side"] == "home"


def test_match_injuries_defaults_none(db_session):
    h, a = Team(name="France"), Team(name="Spain")
    db_session.add_all([h, a]); db_session.commit()
    m = Match(tournament_id=1, stage="group", team_home_id=h.id, team_away_id=a.id)
    db_session.add(m); db_session.commit()
    assert db_session.get(Match, m.id).injuries is None
