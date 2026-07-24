"""The beat-the-AI loop (design doc: NRL Round Tips, Slice 2): anonymous,
device-first tipping against the model, graded once each round finishes.

A separate router from app.api.nrl_tips -- that file is the model's OWN round
tipsheet (read-only, no player rows); this one is the human side. Same
identity convention as app.api.activity: device_id is the durable key
(TipPlayer, one row per device, mirrors DailyActivity), an account is an
optional upgrade attached later via /claim, never required to play.

INTEGRITY: a tip is rejected once its match's kickoff_utc has passed, by the
server clock only (never the client's) -- enforced in submit_tip, mirroring
the frozen-prediction guard in pipeline.sports.nrl_predict._write_prediction.
Until then a device may change its pick freely (upsert on (match_id, player)).

Grading (points/round_margin/graded_at on UserTip) is a SEPARATE pass, owned
by a different builder and hooked into nrl-refresh after the match finishes --
nothing in this file ever writes those three columns. Scoring rule those
columns encode (comp-standard, apples-to-apples with the model): 1 point for
a correct winner pick, or any pick at all if the match drew -- see
_scores_point, which this file uses to compute the MODEL's side of the
comparison live (the model's own graded ledger, SportPredictionResult.
winner_correct, does NOT apply the draw rule, so it can't be reused here).
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app import schemas
from app.api.auth import _email_action_rate_limited
from app.api.nrl_tips import _current_round, _kickoff_locked_prediction, _model_pick
from app.api.sports import _latest_season
from app.auth import get_current_user
from app.db import get_db
from app.models import AppUser, EmailActionAttempt, SportMatch, SportPrediction, SportTeam, TipPlayer, UserTip
from app.security import client_ip, hash_ip, require_same_origin, to_aware_utc

router = APIRouter(prefix="/api/nrl", tags=["nrl"])

_DISCLAIMER = "For analytics and entertainment only. Not betting advice."

# Same strict UUID v4 shape as app.api.activity's _DEVICE_ID_RE (\A/\Z, not
# ^/$, so a trailing newline can't slip a 37-char id past the check).
_DEVICE_ID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)

# A round is ~8 matches and a tip can be revised freely until kickoff, so the
# cap is generous (well above activity.py's once-a-day ping) -- this exists to
# stop a scripted flood, not to limit normal round-by-round play.
_SUBMIT_MAX = 120
_SUBMIT_WINDOW_MIN = 60

_LEADERBOARD_MIN_PARTICIPANTS = 10

_HANDLE_ADJECTIVES = (
    "Swift", "Brave", "Clutch", "Steady", "Fearless", "Rugged", "Sharp",
    "Bold", "Lightning", "Iron", "Golden", "Silent",
)
_HANDLE_NOUNS = (
    "Halfback", "Fullback", "Winger", "Hooker", "Prop", "Playmaker",
    "Enforcer", "Sprinter", "Tackler", "Kicker",
)


def _generate_handle() -> str:
    """A readable display name for a freshly-seen device -- never the raw
    device_id. Not guaranteed unique; collisions are cosmetic only, since
    nothing (grading, the leaderboard) keys on the handle."""
    return f"{random.choice(_HANDLE_ADJECTIVES)}{random.choice(_HANDLE_NOUNS)}{random.randint(1, 999)}"


def _actual_outcome(m: SportMatch) -> str | None:
    """home/draw/away for a match with a final score, else None (not finished
    yet) -- the same three-way outcome nrl_predict.grade() derives, kept local
    since app/api must not import the pipeline layer."""
    if m.score_home is None or m.score_away is None:
        return None
    if m.score_home > m.score_away:
        return "home"
    if m.score_home < m.score_away:
        return "away"
    return "draw"


def _scores_point(pick: str, outcome: str) -> bool:
    """Standard AU tipping-comp rule (design doc, Slice 2): a correct winner
    pick scores; a draw scores EVERY tipper regardless of pick. Used here to
    compute the model's own points for the you-vs-AI comparison -- the
    graded ledger's `winner_correct` is a strict pick match and does not
    apply the draw rule, so it isn't the same number."""
    return outcome == "draw" or pick == outcome


def _featured_match_id(db: Session, season: int, round: int) -> int | None:
    """The round's featured match: earliest kickoff, ties broken by match_no
    -- same ordering nrl_tips.py uses for its fixture list. Only this match
    accepts a margin guess."""
    row = (
        db.query(SportMatch.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season, SportMatch.round == round)
        .order_by(SportMatch.kickoff_utc.is_(None), SportMatch.kickoff_utc.asc(), SportMatch.match_no.asc())
        .first()
    )
    return row[0] if row else None


def _find_player(db: Session, device_id: str) -> TipPlayer | None:
    """Split out from _get_or_create_player so the check-then-insert race (two
    concurrent requests both passing this check) is easy to force in tests --
    mirrors app.api.activity's _find_ping."""
    return db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()


def _get_or_create_player(db: Session, device_id: str) -> TipPlayer:
    player = _find_player(db, device_id)
    if player is None:
        player = TipPlayer(device_id=device_id, handle=_generate_handle())
        db.add(player)
        try:
            db.flush()  # need player.id before it can own a UserTip row
        except IntegrityError:
            # Lost a race with a concurrent first-play from the same brand-new
            # device (both passed the check above before either flushed) --
            # the row exists either way, so re-read it instead of 500ing
            # (mirrors app.api.activity's ping()). Queried directly rather
            # than via _find_player so a test forcing that check to miss
            # doesn't also poison this re-read.
            db.rollback()
            player = db.query(TipPlayer).filter_by(device_id=device_id).one()
    return player


def _find_tip(db: Session, match_id: int, player_id: int) -> UserTip | None:
    """Mirrors _find_player -- split out so a concurrent first-submit race on
    the same (match, player) is easy to force in tests."""
    return db.query(UserTip).filter_by(match_id=match_id, player_id=player_id).one_or_none()


@router.post("/tips/submit", dependencies=[Depends(require_same_origin)])
def submit_tip(payload: schemas.NrlTipSubmitIn, request: Request, db: Session = Depends(get_db)):
    """Upsert one device's pick for one match. A device may change its pick
    freely until the match's kickoff_utc -- checked against the server clock,
    never the client's -- after which the tip is frozen."""
    device_id = payload.device_id
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})
    if payload.pick not in ("home", "draw", "away"):
        raise HTTPException(status_code=422, detail={"code": "bad_pick",
                                                     "message": f"Invalid pick {payload.pick!r}"})
    if payload.margin is not None and not (0 <= payload.margin <= 100):
        raise HTTPException(status_code=422, detail={"code": "bad_margin",
                                                     "message": "margin must be between 0 and 100."})

    ip_h = hash_ip(client_ip(request))
    if _email_action_rate_limited(db, "nrl_tip_submit", device_id, ip_h, _SUBMIT_MAX, _SUBMIT_WINDOW_MIN):
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts",
                                                     "message": "Too many attempts. Try again later."})
    # Committed immediately (not batched with the tip write below) so every
    # attempt that clears the cheap payload checks counts toward the rate
    # limit even if a later check (kickoff lock, bad match) rejects it.
    db.add(EmailActionAttempt(action="nrl_tip_submit", email=device_id, ip_hash=ip_h))
    db.commit()

    m = db.query(SportMatch).filter_by(id=payload.match_id, sport="nrl").one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No NRL match {payload.match_id}"})

    now = datetime.now(timezone.utc)
    # Belt-and-braces on top of the kickoff comparison below: a match that's
    # already finished (or already has a final score) is locked even if its
    # kickoff_utc is somehow missing -- not reachable via today's NRL feed,
    # but the kickoff check alone would otherwise wave a null-kickoff match
    # through regardless of status.
    already_played = m.status == "finished" or (m.score_home is not None and m.score_away is not None)
    if already_played or (m.kickoff_utc is not None and now >= to_aware_utc(m.kickoff_utc)):
        raise HTTPException(status_code=422, detail={
            "code": "match_locked",
            "message": f"Match {m.id} has kicked off and is locked.",
        })

    # Computed once and reused for both the margin gate and the is_featured
    # snapshot stored on the tip below (see UserTip.is_featured).
    featured_id = _featured_match_id(db, m.season, m.round)
    if payload.margin is not None and m.id != featured_id:
        raise HTTPException(status_code=422, detail={
            "code": "margin_not_allowed",
            "message": "Margin guesses are only accepted for the round's featured match.",
        })
    is_featured_now = m.id == featured_id

    player = _get_or_create_player(db, device_id)
    tip = _find_tip(db, m.id, player.id)
    if tip is None:
        tip = UserTip(match_id=m.id, player_id=player.id, pick=payload.pick,
                     margin=payload.margin, updated_at=now, is_featured=is_featured_now)
        db.add(tip)
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent first tip for this (match,
            # player) -- the row exists either way; re-read it (directly,
            # not via _find_tip -- see _get_or_create_player) and apply this
            # request's pick as the update, same idempotent-success idiom.
            db.rollback()
            tip = db.query(UserTip).filter_by(match_id=m.id, player_id=player.id).one()
            tip.pick = payload.pick
            tip.margin = payload.margin
            tip.updated_at = now
            tip.is_featured = is_featured_now
            db.commit()
    else:
        tip.pick = payload.pick
        tip.margin = payload.margin
        tip.updated_at = now
        tip.is_featured = is_featured_now
        db.commit()

    return {
        "ok": True,
        "handle": player.handle,
        "tip": {
            "match_id": m.id, "pick": tip.pick, "margin": tip.margin,
            "updated_at": tip.updated_at.isoformat() if tip.updated_at else None,
        },
    }


@router.get("/tips/mine")
def my_tips(device_id: str, season: int | None = None, round: int | None = None,
           db: Session = Depends(get_db)):
    """One device's tips for a round, with grading once graded, alongside the
    model's own kickoff-locked pick per match for the same round."""
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })
    if round is None:
        round = _current_round(db, season)
        if round is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    home_team, away_team = aliased(SportTeam), aliased(SportTeam)
    rows = (
        db.query(SportMatch, home_team.name, away_team.name)
        .outerjoin(home_team, SportMatch.home_team_id == home_team.id)
        .outerjoin(away_team, SportMatch.away_team_id == away_team.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season, SportMatch.round == round)
        .order_by(SportMatch.kickoff_utc.is_(None), SportMatch.kickoff_utc.asc(),
                  SportMatch.match_no.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail={
            "code": "round_not_found",
            "message": f"No matches for round {round} in season {season}",
        })
    featured_id = rows[0][0].id  # same ordering as _featured_match_id, no extra query

    match_ids = [m.id for m, _, _ in rows]
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[SportPrediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    player = db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()
    tips_by_match: dict[int, UserTip] = {}
    if player is not None:
        for t in db.query(UserTip).filter(UserTip.player_id == player.id, UserTip.match_id.in_(match_ids)).all():
            tips_by_match[t.match_id] = t

    matches_out = []
    for m, home_name, away_name in rows:
        pred = _kickoff_locked_prediction(preds_by_match, m)
        model_out = None
        if pred is not None:
            pick, confidence = _model_pick(pred)
            model_out = {"pick": pick, "pick_confidence": confidence, "expected_margin": pred.expected_margin}
        tip = tips_by_match.get(m.id)
        your_out = None
        if tip is not None:
            your_out = {
                "pick": tip.pick,
                "margin": tip.margin,
                "points": tip.points,
                "round_margin": tip.round_margin,
                "graded_at": tip.graded_at.isoformat() if tip.graded_at else None,
                "updated_at": tip.updated_at.isoformat() if tip.updated_at else None,
            }
        matches_out.append({
            "id": m.id,
            "home": home_name,
            "away": away_name,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "status": m.status,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "is_featured": m.id == featured_id,
            "model": model_out,
            "your_tip": your_out,
        })

    return {
        "season": season,
        "round": round,
        "handle": player.handle if player else None,
        "matches": matches_out,
        "disclaimer": _DISCLAIMER,
    }


@router.get("/tips/summary")
def tips_summary(device_id: str, db: Session = Depends(get_db)):
    """Season-long you-vs-AI record: per graded round, the device's points vs
    the model's -- the model's side scored under the identical draw rule
    (_scores_point), so the two numbers are directly comparable."""
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})

    zero_totals = {"your_points": 0, "model_points": 0, "rounds_played": 0}
    player = db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()
    if player is None:
        return {"handle": None, "rounds": [], "totals": zero_totals, "disclaimer": _DISCLAIMER}

    rows = (
        db.query(UserTip, SportMatch)
        .join(SportMatch, UserTip.match_id == SportMatch.id)
        .filter(UserTip.player_id == player.id, UserTip.graded_at.isnot(None))
        .all()
    )
    if not rows:
        return {"handle": player.handle, "rounds": [], "totals": zero_totals, "disclaimer": _DISCLAIMER}

    by_round: dict[tuple[int, int], list[tuple[UserTip, SportMatch]]] = {}
    for t, m in rows:
        by_round.setdefault((m.season, m.round), []).append((t, m))

    match_ids = [m.id for _, m in rows]
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[SportPrediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    rounds_out = []
    total_your = total_model = 0
    for (season, rnd), items in sorted(by_round.items()):
        your_points = sum(t.points or 0 for t, _ in items)
        model_points = 0
        for t, m in items:
            pred = _kickoff_locked_prediction(preds_by_match, m)
            outcome = _actual_outcome(m)
            if pred is not None and outcome is not None:
                pick, _ = _model_pick(pred)
                if _scores_point(pick, outcome):
                    model_points += 1
        rounds_out.append({
            "season": season, "round": rnd,
            "your_points": your_points, "model_points": model_points,
            "matches_played": len(items),
        })
        total_your += your_points
        total_model += model_points

    return {
        "handle": player.handle,
        "rounds": rounds_out,
        "totals": {"your_points": total_your, "model_points": total_model, "rounds_played": len(rounds_out)},
        "disclaimer": _DISCLAIMER,
    }


@router.get("/tips/leaderboard")
def tips_leaderboard(season: int, round: int, db: Session = Depends(get_db)):
    """Weekly (per-round) leaderboard. Hidden below _LEADERBOARD_MIN_PARTICIPANTS
    -- participant_count is always returned so the UI can show "N players so
    far", but individual entries (and every device_id) stay unexposed until
    the round has a real crowd. Never returns a device_id."""
    match_ids = [
        mid for (mid,) in db.query(SportMatch.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season, SportMatch.round == round)
        .all()
    ]
    if not match_ids:
        raise HTTPException(status_code=404, detail={
            "code": "round_not_found",
            "message": f"No matches for round {round} in season {season}",
        })

    rows = (
        db.query(UserTip, TipPlayer)
        .join(TipPlayer, UserTip.player_id == TipPlayer.id)
        .filter(UserTip.match_id.in_(match_ids))
        .all()
    )
    by_player: dict[int, list[UserTip]] = {}
    handles: dict[int, str] = {}
    for t, p in rows:
        by_player.setdefault(p.id, []).append(t)
        handles[p.id] = p.handle

    participant_count = len(by_player)
    entries = []
    if participant_count >= _LEADERBOARD_MIN_PARTICIPANTS:
        for player_id, tips in by_player.items():
            points = sum(t.points or 0 for t in tips)
            round_margin = next((t.round_margin for t in tips if t.round_margin is not None), None)
            entries.append({"handle": handles[player_id], "points": points, "round_margin": round_margin})
        entries.sort(key=lambda e: (-e["points"], e["round_margin"] if e["round_margin"] is not None else float("inf")))

    return {
        "season": season, "round": round,
        "participant_count": participant_count,
        "entries": entries,
    }


@router.post("/tips/claim", dependencies=[Depends(require_same_origin)])
def claim_device_tips(
    payload: schemas.NrlTipClaimIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach a device's tip history to the signed-in account (merge-on-
    signup). Idempotent: a device with no history, an already-linked device,
    or a device already merged into this account all return success with no
    further change. When the account already owns a different player row,
    the device's tips are merged into it -- conflict rule: the account's own
    tip wins wherever both exist for the same match (mirrors match_picks.py's
    "existing row is never silently overwritten" idiom).

    device_id is a bare, unauthenticated body param (no proof of possession),
    so it must never be trusted to REASSIGN or MERGE-AND-DELETE a player row
    that's already claimed by a *different* account -- a shared/kiosk device,
    or a device_id read off an access log, would otherwise let anyone steal
    another account's tip history out from under it."""
    device_id = payload.device_id
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})

    existing = db.query(TipPlayer).filter_by(user_id=user.id).one_or_none()
    device_player = db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()

    if device_player is None:
        # Nothing to claim -- a friendly no-op rather than an error, since the
        # frontend calls this on every sign-in without knowing in advance
        # whether the device ever tipped.
        return {"ok": True, "handle": existing.handle if existing else None, "claimed_tips": 0}

    if device_player.user_id is not None and device_player.user_id != user.id:
        # Device is already claimed by a DIFFERENT account -- never reassign,
        # merge, or delete another account's player row. Same no-op shape as
        # "nothing to claim" so this doesn't leak whether the device is
        # claimed, or by whom.
        return {"ok": True, "handle": existing.handle if existing else None, "claimed_tips": 0}

    if existing is None:
        device_player.user_id = user.id
        db.commit()
        claimed = db.query(UserTip).filter_by(player_id=device_player.id).count()
        return {"ok": True, "handle": device_player.handle, "claimed_tips": claimed}

    if existing.id == device_player.id:
        claimed = db.query(UserTip).filter_by(player_id=existing.id).count()
        return {"ok": True, "handle": existing.handle, "claimed_tips": claimed}

    existing_match_ids = {
        mid for (mid,) in db.query(UserTip.match_id).filter_by(player_id=existing.id).all()
    }
    moved = 0
    for tip in db.query(UserTip).filter_by(player_id=device_player.id).all():
        if tip.match_id in existing_match_ids:
            db.delete(tip)
        else:
            tip.player_id = existing.id
            moved += 1
    db.delete(device_player)
    db.commit()
    return {"ok": True, "handle": existing.handle, "claimed_tips": moved}
