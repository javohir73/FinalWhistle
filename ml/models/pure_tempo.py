"""Frozen, opt-in pure-tempo challenger for the vNext shadow boundary.

The predictor takes the production lambdas as its strength source.  It changes
their sum by a common multiplier while preserving their home/away ratio in the
latent state.  Team tempo values come only from a canonical, versioned artifact
whose training cutoff is checked against every forecast's feature cutoff.

Nothing in this module registers the predictor with production.  A caller must
explicitly place it in a ``VNextShadowSpec``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ml.models.poisson import MAX_GOALS
from ml.models.vnext import LatentMatchState, MatchContext, ScoreDistribution


ARTIFACT_SCHEMA_VERSION = 1
MAX_ARTIFACT_LOG_TEMPO = 20.0


def _finite_float(value: object, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed <= 0.0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO timezone-aware datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timezone-aware datetime string") from exc
    return _aware_utc(parsed, name)


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"artifact JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(value: str) -> object:
    if not isinstance(value, str):
        raise ValueError("artifact_json must be a string snapshot")
    try:
        return json.loads(value, object_pairs_hook=_without_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("artifact_json must contain finite valid JSON") from exc


@dataclass(frozen=True, slots=True)
class FrozenTeamTempoArtifact:
    """Immutable canonical snapshot of fitted team log-tempo adjustments."""

    artifact_version: str
    trained_through: datetime
    global_log_tempo: float = 0.0
    unknown_team_log_tempo: float = 0.0
    team_log_tempos: tuple[tuple[str, float], ...] = ()
    schema_version: int = ARTIFACT_SCHEMA_VERSION
    canonical_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != ARTIFACT_SCHEMA_VERSION
        ):
            raise ValueError(
                f"schema_version must be exactly {ARTIFACT_SCHEMA_VERSION}"
            )
        version = _nonempty(self.artifact_version, "artifact_version")
        trained_through = _aware_utc(self.trained_through, "trained_through")
        global_tempo = _finite_float(self.global_log_tempo, "global_log_tempo")
        unknown_tempo = _finite_float(
            self.unknown_team_log_tempo, "unknown_team_log_tempo"
        )
        normalized_teams: list[tuple[str, float]] = []
        seen: set[str] = set()
        for raw_team_id, raw_tempo in self.team_log_tempos:
            team_id = _nonempty(raw_team_id, "team_log_tempos team id")
            if team_id in seen:
                raise ValueError(f"duplicate team_log_tempos team id: {team_id}")
            seen.add(team_id)
            tempo = _finite_float(raw_tempo, f"team_log_tempos.{team_id}")
            normalized_teams.append((team_id, tempo))
        for value, name in (
            (global_tempo, "global_log_tempo"),
            (unknown_tempo, "unknown_team_log_tempo"),
            *((tempo, f"team_log_tempos.{team_id}") for team_id, tempo in normalized_teams),
        ):
            if abs(value) > MAX_ARTIFACT_LOG_TEMPO:
                raise ValueError(
                    f"{name} exceeds the artifact log-tempo safety bound"
                )

        normalized_teams.sort(key=lambda item: item[0])
        object.__setattr__(self, "artifact_version", version)
        object.__setattr__(self, "trained_through", trained_through)
        object.__setattr__(self, "global_log_tempo", global_tempo)
        object.__setattr__(self, "unknown_team_log_tempo", unknown_tempo)
        object.__setattr__(self, "team_log_tempos", tuple(normalized_teams))
        canonical = json.dumps(
            {
                "artifact_version": version,
                "global_log_tempo": global_tempo,
                "schema_version": self.schema_version,
                "team_log_tempos": dict(normalized_teams),
                "trained_through": trained_through.isoformat(),
                "unknown_team_log_tempo": unknown_tempo,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        object.__setattr__(self, "canonical_json", canonical)

    @classmethod
    def from_json(cls, artifact_json: str) -> "FrozenTeamTempoArtifact":
        parsed = _load_json(artifact_json)
        if not isinstance(parsed, Mapping):
            raise ValueError("artifact_json root must be an object")
        allowed = {
            "schema_version",
            "artifact_version",
            "trained_through",
            "global_log_tempo",
            "unknown_team_log_tempo",
            "team_log_tempos",
        }
        if set(parsed) != allowed:
            missing = sorted(allowed - set(parsed))
            extra = sorted(set(parsed) - allowed)
            raise ValueError(
                f"artifact fields must match schema; missing={missing}, extra={extra}"
            )
        raw_teams = parsed["team_log_tempos"]
        if not isinstance(raw_teams, Mapping):
            raise ValueError("team_log_tempos must be an object")
        return cls(
            schema_version=parsed["schema_version"],
            artifact_version=parsed["artifact_version"],
            trained_through=_parse_aware_utc(
                parsed["trained_through"], "trained_through"
            ),
            global_log_tempo=parsed["global_log_tempo"],
            unknown_team_log_tempo=parsed["unknown_team_log_tempo"],
            team_log_tempos=tuple(raw_teams.items()),
        )

    @classmethod
    def from_mapping(cls, artifact: Mapping[str, object]) -> "FrozenTeamTempoArtifact":
        """Snapshot a caller's mapping immediately; retain no mutable references."""
        if not isinstance(artifact, Mapping):
            raise ValueError("artifact must be a mapping")
        try:
            snapshot = json.dumps(
                dict(artifact), sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact must contain finite JSON values") from exc
        return cls.from_json(snapshot)

    def tempo_for(self, team_id: str) -> float:
        team_id = _nonempty(team_id, "team_id")
        for candidate, tempo in self.team_log_tempos:
            if candidate == team_id:
                return tempo
        return self.unknown_team_log_tempo


@dataclass(frozen=True, slots=True)
class FrozenPureTempoPredictor:
    """VNext predictor that changes only production's expected goal total."""

    artifact: FrozenTeamTempoArtifact
    max_abs_match_log_adjustment: float = math.log(2.0)
    max_goals: int = MAX_GOALS
    artifact_kind: str = field(default="frozen-pure-tempo-v1", init=False)
    payload_mode: str = field(default="calibrated_wdl", init=False)
    artifact_descriptor_json: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, FrozenTeamTempoArtifact):
            raise ValueError("artifact must be a FrozenTeamTempoArtifact")
        cap = _positive_float(
            self.max_abs_match_log_adjustment,
            "max_abs_match_log_adjustment",
        )
        if cap > MAX_ARTIFACT_LOG_TEMPO:
            raise ValueError("max_abs_match_log_adjustment exceeds the safety bound")
        if (
            isinstance(self.max_goals, bool)
            or not isinstance(self.max_goals, int)
            or self.max_goals < 1
        ):
            raise ValueError("max_goals must be a positive integer")
        object.__setattr__(self, "max_abs_match_log_adjustment", cap)
        descriptor = json.dumps(
            {
                "algorithm": "production-ratio_global-plus-mean-team-log-tempo",
                "artifact": json.loads(self.artifact.canonical_json),
                "artifact_offset_safety_bound": MAX_ARTIFACT_LOG_TEMPO,
                "max_abs_match_log_adjustment": cap,
                "max_goals": self.max_goals,
                "output_calibration": (
                    "fixture-local-production-outcome-class-weight-parity"
                ),
                "payload_mode": self.payload_mode,
                "predictor_kind": self.artifact_kind,
                "rho_source": "production_payload",
                "strength_source": "production_lambda_ratio",
                "unknown_team_policy": "artifact_fallback",
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        object.__setattr__(self, "artifact_descriptor_json", descriptor)

    @classmethod
    def from_artifact_json(
        cls,
        artifact_json: str,
        *,
        max_abs_match_log_adjustment: float = math.log(2.0),
        max_goals: int = MAX_GOALS,
    ) -> "FrozenPureTempoPredictor":
        return cls(
            FrozenTeamTempoArtifact.from_json(artifact_json),
            max_abs_match_log_adjustment=max_abs_match_log_adjustment,
            max_goals=max_goals,
        )

    def predict(
        self,
        context: MatchContext,
        production_payload: Mapping[str, object],
        *,
        model_tag: str,
        artifact_identity: str,
    ) -> ScoreDistribution:
        """Return a coherently calibrated grid with production strength.

        The production payload contains a calibrated W/D/L triple but only raw
        lambdas and rho.  We therefore infer fixture-local outcome-class weights
        from its raw grid versus published triple, then apply the same weights to
        the tempo-adjusted candidate grid.  The calibrated grid is returned with
        explicit provenance; callers must not persist its latent lambdas as if
        they could reconstruct that richer grid.
        """
        if not isinstance(context, MatchContext):
            raise ValueError("context must be a MatchContext")
        if self.artifact.trained_through > context.features_as_of.astimezone(timezone.utc):
            raise ValueError("tempo artifact was trained after the forecast cutoff")
        _nonempty(model_tag, "model_tag")
        _nonempty(artifact_identity, "artifact_identity")
        if not isinstance(production_payload, Mapping):
            raise ValueError("production_payload must be a mapping")

        lambda_home = _positive_float(
            production_payload.get("lambda_home"), "lambda_home"
        )
        lambda_away = _positive_float(
            production_payload.get("lambda_away"), "lambda_away"
        )
        rho = _finite_float(production_payload.get("rho", 0.0), "rho")
        probabilities = production_payload.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise ValueError("probabilities must be a mapping")
        production_target = tuple(
            _finite_float(probabilities.get(key), f"probabilities.{key}")
            for key in ("home_win", "draw", "away_win")
        )
        if any(value < 0.0 or value > 1.0 for value in production_target):
            raise ValueError("production probabilities must be within [0, 1]")
        production_probability_total = sum(production_target)
        if production_probability_total <= 0.0:
            raise ValueError("production probabilities must have positive mass")
        if not math.isclose(
            production_probability_total, 1.0, rel_tol=0.0, abs_tol=0.001
        ):
            raise ValueError(
                "production probabilities must sum to one within persisted rounding"
            )
        normalized_production_target = tuple(
            value / production_probability_total for value in production_target
        )
        raw_adjustment = self.artifact.global_log_tempo + 0.5 * (
            self.artifact.tempo_for(context.home_team_id)
            + self.artifact.tempo_for(context.away_team_id)
        )
        if not math.isfinite(raw_adjustment):
            raise ValueError("combined tempo adjustment must be finite")
        adjustment = min(
            self.max_abs_match_log_adjustment,
            max(-self.max_abs_match_log_adjustment, raw_adjustment),
        )
        production_total = lambda_home + lambda_away
        adjusted_total = production_total * math.exp(adjustment)
        state = LatentMatchState(
            context=context,
            strength_log_ratio=math.log(lambda_home / lambda_away),
            log_total_goals=math.log(adjusted_total),
            rho=rho,
            model_version=model_tag,
        )
        candidate = ScoreDistribution.from_state(state, max_goals=self.max_goals)

        production_state = LatentMatchState(
            context=context,
            strength_log_ratio=math.log(lambda_home / lambda_away),
            log_total_goals=math.log(production_total),
            rho=rho,
            model_version=model_tag,
        )
        production_raw = ScoreDistribution.from_state(
            production_state, max_goals=self.max_goals
        )
        raw_production_wdl = production_raw.wdl.as_tuple()
        if any(value <= 0.0 for value in raw_production_wdl):
            raise ValueError("raw production grid has an empty W/D/L outcome class")
        outcome_weights = tuple(
            target / raw
            for target, raw in zip(
                normalized_production_target, raw_production_wdl
            )
        )
        candidate_wdl = candidate.wdl.as_tuple()
        weighted_target = tuple(
            probability * weight
            for probability, weight in zip(candidate_wdl, outcome_weights)
        )
        weighted_total = sum(weighted_target)
        if not math.isfinite(weighted_total) or weighted_total <= 0.0:
            raise ValueError("fixture-local calibrated target has no finite mass")
        normalized_candidate_target = tuple(
            value / weighted_total for value in weighted_target
        )
        return candidate.calibrated_to_wdl(
            normalized_candidate_target,
            calibrator_artifact_id=(
                f"fixture-local-tempo-parity:{artifact_identity}:{context.match_id}"
            ),
        )
