"""Tests for bounded strength/tempo signal corrections."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from ml.models.vnext import (
    FixtureIdentity,
    LatentMatchState,
    MatchContext,
    ScoreDistribution,
    StateProvenance,
)
from ml.models.vnext_adjustments import (
    LatentAdjustment,
    apply_latent_adjustments,
    decompose_log_lambda_offsets,
)


def _state() -> LatentMatchState:
    return LatentMatchState.from_expected_goals(
        MatchContext(
            match_id="m1",
            home_team_id="A",
            away_team_id="B",
            features_as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        1.6,
        0.9,
        rho=-0.06,
    )


def _times(state: LatentMatchState) -> tuple[datetime, datetime]:
    return (
        state.context.features_as_of - timedelta(minutes=10),
        state.context.features_as_of - timedelta(minutes=5),
    )


def _adjustment(
    state: LatentMatchState,
    source: str,
    artifact_id: str,
    *,
    strength_delta: float = 0.0,
    tempo_delta: float = 0.0,
    fixture: FixtureIdentity | None = None,
    effective_at: datetime | None = None,
    known_at: datetime | None = None,
) -> LatentAdjustment:
    default_effective, default_known = _times(state)
    return LatentAdjustment(
        fixture=fixture or state.context.fixture_identity,
        effective_at=effective_at or default_effective,
        known_at=known_at or default_known,
        source=source,
        artifact_id=artifact_id,
        strength_delta=strength_delta,
        log_total_goals_delta=tempo_delta,
    )


def test_decomposition_exactly_reproduces_legacy_log_lambda_offsets():
    state = _state()
    home_offset, away_offset = 0.12, -0.04
    adjustment = decompose_log_lambda_offsets(
        state,
        home_offset,
        away_offset,
        source="availability",
        artifact_id="availability-v1",
        effective_at=_times(state)[0],
        known_at=_times(state)[1],
    )
    adjusted = apply_latent_adjustments(
        state, [adjustment], model_version="fw-vnext-availability-v1"
    )

    assert adjusted.expected_goals == pytest.approx(
        (1.6 * math.exp(home_offset), 0.9 * math.exp(away_offset))
    )


def test_strength_ablation_preserves_total_and_tempo_ablation_preserves_share():
    state = _state()
    adjustment = decompose_log_lambda_offsets(
        state,
        0.12,
        -0.04,
        source="xg",
        artifact_id="xg-v1",
        effective_at=_times(state)[0],
        known_at=_times(state)[1],
    )
    strength_only = apply_latent_adjustments(
        state,
        [adjustment.isolated("strength")],
        model_version="fw-vnext-xg-strength-v1",
    )
    tempo_only = apply_latent_adjustments(
        state,
        [adjustment.isolated("tempo")],
        model_version="fw-vnext-xg-tempo-v1",
    )

    assert strength_only.total_expected_goals == pytest.approx(state.total_expected_goals)
    assert strength_only.home_goal_share != pytest.approx(state.home_goal_share)
    assert tempo_only.home_goal_share == pytest.approx(state.home_goal_share)
    assert tempo_only.total_expected_goals != pytest.approx(state.total_expected_goals)


def test_combined_safety_bounds_fail_closed_instead_of_clipping():
    state = _state()
    adjustments = [
        _adjustment(state, "player", "p1", strength_delta=0.5),
        _adjustment(state, "market", "m1", strength_delta=0.4),
    ]

    with pytest.raises(ValueError, match="strength adjustment"):
        apply_latent_adjustments(
            state, adjustments, model_version="fw-vnext-too-large"
        )


def test_adjustments_preserve_context_rho_and_uncertainty():
    state = _state()
    adjusted = apply_latent_adjustments(
        state,
        [_adjustment(state, "rest", "rest-v1", tempo_delta=-0.05)],
        model_version="fw-vnext-rest-v1",
    )
    assert adjusted.context is state.context
    assert adjusted.rho == state.rho
    assert adjusted.uncertainty is state.uncertainty


@pytest.mark.parametrize("axis", ["unknown", "", None])
def test_unknown_ablation_axis_is_rejected(axis):
    state = _state()
    adjustment = _adjustment(state, "xg", "xg-v1")
    with pytest.raises(ValueError, match="axis"):
        adjustment.isolated(axis)


def test_adjustments_reject_wrong_fixture_post_cutoff_and_naive_timestamps():
    state = _state()
    wrong_fixture = FixtureIdentity("another", "A", "B")
    with pytest.raises(ValueError, match="fixture"):
        apply_latent_adjustments(
            state,
            [_adjustment(state, "xg", "wrong", fixture=wrong_fixture)],
            model_version="fw-vnext-wrong-fixture",
        )
    with pytest.raises(ValueError, match="effective_at.*cutoff"):
        apply_latent_adjustments(
            state,
            [
                _adjustment(
                    state,
                    "xg",
                    "late",
                    effective_at=state.context.features_as_of + timedelta(seconds=1),
                )
            ],
            model_version="fw-vnext-late",
        )
    with pytest.raises(ValueError, match="known_at.*cutoff"):
        apply_latent_adjustments(
            state,
            [
                _adjustment(
                    state,
                    "xg",
                    "known-late",
                    known_at=state.context.features_as_of + timedelta(seconds=1),
                )
            ],
            model_version="fw-vnext-known-late",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        LatentAdjustment(
            fixture=state.context.fixture_identity,
            effective_at=datetime(2025, 12, 31),
            known_at=_times(state)[1],
            source="xg",
            artifact_id="naive",
        )


def test_decomposition_fails_closed_on_exponential_overflow():
    state = _state()
    with pytest.raises(ValueError, match="invalid expected goals"):
        decompose_log_lambda_offsets(
            state,
            1000.0,
            0.0,
            source="bad-artifact",
            artifact_id="overflow",
            effective_at=_times(state)[0],
            known_at=_times(state)[1],
        )


def test_adjustment_provenance_is_retained_in_order_on_state_and_distribution():
    base = _state()
    effective_at, known_at = _times(base)
    base_marker = StateProvenance(
        source="fundamental",
        artifact_id="elo-v5",
        effective_at=effective_at,
        known_at=known_at,
    )
    state = LatentMatchState.from_expected_goals(
        base.context,
        *base.expected_goals,
        rho=base.rho,
        provenance=(base_marker,),
    )
    first = _adjustment(state, "availability", "xi-v2", strength_delta=0.05)
    second = _adjustment(state, "xg", "xg-v3", tempo_delta=-0.02)
    adjusted = apply_latent_adjustments(
        state,
        [first, second],
        model_version="fw-vnext-adjusted-v1",
    )

    assert [(item.source, item.artifact_id) for item in adjusted.provenance] == [
        ("fundamental", "elo-v5"),
        ("availability", "xi-v2"),
        ("xg", "xg-v3"),
    ]
    assert ScoreDistribution.from_state(adjusted).provenance == adjusted.provenance
