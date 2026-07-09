"""Market intel: prediction-market odds vs the model + movement storylines.

Serves entirely from market_odds_snapshots (written hourly by
pipeline/market_intel.py) — the request path never touches an exchange API.
has_data=False (the frontend then falls back to the movers panel) when the
sport has no snapshot fresher than FRESH_HOURS. Only active exchange markets
are ever ingested, so resolved/eliminated outcomes cannot appear here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import serializers
from app.db import get_db
from app.models import (
    MarketOddsSnapshot, Match, SportMatch, SportPrediction, SportTeam, Team,
)

router = APIRouter(prefix="/api/intel", tags=["intel"])

FRESH_HOURS = 24    # no snapshot this recent -> has_data False (movers fallback)
LIVE_HOURS = 3      # storyline markets need a snapshot this recent (~2 cycles)
WINDOW_HOURS = 24   # movement comparison window
MIN_AGE_HOURS = 18  # a "from" snapshot must be at least this old
MAX_MATCHES = 5
MAX_STORYLINES = 3
_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


def _aware(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes for tz-aware columns; pin to UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("")
def intel(sport: str = Query(...), db: Session = Depends(get_db)):
    if sport not in ("football", "nrl"):
        raise HTTPException(status_code=422, detail={"code": "bad_sport",
                                                     "message": "sport must be football or nrl"})
    now = datetime.now(timezone.utc)
    horizon = (now - timedelta(hours=WINDOW_HOURS + 6)).replace(tzinfo=None)
    rows = (
        db.query(MarketOddsSnapshot)
        .filter(MarketOddsSnapshot.sport == sport,
                MarketOddsSnapshot.fetched_at >= horizon)
        .all()
    )
    latest_at = max((_aware(r.fetched_at) for r in rows), default=None)
    if latest_at is None or latest_at < now - timedelta(hours=FRESH_HOURS):
        return {"sport": sport, "has_data": False, "updated_at": None,
                "matches": [], "storylines": [], "disclaimer": _DISCLAIMER}

    # Newest row per (source, external_id, outcome) + full history per key.
    current: dict[tuple, MarketOddsSnapshot] = {}
    history: dict[tuple, list[MarketOddsSnapshot]] = defaultdict(list)
    for r in rows:
        key = (r.source, r.external_id, r.outcome)
        history[key].append(r)
        if key not in current or _aware(r.fetched_at) > _aware(current[key].fetched_at):
            current[key] = r

    fixtures, teams, models = _sport_context(db, sport, current, now)
    matches_out = _build_matches(sport, current, fixtures, teams, models)
    storylines = _build_storylines(current, history, fixtures, teams, now)
    return {"sport": sport, "has_data": True,
            "updated_at": latest_at.isoformat(),
            "matches": matches_out, "storylines": storylines,
            "disclaimer": _DISCLAIMER}


def _sport_context(db: Session, sport: str, current: dict, now: datetime):
    """(future fixtures by id, team names by id, model probs by match id)."""
    match_ids = {r.match_id for r in current.values()
                 if r.market_type == "match_winner" and r.match_id is not None}
    fixtures: dict[int, dict] = {}
    models: dict[int, dict] = {}
    if sport == "football":
        teams = dict(db.query(Team.id, Team.name).all())
        for m in (db.query(Match).filter(Match.id.in_(match_ids),
                                         Match.status == "scheduled").all()
                  if match_ids else []):
            if m.kickoff_utc is None or _aware(m.kickoff_utc) <= now:
                continue
            fixtures[m.id] = {"kickoff": _aware(m.kickoff_utc),
                              "home_id": m.team_home_id, "away_id": m.team_away_id}
            pred = serializers.latest_prediction(db, m.id)
            if pred is not None:
                models[m.id] = {"home": round(pred.prob_home_win, 3),
                                "draw": round(pred.prob_draw, 3),
                                "away": round(pred.prob_away_win, 3)}
    else:
        teams = dict(db.query(SportTeam.id, SportTeam.name)
                     .filter(SportTeam.sport == sport).all())
        for m in (db.query(SportMatch).filter(SportMatch.id.in_(match_ids),
                                              SportMatch.status == "scheduled").all()
                  if match_ids else []):
            if m.kickoff_utc is None or _aware(m.kickoff_utc) <= now:
                continue
            fixtures[m.id] = {"kickoff": _aware(m.kickoff_utc),
                              "home_id": m.home_team_id, "away_id": m.away_team_id}
            pred = (db.query(SportPrediction)
                    .filter(SportPrediction.match_id == m.id)
                    .order_by(SportPrediction.created_at.desc(),
                              SportPrediction.id.desc())
                    .first())
            if pred is not None:
                models[m.id] = {"home": round(pred.p_home, 3),
                                "draw": round(pred.p_draw, 3),
                                "away": round(pred.p_away, 3)}
    return fixtures, teams, models


def _build_matches(sport, current, fixtures, teams, models):
    by_match: dict[int, dict[str, dict[str, MarketOddsSnapshot]]] = \
        defaultdict(lambda: defaultdict(dict))
    for r in current.values():
        if r.market_type == "match_winner" and r.match_id in fixtures:
            by_match[r.match_id][r.source][r.outcome] = r

    out = []
    for match_id in sorted(by_match, key=lambda i: fixtures[i]["kickoff"])[:MAX_MATCHES]:
        fx = fixtures[match_id]
        markets = []
        for source in sorted(by_match[match_id]):
            oc = by_match[match_id][source]
            if "home" not in oc or "away" not in oc:
                continue
            markets.append({
                "source": source,
                "home": round(oc["home"].implied_prob, 3),
                "draw": round(oc["draw"].implied_prob, 3) if "draw" in oc else None,
                "away": round(oc["away"].implied_prob, 3),
                "fetched_at": _aware(oc["home"].fetched_at).isoformat(),
            })
        if not markets:
            continue
        model = models.get(match_id)
        disagreement = None
        if model is not None:
            market_home = sum(mk["home"] for mk in markets) / len(markets)
            disagreement = round(market_home - model["home"], 3)
        out.append({
            "match_id": match_id,
            "kickoff_utc": fx["kickoff"].isoformat(),
            "home": _team_ref(teams, fx["home_id"]),
            "away": _team_ref(teams, fx["away_id"]),
            "model": model, "market": markets, "disagreement": disagreement,
        })
    return out


def _team_ref(teams: dict, team_id: int | None):
    if team_id is None:
        return None
    return {"id": team_id, "name": teams.get(team_id, "Unknown")}


def _build_storylines(current, history, fixtures, teams, now):
    live_cut = now - timedelta(hours=LIVE_HOURS)
    old_cut = now - timedelta(hours=MIN_AGE_HOURS)
    target = now - timedelta(hours=WINDOW_HOURS)
    candidates = []
    for key, cur in current.items():
        if _aware(cur.fetched_at) < live_cut:
            continue
        if cur.market_type == "match_winner":
            if cur.outcome == "draw" or cur.match_id not in fixtures:
                continue
        elif cur.team_id is None:
            continue
        olds = [r for r in history[key] if _aware(r.fetched_at) <= old_cut]
        if not olds:
            continue
        past = min(olds, key=lambda r: abs((_aware(r.fetched_at) - target).total_seconds()))
        if past.implied_prob == cur.implied_prob:
            continue
        candidates.append((abs(cur.implied_prob - past.implied_prob), cur, past))

    candidates.sort(key=lambda c: c[0], reverse=True)
    out, seen = [], set()
    for _delta, cur, past in candidates:
        dedupe = (cur.market_type, cur.match_id, cur.team_id, cur.outcome)
        if dedupe in seen:
            continue  # same move reported by another source: keep the bigger one
        seen.add(dedupe)
        if cur.market_type == "match_winner":
            fx = fixtures[cur.match_id]
            team = _team_ref(teams, fx["home_id" if cur.outcome == "home" else "away_id"])
        else:
            team = _team_ref(teams, cur.team_id)
        window = (_aware(cur.fetched_at) - _aware(past.fetched_at)).total_seconds() / 3600
        out.append({
            "market_type": cur.market_type, "source": cur.source,
            "outcome": cur.outcome, "match_id": cur.match_id, "team": team,
            "prob_from": round(past.implied_prob, 3),
            "prob_to": round(cur.implied_prob, 3),
            "window_hours": round(window),
        })
        if len(out) == MAX_STORYLINES:
            break
    return out
