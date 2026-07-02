"""Public model-evaluation endpoint: the AI's audited tournament record.

Aggregates the per-match PredictionResult rows written by the learning loop
into the running record (winner accuracy, exact scores, Brier/log loss,
calibration, best calls, biggest misses). This is the source of truth for the
in-app "AI record" strip AND for marketing claims — anything stated publicly
must be reproducible from this endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import settings
from app.db import get_db
from app.models import Match, Prediction, PredictionResult, TeamTournamentState

router = APIRouter(prefix="/api/model", tags=["model"])

_OUTCOME_IDX = {"home": 0, "draw": 1, "away": 2}


def _match_label(m: Match) -> str:
    home = m.home_team.name if m.home_team else "?"
    away = m.away_team.name if m.away_team else "?"
    return f"{home} {m.score_home}–{m.score_away} {away}"


def _entry(r: PredictionResult, p: Prediction, m: Match) -> dict:
    return {
        "match_id": r.match_id,
        "label": _match_label(m),
        "predicted_score": f"{p.predicted_score_home}-{p.predicted_score_away}",
        "prob_assigned": round(r.prob_assigned, 4),
        "winner_correct": r.winner_correct,
        "exact_score_correct": r.exact_score_correct,
        "brier": round(r.brier, 4),
        "log_loss": round(r.log_loss, 4),
    }


@router.get("/record")
def model_record(db: Session = Depends(get_db)):
    cached = cache.get("model:record")
    if cached is not None:
        return cached

    rows = (
        db.query(PredictionResult, Prediction, Match)
        .join(Prediction, PredictionResult.prediction_id == Prediction.id)
        .join(Match, PredictionResult.match_id == Match.id)
        # The audited public record is the PRODUCTION model's alone — shadow
        # evaluations live behind /api/internal/shadow-record (FR-4.5/4.6).
        .filter(PredictionResult.is_shadow.is_(False))
        .order_by(PredictionResult.evaluated_at.asc())
        .all()
    )

    n = len(rows)
    if n == 0:
        out = {
            "evaluated_matches": 0,
            "winner_accuracy": None,
            "winners_correct": 0,
            "exact_score_hits": 0,
            "avg_brier": None,
            "avg_log_loss": None,
            "calibration": [],
            "best_calls": [],
            "biggest_misses": [],
            "last_updated": None,
            "model_version": settings.model_version,
            "disclaimer": "For analytics and entertainment only. Not betting advice.",
        }
        cache.set("model:record", out)
        return out

    winners = sum(1 for r, _, _ in rows if r.winner_correct)
    exacts = sum(1 for r, _, _ in rows if r.exact_score_correct)

    # Calibration: reuse the same reliability-curve math as the methodology
    # backtests, fed with the live tournament outcomes.
    from ml.evaluation.calibration import reliability_curve

    probs_list = [(p.prob_home_win, p.prob_draw, p.prob_away_win) for _, p, _ in rows]
    labels = [_OUTCOME_IDX[r.outcome] for r, _, _ in rows]
    calibration = reliability_curve(probs_list, labels, bins=5)

    best = sorted(rows, key=lambda t: t[0].brier)[:3]
    misses = sorted(
        (t for t in rows if not t[0].winner_correct),
        key=lambda t: t[0].log_loss,
        reverse=True,
    )[:3]

    last_eval = max(r.evaluated_at for r, _, _ in rows)
    state_updated = (
        db.query(TeamTournamentState.updated_at)
        .order_by(TeamTournamentState.updated_at.desc())
        .first()
    )
    last_updated = last_eval
    if state_updated and state_updated[0] and state_updated[0] > last_updated:
        last_updated = state_updated[0]

    out = {
        "evaluated_matches": n,
        "winner_accuracy": round(winners / n, 4),
        "winners_correct": winners,
        "exact_score_hits": exacts,
        "avg_brier": round(sum(r.brier for r, _, _ in rows) / n, 4),
        "avg_log_loss": round(sum(r.log_loss for r, _, _ in rows) / n, 4),
        "calibration": calibration,
        "best_calls": [_entry(r, p, m) for r, p, m in best],
        "biggest_misses": [_entry(r, p, m) for r, p, m in misses],
        "last_updated": last_updated.isoformat() if last_updated else None,
        "model_version": settings.model_version,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
    cache.set("model:record", out)
    return out
