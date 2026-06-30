"""Build the per-team 'likely scorers' block for a match from ingested Player
stats and the match's stored lambda. Lineup mode when an XI is stored, else
squad mode. None when no player data exists for either side."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import schemas
from app.models import LineupPlayer, Match, MatchLineup, Player
from app.serializers import latest_prediction
from ml.models.goalscorers import goalscorers


def _player_dict(p: Player, lineup_status: str | None) -> dict:
    return {
        "provider_player_id": p.provider_player_id, "name": p.name,
        "position": p.position, "club_goals": p.club_goals,
        "club_minutes": p.club_minutes, "wc_goals": p.wc_goals,
        "wc_minutes": p.wc_minutes, "lineup_status": lineup_status,
    }


def _lineup_rows(db: Session, match_id: int, side: str) -> list[LineupPlayer] | None:
    lineup = (
        db.query(MatchLineup).filter_by(match_id=match_id, side=side).one_or_none()
    )
    if lineup is None or not lineup.players:
        return None
    return list(lineup.players)


def _side_players(db: Session, match: Match, side: str) -> tuple[list[dict], bool]:
    """Return (player dicts, lineup_mode) for one side. Lineup mode joins the
    announced XI to Player stats by provider_player_id; squad mode lists all the
    team's Player rows."""
    team_id = match.team_home_id if side == "home" else match.team_away_id
    rows = _lineup_rows(db, match.id, side)
    if rows:
        by_pid = {p.provider_player_id: p for p in
                  db.query(Player).filter_by(team_id=team_id).all()}
        players = []
        for lp in rows:
            status = "starter" if lp.is_starter else "sub"
            stat = by_pid.get(lp.provider_player_id)
            if stat is not None:
                players.append(_player_dict(stat, status))
            else:  # in the XI but no stats row yet -> position prior only
                players.append({"provider_player_id": lp.provider_player_id,
                                "name": lp.name, "position": lp.position,
                                "club_goals": 0, "club_minutes": 0, "wc_goals": 0,
                                "wc_minutes": 0, "lineup_status": status})
        return players, True
    squad = db.query(Player).filter_by(team_id=team_id).all()
    return [_player_dict(p, None) for p in squad], False


def build_goalscorers(db: Session, match: Match, top_n: int = 8) -> schemas.GoalscorersOut | None:
    pred = latest_prediction(db, match.id)
    if pred is None:
        return None
    home_players, home_lineup = _side_players(db, match, "home")
    away_players, away_lineup = _side_players(db, match, "away")
    if not home_players and not away_players:
        return None
    mode = "lineup" if (home_lineup or away_lineup) else "squad"
    home = goalscorers(pred.lambda_home, home_players, mode)[:top_n]
    away = goalscorers(pred.lambda_away, away_players, mode)[:top_n]
    return schemas.GoalscorersOut(
        mode=mode,
        home=[schemas.GoalscorerOut(**{k: g[k] for k in
              ("name", "position", "p_score", "p_score_2plus", "xg")}) for g in home],
        away=[schemas.GoalscorerOut(**{k: g[k] for k in
              ("name", "position", "p_score", "p_score_2plus", "xg")}) for g in away],
    )
