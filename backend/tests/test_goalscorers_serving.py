from datetime import datetime, timezone

from app.goalscorers import build_goalscorers
from app.models import (LineupPlayer, Match, MatchLineup, Player, Prediction, Team)


def _match_with_pred(db, lam_home=2.0, lam_away=0.8):
    h, a = Team(name="Brazil"), Team(name="Serbia")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True,
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    db.add(Prediction(match_id=m.id, model_version="v", prob_home_win=0.6,
                      prob_draw=0.2, prob_away_win=0.2, lambda_home=lam_home,
                      lambda_away=lam_away, rho=-0.1))
    db.commit()
    return m, h, a


def test_squad_mode_when_no_lineup(db_session):
    m, h, a = _match_with_pred(db_session)
    db_session.add_all([
        Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
               club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270),
        Player(provider_player_id=2, name="HDef", team_id=h.id, position="D",
               club_goals=1, club_minutes=2700, wc_goals=0, wc_minutes=270),
        Player(provider_player_id=3, name="AStriker", team_id=a.id, position="F",
               club_goals=10, club_minutes=2000, wc_goals=0, wc_minutes=180),
    ])
    db_session.commit()
    out = build_goalscorers(db_session, m)
    assert out is not None
    assert out.mode == "squad"
    assert out.home[0].name == "HStriker"
    assert abs(sum(g.xg for g in out.home) - 2.0) < 1e-3      # conserves lambda_home


def test_lineup_mode_uses_announced_xi(db_session):
    """Lineup mode only activates when BOTH sides have a stored MatchLineup."""
    m, h, a = _match_with_pred(db_session)
    db_session.add_all([
        Player(provider_player_id=1, name="HStriker", team_id=h.id, position="F",
               club_goals=18, club_minutes=2700, wc_goals=2, wc_minutes=270),
        Player(provider_player_id=9, name="HBench", team_id=h.id, position="F",
               club_goals=20, club_minutes=2700, wc_goals=3, wc_minutes=270),
        Player(provider_player_id=3, name="AStriker", team_id=a.id, position="F",
               club_goals=10, club_minutes=2000, wc_goals=0, wc_minutes=180),
    ])
    # Home lineup
    ml_home = MatchLineup(match_id=m.id, side="home", provider="api_football",
                          fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml_home); db_session.commit()
    db_session.add_all([
        LineupPlayer(match_lineup_id=ml_home.id, name="HStriker", is_starter=True,
                     order=0, provider_player_id=1),
        LineupPlayer(match_lineup_id=ml_home.id, name="HBench", is_starter=False,
                     order=1, provider_player_id=9),
    ])
    # Away lineup (required for lineup mode under the AND fix)
    ml_away = MatchLineup(match_id=m.id, side="away", provider="api_football",
                          fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml_away); db_session.commit()
    db_session.add(
        LineupPlayer(match_lineup_id=ml_away.id, name="AStriker", is_starter=True,
                     order=0, provider_player_id=3)
    )
    db_session.commit()
    out = build_goalscorers(db_session, m)
    assert out.mode == "lineup"
    names = {g.name for g in out.home}
    assert "HStriker" in names and "HBench" in names          # both in the XI/bench


def test_squad_mode_when_only_one_lineup_announced(db_session):
    """When only the home lineup is stored (away not yet announced), mode must
    stay 'squad' so the away side is NOT silently emptied (the half-card bug)."""
    m, h, a = _match_with_pred(db_session)
    # Home squad + away squad players
    db_session.add_all([
        Player(provider_player_id=10, name="HStriker2", team_id=h.id, position="F",
               club_goals=12, club_minutes=2000, wc_goals=1, wc_minutes=180),
        Player(provider_player_id=11, name="HDef2", team_id=h.id, position="D",
               club_goals=0, club_minutes=2500, wc_goals=0, wc_minutes=200),
        Player(provider_player_id=20, name="AStriker2", team_id=a.id, position="F",
               club_goals=9, club_minutes=1800, wc_goals=0, wc_minutes=160),
        Player(provider_player_id=21, name="ADef2", team_id=a.id, position="D",
               club_goals=0, club_minutes=2200, wc_goals=0, wc_minutes=180),
    ])
    # ONLY home lineup is stored — away has no MatchLineup row
    ml = MatchLineup(match_id=m.id, side="home", provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db_session.add(ml); db_session.commit()
    db_session.add_all([
        LineupPlayer(match_lineup_id=ml.id, name="HStriker2", is_starter=True,
                     order=0, provider_player_id=10),
        LineupPlayer(match_lineup_id=ml.id, name="HDef2", is_starter=True,
                     order=1, provider_player_id=11),
    ])
    db_session.commit()

    out = build_goalscorers(db_session, m)
    assert out is not None
    # Both lineups are not yet stored → must fall back to squad mode
    assert out.mode == "squad", f"Expected squad, got {out.mode!r}"
    # Neither side should be silently emptied
    assert len(out.home) > 0, "Home side was unexpectedly empty"
    assert len(out.away) > 0, "Away side was unexpectedly empty (the half-card bug)"


def test_none_when_no_player_data(db_session):
    m, h, a = _match_with_pred(db_session)
    assert build_goalscorers(db_session, m) is None
