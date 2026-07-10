"""Movers: biggest daily probability swings, powering the home hero.

Ranking: |latest - previous| per (entity, market, ref) across the two most
recent snapshot days for the sport. With a single day of data, deltas are
null and rows fall back to highest probability (frontend hides the arrows).
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProbabilitySnapshot, SportMatch, SportTeam, Team

router = APIRouter(prefix="/api/movers", tags=["movers"])

_SERIES_DAYS = 7


@router.get("")
def movers(sport: str = Query(...), limit: int = Query(3, ge=1, le=20),
           db: Session = Depends(get_db)):
    if sport not in ("football", "nrl"):
        raise HTTPException(status_code=422, detail={"code": "bad_sport",
                                                     "message": "sport must be football or nrl"})

    days = [d for (d,) in (
        db.query(ProbabilitySnapshot.snapshot_date)
        .filter(ProbabilitySnapshot.sport == sport)
        .distinct().order_by(ProbabilitySnapshot.snapshot_date.desc())
        .limit(_SERIES_DAYS).all()
    )]
    if not days:
        return {"sport": sport, "as_of": None, "movers": [],
                "disclaimer": "For analytics and entertainment only. Not betting advice."}
    days_asc = sorted(days)

    rows = (
        db.query(ProbabilitySnapshot)
        .filter(ProbabilitySnapshot.sport == sport,
                ProbabilitySnapshot.snapshot_date.in_(days))
        .all()
    )
    by_key: dict[tuple, dict] = defaultdict(dict)  # key -> {date: prob}
    for r in rows:
        by_key[(r.entity_id, r.market, r.ref_id)][r.snapshot_date] = r.prob

    latest, prev = days_asc[-1], (days_asc[-2] if len(days_asc) > 1 else None)
    items = []
    for (entity_id, market, ref_id), by_day in by_key.items():
        if latest not in by_day:
            continue
        prob = by_day[latest]
        delta = (prob - by_day[prev]) if (prev is not None and prev in by_day) else None
        series = [by_day[d] for d in days_asc if d in by_day]
        items.append({"entity_id": entity_id, "market": market, "ref_id": ref_id,
                      "prob": prob, "delta": delta, "series": series})

    items.sort(key=lambda m: (abs(m["delta"]) if m["delta"] is not None else -1, m["prob"]),
               reverse=True)
    items = items[:limit]

    model = SportTeam if sport == "nrl" else Team
    names = dict(
        db.query(model.id, model.name)
        .filter(model.id.in_([m["entity_id"] for m in items]))
        .all()
    ) if items else {}

    match_urls: dict[int, str] = {}
    if sport == "nrl":
        ref_ids = {
            m["ref_id"] for m in items
            if m["market"] == "win_match" and m["ref_id"] is not None
        }
        if ref_ids:
            for sm in db.query(SportMatch).filter(SportMatch.id.in_(ref_ids)).all():
                if sm.round is not None:
                    match_urls[sm.id] = f"/nrl/match/{sm.season}/{sm.round}/{sm.match_no}"

    for m in items:
        m["name"] = names.get(m["entity_id"], "Unknown")
        m["match_url"] = match_urls.get(m["ref_id"]) if sport == "nrl" else None
        del m["ref_id"]  # internal only -- keep the public shape unchanged otherwise

    return {
        "sport": sport,
        "as_of": latest.isoformat(),
        "movers": items,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
