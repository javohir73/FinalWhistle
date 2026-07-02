"""Prediction-coverage sweep (FR-1.1): generate the missing frozen predictions.

Knockout teams are assigned by live-refresh passes whenever the provider
publishes a pairing — which can be hours after the feeders finished and any
time relative to the 06:00 UTC daily pipeline. A match that kicks off before
the next full generation pass would have NO frozen prediction and be silently
skipped at evaluation. This sweep closes that gap: it is called from the live
path right after team assignment, generates the cheap analytic payload only
(no Monte-Carlo — standings/odds stay owned by the full pipeline runs), and is
idempotent.

``changed_match_ids`` lets the caller force regeneration for matches whose
pairing CHANGED this pass (a feed correction re-pairing an already-predicted
tie): the fresh row supersedes the stale one because evaluation freezes the
latest prediction created before kickoff.

The sweep intentionally skips the W/D/L booster blend even if one ships
(params.wdl_blend): the scoreline is Poisson-only by design, and training a
booster inside the live path would violate its latency budget. The next full
pipeline run re-predicts with the complete stack.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Match
from app.prediction_coverage import matches_missing_prediction

log = logging.getLogger(__name__)


def ensure_prediction_coverage(
    db: Session, changed_match_ids: set[int] | frozenset[int] = frozenset()
) -> dict:
    """Generate predictions for covered-but-missing matches; returns
    ``{"generated": n, "match_ids": [...]}``."""
    targets: dict[int, Match] = {m.id: m for m in matches_missing_prediction(db)}
    for mid in changed_match_ids:
        m = db.get(Match, mid)
        if (
            m is not None
            and m.status == "scheduled"
            and m.team_home_id is not None
            and m.team_away_id is not None
        ):
            targets[m.id] = m
    if not targets:
        return {"generated": 0, "match_ids": []}

    # Deferred: keep ml/pipeline imports off the module import path so the web
    # process only pays for them when there is actual work to do.
    from ml.models.params import load_params
    from pipeline.generate_predictions import _write_prediction, build_payload
    from pipeline.learning_loop import effective_elos

    params = load_params()
    strengths = effective_elos(db)
    done: list[int] = []
    for m in targets.values():
        payload = build_payload(
            db, m, params.version, strengths=strengths, params=params
        )
        if payload is None:  # defensive: teams vanished mid-pass
            continue
        _write_prediction(db, payload, params.version)
        done.append(m.id)
    db.commit()
    log.info("prediction coverage sweep generated %d prediction(s): %s", len(done), sorted(done))
    return {"generated": len(done), "match_ids": sorted(done)}
