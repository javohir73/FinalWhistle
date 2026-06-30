from app.models import Team
from pipeline.ingest.players import link_team_ids


def test_link_team_ids_matches_by_normalized_name(db_session):
    db_session.add_all([Team(name="Brazil"), Team(name="South Korea")])
    db_session.commit()

    teams_response = [
        {"team": {"id": 6, "name": "Brazil"}},
        {"team": {"id": 17, "name": "Korea Republic"}},   # api-sports alias
        {"team": {"id": 999, "name": "Wales"}},            # not in our DB -> ignored
    ]
    linked = link_team_ids(db_session, teams_response)

    assert db_session.query(Team).filter_by(name="Brazil").one().provider_team_id == 6
    # alias maps via normalize_team_name -> South Korea
    assert db_session.query(Team).filter_by(name="South Korea").one().provider_team_id == 17
    assert linked == 2
