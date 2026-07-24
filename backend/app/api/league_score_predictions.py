"""League score predictions -- "Beat the AI's scoreline" (design doc:
2026-07-24-league-score-predictions-design.md). The football-league port of
the NRL beat-the-AI loop (app/api/nrl_user_tips.py): anonymous, device-first
scoreline predictions against the model, graded once each match finishes.

LEAGUE-GENERIC BY CONSTRUCTION: every route takes a `league` short code
(path param on the router prefix), resolved to a Tournament row by
_resolve_league. Phase 1 wired up exactly one code (epl); Phase 2 adds La
Liga and Bundesliga to _LEAGUE_TOURNAMENT_NAMES (derived from
pipeline.leagues.LEAGUES, see that dict's own comment) -- not new endpoints
or new code paths.

Identity is shared with NRL: this file reuses tip_players (TipPlayer),
duplicating the small device-id/get-or-create idioms locally rather than
importing them, matching how this codebase already keeps each vertical's
copy of a shared pattern local (see nrl_tips.py's docstring on sports.py /
nrl_intel.py / nrl_live.py, and activity.py's own _DEVICE_ID_RE). POST
/api/nrl/tips/claim already claims a device's rows in this table too (see
its second reassign/dedupe loop, added for this table).

INTEGRITY: a prediction is rejected once its match's kickoff_utc has passed,
by the server clock only -- mirrors nrl_user_tips.submit_tip exactly. Until
then a device may change its scoreline freely (upsert on (match_id, player)).

Grading (points/exact/graded_at on LeagueScorePrediction) is a SEPARATE,
pipeline-owned pass (mirrors pipeline.sports.nrl_user_tips.grade()) --
nothing in this file ever writes those three columns. Scoring rule
(design doc, Super-6-compatible): 5 points for an exact score, 2 for the
correct result direction (win/draw/loss), 0 otherwise -- NOT cumulative. See
_score_prediction, which this file also uses to compute the MODEL's side of
the you-vs-AI comparison live, off the model's own frozen predicted scoreline
-- this is the same pure function the (pipeline-owned) grading pass must use
for player rows, so the two numbers can never disagree (see the parity test
in backend/tests/test_league_score_predictions_api.py)."""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, undefer

from app import schemas
from app.api.auth import _email_action_rate_limited
from app.db import get_db
from app.models import EmailActionAttempt, LeagueScorePrediction, Match, Prediction, Team, TipPlayer, Tournament
from app.security import client_ip, hash_ip, require_same_origin, to_aware_utc
from pipeline.leagues import LEAGUES as _PIPELINE_LEAGUES

router = APIRouter(prefix="/api/leagues/{league}", tags=["league-score-predictions"])

_DISCLAIMER = "For analytics and entertainment only. Not betting advice."

# Same strict UUID v4 shape as app.api.nrl_user_tips._DEVICE_ID_RE /
# app.api.activity's own copy (\A/\Z, not ^$, so a trailing newline can't
# slip a 37-char id past the check).
_DEVICE_ID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)

# A matchweek is ~9-10 fixtures for any of these leagues (Bundesliga 18
# teams/9 fixtures, EPL/La Liga 20 teams/10) and a prediction can be revised
# freely until kickoff, so the cap is generous (same magnitude as
# nrl_user_tips._SUBMIT_MAX) -- this exists to stop a scripted flood, not to
# limit normal matchweek-by-matchweek play. Scoped per-league (action string
# includes the league code) so one league's traffic never eats another's
# budget for the same device -- required once Phase 2 adds more codes.
_SUBMIT_ACTION = "league_tip_submit"
_SUBMIT_MAX = 120
_SUBMIT_WINDOW_MIN = 60

_LEADERBOARD_MIN_PARTICIPANTS = 10

_HANDLE_ADJECTIVES = (
    "Swift", "Brave", "Clutch", "Steady", "Fearless", "Sharp", "Bold",
    "Lightning", "Golden", "Silent", "Rapid", "Iron",
)
_HANDLE_NOUNS = (
    "Striker", "Keeper", "Winger", "Playmaker", "Sweeper", "Baller",
    "Captain", "Finisher", "Maestro", "Enforcer",
)

# Every league code -> tournament name this feature (tips/leaderboards/
# shares) knows how to resolve. Derived from pipeline.leagues.LEAGUES rather
# than hand-copied here as separate literals (Phase 1 had exactly one entry
# so the duplication was harmless; Phase 2 adds two more, and hand-copying
# tournament-name strings across two registries is exactly the kind of typo
# that would silently desync them -- one league's tips API 404ing
# league_not_found while its pipeline data loads fine, or vice versa).
#
# Deliberately keyed off ALL of LEAGUES, not pipeline.leagues.ACTIVE_LEAGUES:
# ACTIVE_LEAGUES gates a SEPARATE, quota-gated decision (whether the pipeline
# actually polls/ingests a league yet); this feature's surface going
# multi-league only needs a code to resolve to a tournament NAME so
# _resolve_league can look for that Tournament row -- correctly 404ing
# league_inactive (not league_not_found) for a registered-but-not-yet-loaded
# league, same as EPL would before its first pipeline run.
_LEAGUE_TOURNAMENT_NAMES: dict[str, str] = {
    code: cfg["tournament_name"] for code, cfg in _PIPELINE_LEAGUES.items()
}


def _resolve_league(db: Session, league: str) -> Tournament:
    """Short code -> the Tournament row it names. 404 `league_not_found` for a
    code outside _LEAGUE_TOURNAMENT_NAMES (typo / unsupported league); 404
    `league_inactive` for a real code whose tournament hasn't been loaded
    into this DB yet (pipeline hasn't run) -- same code/message shape as
    every other 404 in this feature."""
    name = _LEAGUE_TOURNAMENT_NAMES.get(league)
    if name is None:
        raise HTTPException(status_code=404, detail={
            "code": "league_not_found", "message": f"Unknown league {league!r}",
        })
    tournament = db.query(Tournament).filter_by(name=name).one_or_none()
    if tournament is None:
        raise HTTPException(status_code=404, detail={
            "code": "league_inactive", "message": f"League {league!r} has no data loaded yet",
        })
    return tournament


def _generate_handle() -> str:
    """A readable display name for a freshly-seen device -- never the raw
    device_id. Mirrors nrl_user_tips._generate_handle's shape with
    football-flavored words, since a device's first-ever play of EITHER
    sport is what mints its shared tip_players.handle. Not guaranteed
    unique; collisions are cosmetic only, same as the NRL side."""
    return f"{random.choice(_HANDLE_ADJECTIVES)}{random.choice(_HANDLE_NOUNS)}{random.randint(1, 999)}"


def _final_score(m: Match) -> tuple[int, int] | None:
    """The basis for grading a finished match: the frozen 90-minute score
    when present (FR-2.1's exact-score basis), else the final score. League
    fixtures never leave regulation (no knockout/extra-time stage exists for
    a league table), so score_home_90 equals score_home in every real case
    here -- this only matters if that ever stops being true."""
    h = m.score_home_90 if m.score_home_90 is not None else m.score_home
    a = m.score_away_90 if m.score_away_90 is not None else m.score_away
    if h is None or a is None:
        return None
    return h, a


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def _score_prediction(pred_home: int, pred_away: int, actual_home: int, actual_away: int) -> tuple[int, bool]:
    """Super-6-compatible scoring (design doc): 5 points for an exact score,
    2 for the correct result direction (win/draw/loss), 0 otherwise -- NOT
    cumulative (an exact score earns 5, not 7). Pure function shared by
    every caller that scores a prediction against a final result: the
    model's live-computed points here (mine/summary/share) and the
    (pipeline-owned) grading pass's write to a player's own row -- so the two
    numbers can never disagree as long as both feed it the same
    (predicted, actual) pair."""
    if pred_home == actual_home and pred_away == actual_away:
        return 5, True
    if _outcome(pred_home, pred_away) == _outcome(actual_home, actual_away):
        return 2, False
    return 0, False


def _kickoff_locked_prediction(preds_by_match: dict[int, list[Prediction]], m: Match) -> Prediction | None:
    """The prediction shown/scored for `m`: the latest row with created_at <=
    kickoff_utc when a kickoff is set -- mirrors nrl_tips._kickoff_locked_
    prediction and pipeline.learning_loop._frozen_prediction's eligible-row
    filter exactly (candidates already carry the created_at desc, id desc
    order the caller queried them in), so this never shows/scores a
    prediction the (pipeline-owned) grading pass wouldn't also select."""
    candidates = preds_by_match.get(m.id, [])
    if m.kickoff_utc is not None:
        candidates = [p for p in candidates if p.created_at <= m.kickoff_utc]
    return candidates[0] if candidates else None


def _current_matchweek(db: Session, tournament_id: int) -> int | None:
    """Matchweek containing the earliest still-scheduled match; if the whole
    tournament is finished (or nothing has a matchweek yet), the latest
    matchweek that has any match at all. Same rule shape as nrl_tips.
    _current_round, scoped to tournament_id instead of (sport, season) since
    one Tournament row already IS one season for a football league."""
    upcoming = (
        db.query(Match.matchweek)
        .filter(Match.tournament_id == tournament_id, Match.status != "finished",
                Match.matchweek.isnot(None))
        .order_by(Match.kickoff_utc.is_(None), Match.kickoff_utc.asc(), Match.id.asc())
        .first()
    )
    if upcoming is not None:
        return upcoming[0]
    weeks = [
        w for (w,) in db.query(Match.matchweek)
        .filter(Match.tournament_id == tournament_id, Match.matchweek.isnot(None)).all()
    ]
    return max(weeks) if weeks else None


def _prediction_streaks(items: list[tuple[LeagueScorePrediction, Match]]) -> tuple[int, int]:
    """(current_streak, best_streak) of consecutive scoring predictions
    (points > 0) across a player's graded history in this league. Ordered by
    kickoff, ties broken by match id -- mirrors nrl_user_tips._tip_streaks.
    No separate season filter is needed here (unlike NRL's): the caller
    already scopes `items` to one tournament_id, and one Tournament IS one
    season for a football league, so tournament-scoping already gives the
    season-scoping the design doc asks for."""
    ordered = sorted(items, key=lambda tm: (tm[1].kickoff_utc is None, tm[1].kickoff_utc, tm[1].id))
    best = streak = 0
    for t, _ in ordered:
        streak = streak + 1 if (t.points or 0) > 0 else 0
        best = max(best, streak)
    return streak, best


def _find_player(db: Session, device_id: str) -> TipPlayer | None:
    """Split out from _get_or_create_player so the check-then-insert race is
    easy to force in tests -- mirrors nrl_user_tips._find_player."""
    return db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()


def _get_or_create_player(db: Session, device_id: str) -> TipPlayer:
    player = _find_player(db, device_id)
    if player is None:
        player = TipPlayer(device_id=device_id, handle=_generate_handle())
        db.add(player)
        try:
            db.flush()  # need player.id before it can own a LeagueScorePrediction row
        except IntegrityError:
            # Lost a race with a concurrent first-play from the same brand-new
            # device (both passed the check above before either flushed) --
            # the row exists either way, so re-read it instead of 500ing.
            # Queried directly rather than via _find_player so a test forcing
            # that check to miss doesn't also poison this re-read (mirrors
            # nrl_user_tips._get_or_create_player).
            db.rollback()
            player = db.query(TipPlayer).filter_by(device_id=device_id).one()
    return player


def _find_prediction(db: Session, match_id: int, player_id: int) -> LeagueScorePrediction | None:
    """Mirrors _find_player -- split out so a concurrent first-submit race on
    the same (match, player) is easy to force in tests."""
    return db.query(LeagueScorePrediction).filter_by(match_id=match_id, player_id=player_id).one_or_none()


@router.post("/tips/submit", dependencies=[Depends(require_same_origin)])
def submit_prediction(
    league: str, payload: schemas.LeagueScorePredictionSubmitIn, request: Request,
    db: Session = Depends(get_db),
):
    """Upsert one device's scoreline guess for one match. A device may change
    its prediction freely until the match's kickoff_utc -- checked against
    the server clock, never the client's -- after which it's frozen."""
    tournament = _resolve_league(db, league)

    device_id = payload.device_id
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})
    if not (0 <= payload.predicted_home <= 15) or not (0 <= payload.predicted_away <= 15):
        raise HTTPException(status_code=422, detail={"code": "bad_score",
                                                     "message": "predicted_home/predicted_away must be between 0 and 15."})

    ip_h = hash_ip(client_ip(request))
    action = f"{_SUBMIT_ACTION}:{league}"
    if _email_action_rate_limited(db, action, device_id, ip_h, _SUBMIT_MAX, _SUBMIT_WINDOW_MIN):
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts",
                                                     "message": "Too many attempts. Try again later."})
    # Committed immediately (not batched with the prediction write below) so
    # every attempt that clears the cheap payload checks counts toward the
    # rate limit even if a later check (kickoff lock, bad match) rejects it --
    # mirrors nrl_user_tips.submit_tip.
    db.add(EmailActionAttempt(action=action, email=device_id, ip_hash=ip_h))
    db.commit()

    m = db.query(Match).filter_by(id=payload.match_id, tournament_id=tournament.id).one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail={"code": "match_not_found",
                                                     "message": f"No {league} match {payload.match_id}"})

    now = datetime.now(timezone.utc)
    # Belt-and-braces on top of the kickoff comparison below: a match that's
    # already finished (or already has a final score) is locked even if its
    # kickoff_utc is somehow missing -- mirrors nrl_user_tips.submit_tip.
    already_played = m.status == "finished" or (m.score_home is not None and m.score_away is not None)
    if already_played or (m.kickoff_utc is not None and now >= to_aware_utc(m.kickoff_utc)):
        raise HTTPException(status_code=422, detail={
            "code": "match_locked",
            "message": f"Match {m.id} has kicked off and is locked.",
        })

    player = _get_or_create_player(db, device_id)
    pred = _find_prediction(db, m.id, player.id)
    if pred is None:
        pred = LeagueScorePrediction(
            tournament_id=tournament.id, match_id=m.id, player_id=player.id,
            predicted_home=payload.predicted_home, predicted_away=payload.predicted_away,
            updated_at=now,
        )
        db.add(pred)
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with a concurrent first prediction for this (match,
            # player) -- the row exists either way; re-read it (directly, not
            # via _find_prediction -- see _get_or_create_player) and apply
            # this request's guess as the update, same idempotent-success
            # idiom as nrl_user_tips.submit_tip.
            db.rollback()
            pred = db.query(LeagueScorePrediction).filter_by(match_id=m.id, player_id=player.id).one()
            pred.predicted_home = payload.predicted_home
            pred.predicted_away = payload.predicted_away
            pred.updated_at = now
            db.commit()
    else:
        pred.predicted_home = payload.predicted_home
        pred.predicted_away = payload.predicted_away
        pred.updated_at = now
        db.commit()

    return {
        "ok": True,
        "handle": player.handle,
        "prediction": {
            "match_id": m.id,
            "predicted_home": pred.predicted_home,
            "predicted_away": pred.predicted_away,
            "updated_at": pred.updated_at.isoformat() if pred.updated_at else None,
        },
    }


@router.get("/tips/mine")
def my_predictions(league: str, device_id: str, matchweek: int | None = None, db: Session = Depends(get_db)):
    """One device's predictions for a matchweek, with grading once graded,
    alongside the model's own kickoff-locked scoreline per match."""
    tournament = _resolve_league(db, league)
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})
    if matchweek is None:
        matchweek = _current_matchweek(db, tournament.id)
        if matchweek is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_matchweek_data", "message": f"No {league} matchweeks are loaded yet",
            })

    home_team, away_team = aliased(Team), aliased(Team)
    rows = (
        db.query(Match, home_team.name, away_team.name)
        .outerjoin(home_team, Match.team_home_id == home_team.id)
        .outerjoin(away_team, Match.team_away_id == away_team.id)
        .filter(Match.tournament_id == tournament.id, Match.matchweek == matchweek)
        .order_by(Match.kickoff_utc.is_(None), Match.kickoff_utc.asc(), Match.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail={
            "code": "matchweek_not_found",
            "message": f"No matches for matchweek {matchweek}",
        })

    match_ids = [m.id for m, _, _ in rows]
    preds = (
        db.query(Prediction)
        # is_shadow.is_(False): shadow twins (odds/availability/offsets/rest)
        # share created_at with the production row (same generate_predictions
        # transaction) but are written AFTER it, so they'd win the
        # created_at desc, id desc tiebreak in _kickoff_locked_prediction if
        # not excluded here -- mirrors learning_loop._frozen_prediction and
        # every other public-facing Prediction read (predictions.py,
        # prob_history.py, serializers.py).
        .filter(Prediction.match_id.in_(match_ids), Prediction.is_shadow.is_(False))
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[Prediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    player = db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()
    yours_by_match: dict[int, LeagueScorePrediction] = {}
    if player is not None:
        for pr in (
            db.query(LeagueScorePrediction)
            .filter(LeagueScorePrediction.player_id == player.id, LeagueScorePrediction.match_id.in_(match_ids))
            .all()
        ):
            yours_by_match[pr.match_id] = pr

    matches_out = []
    for m, home_name, away_name in rows:
        pred = _kickoff_locked_prediction(preds_by_match, m)
        model_out = None
        if pred is not None:
            model_out = {
                "predicted_home": pred.predicted_score_home,
                "predicted_away": pred.predicted_score_away,
                "model_version": pred.model_version,
            }
        yours = yours_by_match.get(m.id)
        your_out = None
        if yours is not None:
            your_out = {
                "predicted_home": yours.predicted_home,
                "predicted_away": yours.predicted_away,
                "points": yours.points,
                "exact": yours.exact,
                "graded_at": yours.graded_at.isoformat() if yours.graded_at else None,
                "updated_at": yours.updated_at.isoformat() if yours.updated_at else None,
            }
        matches_out.append({
            "id": m.id,
            "home": home_name,
            "away": away_name,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "status": m.status,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "model": model_out,
            "your_prediction": your_out,
        })

    return {
        "league": league,
        "matchweek": matchweek,
        "handle": player.handle if player else None,
        "matches": matches_out,
        "disclaimer": _DISCLAIMER,
    }


@router.get("/tips/summary")
def predictions_summary(league: str, device_id: str, db: Session = Depends(get_db)):
    """Season-long you-vs-AI record for one league: per graded matchweek, the
    device's points vs the model's -- the model's side scored live off its
    own frozen scoreline with the identical _score_prediction rule, so the
    two numbers are directly comparable. Also surfaces streak/best-matchweek
    stats -- null-safe zeroes/None when nothing is graded yet."""
    tournament = _resolve_league(db, league)
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_device_id",
                                                     "message": "device_id must be a UUID v4."})

    zero_totals = {"your_points": 0, "model_points": 0, "matchweeks_played": 0}
    zero_streaks = {"current_streak": 0, "best_streak": 0, "best_matchweek": None}
    player = db.query(TipPlayer).filter_by(device_id=device_id).one_or_none()
    if player is None:
        return {"league": league, "handle": None, "matchweeks": [], "totals": zero_totals,
                **zero_streaks, "disclaimer": _DISCLAIMER}

    rows = (
        db.query(LeagueScorePrediction, Match)
        .join(Match, LeagueScorePrediction.match_id == Match.id)
        # Match.matchweek is deferred (models/__init__.py, mirrors
        # residual_ledger's deploy-window hardening) so a plain full-entity
        # load wouldn't include it -- undefer it here since the by_week
        # grouping below reads m.matchweek on every row and would otherwise
        # take a lazy-load round trip per distinct match.
        .options(undefer(Match.matchweek))
        .filter(LeagueScorePrediction.player_id == player.id,
                LeagueScorePrediction.tournament_id == tournament.id,
                LeagueScorePrediction.graded_at.isnot(None))
        .all()
    )
    if not rows:
        return {"league": league, "handle": player.handle, "matchweeks": [], "totals": zero_totals,
                **zero_streaks, "disclaimer": _DISCLAIMER}

    current_streak, best_streak = _prediction_streaks(rows)

    by_week: dict[int | None, list[tuple[LeagueScorePrediction, Match]]] = {}
    for t, m in rows:
        by_week.setdefault(m.matchweek, []).append((t, m))

    match_ids = [m.id for _, m in rows]
    preds = (
        db.query(Prediction)
        # is_shadow.is_(False): shadow twins (odds/availability/offsets/rest)
        # share created_at with the production row (same generate_predictions
        # transaction) but are written AFTER it, so they'd win the
        # created_at desc, id desc tiebreak in _kickoff_locked_prediction if
        # not excluded here -- mirrors learning_loop._frozen_prediction and
        # every other public-facing Prediction read (predictions.py,
        # prob_history.py, serializers.py).
        .filter(Prediction.match_id.in_(match_ids), Prediction.is_shadow.is_(False))
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[Prediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    weeks_out = []
    total_your = total_model = 0
    for week, items in sorted(by_week.items(), key=lambda kv: (kv[0] is None, kv[0])):
        your_points = sum(t.points or 0 for t, _ in items)
        model_points = 0
        for t, m in items:
            pred = _kickoff_locked_prediction(preds_by_match, m)
            actual = _final_score(m)
            if pred is not None and actual is not None and pred.predicted_score_home is not None \
                    and pred.predicted_score_away is not None:
                pts, _ = _score_prediction(pred.predicted_score_home, pred.predicted_score_away, actual[0], actual[1])
                model_points += pts
        weeks_out.append({
            "matchweek": week, "your_points": your_points, "model_points": model_points,
            "matches_played": len(items),
        })
        total_your += your_points
        total_model += model_points

    # Max your_points wins; ties broken toward the later matchweek. Zero
    # points -- every graded matchweek scored nothing -- isn't a "best
    # matchweek" worth bragging about, so that's null too (mirrors
    # nrl_user_tips.tips_summary's best_round).
    best_matchweek = None
    if weeks_out:
        best = max(weeks_out, key=lambda r: (r["your_points"], r["matchweek"] if r["matchweek"] is not None else -1))
        if best["your_points"] > 0:
            best_matchweek = {"matchweek": best["matchweek"], "points": best["your_points"]}

    return {
        "league": league,
        "handle": player.handle,
        "matchweeks": weeks_out,
        "totals": {"your_points": total_your, "model_points": total_model, "matchweeks_played": len(weeks_out)},
        "current_streak": current_streak,
        "best_streak": best_streak,
        "best_matchweek": best_matchweek,
        "disclaimer": _DISCLAIMER,
    }


@router.get("/tips/leaderboard")
def predictions_leaderboard(league: str, matchweek: int, db: Session = Depends(get_db)):
    """Per-matchweek leaderboard. Hidden below _LEADERBOARD_MIN_PARTICIPANTS
    -- participant_count is always returned so the UI can show "N players so
    far", but individual entries (and every device_id) stay unexposed until
    the matchweek has a real crowd. Never returns a device_id. Counts anyone
    who SUBMITTED a prediction for this matchweek, graded or not (mirrors
    nrl_user_tips.tips_leaderboard's population rule) -- ungraded rows just
    contribute 0 points/0 exact until the match finishes."""
    tournament = _resolve_league(db, league)
    match_ids = [
        mid for (mid,) in db.query(Match.id)
        .filter(Match.tournament_id == tournament.id, Match.matchweek == matchweek)
        .all()
    ]
    if not match_ids:
        raise HTTPException(status_code=404, detail={
            "code": "matchweek_not_found",
            "message": f"No matches for matchweek {matchweek}",
        })

    rows = (
        db.query(LeagueScorePrediction, TipPlayer)
        .join(TipPlayer, LeagueScorePrediction.player_id == TipPlayer.id)
        .filter(LeagueScorePrediction.match_id.in_(match_ids))
        .all()
    )
    by_player: dict[int, list[LeagueScorePrediction]] = {}
    handles: dict[int, str] = {}
    for t, p in rows:
        by_player.setdefault(p.id, []).append(t)
        handles[p.id] = p.handle

    participant_count = len(by_player)
    entries = []
    if participant_count >= _LEADERBOARD_MIN_PARTICIPANTS:
        for player_id, preds in by_player.items():
            points = sum(t.points or 0 for t in preds)
            exact_count = sum(1 for t in preds if t.exact)
            entries.append({"handle": handles[player_id], "points": points, "exact_count": exact_count})
        entries.sort(key=lambda e: (-e["points"], -e["exact_count"], e["handle"]))

    return {
        "league": league, "matchweek": matchweek,
        "participant_count": participant_count,
        "entries": entries,
    }


@router.get("/tips/leaderboard/season")
def predictions_leaderboard_season(league: str, db: Session = Depends(get_db)):
    """Season-long leaderboard: per-player totals across every graded
    matchweek in this league's tournament. Same reveal gate and no-device_id
    rule as the weekly board -- only the ranking key/population differ.
    Unlike the weekly board, population here is players with at least one
    GRADED prediction (mirrors nrl_user_tips.tips_leaderboard_season's
    submitted-vs-graded distinction) -- a running season total only means
    something once something's been graded."""
    tournament = _resolve_league(db, league)

    rows = (
        db.query(LeagueScorePrediction, Match.matchweek, TipPlayer)
        .join(TipPlayer, LeagueScorePrediction.player_id == TipPlayer.id)
        .join(Match, LeagueScorePrediction.match_id == Match.id)
        .filter(LeagueScorePrediction.graded_at.isnot(None), LeagueScorePrediction.tournament_id == tournament.id)
        .all()
    )
    by_player: dict[int, list[tuple[LeagueScorePrediction, int | None]]] = {}
    handles: dict[int, str] = {}
    for t, week, p in rows:
        by_player.setdefault(p.id, []).append((t, week))
        handles[p.id] = p.handle

    participant_count = len(by_player)
    entries = []
    if participant_count >= _LEADERBOARD_MIN_PARTICIPANTS:
        for player_id, preds in by_player.items():
            points = sum(t.points or 0 for t, _ in preds)
            exact_count = sum(1 for t, _ in preds if t.exact)
            matchweeks_played = len({week for _, week in preds})
            entries.append({
                "handle": handles[player_id], "points": points,
                "exact_count": exact_count, "matchweeks_played": matchweeks_played,
            })
        entries.sort(key=lambda e: (-e["points"], -e["exact_count"], e["handle"]))

    return {
        "league": league,
        "participant_count": participant_count,
        "entries": entries,
    }


@router.get("/tips/share/{matchweek}/{handle}")
def predictions_share(league: str, matchweek: int, handle: str, db: Session = Depends(get_db)):
    """Public, handle-addressed data for the share card -- UNFAKEABLE by
    construction: every number here is read straight off the graded
    LeagueScorePrediction/Match rows the leaderboard already trusts, never a
    client-supplied score.

    Exposes GRADED results only: a handle with no graded prediction in this
    matchweek -- because the handle doesn't exist, that player never
    predicted this matchweek, or it just isn't graded yet -- 404s with the
    SAME code/message in every case, so probing the handle namespace can't
    distinguish the three (mirrors nrl_user_tips.tips_share exactly).

    matchweek_complete tells the page whether player_of/model_of are the
    WHOLE matchweek or just what's graded so far -- grading runs per finished
    match, not per whole matchweek, so a matchweek can sit partially graded
    for days."""
    tournament = _resolve_league(db, league)

    candidates = db.query(TipPlayer).filter(TipPlayer.handle == handle).order_by(TipPlayer.id.asc()).all()
    player_ids = [p.id for p in candidates]
    rows = []
    if player_ids:
        rows = (
            db.query(LeagueScorePrediction, Match)
            .join(Match, LeagueScorePrediction.match_id == Match.id)
            .filter(
                LeagueScorePrediction.player_id.in_(player_ids),
                LeagueScorePrediction.graded_at.isnot(None),
                LeagueScorePrediction.tournament_id == tournament.id,
                Match.matchweek == matchweek,
            )
            .all()
        )
    if not rows:
        raise HTTPException(status_code=404, detail={
            "code": "share_not_found",
            "message": f"No graded result for {handle!r} in {league} matchweek {matchweek}.",
        })

    # handle has no uniqueness constraint -- if more than one TipPlayer ever
    # landed on this exact string AND both played this matchweek, resolve
    # deterministically to the oldest registrant (mirrors nrl_user_tips.
    # tips_share) rather than whichever the join happened to return first.
    by_player: dict[int, list[tuple[LeagueScorePrediction, Match]]] = {}
    for t, m in rows:
        by_player.setdefault(t.player_id, []).append((t, m))
    chosen_id = min(by_player)
    items = by_player[chosen_id]
    handle_display = next(p.handle for p in candidates if p.id == chosen_id)

    match_ids = [m.id for _, m in items]
    preds = (
        db.query(Prediction)
        # is_shadow.is_(False): shadow twins (odds/availability/offsets/rest)
        # share created_at with the production row (same generate_predictions
        # transaction) but are written AFTER it, so they'd win the
        # created_at desc, id desc tiebreak in _kickoff_locked_prediction if
        # not excluded here -- mirrors learning_loop._frozen_prediction and
        # every other public-facing Prediction read (predictions.py,
        # prob_history.py, serializers.py).
        .filter(Prediction.match_id.in_(match_ids), Prediction.is_shadow.is_(False))
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[Prediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    # Same live-scoring pattern as predictions_summary, over the SAME
    # per-matchweek prediction set, so this number never disagrees with what
    # /summary shows this player for this matchweek.
    player_points = sum(t.points or 0 for t, _ in items)
    model_points = 0
    for t, m in items:
        pred = _kickoff_locked_prediction(preds_by_match, m)
        actual = _final_score(m)
        if pred is not None and actual is not None and pred.predicted_score_home is not None \
                and pred.predicted_score_away is not None:
            pts, _ = _score_prediction(pred.predicted_score_home, pred.predicted_score_away, actual[0], actual[1])
            model_points += pts

    # Whole-matchweek completeness, independent of what THIS player
    # predicted -- every match in (tournament, matchweek) must be finished.
    # Same belt-and-braces "status OR both scores present" check
    # submit_prediction's already_played uses.
    matchweek_matches = (
        db.query(Match)
        .filter(Match.tournament_id == tournament.id, Match.matchweek == matchweek)
        .all()
    )
    matchweek_complete = bool(matchweek_matches) and all(
        m.status == "finished" or (m.score_home is not None and m.score_away is not None)
        for m in matchweek_matches
    )

    return {
        "handle_display": handle_display,
        "league": league,
        "matchweek": matchweek,
        "player_points": player_points,
        "player_of": len(items),
        "model_points": model_points,
        "model_of": len(items),
        "matchweek_complete": matchweek_complete,
        "disclaimer": _DISCLAIMER,
    }
