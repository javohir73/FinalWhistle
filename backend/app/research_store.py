"""Provider-neutral persistence boundary for research artifacts.

Two backends behind one protocol, so the delivery mechanism is a deployment
choice rather than something welded into the API:

* :class:`FileArtifactStore` -- the local-development path. Unchanged
  behaviour, and honest about its limit: it cannot deliver in production.
* :class:`DatabaseArtifactStore` -- durable and reachable from an ephemeral
  CI runner AND from the API container, using the ``DATABASE_URL`` that
  already exists on both sides. No new service, no new secret, no cost.

**Disabled by default.** Nothing publishes anywhere unless an operator names
a destination. The reader prefers the database, falls back to the file, and
falls back again to "no data" -- and a missing ``research_artifact`` table is
one of those fallbacks, not a 500. That matters because this repository
applies migrations through ``refresh.yml`` rather than on deploy, so code
that depended on a table existing would break the API in the window between
merging and the next migration run. Here the window is simply "no data yet".

Only small aggregate research JSON belongs in the database. Raw venue
payloads keep their own provenance path (``venue_price_tick.raw_payload_ref``
into the raw store) and are refused here by the size bound.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import ResearchArtifact

#: Aggregate research JSON is small. A megabyte is generous for metrics and
#: counts and far below anything resembling a raw payload dump, so the bound
#: doubles as the enforcement of "raw bytes do not belong in Postgres".
MAX_ARTIFACT_BYTES = 1_000_000

MARKET_BENCHMARK_KIND = "market_benchmark"


class ArtifactStoreError(RuntimeError):
    """The artifact cannot be stored as given. Not retryable."""


def canonical_bytes(artifact: dict) -> bytes:
    """The exact bytes a digest is taken over. Stable across processes.

    ``allow_nan=False`` matters: Python's default emits bare ``NaN`` and
    ``Infinity``, which are not JSON, are not portable across parsers, and
    are rejected by the reader's domain checks anyway. Letting them cross
    the boundary stores an artifact that can never be served -- refuse them
    here, where the error can still name the problem.
    """
    try:
        return json.dumps(artifact, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except ValueError as exc:
        raise ArtifactStoreError(
            f"artifact contains a value JSON cannot represent "
            f"(NaN/Infinity are not valid JSON): {exc}") from exc
    except TypeError as exc:
        raise ArtifactStoreError(
            f"artifact is not JSON-serializable: {exc}") from exc


def digest(artifact: dict) -> str:
    return hashlib.sha256(canonical_bytes(artifact)).hexdigest()


class ArtifactStore(Protocol):
    def publish(self, artifact: dict, *, kind: str, published_by: str) -> str: ...

    #: Returns whatever was stored, or None when nothing is stored. A stored
    #: value that is not a valid artifact is returned AS-IS so the reader's
    #: allowlist can reject it by name -- reporting "no data" for a file that
    #: exists and is wrong would hide the actual problem.
    def load(self, *, kind: str) -> object | None: ...


def _generated_at(artifact: dict) -> datetime:
    raw = artifact.get("generated_at")
    if not isinstance(raw, str):
        raise ArtifactStoreError("artifact has no generated_at string")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ArtifactStoreError(
            f"artifact generated_at {raw!r} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ArtifactStoreError("artifact generated_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class FileArtifactStore:
    """Local-development store. Writes atomically; cannot reach production."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def publish(self, artifact: dict, *, kind: str = MARKET_BENCHMARK_KIND,
                published_by: str = "operator") -> str:
        body, _ = _encoded(artifact)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(body + b"\n")
        temporary.replace(self.path)
        return f"file://{self.path}"

    def load(self, *, kind: str = MARKET_BENCHMARK_KIND) -> object | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactStoreError(
                f"artifact file cannot be read: {exc}") from exc


def _encoded(artifact: dict) -> tuple[bytes, str]:
    if not isinstance(artifact, dict):
        raise ArtifactStoreError("artifact must be an object")
    body = canonical_bytes(artifact)
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ArtifactStoreError(
            f"artifact is {len(body)} bytes, over the {MAX_ARTIFACT_BYTES} "
            "byte bound; only aggregate research JSON belongs in the "
            "database -- raw payloads keep their own provenance path"
        )
    return body, hashlib.sha256(body).hexdigest()


class DatabaseArtifactStore:
    """Durable, append-only store both CI and the API can reach."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def publish(self, artifact: dict, *, kind: str = MARKET_BENCHMARK_KIND,
                published_by: str = "operator") -> str:
        body, sha = _encoded(artifact)
        generated_at = _generated_at(artifact)
        if not str(published_by).strip():
            raise ArtifactStoreError("published_by must name who published")
        existing = self._find(kind, sha)
        if existing is not None:
            # Byte-identical replay is a no-op: re-running the generator on
            # unchanged data must not grow the table.
            return f"db://research_artifact/{existing.id} (unchanged)"
        row = ResearchArtifact(
            kind=kind,
            artifact_version=str(artifact.get("artifact_version") or "unknown"),
            generated_at=generated_at,
            payload=artifact,
            sha256=sha,
            size_bytes=len(body),
            published_by=published_by.strip(),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            # Two publishers can both miss the SELECT above and race to the
            # INSERT; the loser gets the uniqueness violation. Byte-identical
            # content means the winner already stored exactly what we have,
            # so resolve to their row. If no matching row appears, the
            # violation was something else entirely -- do not swallow it.
            self.db.rollback()
            winner = self._find(kind, sha)
            if winner is None:
                raise
            return f"db://research_artifact/{winner.id} (unchanged)"
        return f"db://research_artifact/{row.id}"

    def _find(self, kind: str, sha: str) -> ResearchArtifact | None:
        return (
            self.db.query(ResearchArtifact)
            .filter_by(kind=kind, sha256=sha)
            .one_or_none()
        )

    def load(self, *, kind: str = MARKET_BENCHMARK_KIND) -> object | None:
        """Latest by GENERATOR time, tie-broken by insertion order.

        Ordering on generated_at rather than created_at means a late publish
        of older content cannot displace newer content.
        """
        row = (
            self.db.query(ResearchArtifact)
            .filter_by(kind=kind)
            .order_by(ResearchArtifact.generated_at.desc(),
                      ResearchArtifact.id.desc())
            .first()
        )
        return None if row is None else row.payload


#: PostgreSQL SQLSTATE for "relation does not exist".
_UNDEFINED_TABLE = "42P01"


def _is_missing_table(exc: SQLAlchemyError) -> bool:
    """Is this specifically the not-yet-migrated table, and nothing else?

    Only this one condition may fall back. An outage, a permission failure, a
    corrupt schema or a query bug reported as "no data" would be a silent lie
    on a public endpoint -- the operator would see an empty research page and
    conclude no artifact had been published.
    """
    original = getattr(exc, "orig", None)
    if original is None:
        return False
    if getattr(original, "pgcode", None) == _UNDEFINED_TABLE:
        return True
    text = str(original).lower()
    return "no such table" in text or "undefinedtable" in text


def load_latest(db: Session | None, file_path: Path | None, *,
                kind: str = MARKET_BENCHMARK_KIND) -> tuple[object | None, str]:
    """Resolve an artifact through the boundary. Returns (artifact, source).

    Database first because it is the only backend that can deliver in
    production; then the file, which is how local development works; then
    nothing.

    A table that does not exist yet is the ONE accepted fallback: migrations
    land through refresh.yml rather than on deploy, so between merge and the
    next migration run the table is genuinely absent and "no data yet" is the
    truth. Every other database failure raises, so the endpoint reports
    `unreadable` rather than dressing an outage up as an empty result.
    """
    if db is not None:
        try:
            artifact = DatabaseArtifactStore(db).load(kind=kind)
        except SQLAlchemyError as exc:
            db.rollback()
            if not _is_missing_table(exc):
                raise ArtifactStoreError(
                    f"the artifact database could not be read: {exc}") from exc
            artifact = None
        else:
            if artifact is not None:
                return artifact, "database"
    if file_path is not None:
        artifact = FileArtifactStore(file_path).load(kind=kind)
        if artifact is not None:
            return artifact, "file"
    return None, "none"
