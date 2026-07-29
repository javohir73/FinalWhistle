"""The persistence boundary: durable, bounded, append-only, fail-soft."""

from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ResearchArtifact
from app.research_store import (
    MAX_ARTIFACT_BYTES,
    ArtifactStoreError,
    DatabaseArtifactStore,
    FileArtifactStore,
    canonical_bytes,
    digest,
    load_latest,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _artifact(*, generated_at=NOW, version="market-benchmark-artifact-v1",
              **extra):
    return {
        "artifact_version": version,
        "experimental": True,
        "generated_at": generated_at.isoformat(),
        "coverage": {"eligible_observations": 0},
        "exclusions": {},
        "benchmark": {"groups": []},
        "health": {"venues": {}},
        **extra,
    }


# --- database backend --------------------------------------------------------


def test_publish_then_load_round_trips_the_artifact(db):
    store = DatabaseArtifactStore(db)

    reference = store.publish(_artifact(), published_by="pete")

    assert reference.startswith("db://research_artifact/")
    assert store.load() == _artifact()
    row = db.query(ResearchArtifact).one()
    assert row.sha256 == digest(_artifact())
    assert row.size_bytes == len(canonical_bytes(_artifact()))
    assert row.published_by == "pete"
    assert row.artifact_version == "market-benchmark-artifact-v1"


def test_republishing_identical_content_is_a_no_op(db):
    """Re-running the generator on unchanged data must not grow the table."""
    store = DatabaseArtifactStore(db)
    first = store.publish(_artifact(), published_by="pete")

    second = store.publish(_artifact(), published_by="pete")

    assert db.query(ResearchArtifact).count() == 1
    assert "unchanged" in second
    assert first.split("/")[-1] == second.split("/")[-1].split(" ")[0]


def test_the_latest_generation_wins_by_generator_time_not_insert_order(db):
    """A late publish of older content must not displace newer content."""
    store = DatabaseArtifactStore(db)
    newer = _artifact(generated_at=NOW, coverage={"eligible_observations": 9})
    older = _artifact(generated_at=NOW - timedelta(days=1),
                      coverage={"eligible_observations": 1})

    store.publish(newer, published_by="pete")
    store.publish(older, published_by="pete")  # inserted last, older content

    assert db.query(ResearchArtifact).count() == 2
    assert store.load()["coverage"]["eligible_observations"] == 9


def test_history_is_retained_not_overwritten(db):
    store = DatabaseArtifactStore(db)
    for day in range(3):
        store.publish(_artifact(generated_at=NOW + timedelta(days=day),
                                coverage={"eligible_observations": day}),
                      published_by="pete")

    assert db.query(ResearchArtifact).count() == 3
    assert store.load()["coverage"]["eligible_observations"] == 2


def test_an_oversized_artifact_is_refused_not_stored(db):
    """The bound is what keeps raw payloads out of a free-tier Postgres --
    they have their own provenance path and do not belong here."""
    store = DatabaseArtifactStore(db)
    bloated = _artifact(raw_dump="x" * (MAX_ARTIFACT_BYTES + 1))

    with pytest.raises(ArtifactStoreError, match="over the"):
        store.publish(bloated, published_by="pete")

    assert db.query(ResearchArtifact).count() == 0


@pytest.mark.parametrize("artifact,fragment", [
    ({"generated_at": 12345}, "generated_at string"),
    ({"generated_at": "not-a-date"}, "ISO-8601"),
    ({"generated_at": "2026-08-02T12:00:00"}, "timezone-aware"),
])
def test_publishing_refuses_an_unusable_generated_at(db, artifact, fragment):
    with pytest.raises(ArtifactStoreError, match=fragment):
        DatabaseArtifactStore(db).publish(artifact, published_by="pete")


def test_publishing_requires_a_named_publisher(db):
    with pytest.raises(ArtifactStoreError, match="published_by"):
        DatabaseArtifactStore(db).publish(_artifact(), published_by="   ")


def test_loading_an_empty_store_is_none_not_an_error(db):
    assert DatabaseArtifactStore(db).load() is None


def test_kinds_do_not_collide(db):
    store = DatabaseArtifactStore(db)
    store.publish(_artifact(coverage={"eligible_observations": 1}),
                  kind="market_benchmark", published_by="pete")
    store.publish(_artifact(coverage={"eligible_observations": 2}),
                  kind="something_else", published_by="pete")

    assert store.load(kind="market_benchmark")[
        "coverage"]["eligible_observations"] == 1
    assert store.load(kind="something_else")[
        "coverage"]["eligible_observations"] == 2


# --- file backend ------------------------------------------------------------


def test_the_file_backend_writes_atomically_and_round_trips(tmp_path):
    store = FileArtifactStore(tmp_path / "market_benchmark.json")

    reference = store.publish(_artifact(), published_by="pete")

    assert reference.startswith("file://")
    assert store.load() == _artifact()
    assert not (tmp_path / "market_benchmark.tmp").exists(), "temp cleaned up"


def test_a_missing_file_is_none_and_a_corrupt_one_raises(tmp_path):
    path = tmp_path / "market_benchmark.json"
    assert FileArtifactStore(path).load() is None

    path.write_text("{not json")
    with pytest.raises(ArtifactStoreError, match="cannot be read"):
        FileArtifactStore(path).load()


# --- resolution order --------------------------------------------------------


def test_the_database_is_preferred_over_the_file(db, tmp_path):
    """The file cannot deliver in production, so a database row wins whenever
    both exist -- otherwise a stale image-baked file could mask fresh data."""
    path = tmp_path / "market_benchmark.json"
    FileArtifactStore(path).publish(
        _artifact(coverage={"eligible_observations": 1}), published_by="pete")
    DatabaseArtifactStore(db).publish(
        _artifact(coverage={"eligible_observations": 2}), published_by="pete")

    artifact, source = load_latest(db, path)

    assert source == "database"
    assert artifact["coverage"]["eligible_observations"] == 2


def test_the_file_is_used_when_the_database_is_empty(db, tmp_path):
    path = tmp_path / "market_benchmark.json"
    FileArtifactStore(path).publish(_artifact(), published_by="pete")

    artifact, source = load_latest(db, path)

    assert source == "file"
    assert artifact == _artifact()


def test_neither_backend_is_a_clean_no_data(db, tmp_path):
    assert load_latest(db, tmp_path / "missing.json") == (None, "none")


def test_a_missing_table_falls_back_instead_of_erroring(db, tmp_path):
    """Migrations land through refresh.yml, not on deploy, so between merge
    and the next migration run the table does not exist. That window must be
    'no data yet', never a 500."""
    db.execute(text("DROP TABLE research_artifact"))
    db.commit()
    FileArtifactStore(tmp_path / "a.json").publish(_artifact(),
                                                   published_by="pete")

    artifact, source = load_latest(db, tmp_path / "a.json")

    assert source == "file"
    assert artifact == _artifact()


def test_a_missing_table_with_no_file_is_no_data(db, tmp_path):
    db.execute(text("DROP TABLE research_artifact"))
    db.commit()

    assert load_latest(db, tmp_path / "missing.json") == (None, "none")


def test_the_digest_is_stable_and_order_independent():
    a = {"b": 1, "a": {"y": 2, "x": [3, 4]}}
    b = {"a": {"x": [3, 4], "y": 2}, "b": 1}

    assert digest(a) == digest(b)
    assert json.loads(canonical_bytes(a)) == a


# --- review round 2: concurrency, failure honesty, non-finite values ---------


def test_a_concurrent_identical_publish_resolves_to_the_winners_row(db):
    """Two publishers can both miss the SELECT and race to the INSERT. The
    loser must resolve to the winner's row as a no-op, not raise."""
    store = DatabaseArtifactStore(db)
    artifact = _artifact()
    sha = digest(artifact)

    # Simulate the race: the SELECT sees nothing (as it would for both
    # publishers), then a competitor's row lands before our commit.
    original_find = store._find
    calls = {"n": 0}

    def racing_find(kind, digest_value):
        calls["n"] += 1
        if calls["n"] == 1:
            # First lookup: as if the competitor had not committed yet.
            db.add(ResearchArtifact(
                kind=kind, artifact_version="market-benchmark-artifact-v1",
                generated_at=NOW, payload=artifact, sha256=digest_value,
                size_bytes=len(canonical_bytes(artifact)),
                published_by="competitor"))
            db.commit()
            return None
        return original_find(kind, digest_value)

    store._find = racing_find

    reference = store.publish(artifact, published_by="pete")

    assert "unchanged" in reference
    assert db.query(ResearchArtifact).count() == 1
    assert db.query(ResearchArtifact).one().published_by == "competitor"
    assert db.query(ResearchArtifact).one().sha256 == sha


def test_an_unrelated_integrity_failure_is_not_swallowed(db):
    """The IntegrityError handler resolves ONLY a byte-identical duplicate.
    Anything else must surface -- a swallowed constraint violation is a
    silent data-loss bug."""
    from sqlalchemy.exc import IntegrityError

    store = DatabaseArtifactStore(db)
    store._find = lambda kind, sha: None  # never finds a matching row

    def explode():
        raise IntegrityError("INSERT", {}, Exception("some other constraint"))

    store.db.commit = explode

    with pytest.raises(IntegrityError):
        store.publish(_artifact(), published_by="pete")


def test_a_real_database_failure_is_reported_not_disguised_as_no_data(db, tmp_path):
    """Only the not-yet-migrated table may fall back. An outage, a permission
    failure or a query bug reported as 'no data' would be a silent lie on a
    public endpoint."""
    from sqlalchemy.exc import OperationalError

    class BrokenSession:
        def query(self, *_args, **_kwargs):
            raise OperationalError("SELECT", {},
                                   Exception("connection refused"))

        def rollback(self):
            return None

    with pytest.raises(ArtifactStoreError, match="could not be read"):
        load_latest(BrokenSession(), tmp_path / "present.json")


def test_the_missing_table_is_still_the_one_accepted_fallback(db, tmp_path):
    """Distinguishes the accepted case from the rejected one above using the
    real SQLite error, not a mock."""
    FileArtifactStore(tmp_path / "a.json").publish(_artifact(),
                                                   published_by="pete")
    db.execute(text("DROP TABLE research_artifact"))
    db.commit()

    artifact, source = load_latest(db, tmp_path / "a.json")

    assert source == "file"
    assert artifact == _artifact()


def test_a_postgres_undefined_table_is_recognised_by_sqlstate(tmp_path):
    """SQLite says 'no such table'; PostgreSQL reports SQLSTATE 42P01. Both
    must be recognised, or the fallback works locally and breaks in prod."""
    from sqlalchemy.exc import ProgrammingError

    class PgUndefinedTable(Exception):
        pgcode = "42P01"

    class MissingTableSession:
        def query(self, *_args, **_kwargs):
            raise ProgrammingError("SELECT", {}, PgUndefinedTable())

        def rollback(self):
            return None

    assert load_latest(MissingTableSession(), tmp_path / "absent.json") == (
        None, "none")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused_at_the_boundary(db, value):
    """Python's json.dumps emits bare NaN/Infinity by default -- not JSON, not
    portable, and rejected by the reader's domain checks anyway. Storing one
    would persist an artifact that can never be served."""
    with pytest.raises(ArtifactStoreError, match="NaN/Infinity"):
        DatabaseArtifactStore(db).publish(
            _artifact(coverage={"eligible_observations": value}),
            published_by="pete")

    assert db.query(ResearchArtifact).count() == 0


def test_a_non_serializable_value_is_refused_with_a_different_message(db):
    with pytest.raises(ArtifactStoreError, match="not JSON-serializable"):
        DatabaseArtifactStore(db).publish(
            _artifact(coverage={"when": object()}), published_by="pete")
