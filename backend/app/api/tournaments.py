"""Tournament endpoints (league pivot D6/D7, docs/LEAGUE-PIVOT-PLAN.md)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.db import get_db
from app.models import Match, Tournament

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


@router.get("/active")
def active_tournament(db: Session = Depends(get_db)):
    """The tournament with the nearest upcoming scheduled match, falling back
    to the most recent one when nothing is scheduled.

    Lets the frontend switch its layout (bracket UI vs. a plain league table,
    item C5/C6) off ONE call instead of assuming World Cup 2026. A WC26-only
    DB (before/during the tournament) resolves to WC26/knockout/has_brackets
    true; once EPL is seeded with scheduled fixtures, it resolves to
    EPL/league/has_brackets false.
    """
    cached = cache.get("tournaments:active")
    if cached is not None:
        return cached

    match = (
        db.query(Match)
        .filter(Match.status == "scheduled", Match.kickoff_utc.isnot(None))
        .order_by(Match.kickoff_utc.asc())
        .first()
    )
    if match is None:
        match = (
            db.query(Match)
            .filter(Match.kickoff_utc.isnot(None))
            .order_by(Match.kickoff_utc.desc())
            .first()
        )
    if match is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "no_tournament", "message": "no tournament data"},
        )

    tournament = db.get(Tournament, match.tournament_id)
    # A tournament "has brackets" once it has any non-group-stage match —
    # WC26 seeds its 32 knockout placeholders at structure-load time (before
    # a single result exists), so this is true from day one; a league loader
    # never creates a non-"group" stage row, so it's always false there.
    has_brackets = (
        db.query(Match)
        .filter(Match.tournament_id == tournament.id, Match.stage != "group")
        .count()
        > 0
    )
    result = {
        "id": tournament.id,
        "name": tournament.name,
        "year": tournament.year,
        "format": "knockout" if has_brackets else "league",
        "has_brackets": has_brackets,
    }
    cache.set("tournaments:active", result)
    return result
