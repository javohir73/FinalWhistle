"""Read-only NRL API (multi-sport vertical, task 6).

Two endpoints only, both read-only: `/matches` (fixtures grouped by round,
each with its LATEST prediction attached — shadow included, since this
endpoint IS the shadow surface pre-launch, unlike football's public
/api/matches which filters shadow rows out via serializers.latest_prediction)
and `/model/record` (the same record shape family as football's
/api/model/record, computed from the graded SportPredictionResult ledger).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import aliased, Session

from app.api.model_record import wilson_ci95
from app.db import get_db
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam

router = APIRouter(prefix="/api/nrl", tags=["nrl"])


def _latest_season(db: Session) -> int | None:
    row = (
        db.query(SportMatch.season)
        .filter(SportMatch.sport == "nrl")
        .order_by(SportMatch.season.desc())
        .first()
    )
    return row[0] if row else None


@router.get("/matches")
def nrl_matches(round: int | None = None, season: int | None = None,
                db: Session = Depends(get_db)):
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    home = aliased(SportTeam)
    away = aliased(SportTeam)
    q = (
        db.query(SportMatch, home.name, away.name)
        .outerjoin(home, SportMatch.home_team_id == home.id)
        .outerjoin(away, SportMatch.away_team_id == away.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season)
    )
    if round is not None:
        q = q.filter(SportMatch.round == round)
    rows = q.order_by(
        SportMatch.round.asc(), SportMatch.kickoff_utc.is_(None),
        SportMatch.kickoff_utc.asc(), SportMatch.match_no.asc(),
    ).all()

    if not rows:
        detail = (
            {"code": "round_not_found", "message": f"No matches for round {round} in season {season}"}
            if round is not None
            else {"code": "season_not_found", "message": f"No NRL matches for season {season}"}
        )
        raise HTTPException(status_code=404, detail=detail)

    match_ids = [m.id for m, _, _ in rows]
    # Latest prediction per match_id, single query (avoid N+1): pull every
    # prediction for the page's matches ordered so the first row seen per
    # match_id is the latest one (created_at desc, id desc — same tiebreak as
    # serializers.latest_prediction).
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    latest_pred_by_match: dict[int, SportPrediction] = {}
    for p in preds:
        latest_pred_by_match.setdefault(p.match_id, p)

    rounds: dict[int, list[dict]] = {}
    for m, home_name, away_name in rows:
        pred = latest_pred_by_match.get(m.id)
        pred_out = None
        if pred is not None:
            pred_out = {
                "p_home": pred.p_home,
                "p_draw": pred.p_draw,
                "p_away": pred.p_away,
                "expected_margin": pred.expected_margin,
                "model_version": pred.model_version,
                "created_at": pred.created_at.isoformat() if pred.created_at else None,
            }
        rounds.setdefault(m.round, []).append({
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "home": home_name,
            "away": away_name,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "status": m.status,
            "prediction": pred_out,
        })

    return {
        "season": season,
        "rounds": [
            {"round": r, "matches": matches}
            for r, matches in sorted(rounds.items(), key=lambda kv: (kv[0] is None, kv[0]))
        ],
    }


@router.get("/model/record")
def nrl_model_record(db: Session = Depends(get_db)):
    from ml.sports.nrl.params import load_nrl_params

    model_version = load_nrl_params().version

    rows = (
        db.query(SportPredictionResult, SportMatch)
        .join(SportMatch, SportPredictionResult.match_id == SportMatch.id)
        .filter(SportMatch.sport == "nrl")
        .order_by(SportPredictionResult.evaluated_at.asc())
        .all()
    )

    n = len(rows)
    if n == 0:
        return {
            "evaluated_matches": 0,
            "winner_accuracy": None,
            "winner_accuracy_ci95": None,
            "avg_log_loss": None,
            "avg_brier": None,
            "best_streak": 0,
            "model_version": model_version,
            "last_updated": None,
            "disclaimer": "For analytics and entertainment only. Not betting advice.",
        }

    winners = sum(1 for r, _ in rows if r.winner_correct)

    # Longest run of correct winner calls in kickoff order (not evaluation
    # order), same rationale as football's model_record.best_streak.
    by_kickoff = sorted(rows, key=lambda t: (t[1].kickoff_utc is None, t[1].kickoff_utc, t[1].id))
    best_streak = streak = 0
    for r, _ in by_kickoff:
        streak = streak + 1 if r.winner_correct else 0
        best_streak = max(best_streak, streak)

    last_updated = max(r.evaluated_at for r, _ in rows)

    return {
        "evaluated_matches": n,
        "winner_accuracy": round(winners / n, 4),
        "winner_accuracy_ci95": wilson_ci95(winners, n),
        "avg_log_loss": round(sum(r.log_loss for r, _ in rows) / n, 4),
        "avg_brier": round(sum(r.brier for r, _ in rows) / n, 4),
        "best_streak": best_streak,
        "model_version": model_version,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
