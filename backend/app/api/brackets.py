"""Bracket save/restore for signed-in users (account upgrade for anonymous play).

All routes here require a verified account (get_current_user); anonymous players
keep using localStorage + the ?b= share link with no backend involvement.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.auth import get_current_user
from app.cache import cache
from app.db import get_db
from app.models import AppUser, Bracket, BracketGroupPick, BracketKnockoutPick, Match
from app.security import require_same_origin

router = APIRouter(prefix="/api/brackets", tags=["brackets"])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def to_bracket_out(b: Bracket) -> schemas.BracketOut:
    return schemas.BracketOut(
        id=b.id,
        visibility=b.visibility,
        display_name=b.display_name,
        champion_team_id=b.champion_team_id,
        completion_pct=b.completion_pct,
        group_picks=[schemas.GroupPickIn(match_id=p.match_id, pick=p.pick) for p in b.group_picks],
        knockout_picks=[
            schemas.KnockoutPickIn(match_no=p.match_no, picked_team_id=p.picked_team_id)
            for p in b.knockout_picks
        ],
        score=(
            schemas.BracketScoreOut(
                group_points=b.score.group_points,
                knockout_points=b.score.knockout_points,
                champion_bonus=b.score.champion_bonus,
                total_points=b.score.total_points,
                rank=b.score.rank,
            )
            if b.score
            else None
        ),
        submitted_at=_iso(b.submitted_at),
        updated_at=_iso(b.updated_at),
    )


@router.get("/me", response_model=schemas.BracketOut)
def my_bracket(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Restore the signed-in user's saved bracket."""
    b = db.query(Bracket).filter_by(user_id=user.id).one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail={"code": "no_bracket",
                                                     "message": "No saved bracket yet"})
    return to_bracket_out(b)


@router.post("", response_model=schemas.BracketOut,
             dependencies=[Depends(require_same_origin)])
def save_bracket(
    payload: schemas.BracketIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update the user's bracket. Picks for matches that have already
    kicked off are locked: changing them is rejected (no editing after kickoff)."""
    b = db.query(Bracket).filter_by(user_id=user.id).one_or_none()
    if b is None:
        b = Bracket(user_id=user.id)
        db.add(b)
        db.flush()

    now = datetime.now(timezone.utc)
    existing = {p.match_id: p for p in b.group_picks}
    incoming_ids: set[int] = set()

    for gp in payload.group_picks:
        if gp.pick not in ("home", "draw", "away"):
            raise HTTPException(status_code=422, detail={"code": "bad_pick",
                                                         "message": f"Invalid pick {gp.pick!r}"})
        m = db.get(Match, gp.match_id)
        if m is None:
            continue
        incoming_ids.add(gp.match_id)
        locked = m.status != "scheduled"
        cur = existing.get(gp.match_id)
        if locked:
            # Locked matches are immutable; allow an unchanged resend, reject edits.
            if cur is None or cur.pick != gp.pick:
                raise HTTPException(status_code=422, detail={
                    "code": "match_locked",
                    "message": f"Match {gp.match_id} has kicked off and is locked.",
                })
            continue
        if cur:
            cur.pick = gp.pick
        else:
            db.add(BracketGroupPick(bracket_id=b.id, match_id=gp.match_id, pick=gp.pick))

    # Remove de-selected picks, but never touch locked ones.
    for mid, p in existing.items():
        if mid not in incoming_ids:
            m = db.get(Match, mid)
            if m is not None and m.status == "scheduled":
                db.delete(p)

    # Knockout picks: full replace (knockout games are future-dated in the MVP).
    for p in list(b.knockout_picks):
        db.delete(p)
    db.flush()
    for kp in payload.knockout_picks:
        db.add(BracketKnockoutPick(bracket_id=b.id, match_no=kp.match_no, picked_team_id=kp.picked_team_id))

    total_group = db.query(Match).filter(Match.stage == "group").count() or 72
    db.flush()
    picked = db.query(BracketGroupPick).filter_by(bracket_id=b.id).count()
    b.completion_pct = round(100.0 * picked / total_group, 1)
    b.champion_team_id = payload.champion_team_id
    b.encoded_state = payload.encoded_state
    b.updated_at = now

    db.commit()
    db.refresh(b)
    cache.clear()
    return to_bracket_out(b)
