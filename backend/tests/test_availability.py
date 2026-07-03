"""DB-level tests for the announced-XI availability glue."""
from datetime import datetime, timezone

from app.availability import availability_for_match, availability_inputs
from app.models import LineupPlayer, Match, MatchLineup, Player, Team


def _match(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    return m, h, a


def _squad(db, team_id, star_pid):
    # An elite striker (highest minutes, so it's in the reference XI) + 11 regulars.
    players = [Player(provider_player_id=star_pid, name="Star", team_id=team_id,
                      position="F", club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270)]
    for i in range(11):
        players.append(Player(provider_player_id=star_pid * 100 + i, name=f"reg{i}",
                              team_id=team_id, position="M", club_goals=2,
                              club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.add_all(players); db.commit()
    return players


def _lineup(db, match_id, side, starter_pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{pid}", is_starter=True,
                             order=i, provider_player_id=pid)
                for i, pid in enumerate(starter_pids)])
    db.commit()


def test_none_when_no_lineup(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    assert availability_for_match(db_session, m) is None


def test_none_when_only_one_lineup(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    _lineup(db_session, m.id, "home", [1] + [100 + i for i in range(10)])  # away XI missing
    assert availability_for_match(db_session, m) is None


def test_both_lineups_home_missing_star(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    # Home XI = 11 regulars, Star (pid 1) benched.
    _lineup(db_session, m.id, "home", [100 + i for i in range(11)])
    # Away XI = Star (pid 2) + 10 regulars: full strength.
    _lineup(db_session, m.id, "away", [2] + [200 + i for i in range(10)])
    result = availability_for_match(db_session, m)
    assert result is not None
    off_home, off_away, expl_home, expl_away = result
    assert off_home < 0.0                       # home lost its striker
    assert "Star" in {p["name"] for p in expl_home["players_out"]}
    assert off_away == 0.0 or off_away >= -1e-9  # away roughly full strength


def test_inputs_join_stats(db_session):
    m, h, a = _match(db_session)
    _squad(db_session, h.id, 1)
    _lineup(db_session, m.id, "home", [1])
    starters, squad = availability_inputs(db_session, m, "home")
    assert any(s["provider_player_id"] == 1 and s["club_goals"] == 25 for s in starters)
    assert len(squad) == 12
