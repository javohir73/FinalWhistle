"""Resolve public competition codes to their tournament rows.

The frontend routes use short, stable codes (``wc26``, ``epl``, ``laliga``,
``bundesliga``), while the database stores the provider-facing tournament
name.  Keeping that mapping in one backend module lets every list/detail
endpoint apply the same tournament boundary instead of accidentally combining
clubs and national teams when more than one competition is loaded.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Tournament
from pipeline.leagues import LEAGUES


COMPETITION_TOURNAMENT_NAMES: dict[str, str] = {
    "wc26": "FIFA World Cup 2026",
    **{code: config["tournament_name"] for code, config in LEAGUES.items()},
}


def tournament_for_competition(
    db: Session,
    competition: str | None,
) -> Tournament | None:
    """Return the requested tournament, or ``None`` for an unloaded one.

    ``competition=None`` intentionally preserves the legacy all-tournaments
    endpoints for old callers.  A known-but-unloaded competition is not an
    error: its dedicated UI can render an honest empty state.  Unknown codes
    are rejected so a typo can never silently broaden a query to all data.
    """
    if competition is None:
        return None

    tournament_name = COMPETITION_TOURNAMENT_NAMES.get(competition)
    if tournament_name is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "competition_not_found",
                "message": f"Unknown competition {competition}",
            },
        )
    return db.query(Tournament).filter(Tournament.name == tournament_name).one_or_none()


def competition_cache_key(prefix: str, competition: str | None) -> str:
    return f"{prefix}:{competition or 'all'}"
