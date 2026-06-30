from datetime import datetime, timedelta, timezone

from app.models import Player, Team
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import refresh_players


def test_refresh_players_links_ingests_and_bounds(db_session, monkeypatch):
    db_session.add(Team(name="Belgium"))
    db_session.commit()

    monkeypatch.setattr(players_mod, "fetch_teams", lambda *a, **k: [{"team": {"id": 1, "name": "Belgium"}}])
    # squad of 3 players for the linked team
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: [
        {"team": {"id": 1}, "players": [
            {"id": 730, "name": "A", "position": "Goalkeeper"},
            {"id": 909, "name": "B", "position": "Midfielder"},
            {"id": 200, "name": "C", "position": "Attacker"},
        ]}])
    monkeypatch.setattr(players_mod, "fetch_player_stats", lambda api_key, pid, season, **k: [
        {"player": {"id": pid}, "statistics": [{"league": {"id": 1}, "games": {"minutes": 90}, "goals": {"total": 1}, "penalty": {"scored": 0}}]}])
    monkeypatch.setattr(players_mod.time, "sleep", lambda *_a: None)   # no real waiting

    out = refresh_players(db_session, "k", league=1, max_players=2)

    assert out["teams_linked"] == 1
    assert out["squads_ingested"] == 1
    assert out["players_refreshed"] == 2          # capped at max_players, not 3
    assert db_session.query(Team).filter_by(name="Belgium").one().provider_team_id == 1
    refreshed = db_session.query(Player).filter(Player.updated_at.isnot(None)).count()
    assert refreshed == 2


def test_refresh_players_skips_fresh_players(db_session, monkeypatch):
    team = Team(name="Belgium", provider_team_id=1)
    db_session.add(team)
    db_session.commit()
    fresh = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(Player(provider_player_id=730, name="A", team_id=team.id, updated_at=fresh))
    db_session.commit()

    monkeypatch.setattr(players_mod, "fetch_teams", lambda *a, **k: [{"team": {"id": 1, "name": "Belgium"}}])
    monkeypatch.setattr(players_mod, "fetch_squad", lambda api_key, team_id, **k: [
        {"team": {"id": 1}, "players": [{"id": 730, "name": "A", "position": "Goalkeeper"}]}])
    called = []
    monkeypatch.setattr(players_mod, "fetch_player_stats",
                        lambda api_key, pid, season, **k: called.append(pid) or [])
    monkeypatch.setattr(players_mod.time, "sleep", lambda *_a: None)

    out = refresh_players(db_session, "k", league=1, stale_days=7)
    assert out["players_refreshed"] == 0          # the one player is fresh (1 day < 7)
    assert called == []                            # no stat fetch issued
