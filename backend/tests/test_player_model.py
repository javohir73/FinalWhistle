from datetime import datetime, timezone

from app.models import LineupPlayer, Match, MatchLineup, Player, Team


def test_player_row_roundtrips_with_provider_ids(db_session):
    team = Team(name="Brazil", provider_team_id=6)
    db_session.add(team)
    db_session.commit()

    p = Player(
        provider_player_id=1179, name="Vinicius Junior", team_id=team.id,
        position="F", club_goals=24, club_minutes=2800, club_penalties=2,
        wc_goals=1, wc_minutes=270, season=2025,
        updated_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    db_session.add(p)
    db_session.commit()

    got = db_session.query(Player).filter_by(provider_player_id=1179).one()
    assert got.name == "Vinicius Junior"
    assert got.team_id == team.id
    assert got.club_goals == 24 and got.wc_goals == 1
    assert db_session.query(Team).filter_by(name="Brazil").one().provider_team_id == 6


def test_lineup_player_carries_provider_player_id(db_session):
    m = Match(tournament_id=1, stage="group", is_neutral=True)
    db_session.add(m)
    db_session.commit()
    ml = MatchLineup(match_id=m.id, side="home", provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml)
    db_session.commit()
    lp = LineupPlayer(match_lineup_id=ml.id, name="Vini", number=7, position="F",
                      grid="4:1", is_starter=True, order=0, provider_player_id=1179)
    db_session.add(lp)
    db_session.commit()
    assert db_session.query(LineupPlayer).one().provider_player_id == 1179
