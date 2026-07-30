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
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models import Match, Prediction
from app.prediction_coverage import matches_missing_prediction

if TYPE_CHECKING:
    from pipeline.vnext_shadow import VNextShadowSpec

log = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _latest_champion_before_kickoff(
    db: Session,
    match: Match,
    champion_version: str,
) -> Prediction | None:
    if match.kickoff_utc is None:
        return None
    kickoff = _utc(match.kickoff_utc)
    rows = (
        db.query(Prediction)
        .filter(
            Prediction.match_id == match.id,
            Prediction.model_version == champion_version,
            Prediction.is_shadow.is_(False),
            Prediction.created_at.isnot(None),
        )
        .all()
    )
    eligible = [row for row in rows if _utc(row.created_at) < kickoff]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (_utc(row.created_at), row.id))


def _has_current_vnext_receipt(
    db: Session,
    match: Match,
    spec: "VNextShadowSpec",
) -> bool:
    """Whether the exact tag is linked to this fixture's current champion row."""
    champion = _latest_champion_before_kickoff(
        db, match, spec.production_model_version
    )
    if champion is None or match.kickoff_utc is None:
        return False
    from pipeline.vnext_shadow import (
        champion_row_fingerprint,
        extract_vnext_receipt,
        validate_vnext_receipt,
    )

    fingerprint = champion_row_fingerprint(champion)
    kickoff = _utc(match.kickoff_utc)
    shadows = (
        db.query(Prediction)
        .filter(
            Prediction.match_id == match.id,
            Prediction.model_version == spec.model_tag,
            Prediction.is_shadow.is_(True),
            Prediction.created_at.isnot(None),
        )
        .all()
    )
    for shadow in shadows:
        if _utc(shadow.created_at) >= kickoff:
            continue
        try:
            receipt = extract_vnext_receipt(shadow.reasons)
            if receipt is None:
                continue
            validate_vnext_receipt(
                receipt,
                challenger_tag=spec.model_tag,
                champion_model_version=spec.production_model_version,
                kickoff_utc=kickoff,
                artifact_identity=spec.artifact_identity,
                champion_payload_sha256=fingerprint,
                predictor_kind=spec.predictor_kind,
                payload_mode=spec.predictor_payload_mode,
                champion_created_at=champion.created_at,
                challenger_created_at=shadow.created_at,
            )
            return True
        except (TypeError, ValueError):
            continue
    return False


def _payload_from_prediction(row: Prediction) -> dict:
    """Rehydrate the fields needed by an exact parity shadow backfill."""
    created_at = row.created_at
    if created_at is not None and (
        created_at.tzinfo is None or created_at.utcoffset() is None
    ):
        from datetime import timezone

        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "match_id": row.match_id,
        "model_version": row.model_version,
        "generated_at": created_at.isoformat() if created_at else None,
        "probabilities": {
            "home_win": row.prob_home_win,
            "draw": row.prob_draw,
            "away_win": row.prob_away_win,
        },
        "predicted_score": {
            "home": row.predicted_score_home,
            "away": row.predicted_score_away,
            "probability": row.predicted_score_prob,
        },
        "lambda_home": row.lambda_home,
        "lambda_away": row.lambda_away,
        "rho": row.rho,
        "knockout": row.knockout,
        "confidence": row.confidence,
        "reasons": row.reasons,
        "top_features": row.top_features,
        "writeup": row.writeup,
    }


def ensure_prediction_coverage(
    db: Session,
    changed_match_ids: set[int] | frozenset[int] = frozenset(),
    vnext_shadow_spec: "VNextShadowSpec | None" = None,
) -> dict:
    """Generate predictions for covered-but-missing matches; returns
    ``{"generated": n, "match_ids": [...]}``."""
    production_targets: dict[int, Match] = {
        m.id: m for m in matches_missing_prediction(db)
    }
    for mid in changed_match_ids:
        m = db.get(Match, mid)
        if (
            m is not None
            and m.status == "scheduled"
            and m.team_home_id is not None
            and m.team_away_id is not None
        ):
            production_targets[m.id] = m
    vnext_target_ids: set[int] = set()
    if vnext_shadow_spec is not None:
        candidates = db.query(Match).filter(
            Match.status == "scheduled",
            Match.team_home_id.isnot(None),
            Match.team_away_id.isnot(None),
        ).all()
        candidate_ids = {match.id for match in candidates}
        vnext_target_ids = {
            match.id
            for match in candidates
            if not _has_current_vnext_receipt(db, match, vnext_shadow_spec)
        } | (set(changed_match_ids) & candidate_ids)
    targets: dict[int, Match] = dict(production_targets)
    for match_id in vnext_target_ids:
        match = db.get(Match, match_id)
        if match is not None:
            targets[match_id] = match
    if not targets:
        return {"generated": 0, "match_ids": []}

    # Deferred: keep ml/pipeline imports off the module import path so the web
    # process only pays for them when there is actual work to do.
    from ml.models.params import load_params
    from pipeline.generate_predictions import (
        _write_prediction,
        build_payload,
        write_shadow_prediction,
        write_vnext_shadow_prediction,
    )
    from pipeline.learning_loop import effective_elos

    params = load_params()
    strengths = effective_elos(db)
    done: list[int] = []
    for m in targets.values():
        payload = None
        if m.id not in production_targets and vnext_shadow_spec is not None:
            frozen_production = _latest_champion_before_kickoff(
                db,
                m,
                vnext_shadow_spec.production_model_version,
            )
            if frozen_production is not None:
                payload = _payload_from_prediction(frozen_production)
        if payload is None:
            payload = build_payload(
                db, m, params.version, strengths=strengths, params=params
            )
        if payload is None:  # defensive: teams vanished mid-pass
            continue
        if m.id in production_targets:
            _write_prediction(db, m, payload, params.version)
            # Keep the shadow record complete (FR-4.4): a sweep-generated match
            # gets its twin too, so the production-vs-shadow comparison never has
            # coverage holes. Cheap — one more analytic grid at most.
            write_shadow_prediction(db, m, payload, strengths, params)
        vnext_ok = True
        if vnext_shadow_spec is not None and m.id in vnext_target_ids:
            vnext_ok = write_vnext_shadow_prediction(
                db, m, payload, vnext_shadow_spec
            )
        if vnext_ok:
            done.append(m.id)
    db.commit()
    log.info("prediction coverage sweep generated %d prediction(s): %s", len(done), sorted(done))
    return {"generated": len(done), "match_ids": sorted(done)}
