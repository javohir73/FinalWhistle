"""Market evidence expressed in vNext's strength/tempo coordinates.

The production odds twin scales only the total expected goals.  This module is
the additive vNext alternative: a complete 1X2 market supplies relative goal
balance, an over/under market supplies tempo, and each coordinate is blended
independently with the fundamental model.  No market input is required and no
blend is enabled by importing this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ml.models.odds_blend import (
    lambda_total_from_over,
    remove_margin,
)
from ml.models.poisson import outcome_probabilities, score_matrix
from ml.models.vnext import (
    FixtureIdentity,
    LatentMatchState,
    MatchContext,
    NO_UNCERTAINTY,
    StateProvenance,
)

_BISECT_STEPS = 60


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _probability_triple(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("1X2 probabilities must contain home, draw and away")
    triple = tuple(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0.0 for value in triple):
        raise ValueError("1X2 probabilities must be finite and non-negative")
    total = sum(triple)
    if total <= 0.0:
        raise ValueError("1X2 probabilities must have positive mass")
    return tuple(value / total for value in triple)  # type: ignore[return-value]


def _home_share_for_skew(total: float, skew: float, *, rho: float) -> float:
    """Solve the Poisson/DC home share matching ``P(home)-P(away)``."""
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("market total must be positive and finite")
    if not math.isfinite(skew) or not -1.0 <= skew <= 1.0:
        raise ValueError("market home-away skew must be within [-1, 1]")
    lo, hi = 1e-5, 1.0 - 1e-5
    lower_wdl = outcome_probabilities(score_matrix(total * lo, total * (1.0 - lo), rho=rho))
    upper_wdl = outcome_probabilities(score_matrix(total * hi, total * (1.0 - hi), rho=rho))
    lower_skew = lower_wdl[0] - lower_wdl[2]
    upper_skew = upper_wdl[0] - upper_wdl[2]
    if skew < lower_skew or skew > upper_skew:
        raise ValueError("market skew is not representable at the inferred total")
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        wdl = outcome_probabilities(
            score_matrix(total * mid, total * (1.0 - mid), rho=rho)
        )
        if wdl[0] - wdl[2] < skew:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _total_and_share_from_wdl(
    home: float, draw: float, away: float, *, rho: float
) -> tuple[float, float]:
    """Jointly match draw mass and home-away skew for a complete 1X2 market."""
    lo, hi = 0.05, 12.0
    skew = home - away
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        share = _home_share_for_skew(mid, skew, rho=rho)
        wdl = outcome_probabilities(
            score_matrix(mid * share, mid * (1.0 - share), rho=rho)
        )
        if wdl[1] > draw:
            lo = mid
        else:
            hi = mid
    total = (lo + hi) / 2.0
    share = _home_share_for_skew(total, skew, rho=rho)
    represented = outcome_probabilities(
        score_matrix(total * share, total * (1.0 - share), rho=rho)
    )
    if any(
        not math.isclose(observed, target, rel_tol=0.0, abs_tol=2e-6)
        for observed, target in zip(represented, (home, draw, away))
    ):
        raise ValueError("1X2 market is not representable within the model bounds")
    return total, share


@dataclass(frozen=True, slots=True)
class MarketEvidence:
    """Margin-free market inputs captured before the prediction cutoff."""

    fixture: FixtureIdentity
    captured_at: datetime
    known_at: datetime
    wdl: tuple[float, float, float]
    artifact_id: str
    over_2_5: float | None = None
    source: str = "market-consensus"

    def __post_init__(self) -> None:
        if not isinstance(self.fixture, FixtureIdentity):
            raise TypeError("fixture must be a FixtureIdentity")
        _require_aware(self.captured_at, "captured_at")
        _require_aware(self.known_at, "known_at")
        if self.known_at < self.captured_at:
            raise ValueError("known_at cannot be before captured_at")
        if not self.artifact_id or not self.artifact_id.strip():
            raise ValueError("market artifact_id must not be empty")
        object.__setattr__(self, "wdl", _probability_triple(self.wdl))
        if self.over_2_5 is not None:
            value = float(self.over_2_5)
            if not math.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError("over_2_5 must be strictly within (0, 1)")
            object.__setattr__(self, "over_2_5", value)
        if not self.source or not self.source.strip():
            raise ValueError("market source must not be empty")

    @classmethod
    def from_decimal_odds(
        cls,
        odds_home: float,
        odds_draw: float,
        odds_away: float,
        *,
        odds_over_2_5: float | None = None,
        odds_under_2_5: float | None = None,
        fixture: FixtureIdentity,
        captured_at: datetime,
        known_at: datetime,
        artifact_id: str,
        source: str = "market-consensus",
    ) -> "MarketEvidence":
        wdl = remove_margin((odds_home, odds_draw, odds_away))
        over = None
        if odds_over_2_5 is not None or odds_under_2_5 is not None:
            if odds_over_2_5 is None or odds_under_2_5 is None:
                raise ValueError("over and under prices must be supplied together")
            over = remove_margin((odds_over_2_5, odds_under_2_5))[0]
        return cls(
            fixture=fixture,
            captured_at=captured_at,
            known_at=known_at,
            wdl=wdl,
            artifact_id=artifact_id,
            over_2_5=over,
            source=source,
        )


def market_latent_state(
    context: MatchContext,
    evidence: MarketEvidence,
    *,
    rho: float = 0.0,
    model_version: str = "fw-vnext-market-v0",
) -> LatentMatchState:
    """Invert pre-kickoff market probabilities into strength and tempo."""
    if evidence.fixture != context.fixture_identity:
        raise ValueError("market evidence fixture does not match the prediction context")
    if context.kickoff_utc is None:
        raise ValueError("market evidence requires a context kickoff_utc")
    for timestamp, name in (
        (evidence.captured_at, "captured_at"),
        (evidence.known_at, "known_at"),
    ):
        if timestamp > context.features_as_of:
            raise ValueError(f"market {name} is after the prediction cutoff")
        if timestamp > context.kickoff_utc:
            raise ValueError(f"market {name} is after kickoff")
    home, draw, away = evidence.wdl
    if evidence.over_2_5 is not None:
        total = lambda_total_from_over(evidence.over_2_5)
        share = _home_share_for_skew(total, home - away, rho=rho)
    else:
        total, share = _total_and_share_from_wdl(home, draw, away, rho=rho)
    return LatentMatchState(
        context=context,
        strength_log_ratio=math.log(share / (1.0 - share)),
        log_total_goals=math.log(total),
        rho=rho,
        uncertainty=NO_UNCERTAINTY,
        model_version=model_version,
        provenance=(
            StateProvenance(
                source=evidence.source,
                artifact_id=evidence.artifact_id,
                effective_at=evidence.captured_at,
                known_at=evidence.known_at,
            ),
        ),
    )


def blend_fundamental_and_market(
    fundamental: LatentMatchState,
    market: LatentMatchState,
    *,
    strength_weight: float,
    tempo_weight: float,
    model_version: str = "fw-vnext-blend-v0",
) -> LatentMatchState:
    """Blend the two latent axes independently using explicit fixed weights."""
    if fundamental.context != market.context:
        raise ValueError("fundamental and market states must describe the same context")
    if fundamental.rho != market.rho:
        raise ValueError("fundamental and market rho must match before blending")
    for weight, name in (
        (strength_weight, "strength_weight"),
        (tempo_weight, "tempo_weight"),
    ):
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise ValueError(f"{name} must be within [0, 1]")
    if strength_weight == 0.0 and tempo_weight == 0.0:
        uncertainty = fundamental.uncertainty
        provenance = fundamental.provenance
    elif strength_weight == 1.0 and tempo_weight == 1.0:
        uncertainty = market.uncertainty
        provenance = market.provenance
    else:
        # Marginal uncertainty cannot be combined honestly without the
        # cross-model covariance. Keep it explicitly unestimated.
        uncertainty = NO_UNCERTAINTY
        provenance = fundamental.provenance + market.provenance
    return LatentMatchState(
        context=fundamental.context,
        strength_log_ratio=(
            (1.0 - strength_weight) * fundamental.strength_log_ratio
            + strength_weight * market.strength_log_ratio
        ),
        log_total_goals=(
            (1.0 - tempo_weight) * fundamental.log_total_goals
            + tempo_weight * market.log_total_goals
        ),
        rho=fundamental.rho,
        uncertainty=uncertainty,
        model_version=model_version,
        provenance=provenance,
    )
