"""Tournament endpoints (league pivot D6/D7, docs/LEAGUE-PIVOT-PLAN.md)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.competition_scope import tournament_for_competition
from app.db import get_db
from app.models import Match, Tournament

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])

# Short TTL (vs. the ~600s default): the daily pipeline / cutover writer runs
# in a SEPARATE process from this one (see app.cache.InMemoryCache.invalidate),
# so bounding this key's own staleness is what actually keeps the WC26 -> EPL
# cutover from serving the stale knockout answer for a full cache lifetime.
_ACTIVE_TTL_SECONDS = 60


def _tournament_payload(db: Session, tournament: Tournament) -> dict:
    # A non-group fixture is not automatically a supported bracket. Qualifiers
    # and externally ingested cup knockouts have no platform bracket topology;
    # only matches assigned a canonical match_no can back the bracket API/UI.
    has_brackets = (
        db.query(Match)
        .filter(
            Match.tournament_id == tournament.id,
            Match.stage != "group",
            Match.match_no.isnot(None),
        )
        .count()
        > 0
    )
    return {
        "id": tournament.id,
        "name": tournament.name,
        "year": tournament.year,
        "format": "knockout" if has_brackets else "league",
        "has_brackets": has_brackets,
    }


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
    result = _tournament_payload(db, tournament)
    cache.set("tournaments:active", result, ttl_seconds=_ACTIVE_TTL_SECONDS)
    return result


@router.get("/{competition}")
def competition_tournament(competition: str, db: Session = Depends(get_db)):
    """Metadata for one competition without falling back to the active season."""
    tournament = tournament_for_competition(db, competition)
    if tournament is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "competition_inactive",
                "message": f"No tournament data loaded for {competition}",
            },
        )
    return _tournament_payload(db, tournament)
