"""Daily probability snapshots (spec 2026-07-09): the movers feature's data.

Delete-then-insert per (sport, day) so pipeline re-runs stay idempotent.
Reads the already-persisted serving tables — no model computation here.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    ProbabilitySnapshot, SportMatch, SportPrediction, Standing, TournamentOdds,
)


def _replace_day(db: Session, sport: str, day: date, rows: list[ProbabilitySnapshot]) -> int:
    db.query(ProbabilitySnapshot).filter(
        ProbabilitySnapshot.sport == sport,
        ProbabilitySnapshot.snapshot_date == day,
    ).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def snapshot_football(db: Session, snapshot_date: date | None = None) -> int:
    day = snapshot_date or date.today()
    rows: list[ProbabilitySnapshot] = []
    for odds in db.query(TournamentOdds).all():
        for market, prob in (("make_knockout", odds.make_knockout),
                             ("win_title", odds.win_title)):
            if prob is not None:
                rows.append(ProbabilitySnapshot(
                    sport="football", entity_id=odds.team_id, market=market,
                    ref_id=None, prob=prob, snapshot_date=day,
                ))
    for st in db.query(Standing).filter(Standing.qualification_prob.isnot(None)).all():
        rows.append(ProbabilitySnapshot(
            sport="football", entity_id=st.team_id, market="qualify_group",
            ref_id=None, prob=st.qualification_prob, snapshot_date=day,
        ))
    return _replace_day(db, "football", day, rows)


def snapshot_nrl(db: Session, snapshot_date: date | None = None) -> int:
    day = snapshot_date or date.today()
    rows: list[ProbabilitySnapshot] = []
    matches = (
        db.query(SportMatch)
        .filter(SportMatch.sport == "nrl", SportMatch.status == "scheduled")
        .all()
    )
    for m in matches:
        pred = (
            db.query(SportPrediction)
            .filter(SportPrediction.match_id == m.id)
            .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
            .first()
        )
        if pred is None:
            continue
        if m.home_team_id is not None:
            rows.append(ProbabilitySnapshot(
                sport="nrl", entity_id=m.home_team_id, market="win_match",
                ref_id=m.id, prob=pred.p_home, snapshot_date=day,
            ))
        if m.away_team_id is not None:
            rows.append(ProbabilitySnapshot(
                sport="nrl", entity_id=m.away_team_id, market="win_match",
                ref_id=m.id, prob=pred.p_away, snapshot_date=day,
            ))
    return _replace_day(db, "nrl", day, rows)
