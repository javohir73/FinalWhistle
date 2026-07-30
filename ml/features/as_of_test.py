"""Tests for the bitemporal/as-of feature API."""
from datetime import datetime, timedelta, timezone

import pytest

from ml.features.as_of import (
    AsOfFeatureStore,
    ConflictingFeatureError,
    FeatureObservation,
    FeatureProvenance,
    FeatureSubject,
    FeatureValidationError,
    FutureFeatureError,
    MissingFeatureError,
)


UTC = timezone.utc
CUTOFF = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _observation(
    *,
    subject: FeatureSubject | None = None,
    name: str = "xg_for_rolling",
    value: float = 1.4,
    effective_at: datetime | None = None,
    known_at: datetime | None = None,
    source: str = "stats-provider",
    version: str = "v1",
    record_id: str = "row-1",
) -> FeatureObservation:
    return FeatureObservation(
        subject=subject or FeatureSubject.team(10),
        name=name,
        value=value,
        effective_at=effective_at or CUTOFF - timedelta(days=2),
        known_at=known_at or CUTOFF - timedelta(days=1),
        provenance=FeatureProvenance(source, version, record_id),
    )


def test_resolve_rejects_both_kinds_of_future_leakage():
    safe = _observation(record_id="safe")
    not_effective_yet = _observation(
        value=8.0,
        effective_at=CUTOFF + timedelta(seconds=1),
        known_at=CUTOFF - timedelta(days=1),
        record_id="future-effective",
    )
    learned_later = _observation(
        value=9.0,
        effective_at=CUTOFF - timedelta(days=3),
        known_at=CUTOFF + timedelta(seconds=1),
        record_id="future-known",
    )

    resolved = AsOfFeatureStore([not_effective_yet, learned_later, safe]).resolve(
        safe.subject, safe.name, CUTOFF
    )

    assert resolved == safe
    with pytest.raises(FutureFeatureError, match="future known_at"):
        learned_later.require_available_at(CUTOFF)


def test_late_revision_is_not_visible_before_known_time_then_replaces_old_value():
    effective = CUTOFF - timedelta(days=10)
    original = _observation(
        value=1.1, effective_at=effective, known_at=CUTOFF - timedelta(days=9),
        version="v1", record_id="original",
    )
    revision = _observation(
        value=1.3, effective_at=effective, known_at=CUTOFF + timedelta(days=2),
        version="v2", record_id="correction",
    )
    store = AsOfFeatureStore([revision, original])

    assert store.value(original.subject, original.name, CUTOFF) == 1.1
    assert store.value(original.subject, original.name, CUTOFF + timedelta(days=3)) == 1.3


def test_latest_valid_resolution_is_deterministic_across_insertion_order():
    first_source = _observation(value=1.0, source="alpha", record_id="same-time-a")
    second_source = _observation(value=2.0, source="zeta", record_id="same-time-z")

    forward = AsOfFeatureStore([first_source, second_source]).resolve(
        first_source.subject, first_source.name, CUTOFF
    )
    reverse = AsOfFeatureStore([second_source, first_source]).resolve(
        first_source.subject, first_source.name, CUTOFF
    )

    assert forward == reverse == second_source
    assert AsOfFeatureStore([first_source, second_source]).resolve(
        first_source.subject, first_source.name, CUTOFF, source="alpha"
    ) == first_source


def test_conflicting_duplicate_provenance_is_rejected_atomically():
    first = _observation(value=1.0)
    conflicting = _observation(value=2.0)
    store = AsOfFeatureStore([first])

    with pytest.raises(ConflictingFeatureError):
        store.extend([_observation(name="rest_days", value=4.0), conflicting])

    assert store.resolve(first.subject, "rest_days", CUTOFF) is None
    assert store.value(first.subject, first.name, CUTOFF) == 1.0


def test_team_and_match_features_do_not_collide_even_with_same_id():
    team = _observation(subject=FeatureSubject.team("42"), value=1.2, record_id="team")
    match = _observation(subject=FeatureSubject.match("42"), value=3.4, record_id="match")
    store = AsOfFeatureStore([team, match])

    assert store.value(team.subject, team.name, CUTOFF) == 1.2
    assert store.value(match.subject, match.name, CUTOFF) == 3.4


def test_snapshot_exposes_model_ready_values_and_preserves_provenance():
    team = FeatureSubject.team(7)
    xg = _observation(subject=team, name="xg_for", value=1.7, record_id="xg-7")
    rest = _observation(subject=team, name="rest_days", value=5, record_id="rest-7")

    snapshot = AsOfFeatureStore([rest, xg]).snapshot(
        team, ["xg_for", "rest_days"], CUTOFF, require_all=True
    )

    assert snapshot.as_dict() == {"xg_for": 1.7, "rest_days": 5.0}
    assert snapshot.observations["xg_for"].provenance.record_id == "xg-7"
    with pytest.raises(TypeError):
        snapshot.values["xg_for"] = 99.0


def test_required_snapshot_reports_features_unavailable_at_cutoff():
    future = _observation(name="lineup_strength", known_at=CUTOFF + timedelta(hours=1))

    with pytest.raises(MissingFeatureError, match="lineup_strength"):
        AsOfFeatureStore([future]).snapshot(
            future.subject, ["lineup_strength"], CUTOFF, require_all=True
        )


@pytest.mark.parametrize("bad_value", [True, float("nan"), float("inf"), "1.2"])
def test_observation_rejects_non_finite_or_non_numeric_values(bad_value):
    with pytest.raises(FeatureValidationError):
        _observation(value=bad_value)


def test_timestamps_must_be_timezone_aware_and_are_normalized_to_utc():
    with pytest.raises(FeatureValidationError, match="timezone"):
        _observation(effective_at=datetime(2026, 1, 1))

    plus_ten = timezone(timedelta(hours=10))
    row = _observation(
        effective_at=datetime(2026, 5, 30, 22, tzinfo=plus_ten),
        known_at=datetime(2026, 5, 31, 22, tzinfo=plus_ten),
    )
    assert row.effective_at.tzinfo == UTC
    assert row.known_at.tzinfo == UTC


def test_extend_is_atomic_when_batch_contains_invalid_type():
    valid = _observation()
    store = AsOfFeatureStore()

    with pytest.raises(FeatureValidationError):
        store.extend([valid, object()])

    assert store.resolve(valid.subject, valid.name, CUTOFF) is None


@pytest.mark.parametrize("field", ["subject", "name", "provenance"])
def test_observation_requires_structured_identity_fields(field):
    kwargs = {
        "subject": FeatureSubject.team(1),
        "name": "xg_for",
        "provenance": FeatureProvenance("source", "v1", "row"),
    }
    kwargs[field] = None
    with pytest.raises(FeatureValidationError):
        FeatureObservation(
            **kwargs,
            value=1.0,
            effective_at=CUTOFF - timedelta(days=1),
            known_at=CUTOFF,
        )
