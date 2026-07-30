"""Tests for the explicit, shadow-only vNext integration boundary."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import Match, Prediction, Team
from ml.models.poisson import predict_from_lambdas
from pipeline.generate_predictions import generate_predictions, write_vnext_shadow_prediction
from pipeline.ingest.wc26_structure import load_structure
from pipeline.prediction_coverage import ensure_prediction_coverage
from pipeline.vnext_shadow import (
    ParityCanaryPredictor,
    VNextShadowSpec,
    build_vnext_shadow_payload,
    champion_payload_fingerprint,
    champion_row_fingerprint,
    extract_vnext_receipt,
    validate_vnext_receipt,
)


MODEL_VERSION = "poisson-elo-v0.1"


def _set_elos(db) -> None:
    for index, team in enumerate(db.query(Team).order_by(Team.id).all()):
        team.elo_rating = 1500.0 + (index % 12) * 40
    db.commit()


def _move_scheduled_kickoffs_to_future(db) -> None:
    kickoff = datetime.now(timezone.utc) + timedelta(days=30)
    for index, match in enumerate(db.query(Match).filter_by(status="scheduled").all()):
        match.kickoff_utc = kickoff + timedelta(hours=index)
    db.commit()


def _pure_match(kickoff: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        team_home_id=10,
        team_away_id=20,
        kickoff_utc=kickoff,
        tournament_id=1,
        is_neutral=True,
    )


def _production_payload() -> dict:
    prediction = predict_from_lambdas(1.6, 0.9, rho=-0.06)
    return {
        "match_id": 7,
        "model_version": MODEL_VERSION,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "probabilities": {
            "home_win": round(prediction.prob_home_win, 4),
            "draw": round(prediction.prob_draw, 4),
            "away_win": round(prediction.prob_away_win, 4),
        },
        "predicted_score": {
            "home": prediction.score_home,
            "away": prediction.score_away,
            "probability": round(prediction.score_prob, 4),
        },
        "lambda_home": 1.6,
        "lambda_away": 0.9,
        "rho": -0.06,
        "confidence": "Medium",
        "reasons": [],
        "top_features": [],
        "writeup": {"call": "production only"},
    }


def test_spec_identity_is_canonical_deterministic_and_persistable():
    first = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        artifact_config_json='{"weight":0.2,"enabled":true}',
    )
    reordered = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        artifact_config_json=' { "enabled": true, "weight": 0.2 } ',
    )
    changed = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        artifact_config_json='{"weight":0.3,"enabled":true}',
    )

    assert first.artifact_identity == reordered.artifact_identity
    assert first.model_tag == reordered.model_tag
    assert first.artifact_identity != changed.artifact_identity
    assert first.model_tag != changed.model_tag
    assert len(first.model_tag) <= 40
    assert first.model_tag == f"fw-vnext-{first.artifact_identity[:31]}"
    with pytest.raises(FrozenInstanceError):
        first.model_tag = "changed"


def test_spec_tag_binds_production_version_and_predictor_behavior():
    @dataclass(frozen=True)
    class WeightedPredictor:
        weight: float
        artifact_kind: str = "weighted-test-v1"
        payload_mode: str = "raw_distribution"

        @property
        def artifact_descriptor_json(self) -> str:
            return json.dumps(
                {"weight": self.weight}, sort_keys=True, separators=(",", ":")
            )

        def predict(self, *args, **kwargs):
            raise AssertionError("identity construction must not run prediction")

    low = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        predictor=WeightedPredictor(0.2),
    )
    high = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        predictor=WeightedPredictor(0.8),
    )
    other_champion = VNextShadowSpec(
        production_model_version="poisson-elo-club-v0.1",
        predictor=WeightedPredictor(0.2),
    )
    assert low.model_tag != high.model_tag
    assert low.model_tag != other_champion.model_tag


def test_parity_payload_preserves_headline_and_drops_lossy_lambda_fields():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _production_payload()
    untouched = _production_payload()
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)
    shadow = build_vnext_shadow_payload(
        _pure_match(now + timedelta(hours=2)),
        source,
        spec,
        features_as_of=now,
    )

    assert shadow is not None
    assert source == untouched
    assert shadow["model_version"] == spec.model_tag
    assert shadow["probabilities"] == source["probabilities"]
    assert shadow["predicted_score"] == source["predicted_score"]
    assert shadow["lambda_home"] is None
    assert shadow["lambda_away"] is None
    assert shadow["rho"] is None
    assert shadow["writeup"] is None
    assert shadow["vnext_artifact_identity"] == spec.artifact_identity
    assert shadow["vnext_calibration_artifact"].endswith(spec.artifact_identity)


def test_shadow_receipt_persists_exact_pairing_identity_cutoff_and_fingerprint():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _production_payload()
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)
    shadow = build_vnext_shadow_payload(
        _pure_match(now + timedelta(hours=2)),
        source,
        spec,
        features_as_of=now,
    )

    receipt = extract_vnext_receipt(shadow["reasons"])
    assert receipt["artifact_identity"] == spec.artifact_identity
    assert receipt["champion_model_version"] == MODEL_VERSION
    assert receipt["champion_payload_sha256"] == champion_payload_fingerprint(source)
    assert receipt["features_as_of"] == now.isoformat()
    assert receipt["schema_version"] == 2
    assert receipt["predictor_kind"] == spec.predictor_kind
    assert receipt["payload_mode"] == spec.predictor_payload_mode
    assert receipt["candidate_max_goals"] == 10
    assert 0.0 <= receipt["candidate_over_2_5"] <= 1.0
    assert len(receipt["candidate_grid_sha256"]) == 64
    assert validate_vnext_receipt(
        receipt,
        challenger_tag=spec.model_tag,
        champion_model_version=MODEL_VERSION,
        kickoff_utc=now + timedelta(hours=2),
        artifact_identity=spec.artifact_identity,
        champion_payload_sha256=champion_payload_fingerprint(source),
        predictor_kind=spec.predictor_kind,
        payload_mode=spec.predictor_payload_mode,
    ) == receipt
    with pytest.raises(ValueError, match="after champion_created_at"):
        validate_vnext_receipt(
            receipt,
            challenger_tag=spec.model_tag,
            champion_model_version=MODEL_VERSION,
            kickoff_utc=now + timedelta(hours=2),
            champion_created_at=now - timedelta(seconds=2),
        )
    probabilities = source["probabilities"]
    score = source["predicted_score"]
    row = SimpleNamespace(
        confidence=source["confidence"],
        knockout=source.get("knockout"),
        lambda_away=source["lambda_away"],
        lambda_home=source["lambda_home"],
        match_id=source["match_id"],
        model_version=source["model_version"],
        predicted_score_away=score["away"],
        predicted_score_home=score["home"],
        predicted_score_prob=score["probability"],
        prob_away_win=probabilities["away_win"],
        prob_draw=probabilities["draw"],
        prob_home_win=probabilities["home_win"],
        reasons=source["reasons"],
        rho=source["rho"],
        top_features=source["top_features"],
        writeup=source["writeup"],
    )
    assert champion_row_fingerprint(row) == receipt["champion_payload_sha256"]


def test_predictor_receives_deep_copy_and_cannot_mutate_production_nested_state():
    @dataclass(frozen=True)
    class MutatingPredictor(ParityCanaryPredictor):
        artifact_kind: str = "malicious-mutation-test-v1"

        def predict(self, context, production_payload, **kwargs):
            production_payload["probabilities"]["home_win"] = 0.01
            production_payload["reasons"].append("poison")
            production_payload["top_features"][0]["weight"] = 999
            return super().predict(context, production_payload, **kwargs)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _production_payload()
    source["reasons"] = ["production reason"]
    source["top_features"] = [{"name": "elo", "weight": 1}]
    reasons_reference = source["reasons"]
    features_reference = source["top_features"]
    untouched = json.loads(json.dumps(source))
    spec = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        predictor=MutatingPredictor(),
    )

    shadow = build_vnext_shadow_payload(
        _pure_match(now + timedelta(hours=2)),
        source,
        spec,
        features_as_of=now,
    )

    assert source == untouched
    assert reasons_reference == ["production reason"]
    assert features_reference == [{"name": "elo", "weight": 1}]
    assert "poison" not in shadow["reasons"]
    assert shadow["top_features"] == [{"name": "elo", "weight": 1}]


def test_non_parity_clears_inherited_knockout_until_candidate_policy_exists():
    from ml.models.pure_tempo import (
        FrozenPureTempoPredictor,
        FrozenTeamTempoArtifact,
    )

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _production_payload()
    source["knockout"] = {"advance_home": 0.7, "advance_away": 0.3}
    parity = build_vnext_shadow_payload(
        _pure_match(now + timedelta(hours=2)),
        source,
        VNextShadowSpec(production_model_version=MODEL_VERSION),
        features_as_of=now,
    )
    artifact = FrozenTeamTempoArtifact.from_mapping(
        {
            "schema_version": 1,
            "artifact_version": "test-v1",
            "trained_through": "2025-12-31T00:00:00+00:00",
            "global_log_tempo": 0.0,
            "unknown_team_log_tempo": 0.0,
            "team_log_tempos": {},
        }
    )
    challenger = build_vnext_shadow_payload(
        _pure_match(now + timedelta(hours=2)),
        source,
        VNextShadowSpec(
            production_model_version=MODEL_VERSION,
            predictor=FrozenPureTempoPredictor(artifact),
        ),
        features_as_of=now,
    )

    assert parity["knockout"] == source["knockout"]
    assert challenger["knockout"] is None


def test_builder_rejects_wrong_distribution_tag_and_calibrated_distribution_mode():
    @dataclass(frozen=True)
    class WrongTagPredictor(ParityCanaryPredictor):
        artifact_kind: str = "wrong-tag-test-v1"

        def predict(self, *args, **kwargs):
            distribution = super().predict(*args, **kwargs)
            state = replace(distribution.state, model_version="wrong-tag")
            return type(distribution)(
                state=state,
                grid=distribution.grid,
                calibration=distribution.calibration,
            )

    @dataclass(frozen=True)
    class CalibratedDistributionPredictor(ParityCanaryPredictor):
        artifact_kind: str = "calibrated-distribution-test-v1"
        payload_mode: str = "raw_distribution"

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    match = _pure_match(now + timedelta(hours=2))
    with pytest.raises(ValueError, match="model_version"):
        build_vnext_shadow_payload(
            match,
            _production_payload(),
            VNextShadowSpec(
                production_model_version=MODEL_VERSION,
                predictor=WrongTagPredictor(),
            ),
            features_as_of=now,
        )
    with pytest.raises(ValueError, match="uncalibrated grid"):
        build_vnext_shadow_payload(
            match,
            _production_payload(),
            VNextShadowSpec(
                production_model_version=MODEL_VERSION,
                predictor=CalibratedDistributionPredictor(),
            ),
            features_as_of=now,
        )


def test_raw_distribution_mode_rejects_a_calibrated_champion():
    class MustNotRunRawPredictor:
        artifact_kind = "raw-calibrated-champion-guard-test-v1"
        payload_mode = "raw_distribution"
        artifact_descriptor_json = "{}"

        def predict(self, *args, **kwargs):
            raise AssertionError("raw predictor must be blocked before execution")

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _production_payload()
    source["probabilities"] = {
        "home_win": 0.60,
        "draw": 0.25,
        "away_win": 0.15,
    }
    with pytest.raises(ValueError, match="calibrated champion"):
        build_vnext_shadow_payload(
            _pure_match(now + timedelta(hours=2)),
            source,
            VNextShadowSpec(
                production_model_version=MODEL_VERSION,
                predictor=MustNotRunRawPredictor(),
            ),
            features_as_of=now,
        )


def test_raw_distribution_grid_must_match_the_state_that_will_be_persisted():
    from ml.models.vnext import LatentMatchState, ScoreDistribution

    class ForgedGridPredictor:
        artifact_kind = "forged-raw-grid-test-v1"
        payload_mode = "raw_distribution"
        artifact_descriptor_json = "{}"

        def predict(
            self,
            context,
            production_payload,
            *,
            model_tag,
            artifact_identity,
        ):
            state = LatentMatchState.from_expected_goals(
                context,
                production_payload["lambda_home"],
                production_payload["lambda_away"],
                rho=production_payload["rho"],
                model_version=model_tag,
            )
            genuine = ScoreDistribution.from_state(state)
            forged = [list(row) for row in genuine.grid]
            forged[0][0] -= 1e-5
            forged[2][2] += 1e-5
            return ScoreDistribution(state=state, grid=tuple(map(tuple, forged)))

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="not reconstructable"):
        build_vnext_shadow_payload(
            _pure_match(now + timedelta(hours=2)),
            _production_payload(),
            VNextShadowSpec(
                production_model_version=MODEL_VERSION,
                predictor=ForgedGridPredictor(),
            ),
            features_as_of=now,
        )


@pytest.mark.parametrize("offset", (timedelta(0), timedelta(seconds=1)))
def test_cutoff_at_or_after_kickoff_skips_before_predictor_runs(offset):
    class ExplodingPredictor:
        artifact_kind = "must-not-run-v1"
        payload_mode = "parity"
        artifact_descriptor_json = "{}"

        def predict(self, *args, **kwargs):
            raise AssertionError("predictor must not run after cutoff")

    kickoff = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    spec = VNextShadowSpec(
        production_model_version=MODEL_VERSION,
        predictor=ExplodingPredictor(),
    )
    assert build_vnext_shadow_payload(
        _pure_match(kickoff),
        _production_payload(),
        spec,
        features_as_of=kickoff + offset,
    ) is None


def test_fresh_cutoff_check_blocks_predictor_that_crosses_kickoff():
    class NoWriteDb:
        def add(self, value):
            raise AssertionError("post-kickoff row must not be added")

    kickoff = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    payload = _production_payload()
    payload["generated_at"] = (kickoff - timedelta(microseconds=1)).isoformat()
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)
    written = write_vnext_shadow_prediction(
        NoWriteDb(),
        _pure_match(kickoff),
        payload,
        spec,
        clock=lambda: kickoff,
    )
    assert written is False


def test_generate_default_writes_no_vnext_row_or_summary_change(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)

    summary = generate_predictions(
        db_session,
        MODEL_VERSION,
        n_sims=20,
        tournament_sims=10,
    )

    assert summary == {
        "matches_predicted": 72,
        "groups_simulated": 12,
        "tournament_teams": 48,
    }
    assert db_session.query(Prediction).filter_by(model_version=spec.model_tag).count() == 0


def test_generate_opt_in_adds_exact_tagged_parity_rows_only_to_shadow(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)

    generate_predictions(
        db_session,
        MODEL_VERSION,
        n_sims=20,
        tournament_sims=10,
        vnext_shadow_spec=spec,
    )

    vnext_rows = (
        db_session.query(Prediction)
        .filter(
            Prediction.is_shadow.is_(True),
            Prediction.model_version == spec.model_tag,
        )
        .all()
    )
    assert len(vnext_rows) == 72
    candidate = vnext_rows[0]
    production = (
        db_session.query(Prediction)
        .filter_by(match_id=candidate.match_id, model_version=MODEL_VERSION, is_shadow=False)
        .one()
    )
    assert (
        candidate.prob_home_win,
        candidate.prob_draw,
        candidate.prob_away_win,
        candidate.predicted_score_home,
        candidate.predicted_score_away,
        candidate.predicted_score_prob,
    ) == (
        production.prob_home_win,
        production.prob_draw,
        production.prob_away_win,
        production.predicted_score_home,
        production.predicted_score_away,
        production.predicted_score_prob,
    )
    assert candidate.lambda_home is None
    assert candidate.lambda_away is None
    assert candidate.rho is None
    receipt = extract_vnext_receipt(candidate.reasons)
    assert receipt is not None
    assert receipt["champion_model_version"] == production.model_version
    assert receipt["champion_payload_sha256"] == champion_row_fingerprint(production)
    assert db_session.query(Prediction).filter_by(is_shadow=False).count() == 72
    assert all(row.model_version != spec.model_tag for row in (
        db_session.query(Prediction).filter_by(is_shadow=False).all()
    ))


def test_exact_tag_filter_does_not_capture_neighbouring_shadow_tag(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)
    generate_predictions(
        db_session,
        MODEL_VERSION,
        n_sims=20,
        tournament_sims=10,
        vnext_shadow_spec=spec,
    )
    exemplar = db_session.query(Prediction).filter_by(model_version=spec.model_tag).first()
    replacement = "x" if spec.model_tag[-1] != "x" else "y"
    db_session.add(
        Prediction(
            match_id=exemplar.match_id,
            model_version=f"{spec.model_tag[:-1]}{replacement}",
            prob_home_win=exemplar.prob_home_win,
            prob_draw=exemplar.prob_draw,
            prob_away_win=exemplar.prob_away_win,
            predicted_score_home=exemplar.predicted_score_home,
            predicted_score_away=exemplar.predicted_score_away,
            is_shadow=True,
        )
    )
    db_session.commit()

    exact = db_session.query(Prediction).filter(
        Prediction.is_shadow.is_(True),
        Prediction.model_version == spec.model_tag,
    )
    assert exact.count() == 72


def test_post_kickoff_match_gets_production_but_no_vnext_shadow(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    match = db_session.query(Match).filter_by(status="scheduled").order_by(Match.id).first()
    match.kickoff_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    spec = VNextShadowSpec(production_model_version=MODEL_VERSION)

    generate_predictions(
        db_session,
        MODEL_VERSION,
        n_sims=20,
        tournament_sims=10,
        vnext_shadow_spec=spec,
    )

    assert db_session.query(Prediction).filter_by(
        match_id=match.id, model_version=MODEL_VERSION, is_shadow=False
    ).count() == 1
    assert db_session.query(Prediction).filter_by(
        match_id=match.id, model_version=spec.model_tag, is_shadow=True
    ).count() == 0


def test_coverage_sweep_accepts_the_same_opt_in_spec(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    from ml.models.params import load_params

    spec = VNextShadowSpec(production_model_version=load_params().version)

    result = ensure_prediction_coverage(db_session, vnext_shadow_spec=spec)
    match_id = result["match_ids"][0]
    production = db_session.query(Prediction).filter_by(
        match_id=match_id, is_shadow=False
    ).one()
    shadow = db_session.query(Prediction).filter_by(
        match_id=match_id, model_version=spec.model_tag, is_shadow=True
    ).one()
    assert (shadow.prob_home_win, shadow.prob_draw, shadow.prob_away_win) == (
        production.prob_home_win,
        production.prob_draw,
        production.prob_away_win,
    )
def test_coverage_backfills_missing_exact_tag_without_duplicate_production(
    db_session, monkeypatch
):
    import pipeline.generate_predictions as generation
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    ensure_prediction_coverage(db_session)
    production_count = db_session.query(Prediction).filter_by(is_shadow=False).count()
    spec = VNextShadowSpec(production_model_version=load_params().version)
    original_writer = generation.write_vnext_shadow_prediction

    monkeypatch.setattr(generation, "write_vnext_shadow_prediction", lambda *a, **k: False)
    failed = ensure_prediction_coverage(db_session, vnext_shadow_spec=spec)
    assert failed == {"generated": 0, "match_ids": []}
    assert db_session.query(Prediction).filter_by(model_version=spec.model_tag).count() == 0

    monkeypatch.setattr(generation, "write_vnext_shadow_prediction", original_writer)
    retried = ensure_prediction_coverage(db_session, vnext_shadow_spec=spec)
    assert retried["generated"] == production_count
    assert db_session.query(Prediction).filter_by(model_version=spec.model_tag).count() == (
        production_count
    )
    assert db_session.query(Prediction).filter_by(is_shadow=False).count() == production_count
    shadow = db_session.query(Prediction).filter_by(model_version=spec.model_tag).first()
    production = db_session.query(Prediction).filter_by(
        match_id=shadow.match_id,
        model_version=spec.production_model_version,
        is_shadow=False,
    ).one()
    assert (shadow.prob_home_win, shadow.prob_draw, shadow.prob_away_win) == (
        production.prob_home_win,
        production.prob_draw,
        production.prob_away_win,
    )
    receipt = extract_vnext_receipt(shadow.reasons)
    parent_created_at = production.created_at
    if parent_created_at.tzinfo is None or parent_created_at.utcoffset() is None:
        parent_created_at = parent_created_at.replace(tzinfo=timezone.utc)
    assert datetime.fromisoformat(receipt["features_as_of"]) == parent_created_at


def test_coverage_repairs_a_tagged_shadow_with_tampered_lineage(db_session):
    from ml.models.params import load_params

    load_structure(db_session)
    _set_elos(db_session)
    _move_scheduled_kickoffs_to_future(db_session)
    spec = VNextShadowSpec(production_model_version=load_params().version)
    ensure_prediction_coverage(db_session, vnext_shadow_spec=spec)
    production_count = db_session.query(Prediction).filter_by(is_shadow=False).count()
    original_shadow_count = db_session.query(Prediction).filter_by(
        model_version=spec.model_tag, is_shadow=True
    ).count()
    damaged = db_session.query(Prediction).filter_by(
        model_version=spec.model_tag, is_shadow=True
    ).first()
    damaged_reasons = json.loads(json.dumps(damaged.reasons))
    damaged_receipt = extract_vnext_receipt(damaged_reasons)
    damaged_receipt["artifact_identity"] = "0" * 64
    for item in damaged_reasons:
        if isinstance(item, dict) and "_vnext_receipt" in item:
            item["_vnext_receipt"] = damaged_receipt
    damaged.reasons = damaged_reasons
    db_session.commit()

    repaired = ensure_prediction_coverage(db_session, vnext_shadow_spec=spec)

    assert repaired == {"generated": 1, "match_ids": [damaged.match_id]}
    assert db_session.query(Prediction).filter_by(is_shadow=False).count() == production_count
    assert db_session.query(Prediction).filter_by(
        model_version=spec.model_tag, is_shadow=True
    ).count() == original_shadow_count + 1
    newest = db_session.query(Prediction).filter_by(
        match_id=damaged.match_id,
        model_version=spec.model_tag,
        is_shadow=True,
    ).order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()
    parent = db_session.query(Prediction).filter_by(
        match_id=damaged.match_id,
        model_version=spec.production_model_version,
        is_shadow=False,
    ).one()
    assert extract_vnext_receipt(newest.reasons)[
        "champion_payload_sha256"
    ] == champion_row_fingerprint(parent)
    assert ensure_prediction_coverage(
        db_session, vnext_shadow_spec=spec
    ) == {"generated": 0, "match_ids": []}
