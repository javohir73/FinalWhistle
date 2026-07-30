"""Bounded, auditable corrections to vNext strength and tempo.

Player availability, xG state and residual ML are not allowed to mutate home
and away goal rates independently without explanation.  They must first express
their effect as a relative-strength correction, a tempo correction, or both.
This module also decomposes the repository's existing log-lambda offsets so
each old signal can be tested axis by axis before it is combined.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Sequence

from ml.models.vnext import FixtureIdentity, LatentMatchState, StateProvenance

AdjustmentAxis = Literal["strength", "tempo", "both"]


@dataclass(frozen=True, slots=True)
class LatentAdjustment:
    """One versioned correction in the same coordinates as the core model."""

    fixture: FixtureIdentity
    effective_at: datetime
    known_at: datetime
    source: str
    artifact_id: str
    strength_delta: float = 0.0
    log_total_goals_delta: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.fixture, FixtureIdentity):
            raise TypeError("fixture must be a FixtureIdentity")
        for value, name in (
            (self.effective_at, "effective_at"),
            (self.known_at, "known_at"),
        ):
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must be a timezone-aware datetime")
        if not self.source or not self.source.strip():
            raise ValueError("adjustment source must not be empty")
        if not self.artifact_id or not self.artifact_id.strip():
            raise ValueError("adjustment artifact_id must not be empty")
        for value, name in (
            (self.strength_delta, "strength_delta"),
            (self.log_total_goals_delta, "log_total_goals_delta"),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")

    def isolated(self, axis: AdjustmentAxis) -> "LatentAdjustment":
        """Return the pre-declared ablation used to test one causal axis."""
        if axis == "strength":
            return replace(self, log_total_goals_delta=0.0)
        if axis == "tempo":
            return replace(self, strength_delta=0.0)
        if axis == "both":
            return self
        raise ValueError("axis must be strength, tempo or both")


def decompose_log_lambda_offsets(
    state: LatentMatchState,
    home_log_offset: float,
    away_log_offset: float,
    *,
    source: str,
    artifact_id: str,
    effective_at: datetime,
    known_at: datetime,
) -> LatentAdjustment:
    """Exactly rewrite two legacy log-rate offsets as latent corrections."""
    for value, name in (
        (home_log_offset, "home_log_offset"),
        (away_log_offset, "away_log_offset"),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    lambda_home, lambda_away = state.expected_goals
    try:
        adjusted_home = lambda_home * math.exp(home_log_offset)
        adjusted_away = lambda_away * math.exp(away_log_offset)
        tempo_delta = math.log(
            (adjusted_home + adjusted_away) / (lambda_home + lambda_away)
        )
    except (OverflowError, ValueError) as exc:
        raise ValueError("log-lambda offsets produce invalid expected goals") from exc
    if not all(math.isfinite(value) for value in (adjusted_home, adjusted_away, tempo_delta)):
        raise ValueError("log-lambda offsets produce non-finite expected goals")
    return LatentAdjustment(
        fixture=state.context.fixture_identity,
        effective_at=effective_at,
        known_at=known_at,
        source=source,
        artifact_id=artifact_id,
        strength_delta=home_log_offset - away_log_offset,
        log_total_goals_delta=tempo_delta,
    )


def apply_latent_adjustments(
    state: LatentMatchState,
    adjustments: Sequence[LatentAdjustment],
    *,
    model_version: str,
    max_abs_strength_delta: float = 0.75,
    max_abs_log_total_goals_delta: float = 0.35,
) -> LatentMatchState:
    """Apply explicit corrections, failing rather than silently clipping them."""
    adjustments = tuple(adjustments)
    if not model_version or len(model_version) > 40:
        raise ValueError("model_version must contain 1 to 40 characters")
    for cap, name in (
        (max_abs_strength_delta, "max_abs_strength_delta"),
        (max_abs_log_total_goals_delta, "max_abs_log_total_goals_delta"),
    ):
        if not math.isfinite(cap) or cap <= 0.0:
            raise ValueError(f"{name} must be positive and finite")
    if any(not isinstance(item, LatentAdjustment) for item in adjustments):
        raise TypeError("adjustments must contain LatentAdjustment values")
    for item in adjustments:
        if item.fixture != state.context.fixture_identity:
            raise ValueError("adjustment fixture does not match the latent state context")
        for timestamp, name in (
            (item.effective_at, "effective_at"),
            (item.known_at, "known_at"),
        ):
            if timestamp > state.context.features_as_of:
                raise ValueError(f"adjustment {name} is after the prediction cutoff")
            if (
                state.context.kickoff_utc is not None
                and timestamp > state.context.kickoff_utc
            ):
                raise ValueError(f"adjustment {name} is after kickoff")
    strength_delta = sum(item.strength_delta for item in adjustments)
    tempo_delta = sum(item.log_total_goals_delta for item in adjustments)
    if abs(strength_delta) > max_abs_strength_delta:
        raise ValueError("combined strength adjustment exceeds its safety bound")
    if abs(tempo_delta) > max_abs_log_total_goals_delta:
        raise ValueError("combined tempo adjustment exceeds its safety bound")
    provenance = state.provenance + tuple(
        StateProvenance(
            source=item.source,
            artifact_id=item.artifact_id,
            effective_at=item.effective_at,
            known_at=item.known_at,
        )
        for item in adjustments
    )
    return LatentMatchState(
        context=state.context,
        strength_log_ratio=state.strength_log_ratio + strength_delta,
        log_total_goals=state.log_total_goals + tempo_delta,
        rho=state.rho,
        uncertainty=state.uncertainty,
        model_version=model_version,
        provenance=provenance,
    )
