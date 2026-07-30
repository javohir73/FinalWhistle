"""Safe, opt-in shadow boundary for the additive FinalWhistle vNext core.

Nothing in this module is activated by import.  Callers must supply an explicit
``VNextShadowSpec``; the default production and existing shadow paths remain
unchanged.  Artifact identity is a deterministic hash of the predictor kind,
declared artifact version and canonical JSON configuration.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping, Protocol, runtime_checkable

from ml.models.poisson import DRAW_HEADLINE_BAND, most_likely_score
from ml.models.vnext import (
    ExactScoreProbability,
    LatentMatchState,
    MatchContext,
    ScoreDistribution,
)


PayloadMode = Literal["raw_distribution", "calibrated_wdl", "parity"]
VNEXT_RECEIPT_SCHEMA_VERSION = 2
VNEXT_RECEIPT_KEY = "_vnext_receipt"


@runtime_checkable
class VNextPredictor(Protocol):
    """Minimal protocol for an independently testable vNext match predictor."""

    @property
    def artifact_kind(self) -> str: ...

    @property
    def payload_mode(self) -> PayloadMode: ...

    @property
    def artifact_descriptor_json(self) -> str: ...

    def predict(
        self,
        context: MatchContext,
        production_payload: Mapping[str, object],
        *,
        model_tag: str,
        artifact_identity: str,
    ) -> ScoreDistribution: ...


@dataclass(frozen=True, slots=True)
class ParityCanaryPredictor:
    """Rebuild the current forecast through vNext without claiming improvement.

    The existing payload's lambdas and rho create the Dixon-Coles grid.  Its
    published W/D/L triple is then applied with coherent outcome-class raking,
    which accounts for today's W/D/L-only calibrator.  ``payload_mode=parity``
    tells the payload builder to preserve the existing rounded headline fields
    exactly: this canary tests the integration seam, not a challenger model.
    """

    artifact_kind: str = "legacy-payload-parity-v1"
    payload_mode: PayloadMode = "parity"
    artifact_descriptor_json: str = "{}"

    def predict(
        self,
        context: MatchContext,
        production_payload: Mapping[str, object],
        *,
        model_tag: str,
        artifact_identity: str,
    ) -> ScoreDistribution:
        lambda_home = _positive_float(production_payload.get("lambda_home"), "lambda_home")
        lambda_away = _positive_float(production_payload.get("lambda_away"), "lambda_away")
        rho = _finite_float(production_payload.get("rho", 0.0), "rho")
        state = LatentMatchState.from_expected_goals(
            context,
            lambda_home,
            lambda_away,
            rho=rho,
            model_version=model_tag,
        )
        distribution = ScoreDistribution.from_state(state)
        probabilities = _mapping(production_payload.get("probabilities"), "probabilities")
        target = (
            _nonnegative_float(probabilities.get("home_win"), "probabilities.home_win"),
            _nonnegative_float(probabilities.get("draw"), "probabilities.draw"),
            _nonnegative_float(probabilities.get("away_win"), "probabilities.away_win"),
        )
        total = sum(target)
        if total <= 0.0:
            raise ValueError("production W/D/L has no probability mass")
        normalized_target = tuple(value / total for value in target)
        return distribution.calibrated_to_wdl(
            normalized_target,
            calibrator_artifact_id=f"parity:{artifact_identity}",
        )


@dataclass(frozen=True, slots=True)
class VNextShadowSpec:
    """Frozen opt-in specification with content-addressed artifact identity."""

    production_model_version: str
    artifact_name: str = "finalwhistle-vnext-parity"
    artifact_version: str = "1"
    artifact_config_json: str = "{}"
    predictor: VNextPredictor = field(
        default_factory=ParityCanaryPredictor,
        compare=False,
        hash=False,
        repr=False,
    )
    artifact_identity: str = field(init=False)
    model_tag: str = field(init=False)
    predictor_kind: str = field(init=False)
    predictor_payload_mode: PayloadMode = field(init=False)
    predictor_descriptor_json: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.artifact_name or not self.artifact_name.strip():
            raise ValueError("artifact_name must not be empty")
        if not self.artifact_version or not self.artifact_version.strip():
            raise ValueError("artifact_version must not be empty")
        if not self.production_model_version or not self.production_model_version.strip():
            raise ValueError("production_model_version must not be empty")
        if not isinstance(self.predictor, VNextPredictor):
            raise TypeError("predictor must implement VNextPredictor")
        if not self.predictor.artifact_kind or not self.predictor.artifact_kind.strip():
            raise ValueError("predictor artifact_kind must not be empty")
        if self.predictor.payload_mode not in (
            "raw_distribution",
            "calibrated_wdl",
            "parity",
        ):
            raise ValueError(
                "predictor payload_mode must be raw_distribution, "
                "calibrated_wdl or parity"
            )
        canonical_config, config = _canonical_json(
            self.artifact_config_json, "artifact_config_json"
        )
        canonical_predictor, predictor_config = _canonical_json(
            self.predictor.artifact_descriptor_json,
            "predictor.artifact_descriptor_json",
        )
        if self.predictor.artifact_descriptor_json != canonical_predictor:
            raise ValueError("predictor artifact descriptor must already be canonical JSON")
        object.__setattr__(self, "artifact_config_json", canonical_config)
        object.__setattr__(self, "predictor_kind", self.predictor.artifact_kind)
        object.__setattr__(self, "predictor_payload_mode", self.predictor.payload_mode)
        object.__setattr__(self, "predictor_descriptor_json", canonical_predictor)
        descriptor = json.dumps(
            {
                "artifact_name": self.artifact_name,
                "artifact_version": self.artifact_version,
                "config": config,
                "production_model_version": self.production_model_version,
                "payload_mode": self.predictor.payload_mode,
                "predictor": self.predictor.artifact_kind,
                "predictor_config": predictor_config,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        identity = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()
        model_tag = f"fw-vnext-{identity[:31]}"
        if len(model_tag) > 40:
            raise ValueError("vNext model tag exceeds the persistence limit")
        object.__setattr__(self, "artifact_identity", identity)
        object.__setattr__(self, "model_tag", model_tag)


def build_vnext_shadow_payload(
    match: object,
    production_payload: Mapping[str, object],
    spec: VNextShadowSpec,
    *,
    features_as_of: datetime,
) -> dict | None:
    """Purely build one vNext shadow payload, or skip outside the safe cutoff.

    ``features_as_of`` is explicit to make tests and replays deterministic.  A
    missing kickoff, a missing team or a cutoff at/after kickoff returns ``None``
    before the predictor runs.  Aware UTC is required for the information
    cutoff; database kickoffs that are timezone-naive follow the repository's
    established convention and are interpreted as UTC.

    A calibrated/raked grid cannot be reconstructed from legacy lambda fields.
    Such payloads therefore persist NULL lambdas and rho instead of squeezing a
    richer distribution into a lossy legacy representation.
    """
    as_of = _aware_utc(features_as_of, "features_as_of", allow_naive=False)
    kickoff_value = getattr(match, "kickoff_utc", None)
    if kickoff_value is None:
        return None
    kickoff = _aware_utc(kickoff_value, "kickoff_utc", allow_naive=True)
    home_team_id = getattr(match, "team_home_id", None)
    away_team_id = getattr(match, "team_away_id", None)
    if home_team_id is None or away_team_id is None or as_of >= kickoff:
        return None

    payload_match_id = production_payload.get("match_id")
    match_id = getattr(match, "id", None)
    if payload_match_id != match_id:
        raise ValueError("production payload match_id does not match the fixture")
    if production_payload.get("model_version") != spec.production_model_version:
        raise ValueError("production payload model_version does not match the shadow spec")
    if (
        spec.predictor.artifact_kind != spec.predictor_kind
        or spec.predictor.payload_mode != spec.predictor_payload_mode
        or spec.predictor.artifact_descriptor_json != spec.predictor_descriptor_json
    ):
        raise ValueError("predictor descriptor changed after the shadow spec was frozen")
    context = MatchContext(
        match_id=str(match_id),
        home_team_id=str(home_team_id),
        away_team_id=str(away_team_id),
        features_as_of=as_of,
        kickoff_utc=kickoff,
        competition_id=(
            str(getattr(match, "tournament_id"))
            if getattr(match, "tournament_id", None) is not None
            else None
        ),
        neutral_venue=bool(getattr(match, "is_neutral", False)),
    )
    if spec.predictor_payload_mode == "raw_distribution" and not _champion_wdl_is_raw(
        context, production_payload
    ):
        raise ValueError(
            "raw_distribution cannot be compared with a calibrated champion"
        )
    champion_fingerprint_before = champion_payload_fingerprint(production_payload)
    predictor_payload = copy.deepcopy(dict(production_payload))
    distribution = spec.predictor.predict(
        context,
        predictor_payload,
        model_tag=spec.model_tag,
        artifact_identity=spec.artifact_identity,
    )
    if champion_payload_fingerprint(production_payload) != champion_fingerprint_before:
        raise ValueError("vNext predictor mutated the production payload")
    if distribution.context != context:
        raise ValueError("vNext predictor returned a distribution for a different fixture")
    if distribution.state.model_version != spec.model_tag:
        raise ValueError("vNext distribution model_version does not match the persisted tag")

    shadow = copy.deepcopy(dict(production_payload))
    shadow["model_version"] = spec.model_tag
    shadow["generated_at"] = as_of.isoformat()
    shadow["writeup"] = None
    shadow["vnext_artifact_identity"] = spec.artifact_identity

    if spec.predictor_payload_mode == "parity":
        # The canary deliberately preserves today's rounded public headline.
        # Its grid is still built and validated above, and the lossy legacy
        # lambda fields are removed because the grid was coherently raked.
        if distribution.calibration is None:
            raise ValueError("parity predictor must return a calibrated distribution")
    elif spec.predictor_payload_mode == "raw_distribution":
        if distribution.calibration is not None:
            raise ValueError(
                "raw_distribution predictors must return an uncalibrated grid"
            )
        reconstructed = ScoreDistribution.from_state(
            distribution.state,
            max_goals=distribution.max_goals,
        )
        if any(
            not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-12)
            for observed_row, expected_row in zip(
                distribution.grid, reconstructed.grid
            )
            for observed, expected in zip(observed_row, expected_row)
        ):
            raise ValueError(
                "raw_distribution grid is not reconstructable from its persisted state"
            )
        shadow["probabilities"] = _wdl_payload(distribution)
        shadow["predicted_score"] = _headline_payload(distribution)
        shadow["knockout"] = None
    else:
        if distribution.calibration is None:
            raise ValueError(
                "calibrated_wdl predictors must return calibration provenance"
            )
        shadow["probabilities"] = _wdl_payload(distribution)
        shadow["predicted_score"] = _headline_payload(distribution)
        shadow["knockout"] = None

    if distribution.calibration is not None:
        shadow["lambda_home"] = None
        shadow["lambda_away"] = None
        shadow["rho"] = None
        shadow["vnext_calibration_artifact"] = distribution.calibration.artifact_id
    else:
        lambda_home, lambda_away = distribution.latent_expected_goals
        shadow["lambda_home"] = round(lambda_home, 4)
        shadow["lambda_away"] = round(lambda_away, 4)
        shadow["rho"] = distribution.state.rho

    receipt = build_vnext_receipt(
        production_payload,
        champion_model_version=spec.production_model_version,
        artifact_identity=spec.artifact_identity,
        features_as_of=as_of,
        predictor_kind=spec.predictor_kind,
        payload_mode=spec.predictor_payload_mode,
        distribution=distribution,
    )
    reasons = shadow.get("reasons")
    if reasons is None:
        reasons = []
    if not isinstance(reasons, list):
        raise ValueError("production reasons must be a list or null")
    shadow["reasons"] = [*reasons, {VNEXT_RECEIPT_KEY: receipt}]
    return shadow


def _persisted_projection_from_payload(
    production_payload: Mapping[str, object],
) -> dict[str, object]:
    """Exact production payload values written by ``_write_prediction``."""
    probabilities = _mapping(production_payload.get("probabilities"), "probabilities")
    predicted_score = _mapping(
        production_payload.get("predicted_score"), "predicted_score"
    )
    required = ("match_id", "model_version", "confidence", "reasons", "top_features")
    missing = [key for key in required if key not in production_payload]
    if missing:
        raise ValueError(
            f"production payload is missing persisted fields: {', '.join(missing)}"
        )
    return {
        "confidence": production_payload["confidence"],
        "knockout": production_payload.get("knockout"),
        "lambda_away": production_payload.get("lambda_away"),
        "lambda_home": production_payload.get("lambda_home"),
        "match_id": production_payload["match_id"],
        "model_version": production_payload["model_version"],
        "predicted_score_away": predicted_score.get("away"),
        "predicted_score_home": predicted_score.get("home"),
        "predicted_score_prob": predicted_score.get("probability"),
        "prob_away_win": probabilities.get("away_win"),
        "prob_draw": probabilities.get("draw"),
        "prob_home_win": probabilities.get("home_win"),
        "reasons": production_payload["reasons"],
        "rho": production_payload.get("rho"),
        "top_features": production_payload["top_features"],
        "writeup": production_payload.get("writeup"),
    }


def _persisted_projection_from_row(row: object) -> dict[str, object]:
    """Equivalent persisted projection from a ``Prediction``-shaped row."""
    fields = (
        "confidence",
        "knockout",
        "lambda_away",
        "lambda_home",
        "match_id",
        "model_version",
        "predicted_score_away",
        "predicted_score_home",
        "predicted_score_prob",
        "prob_away_win",
        "prob_draw",
        "prob_home_win",
        "reasons",
        "rho",
        "top_features",
        "writeup",
    )
    missing = [name for name in fields if not hasattr(row, name)]
    if missing:
        raise ValueError(f"prediction row is missing fields: {', '.join(missing)}")
    return {name: getattr(row, name) for name in fields}


def _fingerprint(projection: Mapping[str, object]) -> str:
    try:
        canonical = json.dumps(
            projection,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("persisted champion fields must contain finite JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def champion_payload_fingerprint(production_payload: Mapping[str, object]) -> str:
    """Fingerprint exactly the champion payload fields persisted to Prediction."""
    return _fingerprint(_persisted_projection_from_payload(production_payload))


def champion_row_fingerprint(row: object) -> str:
    """Fingerprint a stored champion row for exact shadow-pair validation."""
    return _fingerprint(_persisted_projection_from_row(row))


def build_vnext_receipt(
    production_payload: Mapping[str, object],
    *,
    champion_model_version: str,
    artifact_identity: str,
    features_as_of: datetime,
    predictor_kind: str,
    payload_mode: PayloadMode,
    distribution: ScoreDistribution,
) -> dict[str, object]:
    """Build the lineage and metric receipt stored only on the shadow row."""
    if production_payload.get("model_version") != champion_model_version:
        raise ValueError("champion model version does not match production payload")
    if not champion_model_version or not champion_model_version.strip():
        raise ValueError("champion_model_version must not be empty")
    if not artifact_identity or not artifact_identity.strip():
        raise ValueError("artifact_identity must not be empty")
    if len(artifact_identity) != 64 or any(
        character not in "0123456789abcdef" for character in artifact_identity
    ):
        raise ValueError("artifact_identity must be a lowercase SHA-256 digest")
    if not predictor_kind or not predictor_kind.strip():
        raise ValueError("predictor_kind must not be empty")
    if payload_mode not in ("raw_distribution", "calibrated_wdl", "parity"):
        raise ValueError("payload_mode is invalid")
    if not isinstance(distribution, ScoreDistribution):
        raise TypeError("distribution must be a ScoreDistribution")
    as_of = _aware_utc(features_as_of, "features_as_of", allow_naive=False)
    over_2_5 = distribution.total_goals_over(2.5)
    return {
        "artifact_identity": artifact_identity,
        "candidate_grid_sha256": distribution_grid_fingerprint(distribution),
        "candidate_max_goals": distribution.max_goals,
        "candidate_over_2_5": over_2_5,
        "champion_model_version": champion_model_version,
        "champion_payload_sha256": champion_payload_fingerprint(production_payload),
        "features_as_of": as_of.isoformat(),
        "payload_mode": payload_mode,
        "predictor_kind": predictor_kind,
        "schema_version": VNEXT_RECEIPT_SCHEMA_VERSION,
    }


def distribution_grid_fingerprint(distribution: ScoreDistribution) -> str:
    """Hash the exact normalized candidate grid without storing it twice."""
    if not isinstance(distribution, ScoreDistribution):
        raise TypeError("distribution must be a ScoreDistribution")
    return _fingerprint({"grid": distribution.grid})


def extract_vnext_receipt(reasons: object) -> dict[str, object] | None:
    """Read the single internal receipt from shadow reasons, if present."""
    if reasons is None:
        return None
    if not isinstance(reasons, list):
        raise ValueError("shadow reasons must be a list or null")
    found = [
        item[VNEXT_RECEIPT_KEY]
        for item in reasons
        if isinstance(item, Mapping) and VNEXT_RECEIPT_KEY in item
    ]
    if not found:
        return None
    if len(found) != 1 or not isinstance(found[0], Mapping):
        raise ValueError("shadow reasons must contain exactly one valid vNext receipt")
    return copy.deepcopy(dict(found[0]))


def validate_vnext_receipt(
    receipt: Mapping[str, object],
    *,
    challenger_tag: str,
    champion_model_version: str,
    kickoff_utc: datetime,
    artifact_identity: str | None = None,
    champion_payload_sha256: str | None = None,
    predictor_kind: str | None = None,
    payload_mode: PayloadMode | None = None,
    champion_created_at: datetime | None = None,
    challenger_created_at: datetime | None = None,
) -> dict[str, object]:
    """Fail closed unless a stored receipt is complete and content-linked.

    Callers that know the full shadow specification and current champion should
    pass the optional expected values.  The stored benchmark can omit those
    expectations, then use the validated full digest to locate its exact parent.
    """
    if not isinstance(receipt, Mapping):
        raise ValueError("vNext receipt must be a mapping")
    value = dict(receipt)
    required = {
        "artifact_identity",
        "candidate_grid_sha256",
        "candidate_max_goals",
        "candidate_over_2_5",
        "champion_model_version",
        "champion_payload_sha256",
        "features_as_of",
        "payload_mode",
        "predictor_kind",
        "schema_version",
    }
    if set(value) != required:
        raise ValueError("vNext receipt fields do not match the current schema")
    if value["schema_version"] != VNEXT_RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported vNext receipt schema")
    stored_identity = value["artifact_identity"]
    if not _is_sha256(stored_identity):
        raise ValueError("receipt artifact identity must be a lowercase SHA-256 digest")
    if artifact_identity is not None and stored_identity != artifact_identity:
        raise ValueError("receipt artifact identity does not match the shadow spec")
    if challenger_tag != f"fw-vnext-{stored_identity[:31]}":
        raise ValueError("challenger tag does not match the full artifact identity")
    if value["champion_model_version"] != champion_model_version:
        raise ValueError("receipt champion model version is incorrect")
    stored_champion_hash = value["champion_payload_sha256"]
    if not _is_sha256(stored_champion_hash):
        raise ValueError("receipt champion fingerprint must be a SHA-256 digest")
    if (
        champion_payload_sha256 is not None
        and stored_champion_hash != champion_payload_sha256
    ):
        raise ValueError("receipt does not reference the expected champion payload")
    if not _is_sha256(value["candidate_grid_sha256"]):
        raise ValueError("receipt candidate grid fingerprint must be a SHA-256 digest")
    max_goals = value["candidate_max_goals"]
    if isinstance(max_goals, bool) or not isinstance(max_goals, int) or max_goals < 1:
        raise ValueError("receipt candidate_max_goals must be a positive integer")
    candidate_over = _finite_float(
        value["candidate_over_2_5"], "receipt candidate_over_2_5"
    )
    if not 0.0 <= candidate_over <= 1.0:
        raise ValueError("receipt candidate_over_2_5 must be within [0, 1]")
    stored_kind = value["predictor_kind"]
    if not isinstance(stored_kind, str) or not stored_kind.strip():
        raise ValueError("receipt predictor_kind must not be empty")
    if predictor_kind is not None and stored_kind != predictor_kind:
        raise ValueError("receipt predictor_kind does not match the shadow spec")
    stored_mode = value["payload_mode"]
    if stored_mode not in ("raw_distribution", "calibrated_wdl", "parity"):
        raise ValueError("receipt payload_mode is invalid")
    if payload_mode is not None and stored_mode != payload_mode:
        raise ValueError("receipt payload_mode does not match the shadow spec")
    cutoff_value = value["features_as_of"]
    if not isinstance(cutoff_value, str):
        raise ValueError("receipt features_as_of must be an ISO datetime")
    try:
        cutoff = datetime.fromisoformat(cutoff_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("receipt features_as_of must be an ISO datetime") from exc
    cutoff = _aware_utc(cutoff, "receipt features_as_of", allow_naive=False)
    kickoff = _aware_utc(kickoff_utc, "kickoff_utc", allow_naive=True)
    if cutoff >= kickoff:
        raise ValueError("receipt feature cutoff is at or after kickoff")
    for created_at, name in (
        (champion_created_at, "champion_created_at"),
        (challenger_created_at, "challenger_created_at"),
    ):
        # SQLite's CURRENT_TIMESTAMP round-trip is second-resolution while the
        # in-memory feature cutoff includes microseconds.  Allow only that
        # persistence precision gap; larger future-cutoff claims fail closed.
        if created_at is not None and cutoff > _aware_utc(
            created_at, name, allow_naive=True
        ) + timedelta(seconds=1):
            raise ValueError(f"receipt feature cutoff is after {name}")
    value["candidate_over_2_5"] = candidate_over
    return copy.deepcopy(value)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _wdl_payload(distribution: ScoreDistribution) -> dict[str, float]:
    wdl = distribution.wdl
    return {
        "home_win": round(wdl.home, 4),
        "draw": round(wdl.draw, 4),
        "away_win": round(wdl.away, 4),
    }


def _champion_wdl_is_raw(
    context: MatchContext, production_payload: Mapping[str, object]
) -> bool:
    """Whether persisted champion W/D/L is raw lambda/rho output to 4dp."""
    lambda_home = _positive_float(production_payload.get("lambda_home"), "lambda_home")
    lambda_away = _positive_float(production_payload.get("lambda_away"), "lambda_away")
    rho = _finite_float(production_payload.get("rho", 0.0), "rho")
    probabilities = _mapping(production_payload.get("probabilities"), "probabilities")
    published = tuple(
        _nonnegative_float(probabilities.get(key), f"probabilities.{key}")
        for key in ("home_win", "draw", "away_win")
    )
    if any(value > 1.0 for value in published):
        raise ValueError("production probabilities must be within [0, 1]")
    total = sum(published)
    if total <= 0.0 or not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=0.001):
        raise ValueError("production probabilities must sum to one within rounding")
    raw_state = LatentMatchState.from_expected_goals(
        context,
        lambda_home,
        lambda_away,
        rho=rho,
        model_version="fw-vnext-raw-champion-check-v1",
    )
    raw = ScoreDistribution.from_state(raw_state).wdl.as_tuple()
    return all(
        math.isclose(observed, round(expected, 4), rel_tol=0.0, abs_tol=5e-5)
        for observed, expected in zip(published, raw)
    )


def _headline_payload(distribution: ScoreDistribution) -> dict[str, int | float]:
    wdl = distribution.wdl
    if abs(wdl.home - wdl.away) <= DRAW_HEADLINE_BAND:
        score = distribution.most_likely_score
    else:
        outcome = "home" if wdl.home > wdl.away else "away"
        home, away, probability = most_likely_score(distribution.grid, outcome)
        score = ExactScoreProbability(home=home, away=away, probability=probability)
    return {
        "home": score.home,
        "away": score.away,
        "probability": round(score.probability, 4),
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def is_strictly_before_kickoff(match: object, at: datetime) -> bool:
    """Return whether an aware instant is safely before this fixture's kickoff."""
    instant = _aware_utc(at, "at", allow_naive=False)
    kickoff_value = getattr(match, "kickoff_utc", None)
    if kickoff_value is None:
        return False
    kickoff = _aware_utc(kickoff_value, "kickoff_utc", allow_naive=True)
    return instant < kickoff


def _canonical_json(value: str, name: str) -> tuple[str, object]:
    try:
        parsed = json.loads(value)
        canonical = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} must contain finite valid JSON") from exc
    return canonical, parsed


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


def _nonnegative_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _aware_utc(value: datetime, name: str, *, allow_naive: bool) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        if not allow_naive:
            raise ValueError(f"{name} must be timezone-aware")
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
