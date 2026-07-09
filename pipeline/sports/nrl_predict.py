"""NRL frozen shadow prediction generation + grading (task 5).

Two idempotent, append-only sweeps over sport="nrl" rows:

  generate(db, params) -- for every scheduled match, replay ALL finished nrl
    matches in kickoff order (regress_season applied at each season boundary,
    same convention as ml.sports.nrl.backtest.replay_seasons) to get the
    CURRENT Elo state, then predict() the fixture and append a SportPrediction
    (is_shadow=True -- this vertical ships shadow-only until proven, mirroring
    the football SHADOW_MODEL_VERSION twins). A new row is written only if
    none exists yet for the match or the newest existing row's triple differs
    by more than 1e-9 in any of p_home/p_draw/p_away -- so re-running after a
    no-op day adds nothing. HARD GUARD: matches whose status != "scheduled"
    are never written to, enforced inside _write_prediction so no call path
    can bypass it (frozen-prediction invariant, mirrors pipeline.learning_loop).

  grade(db) -- for every finished match with >=1 prediction and no
    SportPredictionResult yet, scores the LATEST prediction row against the
    final score and appends one result row. When kickoff_utc is set, only
    predictions with created_at <= kickoff_utc are eligible (same backstop as
    football's pipeline.learning_loop._prediction_row) -- a match whose only
    rows were written after kickoff grades nothing, like no-prediction at all.
    Never re-grades (idempotent).

CLI: python -m pipeline.sports.nrl_predict --generate --grade
"""
from __future__ import annotations

import argparse
import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import SportMatch, SportPrediction, SportPredictionResult
from ml.sports.nrl.model import NrlParams, predict, regress_season, update
from ml.sports.nrl.params import load_nrl_params

log = logging.getLogger(__name__)

SPORT = "nrl"
_EPS = 1e-15
_DEDUP_TOL = 1e-9


def _kickoff_key(m: SportMatch) -> tuple:
    """Sort key that puts undated rows last, deterministic on ties."""
    return (m.kickoff_utc is None, m.kickoff_utc or datetime.min, m.id)


def _current_elos(db: Session) -> dict[int, float]:
    """Replay every finished nrl match in kickoff order to derive the CURRENT
    per-team Elo state, applying regress_season at each season boundary.

    A single chronological walk (rather than ml.sports.nrl.backtest.replay_seasons'
    season-keyed snapshots) since generate() only ever needs the latest state,
    not a per-season history. Season boundaries are detected by season number
    changing between consecutive matches in kickoff order -- correct as long
    as a season's matches don't interleave with another season's in time,
    which fixturedownload's data never does.
    """
    finished = (
        db.query(SportMatch)
        .filter_by(sport=SPORT, status="finished")
        .all()
    )
    finished.sort(key=_kickoff_key)

    params = load_nrl_params()
    elos: dict[int, float] = {}
    current_season: int | None = None

    for m in finished:
        if current_season is not None and m.season != current_season:
            elos = regress_season(elos, params)
        current_season = m.season

        home_id, away_id = m.home_team_id, m.away_team_id
        elo_home = elos.get(home_id, 1500.0)
        elo_away = elos.get(away_id, 1500.0)
        new_home, new_away = update(elo_home, elo_away, m.score_home, m.score_away, params)
        elos[home_id] = new_home
        elos[away_id] = new_away

    return elos


def _triples_differ(a: SportPrediction, triple: tuple[float, float, float]) -> bool:
    return (
        abs(a.p_home - triple[0]) > _DEDUP_TOL
        or abs(a.p_draw - triple[1]) > _DEDUP_TOL
        or abs(a.p_away - triple[2]) > _DEDUP_TOL
    )


def _write_prediction(db: Session, match: SportMatch, params: NrlParams, out: dict) -> bool:
    """Append a SportPrediction for `match` if warranted. Returns True if written.

    HARD GUARD: refuses to write unless match.status == "scheduled" -- the
    frozen-prediction rule lives here, not in the caller's loop, so no future
    call path (a different sweep, a one-off script) can bypass it.
    """
    if match.status != "scheduled":
        return False

    latest = (
        db.query(SportPrediction)
        .filter_by(match_id=match.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    triple = (out["p_home"], out["p_draw"], out["p_away"])
    if latest is not None and not _triples_differ(latest, triple):
        return False

    db.add(SportPrediction(
        match_id=match.id,
        model_version=params.version,
        p_home=out["p_home"],
        p_draw=out["p_draw"],
        p_away=out["p_away"],
        expected_margin=out["expected_margin"],
        is_shadow=True,
    ))
    return True


def generate(db: Session, params: NrlParams | None = None) -> int:
    """Predict every scheduled nrl match from current Elo state. Returns the
    number of SportPrediction rows written this run (0 on a no-op re-run)."""
    params = params or load_nrl_params()
    elos = _current_elos(db)

    scheduled = (
        db.query(SportMatch)
        .filter_by(sport=SPORT, status="scheduled")
        .all()
    )

    written = 0
    for m in scheduled:
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        out = predict(elo_home, elo_away, params)
        if _write_prediction(db, m, params, out):
            written += 1

    db.commit()
    return written


def _outcome(score_home: int, score_away: int) -> str:
    if score_home > score_away:
        return "home"
    if score_home < score_away:
        return "away"
    return "draw"


def _clamp(p: float) -> float:
    return max(_EPS, min(1 - _EPS, p))


def grade(db: Session) -> int:
    """Grade every finished nrl match that has a pre-kickoff prediction and
    hasn't been graded yet, using the latest such prediction row. Append-only:
    never re-grades. Returns the number of SportPredictionResult rows written
    this run."""
    finished = (
        db.query(SportMatch)
        .filter_by(sport=SPORT, status="finished")
        .all()
    )

    graded = 0
    for m in finished:
        already = db.query(SportPredictionResult).filter_by(match_id=m.id).first()
        if already is not None:
            continue

        q = db.query(SportPrediction).filter_by(match_id=m.id)
        if m.kickoff_utc is not None:
            q = q.filter(SportPrediction.created_at <= m.kickoff_utc)
        latest = q.order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc()).first()
        if latest is None:
            continue

        probs = (latest.p_home, latest.p_draw, latest.p_away)
        outcome = _outcome(m.score_home, m.score_away)
        idx = {"home": 0, "draw": 1, "away": 2}[outcome]
        predicted_idx = max(range(3), key=lambda i: (probs[i], -i))
        prob_assigned = probs[idx]

        log_loss = -math.log(_clamp(prob_assigned))
        brier = sum((p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs))
        actual_margin = m.score_home - m.score_away
        margin_error = (
            abs(latest.expected_margin - actual_margin)
            if latest.expected_margin is not None
            else None
        )

        db.add(SportPredictionResult(
            match_id=m.id,
            prediction_id=latest.id,
            model_version=latest.model_version,
            outcome=outcome,
            winner_correct=predicted_idx == idx,
            prob_assigned=prob_assigned,
            log_loss=log_loss,
            brier=brier,
            margin_error=margin_error,
        ))
        graded += 1

    db.commit()
    return graded


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate", action="store_true", help="write predictions for scheduled matches")
    ap.add_argument("--grade", action="store_true", help="grade finished matches with predictions")
    args = ap.parse_args()

    if not args.generate and not args.grade:
        ap.error("pass --generate, --grade, or both")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.generate:
            n = generate(db)
            log.info("generate: %d prediction row(s) written", n)

            from pipeline.prob_snapshots import snapshot_nrl
            n_snap = snapshot_nrl(db)
            print(f"snapshots: {n_snap} probability row(s) written")
        if args.grade:
            n = grade(db)
            log.info("grade: %d result row(s) written", n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
