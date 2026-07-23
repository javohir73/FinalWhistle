"""GET /api/nrl/tips -- the round tipsheet (design doc: NRL Round Tips,
Recommended Approach / Slice 1). A separate router from app.api.sports (same
/api/nrl prefix, different path -- mirrors how the vertical already splits
concerns across sports.py / nrl_intel.py / nrl_live.py).

Aggregates three already-existing surfaces into one payload for the public
tipsheet page: the round's fixtures with the model's pick per game, the
graded season record (/api/nrl/model/record's own computation, reused via
`_ledger_record` rather than duplicated), and the most recent graded round's
worst miss.

The one new seam this endpoint closes (design doc): /api/nrl/matches attaches
the LATEST prediction row unconditionally, which in the narrow post-kickoff
window before nrl-refresh flips a match's status to "finished" could surface
a post-kickoff write as "the prediction". Here the prediction picked per
match is the latest one with created_at <= kickoff_utc -- the same row
pipeline.sports.nrl_predict.grade() will eventually score -- so what the
tipsheet shows always matches what the ledger grades.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, aliased

from app.api.sports import _latest_season, _ledger_record
from app.db import get_db
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam

router = APIRouter(prefix="/api/nrl", tags=["nrl"])

_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


def _model_pick(pred: SportPrediction) -> tuple[str, float]:
    """The model's side pick and its confidence: highest of p_home/p_draw/
    p_away, ties broken toward home over draw over away -- the same tiebreak
    pipeline.sports.nrl_predict.grade() uses for winner_correct, so the pick
    shown here always matches what the ledger scored."""
    probs = (pred.p_home, pred.p_draw, pred.p_away)
    idx = max(range(3), key=lambda i: (probs[i], -i))
    return ("home", "draw", "away")[idx], probs[idx]


def _current_round(db: Session, season: int) -> int | None:
    """Round containing the earliest still-scheduled match; if the whole
    season is finished, the latest round that has any matches at all."""
    upcoming = (
        db.query(SportMatch.round)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season,
                SportMatch.status != "finished")
        .order_by(SportMatch.kickoff_utc.is_(None), SportMatch.kickoff_utc.asc(),
                  SportMatch.match_no.asc())
        .first()
    )
    if upcoming is not None:
        return upcoming[0]
    rounds = [
        r for (r,) in db.query(SportMatch.round)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season).all()
        if r is not None
    ]
    return max(rounds) if rounds else None


def _kickoff_locked_prediction(
    preds_by_match: dict[int, list[SportPrediction]], m: SportMatch,
) -> SportPrediction | None:
    """The prediction shown for `m`: the latest row with created_at <=
    kickoff_utc when a kickoff is set -- mirrors nrl_predict.grade()'s
    eligible-row filter exactly (candidates already carry the created_at
    desc, id desc order the caller queried them in), so the tipsheet never
    shows a pick the graded ledger wouldn't have scored."""
    candidates = preds_by_match.get(m.id, [])
    if m.kickoff_utc is not None:
        candidates = [p for p in candidates if p.created_at <= m.kickoff_utc]
    return candidates[0] if candidates else None


def _worst_miss(db: Session, sport: str) -> dict | None:
    """The tipsheet's honest 'worst miss' line: within the most recently
    played round with graded results, the highest-confidence pick the model
    got wrong. None if nothing is graded yet, or the latest graded round was
    a clean sweep."""
    home = aliased(SportTeam)
    away = aliased(SportTeam)
    rows = (
        db.query(SportPredictionResult, SportPrediction, SportMatch, home.name, away.name)
        .join(SportPrediction, SportPredictionResult.prediction_id == SportPrediction.id)
        .join(SportMatch, SportPredictionResult.match_id == SportMatch.id)
        .outerjoin(home, SportMatch.home_team_id == home.id)
        .outerjoin(away, SportMatch.away_team_id == away.id)
        .filter(SportMatch.sport == sport)
        .all()
    )
    if not rows:
        return None

    # "Most recent round" is keyed on the (season, round) of the latest-
    # kickoff graded match -- not the highest round NUMBER, which resets
    # every season -- same kickoff-order convention _ledger_record uses for
    # best_streak.
    by_kickoff = sorted(rows, key=lambda t: (t[2].kickoff_utc is None, t[2].kickoff_utc, t[2].id))
    latest_match = by_kickoff[-1][2]
    season, rnd = latest_match.season, latest_match.round

    misses = [
        row for row in rows
        if row[2].season == season and row[2].round == rnd and not row[0].winner_correct
    ]
    if not misses:
        return None

    result, pred, m, home_name, away_name = max(
        misses, key=lambda row: _model_pick(row[1])[1],
    )
    pick_side, pick_prob = _model_pick(pred)
    pick_team = {"home": home_name, "away": away_name, "draw": None}[pick_side]
    winner_team = {"home": home_name, "away": away_name, "draw": None}[result.outcome]

    return {
        "season": season, "round": rnd,
        "home": home_name, "away": away_name,
        "score_home": m.score_home, "score_away": m.score_away,
        "pick": pick_side, "pick_team": pick_team, "pick_probability": pick_prob,
        "winner": result.outcome, "winner_team": winner_team,
    }


@router.get("/tips")
def nrl_tips(season: int | None = None, round: int | None = None,
             db: Session = Depends(get_db)):
    """The round tipsheet: this round's fixtures with the model's kickoff-
    locked pick per game, the season-long graded record, and last round's
    worst miss."""
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })
    elif (
        db.query(SportMatch.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season)
        .first()
    ) is None:
        raise HTTPException(status_code=404, detail={
            "code": "season_not_found",
            "message": f"No NRL matches for season {season}",
        })

    if round is None:
        round = _current_round(db, season)
        if round is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    home = aliased(SportTeam)
    away = aliased(SportTeam)
    rows = (
        db.query(SportMatch, home.name, away.name)
        .outerjoin(home, SportMatch.home_team_id == home.id)
        .outerjoin(away, SportMatch.away_team_id == away.id)
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

    match_ids = [m.id for m, _, _ in rows]
    # Latest-first per match_id, same single-query dedup pattern as /matches;
    # unlike /matches, each match's row is then narrowed to created_at <=
    # kickoff_utc before picking the first (see _kickoff_locked_prediction).
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    preds_by_match: dict[int, list[SportPrediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    matches_out = []
    for m, home_name, away_name in rows:
        pred = _kickoff_locked_prediction(preds_by_match, m)
        pred_out = None
        if pred is not None:
            pick_side, pick_prob = _model_pick(pred)
            pred_out = {
                "p_home": pred.p_home,
                "p_draw": pred.p_draw,
                "p_away": pred.p_away,
                "expected_margin": pred.expected_margin,
                "model_version": pred.model_version,
                "created_at": pred.created_at.isoformat() if pred.created_at else None,
                "is_shadow": pred.is_shadow,
                "pick": pick_side,
                "pick_confidence": pick_prob,
            }
        matches_out.append({
            "id": m.id,
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "home": home_name,
            "away": away_name,
            "home_team_id": m.home_team_id,
            "away_team_id": m.away_team_id,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "status": m.status,
            "prediction": pred_out,
        })

    return {
        "season": season,
        "round": round,
        "matches": matches_out,
        "record": _ledger_record(db, "nrl"),
        "worst_miss": _worst_miss(db, "nrl"),
        "disclaimer": _DISCLAIMER,
    }
