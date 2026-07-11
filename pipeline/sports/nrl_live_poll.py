"""NRL live-match polling (Wave 3).

For every nrl match currently inside its live window, calls
StatsProvider.fetch_live, computes the in-play win probability via
ml.sports.nrl.live_model.predict_live_prob (reusing the SAME pre-game
probability already frozen in SportPrediction -- never recomputed here),
and upserts NrlLiveState + appends any new NrlLiveEvent rows.

Matches don't carry an "in_play" status (NRL ingest only ever writes
"scheduled" or "finished" -- see pipeline/sports/nrl_ingest.py), and
nrl-refresh's twice-weekly ingest cron can lag a finished match's status
update by days. So "is this match live right now" is purely time-based:
kickoff_utc - 5min <= now <= kickoff_utc + 110min (80 minutes' play plus a
generous half-time/stoppage buffer), regardless of SportMatch.status.

StatsProvider.fetch_live's real contract (pipeline/sports/nrl_stats.py)
returns a LivePayload with status "pre" | "live" | "final" and a nullable
minute, and carries no scorer identity -- so events are logged as anonymous
"score" deltas for now; enrich type/player once a fetch_live implementation
richer than NrlComStatsProvider's honest None-stub lands. A "pre" payload
means the provider has nothing live yet -- treated the same as no payload
at all, and NrlLiveState is never written for it (see NrlLiveState's
docstring: its status is never "pre"). When the provider hasn't resolved a
minute yet (minute is None while status == "live"), a wall-clock estimate
is derived purely to drive the probability model and the NOT NULL
NrlLiveEvent.minute column -- NrlLiveState.minute itself is always stored
exactly as received (nullable by design), never fabricated.

Event attribution is per-side: a side gets a "score" event iff ITS score
increased vs the previously-stored state, so both sides scoring between two
polls yields two events (same minute/prob_after), and a downward feed
correction (a score revised down, nothing increased) updates the state
without logging any event.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction
from ml.sports.nrl.live_model import predict_live_prob
from ml.sports.nrl.live_params import load_nrl_live_params
from pipeline.sports.nrl_stats import LivePayload, StatsProvider

log = logging.getLogger(__name__)

SPORT = "nrl"
MATCH_MINUTES = 80
_WINDOW_AHEAD = timedelta(minutes=5)
_MATCH_DURATION = timedelta(minutes=110)


def matches_in_live_window(db: Session, now: datetime | None = None) -> list[SportMatch]:
    now = now or datetime.now(timezone.utc)
    return (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.kickoff_utc.isnot(None),
            SportMatch.kickoff_utc >= now - _MATCH_DURATION,
            SportMatch.kickoff_utc <= now + _WINDOW_AHEAD,
        )
        .all()
    )


def _pregame_prob(db: Session, match: SportMatch) -> float:
    latest = (
        db.query(SportPrediction)
        .filter_by(match_id=match.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    return latest.p_home if latest is not None else 0.5


def _elapsed_minutes(match: SportMatch, now: datetime) -> int:
    """Wall-clock fallback minute estimate for when the provider hasn't
    resolved a real minute yet (LivePayload.minute is None while
    status == "live"). SQLite round-trips DateTime(timezone=True) columns
    as naive, so a match's kickoff_utc may come back tzinfo-less even
    though it was always conceptually UTC -- normalize before subtracting.
    Clamped to a normal match's playing length. A match with no kickoff_utc
    at all (nullable column) estimates 0 elapsed -- conservative: the full 80
    minutes remain, so the probability stays pregame-dominated."""
    kickoff = match.kickoff_utc
    if kickoff is None:
        return 0
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    elapsed = int((now - kickoff).total_seconds() / 60)
    return max(0, min(elapsed, MATCH_MINUTES))


def poll_match(db: Session, match: SportMatch, provider: StatsProvider, now: datetime | None = None) -> dict | None:
    """Poll one match. Returns the upserted state as a dict, or None if the
    provider has nothing live yet -- no payload, or status == "pre" (never
    raises; a feed hiccup is logged and treated the same way)."""
    now = now or datetime.now(timezone.utc)
    try:
        payload: LivePayload | None = provider.fetch_live(match.season, match.round, match.match_no)
    except Exception as exc:  # noqa: BLE001
        log.warning("nrl live fetch(%s,%s,%s) failed: %s", match.season, match.round, match.match_no, exc)
        return None
    if payload is None or payload.status == "pre":
        return None

    effective_minute = payload.minute if payload.minute is not None else _elapsed_minutes(match, now)

    pregame = _pregame_prob(db, match)
    minutes_remaining = max(MATCH_MINUTES - effective_minute, 0)
    live_prob = predict_live_prob(
        score_diff=float(payload.score_home - payload.score_away),
        minutes_remaining=float(minutes_remaining),
        pregame_prob=pregame,
        params=load_nrl_live_params(),
    )

    state = db.query(NrlLiveState).filter_by(match_id=match.id).one_or_none()
    prev_score = (state.score_home, state.score_away) if state is not None else None
    if state is None:
        state = NrlLiveState(match_id=match.id)
        db.add(state)
    state.status = payload.status
    state.minute = payload.minute  # stored as-received -- nullable by design, never fabricated
    state.score_home = payload.score_home
    state.score_away = payload.score_away
    state.live_home_prob = live_prob

    if prev_score is not None:
        # Per-side attribution: an event is logged for each side whose score
        # INCREASED vs the previous observation (both can fire in one poll).
        # A change that is only a decrease is a feed correction -- the state
        # above is still updated, but nobody scored, so no event.
        for team, new, old in (("home", payload.score_home, prev_score[0]),
                               ("away", payload.score_away, prev_score[1])):
            if new > old:
                db.add(NrlLiveEvent(
                    match_id=match.id, minute=effective_minute, type="score",
                    team=team, player=None, prob_after=live_prob,
                ))

    db.commit()
    return {
        "match_id": match.id, "status": payload.status, "minute": payload.minute,
        "score_home": payload.score_home, "score_away": payload.score_away,
        "live_home_prob": live_prob,
    }


def poll_live_matches(db: Session, provider: StatsProvider, now: datetime | None = None) -> dict:
    """Poll every match currently in its live window. Never raises."""
    matches = matches_in_live_window(db, now=now)
    polled = sum(1 for m in matches if poll_match(db, m, provider, now=now) is not None)
    return {"candidates": len(matches), "polled": polled}
