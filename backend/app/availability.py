"""Announced-XI availability adjustment, wired to the DB (v1).

Loads a match's announced XI + squad and turns them into the per-team attack
offset from ml.models.availability. BOTH the daily writer (the shadow twin) and
the read path (the match-page note) go through here, so they never diverge.
Requires BOTH sides to have an announced XI — mirrors the goalscorers 'lineup
mode' gate; otherwise returns None (no adjustment, no note).

Cycle-safe: app.goalscorers imports app.serializers at module load, and
serializers.py imports THIS module — so the shared lineup/player helpers are
imported lazily inside availability_inputs (at call time, when every module is
initialized), never at module load. That reuses app.goalscorers._lineup_rows /
._player_dict (DRY) without a circular import.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Match, Player
from ml.models.availability import availability_offset


def availability_inputs(
    db: Session, match: Match, side: str
) -> tuple[list[dict], list[dict]] | None:
    """(announced_starter_dicts, full_squad_dicts) for one side, or None when no
    announced XI is stored. Starters join the XI to Player stats by
    provider_player_id; an XI player with no stats row falls back to zeros (the
    position prior carries it, exactly as the goalscorers path does). Reuses the
    goalscorers lineup/player helpers via a lazy import (see module docstring)."""
    from app.goalscorers import _lineup_rows, _player_dict  # lazy: avoids import cycle

    team_id = match.team_home_id if side == "home" else match.team_away_id
    rows = _lineup_rows(db, match.id, side)
    if not rows:
        return None
    squad = db.query(Player).filter_by(team_id=team_id).all()
    by_pid = {p.provider_player_id: p for p in squad}
    starters: list[dict] = []
    for lp in rows:
        if not lp.is_starter:
            continue
        stat = by_pid.get(lp.provider_player_id)
        if stat is not None:
            starters.append(_player_dict(stat, "starter"))
        else:
            starters.append({"provider_player_id": lp.provider_player_id,
                             "name": lp.name, "position": lp.position,
                             "club_goals": 0, "club_minutes": 0,
                             "wc_goals": 0, "wc_minutes": 0, "lineup_status": "starter"})
    return starters, [_player_dict(p, None) for p in squad]


def availability_for_match(
    db: Session, match: Match
) -> tuple[float, float, dict, dict] | None:
    """(off_home, off_away, expl_home, expl_away) or None unless BOTH sides have an
    announced XI and both offsets are computable."""
    home = availability_inputs(db, match, "home")
    away = availability_inputs(db, match, "away")
    if home is None or away is None:
        return None
    h = availability_offset(home[0], home[1])
    a = availability_offset(away[0], away[1])
    if h is None or a is None:
        return None
    return h[0], a[0], h[1], a[1]
