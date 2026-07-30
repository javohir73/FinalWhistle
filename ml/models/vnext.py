"""Additive vNext probabilistic core for FinalWhistle.

This module deliberately does not replace the production Poisson/Elo path.  It
introduces a small set of immutable contracts that a future champion/challenger
pipeline can use while keeping every published market coherent with one score
distribution.

The two latent match coordinates are orthogonal by construction:

``strength_log_ratio = log(lambda_home / lambda_away)``
    Controls only which team receives the expected goals.

``log_total_goals = log(lambda_home + lambda_away)``
    Controls only match tempo (the expected total number of goals).

Consequently a strength change cannot silently change the expected total, and a
tempo change cannot silently change the home/away goal share.  This is the seam
needed for independent strength, lineup, xG and market-total experts later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping

from ml.models.poisson import (
    BASE_GOALS,
    DRAW_HEADLINE_BAND,
    ELO_TO_GOALS_BETA,
    MAX_GOALS,
    MatchPrediction,
    expected_goals_from_elo,
    most_likely_score,
    predict_match,
    score_matrix,
)


Side = Literal["home", "away"]
UncertaintyStatus = Literal["not_estimated", "externally_supplied"]

# math.factorial(171) is larger than the largest float, so poisson_pmf raises
# OverflowError on a grid that deep before a single probability exists.  Callers
# derive max_goals from observed scores, so the bound has to be enforced here.
_MAX_GRID_GOALS = 170


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_aware(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FixtureIdentity:
    """Exact, orientation-sensitive identity for evidence attached to a match."""

    match_id: str
    home_team_id: str
    away_team_id: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.match_id, "match_id"),
            (self.home_team_id, "home_team_id"),
            (self.away_team_id, "away_team_id"),
        ):
            if not value or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must differ")


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Immutable fixture identity and information cutoff.

    ``features_as_of`` is part of the contract rather than an informal pipeline
    convention.  That makes it possible for future training and backtests to
    reject information that arrived after the prediction was made.
    """

    match_id: str
    home_team_id: str
    away_team_id: str
    features_as_of: datetime
    kickoff_utc: datetime | None = None
    competition_id: str | None = None
    neutral_venue: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.match_id, "match_id"),
            (self.home_team_id, "home_team_id"),
            (self.away_team_id, "away_team_id"),
        ):
            if not value or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must differ")
        _require_aware(self.kickoff_utc, "kickoff_utc")
        if self.features_as_of is None:
            raise ValueError("features_as_of is required")
        _require_aware(self.features_as_of, "features_as_of")
        if (
            self.kickoff_utc is not None
            and self.features_as_of > self.kickoff_utc
        ):
            raise ValueError("features_as_of cannot be after kickoff_utc")

    @property
    def fixture_identity(self) -> FixtureIdentity:
        return FixtureIdentity(
            match_id=self.match_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
        )


@dataclass(frozen=True, slots=True)
class StateProvenance:
    """Ordered artifact lineage carried with a latent state and distribution."""

    source: str
    artifact_id: str
    effective_at: datetime
    known_at: datetime

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError("provenance source must not be empty")
        if not self.artifact_id or not self.artifact_id.strip():
            raise ValueError("provenance artifact_id must not be empty")
        if self.effective_at is None or self.known_at is None:
            raise ValueError("provenance timestamps are required")
        _require_aware(self.effective_at, "effective_at")
        _require_aware(self.known_at, "known_at")


@dataclass(frozen=True, slots=True)
class UncertaintyMetadata:
    """Evidence metadata only; this module does not invent uncertainty.

    The default truthfully says that uncertainty has not been estimated.  A
    future fitted model may attach externally calculated standard deviations,
    but it must name their source.  The score grid remains a point prediction;
    no unsupported posterior sampling is performed here.
    """

    status: UncertaintyStatus = "not_estimated"
    strength_std: float | None = None
    log_total_goals_std: float | None = None
    strength_tempo_correlation: float | None = None
    source: str | None = None
    sample_count: int | None = None

    def __post_init__(self) -> None:
        if self.status not in ("not_estimated", "externally_supplied"):
            raise ValueError(f"unsupported uncertainty status: {self.status}")
        for value, name in (
            (self.strength_std, "strength_std"),
            (self.log_total_goals_std, "log_total_goals_std"),
        ):
            if value is not None:
                _require_finite(value, name)
                if value < 0.0:
                    raise ValueError(f"{name} must be non-negative")
        if self.strength_tempo_correlation is not None:
            _require_finite(self.strength_tempo_correlation, "strength_tempo_correlation")
            if not -1.0 <= self.strength_tempo_correlation <= 1.0:
                raise ValueError("strength_tempo_correlation must be within [-1, 1]")
            if self.strength_std is None or self.log_total_goals_std is None:
                raise ValueError("strength_tempo_correlation requires both standard deviations")
        if self.sample_count is not None and self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        has_estimate = self.strength_std is not None or self.log_total_goals_std is not None
        if self.status == "not_estimated":
            if (
                has_estimate
                or self.strength_tempo_correlation is not None
                or self.source is not None
                or self.sample_count is not None
            ):
                raise ValueError("not_estimated uncertainty cannot contain estimates")
        elif not has_estimate or not self.source or not self.source.strip():
            raise ValueError("externally_supplied uncertainty needs an estimate and source")


NO_UNCERTAINTY = UncertaintyMetadata()


@dataclass(frozen=True, slots=True)
class LatentMatchState:
    """Orthogonal strength and tempo state for one fixture.

    ``strength_log_ratio`` is a home-relative log goal-rate ratio.  Zero means
    an equal goal split.  ``log_total_goals`` is the log of the expected match
    total.  Both are unconstrained real-valued coordinates suitable for later
    model components and blending.
    """

    context: MatchContext
    strength_log_ratio: float
    log_total_goals: float
    rho: float = 0.0
    uncertainty: UncertaintyMetadata = NO_UNCERTAINTY
    model_version: str = "fw-vnext-core-v0"
    provenance: tuple[StateProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, MatchContext):
            raise TypeError("context must be a MatchContext")
        if not isinstance(self.uncertainty, UncertaintyMetadata):
            raise TypeError("uncertainty must be UncertaintyMetadata")
        _require_finite(self.strength_log_ratio, "strength_log_ratio")
        _require_finite(self.log_total_goals, "log_total_goals")
        _require_finite(self.rho, "rho")
        try:
            total = math.exp(self.log_total_goals)
        except OverflowError as exc:
            raise ValueError("log_total_goals produces a non-finite total") from exc
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("log_total_goals must produce a positive finite total")
        if not self.model_version or not self.model_version.strip():
            raise ValueError("model_version must not be empty")
        if len(self.model_version) > 40:
            raise ValueError("model_version must fit the 40-character persistence field")
        immutable_provenance = tuple(self.provenance)
        if any(not isinstance(item, StateProvenance) for item in immutable_provenance):
            raise TypeError("provenance must contain StateProvenance values")
        for item in immutable_provenance:
            for timestamp, name in (
                (item.effective_at, "effective_at"),
                (item.known_at, "known_at"),
            ):
                if timestamp > self.context.features_as_of:
                    raise ValueError(f"provenance {name} is after the prediction cutoff")
                if (
                    self.context.kickoff_utc is not None
                    and timestamp > self.context.kickoff_utc
                ):
                    raise ValueError(f"provenance {name} is after kickoff")
        object.__setattr__(self, "provenance", immutable_provenance)

    @property
    def total_expected_goals(self) -> float:
        """Expected total goals; controlled only by the tempo coordinate."""
        return math.exp(self.log_total_goals)

    @property
    def home_goal_share(self) -> float:
        """Stable logistic transform of strength into the home goal share."""
        if self.strength_log_ratio >= 0.0:
            z = math.exp(-self.strength_log_ratio)
            return 1.0 / (1.0 + z)
        z = math.exp(self.strength_log_ratio)
        return z / (1.0 + z)

    @property
    def expected_goals(self) -> tuple[float, float]:
        """Return ``(lambda_home, lambda_away)`` from the two latent axes."""
        total = self.total_expected_goals
        home = total * self.home_goal_share
        return home, total - home

    @classmethod
    def from_expected_goals(
        cls,
        context: MatchContext,
        lambda_home: float,
        lambda_away: float,
        *,
        rho: float = 0.0,
        uncertainty: UncertaintyMetadata = NO_UNCERTAINTY,
        model_version: str = "fw-vnext-core-v0",
        provenance: tuple[StateProvenance, ...] = (),
    ) -> "LatentMatchState":
        """Losslessly re-express a positive lambda pair in latent coordinates."""
        _require_finite(lambda_home, "lambda_home")
        _require_finite(lambda_away, "lambda_away")
        if lambda_home <= 0.0 or lambda_away <= 0.0:
            raise ValueError("expected goals must both be positive")
        return cls(
            context=context,
            strength_log_ratio=math.log(lambda_home / lambda_away),
            log_total_goals=math.log(lambda_home + lambda_away),
            rho=rho,
            uncertainty=uncertainty,
            model_version=model_version,
            provenance=provenance,
        )


def state_from_elo_strength_and_tempo(
    context: MatchContext,
    elo_home: float,
    elo_away: float,
    *,
    total_expected_goals: float,
    beta: float = ELO_TO_GOALS_BETA,
    home_advantage_elo: float = 0.0,
    rho: float = 0.0,
    uncertainty: UncertaintyMetadata = NO_UNCERTAINTY,
    model_version: str = "fw-vnext-orthogonal-v0",
) -> LatentMatchState:
    """Create a state whose Elo strength and supplied tempo cannot interfere.

    The ``2 * beta`` coefficient preserves the legacy Elo model's home/away
    lambda ratio.  Unlike that legacy exponential pair, however, the caller's
    ``total_expected_goals`` remains exactly fixed for every strength value.
    """
    for value, name in (
        (elo_home, "elo_home"),
        (elo_away, "elo_away"),
        (total_expected_goals, "total_expected_goals"),
        (beta, "beta"),
        (home_advantage_elo, "home_advantage_elo"),
    ):
        _require_finite(value, name)
    if total_expected_goals <= 0.0:
        raise ValueError("total_expected_goals must be positive")
    effective_gap = (elo_home + home_advantage_elo) - elo_away
    return LatentMatchState(
        context=context,
        strength_log_ratio=2.0 * beta * effective_gap,
        log_total_goals=math.log(total_expected_goals),
        rho=rho,
        uncertainty=uncertainty,
        model_version=model_version,
    )


@dataclass(frozen=True, slots=True)
class WinDrawLoss:
    home: float
    draw: float
    away: float

    def as_tuple(self) -> tuple[float, float, float]:
        return self.home, self.draw, self.away


@dataclass(frozen=True, slots=True)
class GoalMarkets:
    """Common goal markets marginalized from a single normalized score grid."""

    home_to_score: float
    home_two_plus: float
    home_three_plus: float
    away_to_score: float
    away_two_plus: float
    away_three_plus: float
    over_1_5: float
    over_2_5: float
    over_3_5: float
    btts_yes: float

    @property
    def btts_no(self) -> float:
        return 1.0 - self.btts_yes


@dataclass(frozen=True, slots=True)
class ExactScoreProbability:
    home: int
    away: int
    probability: float


@dataclass(frozen=True, slots=True)
class DistributionCalibration:
    """Provenance needed to reproduce a coherently calibrated score grid."""

    artifact_id: str
    target_wdl: WinDrawLoss
    method: str = "outcome_class_raking"

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.artifact_id.strip():
            raise ValueError("calibration artifact_id must not be empty")
        if not isinstance(self.target_wdl, WinDrawLoss):
            raise TypeError("calibration target_wdl must be WinDrawLoss")
        values = self.target_wdl.as_tuple()
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("calibration target W/D/L must be finite and non-negative")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("calibration target W/D/L must sum to one")


@dataclass(frozen=True, slots=True)
class ScoreDistribution:
    """An immutable, normalized Dixon-Coles score distribution.

    All W/D/L, total-goals, BTTS and exact-score answers below are marginals of
    ``grid``.  There is no second probability path that can drift out of sync.
    """

    state: LatentMatchState
    grid: tuple[tuple[float, ...], ...]
    calibration: DistributionCalibration | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, LatentMatchState):
            raise TypeError("state must be a LatentMatchState")
        if self.calibration is not None and not isinstance(
            self.calibration, DistributionCalibration
        ):
            raise TypeError("calibration must be DistributionCalibration or None")
        immutable_grid = tuple(tuple(float(cell) for cell in row) for row in self.grid)
        object.__setattr__(self, "grid", immutable_grid)
        if not immutable_grid or any(len(row) != len(immutable_grid) for row in immutable_grid):
            raise ValueError("score grid must be a non-empty square matrix")
        cells = [cell for row in immutable_grid for cell in row]
        if any(not math.isfinite(cell) or cell < 0.0 for cell in cells):
            raise ValueError("score grid cells must be finite and non-negative")
        if not math.isclose(sum(cells), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("score grid must be normalized")
        if self.calibration is not None:
            if any(
                not math.isclose(observed, target, rel_tol=0.0, abs_tol=1e-12)
                for observed, target in zip(
                    self.wdl.as_tuple(), self.calibration.target_wdl.as_tuple()
                )
            ):
                raise ValueError("calibration target W/D/L does not match the score grid")

    @classmethod
    def from_state(
        cls, state: LatentMatchState, *, max_goals: int = MAX_GOALS
    ) -> "ScoreDistribution":
        """Build and normalize the existing Dixon-Coles grid exactly once."""
        if max_goals < 1 or max_goals > _MAX_GRID_GOALS:
            raise ValueError(
                f"max_goals must be within [1, {_MAX_GRID_GOALS}], got {max_goals}"
            )
        lambda_home, lambda_away = state.expected_goals
        for value, name in ((lambda_home, "lambda_home"), (lambda_away, "lambda_away")):
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive, got {value}")
            # poisson_pmf evaluates lam ** max_goals; probe the exponent rather
            # than the power so the guard cannot overflow while checking.
            if max_goals * math.log(value) > 709.0:
                raise ValueError(
                    f"{name}={value} overflows the score grid at max_goals={max_goals}"
                )
        tau = (
            1.0 - lambda_home * lambda_away * state.rho,
            1.0 + lambda_home * state.rho,
            1.0 + lambda_away * state.rho,
            1.0 - state.rho,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in tau):
            raise ValueError("rho produces an invalid Dixon-Coles low-score multiplier")
        try:
            raw = score_matrix(lambda_home, lambda_away, max_goals=max_goals, rho=state.rho)
        except OverflowError as exc:
            raise ValueError(
                f"score grid overflows for lambdas ({lambda_home}, {lambda_away}) "
                f"at max_goals={max_goals}"
            ) from exc
        cleaned = [
            [cell if math.isfinite(cell) and cell > 0.0 else 0.0 for cell in row]
            for row in raw
        ]
        total = sum(sum(row) for row in cleaned)
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("degenerate score grid: non-positive total mass")
        grid = tuple(tuple(cell / total for cell in row) for row in cleaned)
        return cls(state=state, grid=grid)

    @property
    def context(self) -> MatchContext:
        return self.state.context

    @property
    def max_goals(self) -> int:
        return len(self.grid) - 1

    @property
    def expected_goals(self) -> tuple[float, float]:
        """Goal means of this normalized (and possibly calibrated) grid."""
        return self.grid_expected_goals

    @property
    def grid_expected_goals(self) -> tuple[float, float]:
        """Marginal home/away goal means computed from the published grid."""
        home = sum(
            h * self.grid[h][a]
            for h in range(len(self.grid))
            for a in range(len(self.grid))
        )
        away = sum(
            a * self.grid[h][a]
            for h in range(len(self.grid))
            for a in range(len(self.grid))
        )
        return home, away

    @property
    def latent_expected_goals(self) -> tuple[float, float]:
        """Untruncated Poisson lambdas that generated the original raw grid."""
        return self.state.expected_goals

    @property
    def uncertainty(self) -> UncertaintyMetadata:
        return self.state.uncertainty

    @property
    def provenance(self) -> tuple[StateProvenance, ...]:
        return self.state.provenance

    @property
    def wdl(self) -> WinDrawLoss:
        home = draw = away = 0.0
        for h, row in enumerate(self.grid):
            for a, probability in enumerate(row):
                if h > a:
                    home += probability
                elif h == a:
                    draw += probability
                else:
                    away += probability
        return WinDrawLoss(home=home, draw=draw, away=away)

    def team_goals_at_least(self, side: Side, goals: int) -> float:
        if side not in ("home", "away"):
            raise ValueError("side must be 'home' or 'away'")
        if goals < 0:
            raise ValueError("goals must be non-negative")
        if side == "home":
            return sum(
                self.grid[h][a]
                for h in range(goals, len(self.grid))
                for a in range(len(self.grid))
            )
        return sum(
            self.grid[h][a]
            for h in range(len(self.grid))
            for a in range(goals, len(self.grid))
        )

    def total_goals_over(self, line: float) -> float:
        _require_finite(line, "line")
        return sum(
            self.grid[h][a]
            for h in range(len(self.grid))
            for a in range(len(self.grid))
            if h + a > line
        )

    @property
    def btts_yes(self) -> float:
        return sum(
            self.grid[h][a]
            for h in range(1, len(self.grid))
            for a in range(1, len(self.grid))
        )

    @property
    def goal_markets(self) -> GoalMarkets:
        return GoalMarkets(
            home_to_score=self.team_goals_at_least("home", 1),
            home_two_plus=self.team_goals_at_least("home", 2),
            home_three_plus=self.team_goals_at_least("home", 3),
            away_to_score=self.team_goals_at_least("away", 1),
            away_two_plus=self.team_goals_at_least("away", 2),
            away_three_plus=self.team_goals_at_least("away", 3),
            over_1_5=self.total_goals_over(1.5),
            over_2_5=self.total_goals_over(2.5),
            over_3_5=self.total_goals_over(3.5),
            btts_yes=self.btts_yes,
        )

    def exact_score_probability(self, home: int, away: int) -> float:
        if home < 0 or away < 0 or home > self.max_goals or away > self.max_goals:
            return 0.0
        return self.grid[home][away]

    def correct_scores(self, top_n: int | None = None) -> tuple[ExactScoreProbability, ...]:
        if top_n is not None and top_n < 0:
            raise ValueError("top_n must be non-negative")
        scores = [
            ExactScoreProbability(home=h, away=a, probability=self.grid[h][a])
            for h in range(len(self.grid))
            for a in range(len(self.grid))
        ]
        scores.sort(key=lambda item: (-item.probability, item.home, item.away))
        if top_n is not None:
            scores = scores[:top_n]
        return tuple(scores)

    @property
    def most_likely_score(self) -> ExactScoreProbability:
        home, away, probability = most_likely_score(self.grid)
        return ExactScoreProbability(home=home, away=away, probability=probability)

    def calibrated_to_wdl(
        self,
        target: WinDrawLoss | tuple[float, float, float],
        *,
        calibrator_artifact_id: str,
    ) -> "ScoreDistribution":
        """Return a coherently W/D/L-calibrated copy of this distribution."""
        return calibrate_distribution_to_wdl(
            self, target, calibrator_artifact_id=calibrator_artifact_id
        )


def calibrate_distribution_to_wdl(
    distribution: ScoreDistribution,
    target: WinDrawLoss | tuple[float, float, float],
    *,
    calibrator_artifact_id: str,
) -> ScoreDistribution:
    """Calibrate W/D/L while retaining one coherent score distribution.

    Every score cell is multiplied by ``target_outcome / raw_outcome`` for its
    result class, then the whole grid is normalized.  The resulting W/D/L
    marginal therefore equals ``target`` while totals, BTTS and exact scores
    remain honest marginals of that same adjusted grid.  This replaces the
    contradictory pattern of calibrating a separate W/D/L triple after the score
    grid has already been built.  The target must come from a frozen,
    out-of-fold-fitted calibrator; its required artifact ID is retained because
    a raked grid cannot be reconstructed later from lambdas and rho alone.
    """
    target_wdl = target if isinstance(target, WinDrawLoss) else WinDrawLoss(*target)
    if distribution.calibration is not None:
        raise ValueError("distribution is already calibrated; start from its raw grid")
    calibration = DistributionCalibration(
        artifact_id=calibrator_artifact_id,
        target_wdl=target_wdl,
    )
    target_values = target_wdl.as_tuple()
    if any(not math.isfinite(value) or value < 0.0 for value in target_values):
        raise ValueError("target W/D/L probabilities must be finite and non-negative")
    if not math.isclose(sum(target_values), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("target W/D/L probabilities must sum to one")

    raw = distribution.wdl
    raw_values = raw.as_tuple()
    if target_values == raw_values:
        return ScoreDistribution(
            state=distribution.state,
            grid=distribution.grid,
            calibration=calibration,
        )
    if any(
        raw_value <= 0.0 < target_value
        for raw_value, target_value in zip(raw_values, target_values)
    ):
        raise ValueError("cannot create positive target mass from an empty outcome class")
    ratios = tuple(
        (target_value / raw_value) if raw_value > 0.0 else 0.0
        for raw_value, target_value in zip(raw_values, target_values)
    )

    adjusted: list[list[float]] = []
    for h, row in enumerate(distribution.grid):
        adjusted_row: list[float] = []
        for a, probability in enumerate(row):
            outcome_index = 0 if h > a else 1 if h == a else 2
            adjusted_row.append(probability * ratios[outcome_index])
        adjusted.append(adjusted_row)
    total = sum(sum(row) for row in adjusted)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("calibrated score grid has non-positive total mass")
    normalized = tuple(tuple(cell / total for cell in row) for row in adjusted)
    return ScoreDistribution(
        state=distribution.state,
        grid=normalized,
        calibration=calibration,
    )


@dataclass(frozen=True, slots=True)
class LegacyPoissonEloAdapter:
    """Compatibility boundary around the unchanged production engine.

    ``prediction`` delegates to today's implementation, preserving its
    calibration and headline-score rules.  ``raw_distribution`` re-expresses the
    same legacy lambdas in the vNext immutable contracts for shadow comparison.
    """

    base: float = BASE_GOALS
    beta: float = ELO_TO_GOALS_BETA
    home_advantage_elo: float = 0.0
    rho: float = 0.0
    temperature: float = 1.0
    calibrator: Mapping[str, object] | None = None
    model_version: str = "fw-legacy-poisson-elo-adapter-v0"

    def __post_init__(self) -> None:
        for value, name in (
            (self.base, "base"),
            (self.beta, "beta"),
            (self.home_advantage_elo, "home_advantage_elo"),
            (self.rho, "rho"),
            (self.temperature, "temperature"),
        ):
            _require_finite(value, name)
        if self.base <= 0.0:
            raise ValueError("base must be positive")
        if self.temperature <= 0.0:
            raise ValueError("temperature must be positive")
        if not self.model_version or len(self.model_version) > 40:
            raise ValueError("model_version must contain 1 to 40 characters")

    def expected_goals(
        self,
        elo_home: float,
        elo_away: float,
        *,
        atk_home: float = 0.0,
        def_home: float = 0.0,
        atk_away: float = 0.0,
        def_away: float = 0.0,
    ) -> tuple[float, float]:
        return expected_goals_from_elo(
            elo_home,
            elo_away,
            self.home_advantage_elo,
            self.base,
            self.beta,
            atk_home=atk_home,
            def_home=def_home,
            atk_away=atk_away,
            def_away=def_away,
        )

    def state(
        self,
        context: MatchContext,
        elo_home: float,
        elo_away: float,
        *,
        atk_home: float = 0.0,
        def_home: float = 0.0,
        atk_away: float = 0.0,
        def_away: float = 0.0,
        uncertainty: UncertaintyMetadata = NO_UNCERTAINTY,
    ) -> LatentMatchState:
        lambda_home, lambda_away = self.expected_goals(
            elo_home,
            elo_away,
            atk_home=atk_home,
            def_home=def_home,
            atk_away=atk_away,
            def_away=def_away,
        )
        return LatentMatchState.from_expected_goals(
            context,
            lambda_home,
            lambda_away,
            rho=self.rho,
            uncertainty=uncertainty,
            model_version=self.model_version,
        )

    def raw_distribution(
        self,
        context: MatchContext,
        elo_home: float,
        elo_away: float,
        *,
        max_goals: int = MAX_GOALS,
        atk_home: float = 0.0,
        def_home: float = 0.0,
        atk_away: float = 0.0,
        def_away: float = 0.0,
        uncertainty: UncertaintyMetadata = NO_UNCERTAINTY,
    ) -> ScoreDistribution:
        """Return the uncalibrated legacy grid in vNext contracts.

        This intentionally differs from ``prediction`` when the legacy adapter
        has a scalar/vector W/D/L calibrator.  The explicit ``raw_`` name keeps
        callers from mistaking it for calibrated serving parity.
        """
        state = self.state(
            context,
            elo_home,
            elo_away,
            atk_home=atk_home,
            def_home=def_home,
            atk_away=atk_away,
            def_away=def_away,
            uncertainty=uncertainty,
        )
        return ScoreDistribution.from_state(state, max_goals=max_goals)

    def prediction(
        self,
        elo_home: float,
        elo_away: float,
        *,
        atk_home: float = 0.0,
        def_home: float = 0.0,
        atk_away: float = 0.0,
        def_away: float = 0.0,
    ) -> MatchPrediction:
        """Return the current public result through the compatibility seam."""
        calibrator = dict(self.calibrator) if self.calibrator is not None else None
        return predict_match(
            elo_home,
            elo_away,
            home_adv=self.home_advantage_elo,
            base=self.base,
            beta=self.beta,
            rho=self.rho,
            temperature=self.temperature,
            calibrator=calibrator,
            atk_home=atk_home,
            def_home=def_home,
            atk_away=atk_away,
            def_away=def_away,
        )


def headline_prediction_from_distribution(distribution: ScoreDistribution) -> MatchPrediction:
    """Project a coherent vNext grid into the legacy response shape.

    This intentionally applies no 1X2-only calibration: doing so would make the
    published outcome probabilities disagree with the score and goal markets.
    A raked distribution is rejected because the legacy DTO stores only lambdas,
    rho-less W/D/L and one score; it cannot persist the calibrated grid or its
    reconstruction artifact without losing coherence.
    """
    if distribution.calibration is not None:
        raise ValueError(
            "legacy MatchPrediction cannot represent a calibrated score grid; "
            "persist ScoreDistribution and its calibration metadata"
        )
    wdl = distribution.wdl
    if abs(wdl.home - wdl.away) <= DRAW_HEADLINE_BAND:
        score = distribution.most_likely_score
    else:
        outcome = "home" if wdl.home > wdl.away else "away"
        home, away, probability = most_likely_score(distribution.grid, outcome)
        score = ExactScoreProbability(home=home, away=away, probability=probability)
    lambda_home, lambda_away = distribution.latent_expected_goals
    return MatchPrediction(
        prob_home_win=wdl.home,
        prob_draw=wdl.draw,
        prob_away_win=wdl.away,
        score_home=score.home,
        score_away=score.away,
        score_prob=score.probability,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
    )


def normalized_dixon_coles_distribution(
    state: LatentMatchState, *, max_goals: int = MAX_GOALS
) -> ScoreDistribution:
    """Named functional entry point for callers that do not use class methods."""
    return ScoreDistribution.from_state(state, max_goals=max_goals)
