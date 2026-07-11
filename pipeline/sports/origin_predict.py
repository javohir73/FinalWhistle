"""Origin frozen shadow prediction generation + grading (design 2026-07-11).

Mirror of pipeline.sports.nrl_predict scoped to sport="origin", with two
Origin-specific twists: params come from ml.sports.origin.params and each
fixture carries a neutral-venue flag through both replay (update) and
prediction (predict). That flag is ml.sports.origin.venues.model_is_neutral,
NOT is_neutral -- task 4's backtest REFUTED the hypothesis that the model
should zero home_adv at neutral-labeled venues (log loss 0.7456 with zeroing
vs 0.7216 without; see ml/sports/origin/venues.py), so MODEL_NEUTRAL_VENUES is
empty and model_is_neutral is currently always False, meaning home_adv
applies everywhere on the model path. is_neutral remains display-only (the
API badges neutral venues regardless of what the model does with them).
Grading reuses nrl_predict.grade(sport="origin") verbatim -- same pre-kickoff
backstop, same append-only ledger. The frozen-prediction hard guard lives in
the shared _write_prediction. No probability snapshots (movers doesn't cover
origin, by design).

CLI: python -m pipeline.sports.origin_predict --generate --grade
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy.orm import Session

from app.models import SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams, predict, regress_season, update
from ml.sports.origin.params import load_origin_params
from ml.sports.origin.venues import model_is_neutral
from pipeline.sports import nrl_predict
from pipeline.sports.nrl_predict import _kickoff_key, _write_prediction

log = logging.getLogger(__name__)

SPORT = "origin"
_DEDUP_TOL = 1e-9


def _current_elos(db: Session, params: NrlParams) -> dict[int, float]:
    """Replay every finished origin match in kickoff order (season-boundary
    regression + neutral flags) to the CURRENT per-team Elo state."""
    finished = db.query(SportMatch).filter_by(sport=SPORT, status="finished").all()
    finished.sort(key=_kickoff_key)

    elos: dict[int, float] = {}
    current_season: int | None = None
    for m in finished:
        if current_season is not None and m.season != current_season:
            elos = regress_season(elos, params)
        current_season = m.season
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        new_home, new_away = update(
            elo_home, elo_away, m.score_home, m.score_away, params,
            neutral=model_is_neutral(m.venue),
        )
        elos[m.home_team_id] = new_home
        elos[m.away_team_id] = new_away
    return elos


def _sync_team_elos(db: Session, elos: dict[int, float]) -> int:
    """Display-cache sync, same contract as nrl_predict._sync_team_elos."""
    ids = [team_id for team_id in elos if team_id is not None]
    if not ids:
        return 0
    changed = 0
    for team in db.query(SportTeam).filter(
        SportTeam.sport == SPORT, SportTeam.id.in_(ids)
    ):
        new = elos[team.id]
        if team.elo_rating is None or abs(team.elo_rating - new) > _DEDUP_TOL:
            team.elo_rating = new
            changed += 1
    return changed


def generate(db: Session, params: NrlParams | None = None) -> int:
    """Predict every scheduled origin match from current Elo state. Returns
    the number of SportPrediction rows written this run."""
    params = params or load_origin_params()
    elos = _current_elos(db, params)
    synced = _sync_team_elos(db, elos)
    if synced:
        log.info("elo sync: %d team rating(s) updated", synced)

    written = 0
    for m in db.query(SportMatch).filter_by(sport=SPORT, status="scheduled").all():
        elo_home = elos.get(m.home_team_id, 1500.0)
        elo_away = elos.get(m.away_team_id, 1500.0)
        out = predict(elo_home, elo_away, params, neutral=model_is_neutral(m.venue))
        if _write_prediction(db, m, params, out):
            written += 1

    db.commit()
    return written


def grade(db: Session) -> int:
    """Grade finished origin matches against their latest pre-kickoff
    prediction -- nrl_predict.grade scoped to this sport."""
    return nrl_predict.grade(db, sport=SPORT)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--grade", action="store_true")
    args = ap.parse_args()
    if not args.generate and not args.grade:
        ap.error("pass --generate, --grade, or both")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.generate:
            log.info("generate: %d prediction row(s) written", generate(db))
        if args.grade:
            log.info("grade: %d result row(s) written", grade(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
