"""Live layer read endpoint (Wave 3): GET /api/nrl/matches/{id}/live.

Reads whatever pipeline.sports.nrl_live_poll has persisted (NrlLiveState /
NrlLiveEvent); never calls a StatsProvider itself -- all provider calls
happen in the poller so this endpoint stays fast under board traffic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction

router = APIRouter(prefix="/api/nrl", tags=["nrl-live"])

MATCH_MINUTES = 80
_WINDOW_AHEAD = timedelta(minutes=5)
_MATCH_DURATION = timedelta(minutes=110)


def _pregame_prob(db: Session, match_id: int) -> float:
    latest = (
        db.query(SportPrediction)
        .filter_by(match_id=match_id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    return latest.p_home if latest is not None else 0.5


@router.get("/matches/{match_id}/live")
def nrl_match_live(match_id: int, db: Session = Depends(get_db)):
    match = db.query(SportMatch).filter_by(id=match_id, sport="nrl").one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "no_nrl_match", "message": "No NRL match with that id",
        })

    state = db.query(NrlLiveState).filter_by(match_id=match_id).one_or_none()
    now = datetime.now(timezone.utc)

    # Handle naive datetime from SQLite: if kickoff_utc has no tzinfo, assume UTC
    kickoff_utc = match.kickoff_utc
    if kickoff_utc is not None and kickoff_utc.tzinfo is None:
        kickoff_utc = kickoff_utc.replace(tzinfo=timezone.utc)

    in_window = (
        kickoff_utc is not None
        and kickoff_utc - _WINDOW_AHEAD <= now <= kickoff_utc + _MATCH_DURATION
    )

    if match.status == "finished" and (state is None or state.status != "final"):
        # The match has finished, but the live state row (if any) is stale —
        # either never reached "final" (a feed died mid-match, or golden
        # point ran past the poller's window) or there's no row at all.
        # Serve the finished fallback so the UI stops pinning a LIVE strip
        # and polling indefinitely; a state row already at "final" is left
        # alone below since its stored scores/prob are the poller's last word.
        status, minute = "final", MATCH_MINUTES
        score_home, score_away = match.score_home, match.score_away
        live_home_prob = 1.0 if (score_home or 0) > (score_away or 0) else 0.0
    elif state is not None:
        status, minute = state.status, state.minute
        score_home, score_away = state.score_home, state.score_away
        live_home_prob = state.live_home_prob
    elif in_window:
        status, minute = "live", 0
        score_home, score_away = 0, 0
        live_home_prob = _pregame_prob(db, match_id)
    else:
        status, minute = "pre", None
        score_home, score_away = None, None
        live_home_prob = _pregame_prob(db, match_id)

    events = (
        db.query(NrlLiveEvent)
        .filter_by(match_id=match_id)
        .order_by(NrlLiveEvent.minute.asc(), NrlLiveEvent.id.asc())
        .all()
    )

    return {
        "status": status,
        "minute": minute,
        "score_home": score_home,
        "score_away": score_away,
        "live_home_prob": live_home_prob,
        "events": [
            {"minute": e.minute, "type": e.type, "team": e.team,
             "player": e.player, "prob_after": e.prob_after}
            for e in events
        ],
    }
