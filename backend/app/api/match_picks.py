"""Per-match pick save/restore for signed-in users (account upgrade for the
device-local match predictions).

All routes here require a verified account (get_current_user); anonymous players
keep using localStorage with no backend involvement. Same lock rule as brackets:
picks for matches that have kicked off are immutable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.auth import get_current_user
from app.db import get_db
from app.models import AppUser, Match, MatchPick
from app.security import require_same_origin

router = APIRouter(prefix="/api/match-picks", tags=["match-picks"])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _picks_out(rows: list[MatchPick]) -> schemas.MatchPicksOut:
    return schemas.MatchPicksOut(
        picks=[schemas.MatchPickIn(match_id=p.match_id, pick=p.pick) for p in rows],
        updated_at=_iso(max((p.updated_at for p in rows if p.updated_at), default=None)),
    )


def _user_picks(db: Session, user_id: int) -> list[MatchPick]:
    return (
        db.query(MatchPick)
        .filter_by(user_id=user_id)
        .order_by(MatchPick.match_id)
        .all()
    )


@router.get("/me", response_model=schemas.MatchPicksOut)
def my_match_picks(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Restore the signed-in user's saved match picks (empty list when none)."""
    return _picks_out(_user_picks(db, user.id))


@router.post("", response_model=schemas.MatchPicksOut,
             dependencies=[Depends(require_same_origin)])
def save_match_picks(
    payload: schemas.MatchPicksIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the user's match picks with the submitted set. Picks for matches
    that have already kicked off are locked: changing them is rejected, and
    omitting them never deletes them (no editing after kickoff)."""
    now = datetime.now(timezone.utc)
    existing = {p.match_id: p for p in _user_picks(db, user.id)}
    incoming_ids: set[int] = set()

    for mp in payload.picks:
        if mp.pick not in ("home", "draw", "away"):
            raise HTTPException(status_code=422, detail={"code": "bad_pick",
                                                         "message": f"Invalid pick {mp.pick!r}"})
        m = db.get(Match, mp.match_id)
        if m is None:
            continue
        incoming_ids.add(mp.match_id)
        locked = m.status != "scheduled"
        cur = existing.get(mp.match_id)
        if locked:
            # Locked matches are immutable; allow an unchanged resend, reject edits.
            if cur is None or cur.pick != mp.pick:
                raise HTTPException(status_code=422, detail={
                    "code": "match_locked",
                    "message": f"Match {mp.match_id} has kicked off and is locked.",
                })
            continue
        if cur:
            if cur.pick != mp.pick:
                cur.pick = mp.pick
                cur.updated_at = now
        else:
            db.add(MatchPick(user_id=user.id, match_id=mp.match_id, pick=mp.pick, updated_at=now))

    # Remove de-selected picks, but never touch locked ones.
    for mid, p in existing.items():
        if mid not in incoming_ids:
            m = db.get(Match, mid)
            if m is not None and m.status == "scheduled":
                db.delete(p)

    db.commit()
    return _picks_out(_user_picks(db, user.id))
