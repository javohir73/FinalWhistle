from app.models import Player, Team
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import ingest_squad


def _patch_squad(monkeypatch, response):
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: response)


def test_ingest_squad_upserts_players_with_mapped_position(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    # api-sports /players/squads shape: response[0].players[]
    _patch_squad(monkeypatch, [
        {"team": {"id": 1, "name": "Belgium"}, "players": [
            {"id": 730, "name": "T. Courtois", "age": 33, "number": 1, "position": "Goalkeeper"},
            {"id": 909, "name": "K. De Bruyne", "age": 34, "number": 7, "position": "Midfielder"},
        ]},
    ])
    n = ingest_squad(db_session, "k", team)
    assert n == 2
    courtois = db_session.query(Player).filter_by(provider_player_id=730).one()
    assert courtois.name == "T. Courtois"
    assert courtois.team_id == team.id
    assert courtois.position == "G"           # Goalkeeper -> G
    assert db_session.query(Player).filter_by(provider_player_id=909).one().position == "M"


def test_ingest_squad_skips_nameless_entries(db_session, monkeypatch):
    """An entry with an id but no name must be silently skipped — no Player row
    created and no IntegrityError raised (players.name is NOT NULL)."""
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    _patch_squad(monkeypatch, [
        {"team": {"id": 1}, "players": [
            {"id": 730, "name": "T. Courtois", "position": "Goalkeeper"},  # valid
            {"id": 999, "name": None, "position": "Defender"},              # nameless — skip
            {"id": 998, "position": "Midfielder"},                          # name key absent — skip
        ]},
    ])
    n = ingest_squad(db_session, "k", team)
    assert n == 1  # only the valid player counted
    assert db_session.query(Player).filter_by(provider_player_id=730).count() == 1
    assert db_session.query(Player).filter_by(provider_player_id=999).count() == 0
    assert db_session.query(Player).filter_by(provider_player_id=998).count() == 0


def test_ingest_squad_is_idempotent(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    resp = [{"team": {"id": 1}, "players": [{"id": 730, "name": "T. Courtois", "position": "Goalkeeper"}]}]
    _patch_squad(monkeypatch, resp)
    ingest_squad(db_session, "k", team)
    ingest_squad(db_session, "k", team)   # second run must not duplicate
    assert db_session.query(Player).filter_by(provider_player_id=730).count() == 1
