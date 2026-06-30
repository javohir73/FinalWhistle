"""Match endpoints (PRD §11)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.cache import cache
from app.config import settings
from app.db import get_db
from app.goalscorers import build_goalscorers
from app.lineups import get_match_lineups
from app.live_refresh import maybe_refresh_live
from app.models import Match

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/upcoming", response_model=list[schemas.MatchSummaryOut])
def upcoming_matches(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # The board's polling doubles as the live-score heartbeat: viewers watching
    # matches are exactly when scores must stay fresh (see app/live_refresh.py).
    if settings.live_updates_active:
        background_tasks.add_task(maybe_refresh_live)
    cached = cache.get("matches:upcoming")
    if cached is not None:
        return cached
    # All fixtures with known teams (scheduled, in-play, or finished) so the
    # board can show live and full-time scores, not just upcoming kickoffs.
    matches = (
        db.query(Match)
        .filter(Match.team_home_id.isnot(None))
        .order_by(Match.kickoff_utc.is_(None), Match.kickoff_utc.asc(), Match.id.asc())
        .all()
    )
    result = [serializers.match_to_summary(db, m) for m in matches]
    cache.set("matches:upcoming", result)
    return result


@router.get("/{match_id}/summary", response_model=schemas.MatchSummaryOut)
def match_summary(match_id: int, background_tasks: BackgroundTasks,
                  db: Session = Depends(get_db)):
    """Scoreboard feed for the match page: actual status/score/minute alongside
    the predicted score. Viewers parked on a live match page also drive the
    opportunistic live refresh, same as the matches board."""
    if settings.live_updates_active:
        background_tasks.add_task(maybe_refresh_live)
    cache_key = f"matches:summary:{match_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    result = serializers.match_to_summary(db, match)
    cache.set(cache_key, result)
    return result


@router.get("/{match_id}/goalscorers", response_model=schemas.GoalscorersOut | None)
def match_goalscorers(match_id: int, db: Session = Depends(get_db)):
    """Likely scorers per team (squad estimate, or the announced XI when stored).
    `null` body when there's no player data yet — never fabricated, never 5xx."""
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    return build_goalscorers(db, match)


@router.get("/{match_id}/lineups", response_model=schemas.MatchLineupsOut)
def match_lineups(match_id: int, db: Session = Depends(get_db)):
    """Display-only starting XI + bench for the match (never feeds the prediction
    model). Stored lineups are returned directly; otherwise, if the match is
    within the lineup window and a provider key + fixture id resolve, they are
    fetched on demand and cached. A missing key, a future fixture, or any
    provider error degrades to ``{ available: false }`` — never a 5xx, never
    fabricated players."""
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    return get_match_lineups(db, match)


@router.get("/{match_id}", response_model=schemas.PredictionOut)
def match_detail(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No match {match_id}"})
    pred = serializers.latest_prediction(db, match_id)
    if pred is None:
        raise HTTPException(status_code=404, detail={"code": "no_prediction",
                                                     "message": "No prediction for this match yet"})
    return serializers.prediction_to_out(db, match, pred)
