"""Time-aware numeric features for leak-free training and prediction.

An observation carries two independent clocks:

* ``effective_at`` -- when the fact applies in the real world; and
* ``known_at`` -- when FinalWhistle first had that exact observation available.

A feature is safe at a prediction cutoff only when both clocks are at or before
the cutoff.  Keeping the clocks separate matters for late data feeds and revised
statistics: a correction to an old match must not appear in a historical training
row created before the correction was known.

This module is deliberately storage-agnostic.  ``AsOfFeatureStore`` is a small
in-memory reference implementation and API boundary; a database-backed store can
implement the same ``resolve``/``snapshot`` behaviour later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping


class FeatureValidationError(ValueError):
    """Raised when feature data cannot be represented safely."""


class FutureFeatureError(FeatureValidationError):
    """Raised when an observation is explicitly required before it is safe."""


class MissingFeatureError(LookupError):
    """Raised when a required feature is unavailable at an as-of cutoff."""


class ConflictingFeatureError(FeatureValidationError):
    """Raised when one provenance identity claims two different observations."""


class SubjectKind(str, Enum):
    """Entities currently supported by the prediction feature layer."""

    TEAM = "team"
    MATCH = "match"


def _required_text(value: object, field_name: str) -> str:
    if value is None:
        raise FeatureValidationError(f"{field_name} must not be empty")
    text = str(value).strip()
    if not text:
        raise FeatureValidationError(f"{field_name} must not be empty")
    return text


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise FeatureValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureValidationError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FeatureSubject:
    """A stable team or match identifier."""

    kind: SubjectKind
    entity_id: str

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, SubjectKind) else SubjectKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise FeatureValidationError("subject kind must be 'team' or 'match'") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "entity_id", _required_text(self.entity_id, "entity_id"))

    @classmethod
    def team(cls, team_id: object) -> "FeatureSubject":
        return cls(SubjectKind.TEAM, _required_text(team_id, "team_id"))

    @classmethod
    def match(cls, match_id: object) -> "FeatureSubject":
        return cls(SubjectKind.MATCH, _required_text(match_id, "match_id"))


@dataclass(frozen=True)
class FeatureProvenance:
    """Origin of an observation, retained for audit and reproducibility."""

    source: str
    version: str
    record_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        object.__setattr__(self, "record_id", _required_text(self.record_id, "record_id"))


@dataclass(frozen=True)
class FeatureObservation:
    """One numeric feature value with full bitemporal provenance."""

    subject: FeatureSubject
    name: str
    value: float
    effective_at: datetime
    known_at: datetime
    provenance: FeatureProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.subject, FeatureSubject):
            raise FeatureValidationError("subject must be a FeatureSubject")
        if not isinstance(self.provenance, FeatureProvenance):
            raise FeatureValidationError("provenance must be a FeatureProvenance")
        object.__setattr__(self, "name", _required_text(self.name, "name"))

        # bool is an int subclass, but accepting True as a model value tends to hide
        # feature-encoding mistakes.  Callers should encode booleans explicitly.
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise FeatureValidationError("value must be numeric (not bool)")
        value = float(self.value)
        if not math.isfinite(value):
            raise FeatureValidationError("value must be finite")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "effective_at", _utc(self.effective_at, "effective_at"))
        object.__setattr__(self, "known_at", _utc(self.known_at, "known_at"))

    def is_available_at(self, as_of: datetime) -> bool:
        """Whether this exact value was safe to use at ``as_of``."""
        cutoff = _utc(as_of, "as_of")
        return self.effective_at <= cutoff and self.known_at <= cutoff

    def require_available_at(self, as_of: datetime) -> "FeatureObservation":
        """Return self, or reject an attempt to use future information."""
        cutoff = _utc(as_of, "as_of")
        if not self.is_available_at(cutoff):
            blocked_by = []
            if self.effective_at > cutoff:
                blocked_by.append("effective_at")
            if self.known_at > cutoff:
                blocked_by.append("known_at")
            raise FutureFeatureError(
                f"feature {self.name!r} is unavailable at {cutoff.isoformat()}; "
                f"future {', '.join(blocked_by)}"
            )
        return self

    @property
    def deterministic_order(self) -> tuple:
        """Selection order, including stable metadata tie-breakers."""
        return (
            self.effective_at,
            self.known_at,
            self.provenance.source,
            self.provenance.version,
            self.provenance.record_id,
        )

    @property
    def identity(self) -> tuple:
        """Unique observation identity used to reject ambiguous source records."""
        return (self.subject, self.name, *self.deterministic_order)


@dataclass(frozen=True)
class FeatureSnapshot:
    """Resolved model inputs and the observations that produced them."""

    subject: FeatureSubject
    as_of: datetime
    observations: Mapping[str, FeatureObservation]

    def __post_init__(self) -> None:
        if not isinstance(self.subject, FeatureSubject):
            raise FeatureValidationError("subject must be a FeatureSubject")
        object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))
        copied = dict(self.observations)
        for name, observation in copied.items():
            if not isinstance(observation, FeatureObservation):
                raise FeatureValidationError("snapshot values must be FeatureObservation values")
            if name != observation.name or observation.subject != self.subject:
                raise FeatureValidationError("snapshot observations do not match the subject/name")
            observation.require_available_at(self.as_of)
        object.__setattr__(self, "observations", MappingProxyType(copied))

    @property
    def values(self) -> Mapping[str, float]:
        """Read-only numeric inputs suitable for a model adapter."""
        return MappingProxyType({name: obs.value for name, obs in self.observations.items()})

    def as_dict(self) -> dict[str, float]:
        """Return a mutable copy for libraries that require a plain dict."""
        return dict(self.values)


class AsOfFeatureStore:
    """Storage-neutral reference resolver for time-aware observations."""

    def __init__(self, observations: Iterable[FeatureObservation] = ()) -> None:
        self._observations: list[FeatureObservation] = []
        self.extend(observations)

    def add(self, observation: FeatureObservation) -> None:
        if not isinstance(observation, FeatureObservation):
            raise FeatureValidationError("observation must be a FeatureObservation")
        self._reject_conflicts([observation])
        self._observations.append(observation)

    def extend(self, observations: Iterable[FeatureObservation]) -> None:
        # Validate the complete batch before mutation so a bad row cannot leave a
        # partially loaded feature set.
        batch = list(observations)
        if any(not isinstance(row, FeatureObservation) for row in batch):
            raise FeatureValidationError("all observations must be FeatureObservation values")
        self._reject_conflicts(batch)
        self._observations.extend(batch)

    def _reject_conflicts(self, batch: list[FeatureObservation]) -> None:
        by_identity = {row.identity: row for row in self._observations}
        for row in batch:
            existing = by_identity.get(row.identity)
            if existing is not None and existing != row:
                raise ConflictingFeatureError(
                    f"conflicting values share provenance identity for "
                    f"{row.subject.kind.value}:{row.subject.entity_id}/{row.name}"
                )
            by_identity[row.identity] = row

    def resolve(
        self,
        subject: FeatureSubject,
        name: str,
        as_of: datetime,
        *,
        source: str | None = None,
    ) -> FeatureObservation | None:
        """Resolve the latest safe observation, independent of insertion order.

        The most recent effective fact wins; a later-known revision wins when two
        rows describe the same effective instant.  Provenance fields provide a
        stable final tie-break when multiple sources publish at identical times.
        """
        if not isinstance(subject, FeatureSubject):
            raise FeatureValidationError("subject must be a FeatureSubject")
        feature_name = _required_text(name, "name")
        cutoff = _utc(as_of, "as_of")
        source_filter = _required_text(source, "source") if source is not None else None

        candidates = (
            row
            for row in self._observations
            if row.subject == subject
            and row.name == feature_name
            and (source_filter is None or row.provenance.source == source_filter)
            and row.is_available_at(cutoff)
        )
        return max(candidates, key=lambda row: row.deterministic_order, default=None)

    def value(
        self,
        subject: FeatureSubject,
        name: str,
        as_of: datetime,
        *,
        default: float | None = None,
        source: str | None = None,
    ) -> float | None:
        """Resolve only the numeric value, with an optional cold-start default."""
        observation = self.resolve(subject, name, as_of, source=source)
        return observation.value if observation is not None else default

    def snapshot(
        self,
        subject: FeatureSubject,
        names: Iterable[str],
        as_of: datetime,
        *,
        require_all: bool = False,
    ) -> FeatureSnapshot:
        """Resolve several named inputs at one prediction cutoff."""
        cutoff = _utc(as_of, "as_of")
        requested = tuple(dict.fromkeys(_required_text(name, "name") for name in names))
        resolved = {
            name: observation
            for name in requested
            if (observation := self.resolve(subject, name, cutoff)) is not None
        }
        if require_all:
            missing = [name for name in requested if name not in resolved]
            if missing:
                raise MissingFeatureError(
                    f"missing features for {subject.kind.value}:{subject.entity_id} at "
                    f"{cutoff.isoformat()}: {', '.join(missing)}"
                )
        return FeatureSnapshot(subject=subject, as_of=cutoff, observations=resolved)
