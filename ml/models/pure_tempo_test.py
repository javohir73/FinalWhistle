"""Focused tests for the frozen pure-tempo vNext challenger."""
from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ml.models.pure_tempo import (
    FrozenPureTempoPredictor,
    FrozenTeamTempoArtifact,
)
from ml.models.vnext import MatchContext
from pipeline.vnext_shadow import (
    VNextPredictor,
    VNextShadowSpec,
    build_vnext_shadow_payload,
)


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
PRODUCTION_VERSION = "poisson-elo-v0.5"


def _artifact_mapping(**changes):
    artifact = {
        "schema_version": 1,
        "artifact_version": "tempo-fit-2025-v1",
        "trained_through": "2025-12-31T00:00:00+00:00",
        "global_log_tempo": 0.05,
        "unknown_team_log_tempo": -0.02,
        "team_log_tempos": {"10": 0.20, "20": -0.10},
    }
    artifact.update(changes)
    return artifact


def _predictor(**changes) -> FrozenPureTempoPredictor:
    artifact = FrozenTeamTempoArtifact.from_mapping(_artifact_mapping(**changes))
    return FrozenPureTempoPredictor(artifact)


def _context(home="10", away="20", as_of=NOW) -> MatchContext:
    return MatchContext(
        match_id="7",
        home_team_id=home,
        away_team_id=away,
        features_as_of=as_of,
        kickoff_utc=NOW + timedelta(hours=2),
    )


def _payload() -> dict:
    return {
        "match_id": 7,
        "model_version": PRODUCTION_VERSION,
        "generated_at": "unchanged",
        "lambda_home": 1.6,
        "lambda_away": 0.9,
        "rho": -0.06,
        "probabilities": {"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
        "predicted_score": {"home": 1, "away": 0, "probability": 0.1},
        "confidence": "Medium",
        "reasons": ["production reason"],
        "top_features": [{"name": "elo", "weight": 1}],
        "writeup": {"production": True},
    }


def test_predictor_implements_protocol_and_is_distribution_mode():
    predictor = _predictor()
    assert isinstance(predictor, VNextPredictor)
    assert predictor.payload_mode == "calibrated_wdl"


def test_pure_tempo_preserves_production_strength_ratio_exactly():
    predictor = _predictor()
    distribution = predictor.predict(
        _context(),
        _payload(),
        model_tag="fw-vnext-pure-tempo-test",
        artifact_identity="identity",
    )

    expected_strength = math.log(1.6 / 0.9)
    assert distribution.state.strength_log_ratio == expected_strength
    latent_home, latent_away = distribution.latent_expected_goals
    assert latent_home / latent_away == pytest.approx(1.6 / 0.9)
    expected_adjustment = 0.05 + 0.5 * (0.20 - 0.10)
    assert sum(distribution.latent_expected_goals) == pytest.approx(
        (1.6 + 0.9) * math.exp(expected_adjustment)
    )
    assert distribution.calibration is not None
    assert distribution.calibration.artifact_id.endswith(":identity:7")
    assert distribution.state.model_version == "fw-vnext-pure-tempo-test"


def test_unknown_teams_use_frozen_fallback_without_changing_strength():
    distribution = _predictor().predict(
        _context(home="unknown-a", away="unknown-b"),
        _payload(),
        model_tag="fw-vnext-pure-tempo-test",
        artifact_identity="identity",
    )
    expected_adjustment = 0.05 - 0.02
    assert sum(distribution.latent_expected_goals) == pytest.approx(
        2.5 * math.exp(expected_adjustment)
    )
    assert distribution.state.strength_log_ratio == math.log(1.6 / 0.9)


def test_zero_tempo_reproduces_persisted_production_wdl():
    predictor = _predictor(
        global_log_tempo=0.0,
        unknown_team_log_tempo=0.0,
        team_log_tempos={"10": 0.0, "20": 0.0},
    )
    distribution = predictor.predict(
        _context(),
        _payload(),
        model_tag="fw-vnext-pure-tempo-test",
        artifact_identity="zero-identity",
    )

    assert distribution.wdl.as_tuple() == pytest.approx((0.55, 0.25, 0.20))
    assert distribution.latent_expected_goals == pytest.approx((1.6, 0.9))
    assert distribution.calibration is not None
    assert distribution.calibration.artifact_id == (
        "fixture-local-tempo-parity:zero-identity:7"
    )


def test_zero_tempo_shadow_reproduces_production_wdl_after_persistence_rounding():
    predictor = _predictor(
        global_log_tempo=0.0,
        unknown_team_log_tempo=0.0,
        team_log_tempos={"10": 0.0, "20": 0.0},
    )
    spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION,
        predictor=predictor,
    )
    production = _payload()
    match = SimpleNamespace(
        id=7,
        team_home_id=10,
        team_away_id=20,
        kickoff_utc=NOW + timedelta(hours=2),
        tournament_id=1,
        is_neutral=True,
    )

    shadow = build_vnext_shadow_payload(
        match, production, spec, features_as_of=NOW
    )

    assert shadow["probabilities"] == production["probabilities"]
    assert shadow["lambda_home"] is None
    assert shadow["lambda_away"] is None
    assert shadow["rho"] is None


def test_nonzero_tempo_changes_total_before_the_same_calibration_only():
    zero = _predictor(
        global_log_tempo=0.0,
        unknown_team_log_tempo=0.0,
        team_log_tempos={"10": 0.0, "20": 0.0},
    ).predict(
        _context(),
        _payload(),
        model_tag="fw-vnext-pure-tempo-zero",
        artifact_identity="zero",
    )
    changed = _predictor().predict(
        _context(),
        _payload(),
        model_tag="fw-vnext-pure-tempo-changed",
        artifact_identity="changed",
    )

    assert changed.state.strength_log_ratio == zero.state.strength_log_ratio
    assert sum(changed.latent_expected_goals) != pytest.approx(
        sum(zero.latent_expected_goals)
    )
    assert changed.wdl.as_tuple() != pytest.approx(zero.wdl.as_tuple())
    assert changed.calibration is not None
    assert changed.calibration.method == zero.calibration.method


def test_canonical_descriptor_makes_identity_deterministic_and_behavior_bound():
    artifact = _artifact_mapping()
    reordered_json = json.dumps(dict(reversed(list(artifact.items()))), indent=2)
    first = FrozenPureTempoPredictor.from_artifact_json(json.dumps(artifact))
    reordered = FrozenPureTempoPredictor.from_artifact_json(reordered_json)
    changed = _predictor(global_log_tempo=0.06)

    assert first.artifact_descriptor_json == reordered.artifact_descriptor_json
    first_spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION, predictor=first
    )
    reordered_spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION, predictor=reordered
    )
    changed_spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION, predictor=changed
    )
    cap_changed_spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION,
        predictor=FrozenPureTempoPredictor(
            first.artifact, max_abs_match_log_adjustment=0.2
        ),
    )
    assert first_spec.artifact_identity == reordered_spec.artifact_identity
    assert first_spec.artifact_identity != changed_spec.artifact_identity
    assert first_spec.artifact_identity != cap_changed_spec.artifact_identity


def test_artifact_trained_after_forecast_cutoff_is_rejected():
    predictor = _predictor(trained_through="2026-01-02T00:00:00+00:00")
    with pytest.raises(ValueError, match="trained after"):
        predictor.predict(
            _context(),
            _payload(),
            model_tag="fw-vnext-pure-tempo-test",
            artifact_identity="identity",
        )


def test_mapping_is_snapshotted_and_artifact_is_immutable():
    source = _artifact_mapping()
    artifact = FrozenTeamTempoArtifact.from_mapping(source)
    predictor = FrozenPureTempoPredictor(artifact)
    descriptor = predictor.artifact_descriptor_json
    source["team_log_tempos"]["10"] = 99.0
    source["global_log_tempo"] = -99.0

    assert predictor.artifact_descriptor_json == descriptor
    assert artifact.tempo_for("10") == 0.20
    with pytest.raises(FrozenInstanceError):
        artifact.global_log_tempo = 4.0


def test_build_shadow_payload_compatibility_and_source_mutation_safety():
    predictor = _predictor()
    spec = VNextShadowSpec(
        production_model_version=PRODUCTION_VERSION,
        artifact_name="pure-tempo-shadow",
        artifact_version="1",
        predictor=predictor,
    )
    production = _payload()
    untouched = json.loads(json.dumps(production))
    match = SimpleNamespace(
        id=7,
        team_home_id=10,
        team_away_id=20,
        kickoff_utc=NOW + timedelta(hours=2),
        tournament_id=1,
        is_neutral=True,
    )

    shadow = build_vnext_shadow_payload(
        match, production, spec, features_as_of=NOW
    )

    assert shadow is not None
    assert production == untouched
    assert shadow["model_version"] == spec.model_tag
    assert shadow["vnext_artifact_identity"] == spec.artifact_identity
    assert shadow["probabilities"] != production["probabilities"]
    assert shadow["lambda_home"] is None
    assert shadow["lambda_away"] is None
    assert shadow["rho"] is None
    assert shadow["vnext_calibration_artifact"].startswith(
        "fixture-local-tempo-parity:"
    )
    assert shadow["writeup"] is None


@pytest.mark.parametrize(
    "change, error",
    [
        ({"trained_through": "2025-12-31T00:00:00"}, "timezone-aware"),
        ({"global_log_tempo": float("nan")}, "finite JSON"),
        ({"team_log_tempos": {"10": float("inf")}}, "finite JSON"),
        ({"schema_version": 2}, "exactly 1"),
    ],
)
def test_invalid_artifacts_are_rejected(change, error):
    with pytest.raises(ValueError, match=error):
        FrozenTeamTempoArtifact.from_mapping(_artifact_mapping(**change))


def test_invalid_production_lambdas_are_rejected():
    payload = _payload()
    payload["lambda_home"] = 0.0
    with pytest.raises(ValueError, match="positive"):
        _predictor().predict(
            _context(),
            payload,
            model_tag="fw-vnext-pure-tempo-test",
            artifact_identity="identity",
        )


@pytest.mark.parametrize(
    "probabilities, error",
    [
        (None, "must be a mapping"),
        ({"home_win": -0.1, "draw": 0.5, "away_win": 0.6}, "within"),
        ({"home_win": 1.1, "draw": 0.0, "away_win": 0.0}, "within"),
        ({"home_win": 0.0, "draw": 0.0, "away_win": 0.0}, "positive mass"),
        ({"home_win": 0.8, "draw": 0.8, "away_win": 0.0}, "sum to one"),
        ({"home_win": float("nan"), "draw": 0.5, "away_win": 0.5}, "finite"),
    ],
)
def test_invalid_production_probabilities_are_rejected(probabilities, error):
    payload = _payload()
    payload["probabilities"] = probabilities
    with pytest.raises(ValueError, match=error):
        _predictor().predict(
            _context(),
            payload,
            model_tag="fw-vnext-pure-tempo-test",
            artifact_identity="identity",
        )
