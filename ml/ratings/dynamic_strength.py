"""Leak-safe dynamic team strength and match-tempo states.

The model keeps two deliberately separate coordinates for every team:

``strength``
    Changes the share of expected goals assigned to each side.

``tempo``
    Changes only the expected total number of goals in the match.

For a fixture the coordinates are combined as::

    s = strength_home - strength_away + home_advantage
    t = base_log_total + (tempo_home + tempo_away) / 2
    lambda_home = exp(t) * sigmoid(s)
    lambda_away = exp(t) * (1 - sigmoid(s))

This is a coherent independent-Poisson likelihood parameterization.  Its useful
property is that changing strength cannot change the expected total and changing
tempo cannot change the home/away goal share.

This is an unfitted online-state primitive, not a Bayesian posterior model.  The
reported marginal variances are approximate information trackers: they do not
model covariance created when two teams share an update.  Callers must seed or
replay the state before treating it as a challenger to a fitted production model.

The state machine is intentionally strict about match identity and chronology: a
result can only be recorded for a previously issued prediction, and result times
must advance each affected team's state.  Multiple future fixtures may still be
predicted at once.  Their forecasts remain frozen while later online updates are
applied cumulatively to each team's newest state.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ml.models.vnext import LatentMatchState, MatchContext


SNAPSHOT_SCHEMA_VERSION = 1
GLOBAL_GROUP = "__global__"


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


@dataclass(frozen=True, slots=True)
class GroupPrior:
    """Parent state used for cold starts and long-term mean reversion."""

    strength_mean: float = 0.0
    tempo_mean: float = 0.0
    strength_variance: float = 1.0
    tempo_variance: float = 0.25

    def __post_init__(self) -> None:
        for value, name in (
            (self.strength_mean, "strength_mean"),
            (self.tempo_mean, "tempo_mean"),
            (self.strength_variance, "strength_variance"),
            (self.tempo_variance, "tempo_variance"),
        ):
            _finite(value, name)
        if self.strength_variance <= 0.0 or self.tempo_variance <= 0.0:
            raise ValueError("prior variances must be positive")


@dataclass(frozen=True, slots=True)
class DynamicModelConfig:
    """Conservative online-update and numerical-safety settings."""

    base_log_total: float = math.log(2.6)
    home_advantage: float = 0.0
    strength_learning_rate: float = 0.08
    tempo_learning_rate: float = 0.08
    information_scale: float = 1.0
    decay_half_life_days: float = 180.0
    max_abs_team_strength: float = 3.0
    max_abs_team_tempo: float = 1.5
    max_abs_gradient: float = 8.0
    min_log_total: float = math.log(0.25)
    max_log_total: float = math.log(8.0)
    min_variance: float = 1e-4
    max_goals: int = 30

    def __post_init__(self) -> None:
        finite_fields = (
            "base_log_total",
            "home_advantage",
            "strength_learning_rate",
            "tempo_learning_rate",
            "information_scale",
            "decay_half_life_days",
            "max_abs_team_strength",
            "max_abs_team_tempo",
            "max_abs_gradient",
            "min_log_total",
            "max_log_total",
            "min_variance",
        )
        for name in finite_fields:
            _finite(getattr(self, name), name)
        for name in (
            "strength_learning_rate",
            "tempo_learning_rate",
            "information_scale",
            "decay_half_life_days",
            "max_abs_team_strength",
            "max_abs_team_tempo",
            "max_abs_gradient",
            "min_variance",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.min_log_total >= self.max_log_total:
            raise ValueError("min_log_total must be smaller than max_log_total")
        if isinstance(self.max_goals, bool) or not isinstance(self.max_goals, int):
            raise ValueError("max_goals must be an integer")
        if self.max_goals < 1:
            raise ValueError("max_goals must be positive")


@dataclass(frozen=True, slots=True)
class TeamState:
    """One team's online means, approximate variances and evidence count."""

    strength: float
    tempo: float
    strength_variance: float
    tempo_variance: float
    evidence_count: int = 0
    last_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.strength, "strength"),
            (self.tempo, "tempo"),
            (self.strength_variance, "strength_variance"),
            (self.tempo_variance, "tempo_variance"),
        ):
            _finite(value, name)
        if self.strength_variance <= 0.0 or self.tempo_variance <= 0.0:
            raise ValueError("state variances must be positive")
        if isinstance(self.evidence_count, bool) or self.evidence_count < 0:
            raise ValueError("evidence_count must be a non-negative integer")
        if not isinstance(self.evidence_count, int):
            raise ValueError("evidence_count must be a non-negative integer")
        if self.last_updated_at is not None:
            _aware(self.last_updated_at, "last_updated_at")


@dataclass(frozen=True, slots=True)
class DynamicPrediction:
    """Prematch latent prediction retained until the result is observed."""

    match_id: str
    home_team_id: str
    away_team_id: str
    predicted_at: datetime
    strength_log_ratio: float
    log_total_goals: float
    lambda_home: float
    lambda_away: float
    strength_std: float
    log_total_goals_std: float
    evidence_count: int
    home_state: TeamState
    away_state: TeamState

    def __post_init__(self) -> None:
        _nonempty(self.match_id, "match_id")
        _nonempty(self.home_team_id, "home_team_id")
        _nonempty(self.away_team_id, "away_team_id")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must differ")
        _aware(self.predicted_at, "predicted_at")
        for value, name in (
            (self.strength_log_ratio, "strength_log_ratio"),
            (self.log_total_goals, "log_total_goals"),
            (self.lambda_home, "lambda_home"),
            (self.lambda_away, "lambda_away"),
            (self.strength_std, "strength_std"),
            (self.log_total_goals_std, "log_total_goals_std"),
        ):
            _finite(value, name)
        if self.lambda_home <= 0.0 or self.lambda_away <= 0.0:
            raise ValueError("expected goal rates must be positive")
        if self.strength_std < 0.0 or self.log_total_goals_std < 0.0:
            raise ValueError("prediction standard deviations must be non-negative")
        if isinstance(self.evidence_count, bool) or not isinstance(self.evidence_count, int):
            raise ValueError("evidence_count must be a non-negative integer")
        if self.evidence_count < 0:
            raise ValueError("evidence_count must be a non-negative integer")
        if not math.isclose(
            self.lambda_home + self.lambda_away,
            math.exp(self.log_total_goals),
            rel_tol=1e-12,
        ):
            raise ValueError("goal rates are inconsistent with log_total_goals")
        if not math.isclose(
            math.log(self.lambda_home / self.lambda_away),
            self.strength_log_ratio,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("goal rates are inconsistent with strength_log_ratio")

    @property
    def total_expected_goals(self) -> float:
        return self.lambda_home + self.lambda_away

    def to_vnext(
        self,
        context: "MatchContext",
        *,
        rho: float = 0.0,
        model_version: str = "finalwhistle-dynamic-strength-tempo-v0",
    ) -> "LatentMatchState":
        """Adapt to the vNext core without making this ratings module depend on it."""
        from ml.models.vnext import LatentMatchState, UncertaintyMetadata

        if (
            context.match_id != self.match_id
            or context.home_team_id != self.home_team_id
            or context.away_team_id != self.away_team_id
        ):
            raise ValueError("vNext context identity does not match the frozen prediction")
        if (
            context.features_as_of.astimezone(timezone.utc)
            != self.predicted_at.astimezone(timezone.utc)
        ):
            raise ValueError(
                "vNext context features_as_of does not match the frozen prediction cutoff"
            )
        uncertainty = UncertaintyMetadata(
            status="externally_supplied",
            strength_std=self.strength_std,
            log_total_goals_std=self.log_total_goals_std,
            source="approximate-online-state",
            sample_count=self.evidence_count or None,
        )
        return LatentMatchState(
            context=context,
            strength_log_ratio=self.strength_log_ratio,
            log_total_goals=self.log_total_goals,
            rho=rho,
            uncertainty=uncertainty,
            model_version=model_version,
        )


class DynamicStrengthTempoModel:
    """Online hierarchical state model with strict predict-then-update ordering."""

    def __init__(
        self,
        config: DynamicModelConfig | None = None,
        *,
        group_priors: Mapping[str, GroupPrior] | None = None,
        team_groups: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or DynamicModelConfig()
        supplied_priors = dict(group_priors or {})
        if GLOBAL_GROUP in supplied_priors:
            global_prior = supplied_priors[GLOBAL_GROUP]
        else:
            global_prior = GroupPrior()
        self._group_priors: dict[str, GroupPrior] = {
            GLOBAL_GROUP: global_prior,
            **supplied_priors,
        }
        for group_id, prior in self._group_priors.items():
            _nonempty(group_id, "group_id")
            if not isinstance(prior, GroupPrior):
                raise ValueError("group_priors values must be GroupPrior instances")
            if abs(prior.strength_mean) > self.config.max_abs_team_strength:
                raise ValueError("group strength mean exceeds the configured state cap")
            if abs(prior.tempo_mean) > self.config.max_abs_team_tempo:
                raise ValueError("group tempo mean exceeds the configured state cap")

        self._team_groups = dict(team_groups or {})
        for team_id, group_id in self._team_groups.items():
            _nonempty(team_id, "team_id")
            _nonempty(group_id, "group_id")
            if group_id not in self._group_priors:
                raise ValueError(f"unknown group prior: {group_id}")

        self._teams: dict[str, TeamState] = {}
        self._pending: dict[str, DynamicPrediction] = {}
        self._completed_match_ids: set[str] = set()

    @property
    def pending_match_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))

    @property
    def completed_match_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._completed_match_ids))

    def _prior_for(self, team_id: str) -> GroupPrior:
        group_id = self._team_groups.get(team_id, GLOBAL_GROUP)
        return self._group_priors[group_id]

    def _cold_state(self, team_id: str) -> TeamState:
        prior = self._prior_for(team_id)
        return TeamState(
            strength=prior.strength_mean,
            tempo=prior.tempo_mean,
            strength_variance=prior.strength_variance,
            tempo_variance=prior.tempo_variance,
        )

    def _project(self, team_id: str, as_of: datetime) -> TeamState:
        state = self._teams.get(team_id, self._cold_state(team_id))
        if state.last_updated_at is None:
            return state
        if as_of < state.last_updated_at:
            raise ValueError(
                f"as_of precedes the latest available state for team {team_id}"
            )

        elapsed_days = (as_of - state.last_updated_at).total_seconds() / 86_400.0
        weight = math.exp(-math.log(2.0) * elapsed_days / self.config.decay_half_life_days)
        prior = self._prior_for(team_id)

        # An Ornstein-Uhlenbeck-style projection: means return to the parent and
        # posterior certainty dissipates until it reaches the parent variance.
        strength_variance = prior.strength_variance - weight * weight * (
            prior.strength_variance - state.strength_variance
        )
        tempo_variance = prior.tempo_variance - weight * weight * (
            prior.tempo_variance - state.tempo_variance
        )
        return TeamState(
            strength=prior.strength_mean + weight * (state.strength - prior.strength_mean),
            tempo=prior.tempo_mean + weight * (state.tempo - prior.tempo_mean),
            strength_variance=max(self.config.min_variance, strength_variance),
            tempo_variance=max(self.config.min_variance, tempo_variance),
            evidence_count=state.evidence_count,
            last_updated_at=as_of,
        )

    def team_state(self, team_id: str, as_of: datetime) -> TeamState:
        """Return a non-mutating state projection at an information cutoff."""
        team_id = _nonempty(team_id, "team_id")
        as_of = _aware(as_of, "as_of")
        return self._project(team_id, as_of)

    def predict(
        self,
        match_id: str,
        home_team_id: str,
        away_team_id: str,
        as_of: datetime,
        *,
        home_advantage: float | None = None,
    ) -> DynamicPrediction:
        """Issue and register a ticket that must precede a later result update."""
        match_id = _nonempty(match_id, "match_id")
        if match_id in self._pending or match_id in self._completed_match_ids:
            raise ValueError(f"match_id has already been used: {match_id}")
        prediction = self.forecast(
            match_id,
            home_team_id,
            away_team_id,
            as_of,
            home_advantage=home_advantage,
        )
        self._pending[match_id] = prediction
        return prediction

    def forecast(
        self,
        match_id: str,
        home_team_id: str,
        away_team_id: str,
        as_of: datetime,
        *,
        home_advantage: float | None = None,
    ) -> DynamicPrediction:
        """Return a non-registering forecast for repeat production refreshes.

        Unlike :meth:`predict`, this does not create a result-update ticket and
        never changes pending, completed or team state.  The same scheduled
        fixture can therefore be refreshed repeatedly as its information cutoff
        advances.  Historical replay must use ``predict`` so update ordering is
        still enforced.
        """
        match_id = _nonempty(match_id, "match_id")
        home_team_id = _nonempty(home_team_id, "home_team_id")
        away_team_id = _nonempty(away_team_id, "away_team_id")
        as_of = _aware(as_of, "as_of")
        if home_team_id == away_team_id:
            raise ValueError("home_team_id and away_team_id must differ")

        advantage = self.config.home_advantage if home_advantage is None else _finite(
            home_advantage, "home_advantage"
        )
        home = self._project(home_team_id, as_of)
        away = self._project(away_team_id, as_of)
        strength = _clamp(
            home.strength - away.strength + advantage,
            -2.0 * self.config.max_abs_team_strength,
            2.0 * self.config.max_abs_team_strength,
        )
        log_total = _clamp(
            self.config.base_log_total + 0.5 * (home.tempo + away.tempo),
            self.config.min_log_total,
            self.config.max_log_total,
        )
        total = math.exp(log_total)
        home_share = _sigmoid(strength)
        prediction = DynamicPrediction(
            match_id=match_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            predicted_at=as_of,
            strength_log_ratio=strength,
            log_total_goals=log_total,
            lambda_home=total * home_share,
            lambda_away=total * (1.0 - home_share),
            strength_std=math.sqrt(home.strength_variance + away.strength_variance),
            log_total_goals_std=math.sqrt(
                0.25 * (home.tempo_variance + away.tempo_variance)
            ),
            evidence_count=home.evidence_count + away.evidence_count,
            home_state=home,
            away_state=away,
        )
        return prediction

    @staticmethod
    def _approximate_variance_update(
        variance: float, information: float, scale: float, floor: float
    ) -> float:
        precision = (1.0 / variance) + scale * max(0.0, information)
        return max(floor, 1.0 / precision)

    def update(
        self,
        match_id: str,
        goals_home: int,
        goals_away: int,
        observed_at: datetime,
    ) -> tuple[TeamState, TeamState]:
        """Incorporate a result using only its registered prematch forecast.

        The gradients are from the same Poisson rates returned by ``predict``:
        ``d log L / ds = goals_home - total_goals * home_share`` and
        ``d log L / dt = total_goals - expected_total``.
        """
        match_id = _nonempty(match_id, "match_id")
        observed_at = _aware(observed_at, "observed_at")
        if match_id not in self._pending:
            if match_id in self._completed_match_ids:
                raise ValueError(f"result has already been recorded: {match_id}")
            raise ValueError("cannot update a match before predicting it")
        for value, name in ((goals_home, "goals_home"), (goals_away, "goals_away")):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < 0 or value > self.config.max_goals:
                raise ValueError(f"{name} must be between 0 and {self.config.max_goals}")

        prediction = self._pending[match_id]
        if observed_at < prediction.predicted_at:
            raise ValueError("observed_at cannot precede the prediction cutoff")

        total_goals = goals_home + goals_away
        expected_total = prediction.total_expected_goals
        home_share = prediction.lambda_home / expected_total
        strength_gradient = goals_home - total_goals * home_share
        tempo_gradient = total_goals - expected_total
        cap = self.config.max_abs_gradient
        strength_gradient = _clamp(strength_gradient, -cap, cap)
        tempo_gradient = _clamp(tempo_gradient, -cap, cap)

        # The ticket's lambdas stay frozen so the likelihood gradient is the one
        # genuinely implied by the published prematch forecast.  The step itself
        # is applied to the latest available team state, preserving learning from
        # any earlier fixture settled since this prediction was issued.
        home = self._project(prediction.home_team_id, observed_at)
        away = self._project(prediction.away_team_id, observed_at)
        strength_step = self.config.strength_learning_rate * strength_gradient
        # Each team contributes 1/2 to match tempo, hence the 1/2 derivative.
        tempo_step = 0.5 * self.config.tempo_learning_rate * tempo_gradient

        strength_information = expected_total * home_share * (1.0 - home_share)
        tempo_information = 0.25 * expected_total
        new_home = TeamState(
            strength=_clamp(
                home.strength + strength_step,
                -self.config.max_abs_team_strength,
                self.config.max_abs_team_strength,
            ),
            tempo=_clamp(
                home.tempo + tempo_step,
                -self.config.max_abs_team_tempo,
                self.config.max_abs_team_tempo,
            ),
            strength_variance=self._approximate_variance_update(
                home.strength_variance,
                strength_information,
                self.config.information_scale,
                self.config.min_variance,
            ),
            tempo_variance=self._approximate_variance_update(
                home.tempo_variance,
                tempo_information,
                self.config.information_scale,
                self.config.min_variance,
            ),
            evidence_count=home.evidence_count + 1,
            last_updated_at=observed_at,
        )
        new_away = TeamState(
            strength=_clamp(
                away.strength - strength_step,
                -self.config.max_abs_team_strength,
                self.config.max_abs_team_strength,
            ),
            tempo=_clamp(
                away.tempo + tempo_step,
                -self.config.max_abs_team_tempo,
                self.config.max_abs_team_tempo,
            ),
            strength_variance=self._approximate_variance_update(
                away.strength_variance,
                strength_information,
                self.config.information_scale,
                self.config.min_variance,
            ),
            tempo_variance=self._approximate_variance_update(
                away.tempo_variance,
                tempo_information,
                self.config.information_scale,
                self.config.min_variance,
            ),
            evidence_count=away.evidence_count + 1,
            last_updated_at=observed_at,
        )

        self._teams[prediction.home_team_id] = new_home
        self._teams[prediction.away_team_id] = new_away
        del self._pending[match_id]
        self._completed_match_ids.add(match_id)
        return new_home, new_away

    @staticmethod
    def _state_snapshot(state: TeamState) -> dict[str, Any]:
        return {
            "strength": state.strength,
            "tempo": state.tempo,
            "strength_variance": state.strength_variance,
            "tempo_variance": state.tempo_variance,
            "evidence_count": state.evidence_count,
            "last_updated_at": (
                state.last_updated_at.isoformat() if state.last_updated_at is not None else None
            ),
        }

    @classmethod
    def _prediction_snapshot(cls, prediction: DynamicPrediction) -> dict[str, Any]:
        return {
            "match_id": prediction.match_id,
            "home_team_id": prediction.home_team_id,
            "away_team_id": prediction.away_team_id,
            "predicted_at": prediction.predicted_at.isoformat(),
            "strength_log_ratio": prediction.strength_log_ratio,
            "log_total_goals": prediction.log_total_goals,
            "lambda_home": prediction.lambda_home,
            "lambda_away": prediction.lambda_away,
            "strength_std": prediction.strength_std,
            "log_total_goals_std": prediction.log_total_goals_std,
            "evidence_count": prediction.evidence_count,
            "home_state": cls._state_snapshot(prediction.home_state),
            "away_state": cls._state_snapshot(prediction.away_state),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable, versioned representation of all state."""
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "config": asdict(self.config),
            "group_priors": {
                group_id: asdict(prior) for group_id, prior in sorted(self._group_priors.items())
            },
            "team_groups": dict(sorted(self._team_groups.items())),
            "teams": {
                team_id: self._state_snapshot(state)
                for team_id, state in sorted(self._teams.items())
            },
            "pending": {
                match_id: self._prediction_snapshot(prediction)
                for match_id, prediction in sorted(self._pending.items())
            },
            "completed_match_ids": sorted(self._completed_match_ids),
        }

    @staticmethod
    def _parse_state(raw: Mapping[str, Any]) -> TeamState:
        timestamp = raw.get("last_updated_at")
        return TeamState(
            strength=raw["strength"],
            tempo=raw["tempo"],
            strength_variance=raw["strength_variance"],
            tempo_variance=raw["tempo_variance"],
            evidence_count=raw.get("evidence_count", 0),
            last_updated_at=datetime.fromisoformat(timestamp) if timestamp is not None else None,
        )

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "DynamicStrengthTempoModel":
        """Restore a model snapshot, rejecting unsupported or inconsistent data."""
        if not isinstance(snapshot, Mapping):
            raise ValueError("snapshot must be a mapping")
        if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported dynamic-state snapshot schema")
        try:
            config = DynamicModelConfig(**dict(snapshot["config"]))
            group_priors = {
                group_id: GroupPrior(**dict(raw))
                for group_id, raw in dict(snapshot["group_priors"]).items()
            }
            model = cls(
                config,
                group_priors=group_priors,
                team_groups=dict(snapshot.get("team_groups", {})),
            )
            model._teams = {
                team_id: cls._parse_state(raw)
                for team_id, raw in dict(snapshot.get("teams", {})).items()
            }
            for match_id, raw in dict(snapshot.get("pending", {})).items():
                prediction = DynamicPrediction(
                    match_id=raw["match_id"],
                    home_team_id=raw["home_team_id"],
                    away_team_id=raw["away_team_id"],
                    predicted_at=datetime.fromisoformat(raw["predicted_at"]),
                    strength_log_ratio=raw["strength_log_ratio"],
                    log_total_goals=raw["log_total_goals"],
                    lambda_home=raw["lambda_home"],
                    lambda_away=raw["lambda_away"],
                    strength_std=raw["strength_std"],
                    log_total_goals_std=raw["log_total_goals_std"],
                    evidence_count=raw["evidence_count"],
                    home_state=cls._parse_state(raw["home_state"]),
                    away_state=cls._parse_state(raw["away_state"]),
                )
                if match_id != prediction.match_id:
                    raise ValueError("pending match key does not match its payload")
                model._pending[match_id] = prediction
            completed = snapshot.get("completed_match_ids", [])
            if not isinstance(completed, list) or any(
                not isinstance(match_id, str) or not match_id for match_id in completed
            ):
                raise ValueError("completed_match_ids must be a list of non-empty strings")
            model._completed_match_ids = set(completed)
            if model._completed_match_ids.intersection(model._pending):
                raise ValueError("a match cannot be both pending and completed")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid dynamic-state snapshot") from exc
        return model

    restore = from_snapshot
