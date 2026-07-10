"""NRL Match Intelligence (Wave 1): per-match detail (prediction, form, h2h,
factors), finals projections, and NRL probability history. A separate router
from app.api.sports (same /api/nrl prefix, different paths -- mirrors how
football splits /api/matches across matches.py and prob_history.py).
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam
from pipeline.sports.nrl_form import _kickoff_key, form_averages, last_n_results

router = APIRouter(prefix="/api/nrl", tags=["nrl-intel"])

SPORT = "nrl"
_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


_FORM_OVERFETCH = 1000  # effectively "all" -- no NRL team accumulates this many
                        # finished matches in the dataset; used so filtering out
                        # the h2h opponent below still leaves a true last-5.


def _team_form_block(db: Session, team_id: int, before: SportMatch,
                      exclude_opponent_id: int | None = None) -> dict:
    """Last-5 finished results and averages for `team_id`, ahead of `before`.

    `exclude_opponent_id` drops meetings against the upcoming match's other
    side: those are already surfaced in the `h2h` block, so counting them here
    too would double up the same data point across both panels and (for a
    team that meets its next opponent often) crowd out genuinely different
    recent form. Overfetch first, then filter, then truncate -- filtering
    after `last_n_results` already limited to 5 could otherwise leave fewer
    than 5 even when 5 non-h2h results exist.
    """
    raw = last_n_results(db, team_id, n=_FORM_OVERFETCH, before=before)
    if exclude_opponent_id is not None:
        raw = [r for r in raw if r["opponent_id"] != exclude_opponent_id]
    results = raw[:5]
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    last5 = [
        {"round": r["round"], "opponent": names.get(r["opponent_id"], "Unknown"),
         "result": r["result"], "for": r["for"], "against": r["against"]}
        for r in results
    ]
    return {"last5": last5, **form_averages(results)}


def _head_to_head(db: Session, home_id: int, away_id: int, exclude_match_id: int,
                   limit: int = 5) -> list[dict]:
    rows = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT, SportMatch.status == "finished",
            SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None),
            SportMatch.id != exclude_match_id,
            or_(
                (SportMatch.home_team_id == home_id) & (SportMatch.away_team_id == away_id),
                (SportMatch.home_team_id == away_id) & (SportMatch.away_team_id == home_id),
            ),
        )
        .all()
    )
    rows.sort(key=_kickoff_key, reverse=True)
    rows = rows[:limit]
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    out = []
    for m in rows:
        winner = ("home" if m.score_home > m.score_away
                  else "away" if m.score_away > m.score_home else "draw")
        out.append({
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "home": names.get(m.home_team_id, "Unknown"),
            "away": names.get(m.away_team_id, "Unknown"),
            "score_home": m.score_home, "score_away": m.score_away, "winner": winner,
        })
    return out


def _composite(form: dict) -> float:
    results = form["last5"]
    win_rate = (sum(1 for r in results if r["result"] == "W") / len(results)) if results else 0.5
    return win_rate * 0.6 + (form["avg_margin"] / 40.0) * 0.4


def _build_factors(home: SportTeam, away: SportTeam, home_form: dict, away_form: dict) -> list[dict]:
    elo_home = home.elo_rating if home.elo_rating is not None else 1500.0
    elo_away = away.elo_rating if away.elo_rating is not None else 1500.0
    elo_favors = "home" if elo_home >= elo_away else "away"
    form_favors = "home" if _composite(home_form) >= _composite(away_form) else "away"

    return [
        {"key": "elo_gap", "label": "Elo rating gap", "weight": 0.5, "favors": elo_favors},
        {"key": "form_composite", "label": "Recent form", "weight": 0.3, "favors": form_favors},
        {"key": "home_advantage", "label": "Home advantage", "weight": 0.2, "favors": "home"},
    ]


@router.get("/matches/{match_id}")
def nrl_match_detail(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    home = db.get(SportTeam, m.home_team_id) if m.home_team_id else None
    away = db.get(SportTeam, m.away_team_id) if m.away_team_id else None

    match_out = {
        "id": m.id, "season": m.season, "round": m.round, "match_no": m.match_no,
        "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
        "venue": m.venue, "home": home.name if home else None, "away": away.name if away else None,
        "home_team_id": m.home_team_id, "away_team_id": m.away_team_id,
        "score_home": m.score_home, "score_away": m.score_away, "status": m.status,
    }

    pred = (
        db.query(SportPrediction).filter_by(match_id=m.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    prediction_out = None
    if pred is not None:
        prediction_out = {
            "home_prob": pred.p_home, "away_prob": pred.p_away, "draw_prob": pred.p_draw,
            "predicted_margin": pred.predicted_margin, "predicted_total": pred.predicted_total,
            "model_version": pred.model_version, "preview_text": pred.preview_text,
        }

    home_form = (
        _team_form_block(db, m.home_team_id, before=m, exclude_opponent_id=m.away_team_id)
        if m.home_team_id else None
    )
    away_form = (
        _team_form_block(db, m.away_team_id, before=m, exclude_opponent_id=m.home_team_id)
        if m.away_team_id else None
    )

    factors: list[dict] = []
    if home is not None and away is not None and home_form is not None and away_form is not None:
        factors = _build_factors(home, away, home_form, away_form)

    h2h = (
        _head_to_head(db, m.home_team_id, m.away_team_id, exclude_match_id=m.id)
        if (m.home_team_id and m.away_team_id) else []
    )

    return {
        "match": match_out,
        "prediction": prediction_out,
        "form": {"home": home_form, "away": away_form},
        "h2h": h2h,
        "factors": factors,
    }


@router.get("/projections")
def nrl_projections(db: Session = Depends(get_db)):
    rows = db.query(NrlProjection).order_by(NrlProjection.top8.desc()).all()
    computed_at = rows[0].computed_at if rows else None
    return {
        "computed_at": computed_at.isoformat() if computed_at else None,
        "teams": [
            {"team": r.team, "top8": r.top8, "top4": r.top4,
             "minor_premiership": r.minor_premiership}
            for r in rows
        ],
    }


@router.get("/matches/{match_id}/prob-history")
def nrl_prob_history(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    rows = (
        db.query(ProbabilitySnapshot)
        .filter(ProbabilitySnapshot.sport == SPORT, ProbabilitySnapshot.market == "win_match",
                ProbabilitySnapshot.ref_id == match_id)
        .order_by(ProbabilitySnapshot.snapshot_date.asc())
        .all()
    )
    by_day: dict[date, dict[int, float]] = {}
    for r in rows:
        by_day.setdefault(r.snapshot_date, {})[r.entity_id] = r.prob

    points = []
    for day, by_entity in sorted(by_day.items()):
        p_home = by_entity.get(m.home_team_id)
        p_away = by_entity.get(m.away_team_id)
        if p_home is None and p_away is None:
            continue
        p_draw = round(1.0 - p_home - p_away, 6) if p_home is not None and p_away is not None else None
        points.append({"date": day.isoformat(), "p_home": p_home, "p_draw": p_draw, "p_away": p_away})

    return {"match_id": match_id, "points": points, "disclaimer": _DISCLAIMER}
