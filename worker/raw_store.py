"""Lossless, deterministic raw-payload storage.

The normalized tick is a lossy view; this is the record of what the venue
actually said.

:meth:`put_document` is the lossless path: it writes the exact bytes the
socket delivered, so whitespace, key order, duplicate keys and every number's
lexical form survive. :meth:`put` re-serializes a parsed mapping and is used
only for payloads we assembled ourselves -- rejected-item diagnostics and
registry-recovery stubs -- where there are no original bytes to preserve.

Growth is bounded on three axes, because a 30-second cadence writes forever:
a per-object byte ceiling, a per-cycle cap on rejected diagnostics, and a
retention horizon enforced by :meth:`prune` locally and by a **verified**
bucket lifecycle rule for object storage.

Two failure modes are distinguished, because only one is worth retrying:

* :class:`RawStoreError` -- transient IO. Retry.
* :class:`RawPayloadRejected` -- the payload cannot be stored at all (not
  JSON-serializable, or over the size bound). Retrying re-runs the same
  failure; the caller records it and moves on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping, Protocol

from pipeline.ingest.venues.redaction import looks_like_credential
from pipeline.ingest.venues.types import RawDocument

#: Path components we control (venue, kind). Anything outside this set is
#: replaced, so no separator or traversal can appear.
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")

#: A venue key is only allowed into a path VERBATIM when it is already plain:
#: alphanumerics, dot, dash, underscore, not starting with a dot, at most 64
#: characters -- AND does not trip the shared credential detector. Character
#: shape alone is not enough: `api_key_live_sk_1234` is perfectly plain.
_PLAIN_KEY = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}")


class RawStoreError(RuntimeError):
    """Transient raw-store failure. Retryable."""


class RawPayloadRejected(RawStoreError):
    """The payload cannot be stored as-is. Retrying will not help."""


@dataclass(frozen=True, slots=True)
class RawObject:
    reference: str
    sha256: str
    size_bytes: int


class RawPayloadStore(Protocol):
    def put(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> RawObject: ...

    def put_document(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        document: RawDocument,
    ) -> RawObject: ...

    def prune(self, *, now: datetime) -> int: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RawPayloadRejected("captured_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _check_size(body: bytes, max_bytes: int) -> tuple[bytes, str]:
    if max_bytes and len(body) > max_bytes:
        raise RawPayloadRejected(
            f"raw payload is {len(body)} bytes, over the {max_bytes} byte bound"
        )
    return body, hashlib.sha256(body).hexdigest()


def _encode(payload: Mapping[str, object], max_bytes: int) -> tuple[bytes, str]:
    try:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawPayloadRejected(f"raw payload is not JSON serializable: {exc}") from exc
    return _check_size(body, max_bytes)


def _key_component(venue_key: str) -> str:
    """Directory name for a market. Identity is always the digest.

    The readable prefix is a convenience, added only when the key is plain in
    shape AND clean by the shared credential detector. Shape alone would let
    `api_key_live_sk_1234` or `Bearer_xyz` straight through: both are
    alphanumeric-with-underscores and contain no separator for a scrubber to
    find. Two distinct keys never collide -- the digest is always present.
    """
    plain = venue_key.strip()
    digest = hashlib.sha256(venue_key.encode("utf-8")).hexdigest()[:12]
    readable = _PLAIN_KEY.fullmatch(plain) and not looks_like_credential(plain)
    return f"{plain}-{digest}" if readable else digest


def _path_parts(venue: str, venue_key: str, kind: str, captured_at: datetime,
                digest: str, name: str = "") -> tuple[str, str, str, str]:
    safe_venue = _SAFE.sub("-", venue.strip()).strip("-.") or "unknown"
    safe_kind = _SAFE.sub("-", kind.strip()).strip("-.") or "payload"
    safe_name = _SAFE.sub("-", name.strip()).strip("-.")
    suffix = f"-{safe_name}" if safe_name else ""
    return (
        safe_venue,
        _key_component(venue_key),
        captured_at.strftime("%Y/%m/%d"),
        captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
        + f"-{safe_kind}{suffix}-{digest[:16]}.json",
    )


class FileRawPayloadStore:
    """Private local raw store used in tests and non-production operation."""

    def __init__(self, root: Path | str, *, max_payload_bytes: int = 0,
                 retention_days: int = 0) -> None:
        self.root = Path(root)
        self.max_payload_bytes = max_payload_bytes
        self.retention_days = retention_days

    def _write(self, venue, venue_key, kind, captured_at, body, digest, name):
        captured_at = _utc(captured_at)
        venue_part, key_part, date_part, filename = _path_parts(
            venue, venue_key, kind, captured_at, digest, name
        )
        directory = self.root / venue_part / key_part / date_part
        path = directory / filename
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(body)
                os.chmod(path, 0o600)
        except OSError as exc:
            raise RawStoreError(f"raw payload write failed: {exc}") from exc
        return RawObject(
            reference=str(path.resolve()), sha256=digest, size_bytes=len(body)
        )

    def put(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> RawObject:
        body, digest = _encode(payload, self.max_payload_bytes)
        return self._write(venue, venue_key, kind, captured_at, body, digest, "")

    def put_document(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        document: RawDocument,
    ) -> RawObject:
        """Write the venue's exact bytes. Nothing is parsed or re-encoded."""
        body, digest = _check_size(document.body, self.max_payload_bytes)
        return self._write(
            venue, venue_key, kind, captured_at, body, digest, document.name
        )

    def prune(self, *, now: datetime) -> int:
        """Delete objects past the retention horizon. Returns the count.

        Without this the archive is unbounded: a 30-second cadence writes
        forever and the byte ceiling caps each object, not the total. A
        retention of 0 means keep everything, and has to be chosen explicitly.

        Only a genuine disappearance race is suppressed. A PermissionError, a
        read-only mount or an unreadable directory means retention did NOT
        happen, and swallowing that turns "bounded growth" into a claim
        nothing enforces -- so it raises, and the caller refuses to write more.
        """
        if not self.retention_days:
            return 0
        cutoff = _utc(now).timestamp() - self.retention_days * 86_400
        removed = 0
        if not self.root.exists():
            return 0
        try:
            paths = list(self.root.rglob("*.json"))
        except OSError as exc:
            raise RawStoreError(f"raw retention could not read {self.root}: {exc}") from exc
        for path in paths:
            try:
                stale = path.stat().st_mtime < cutoff
            except FileNotFoundError:
                continue  # another prune got there first
            except OSError as exc:
                raise RawStoreError(f"raw retention could not stat {path}: {exc}") from exc
            if not stale:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RawStoreError(f"raw retention could not delete {path}: {exc}") from exc
            removed += 1
        self._remove_empty_directories()
        return removed

    def _remove_empty_directories(self) -> None:
        """Tidy-up only. A directory left behind does not affect the bound."""
        try:
            directories = sorted(self.root.rglob("*"), reverse=True)
        except OSError:
            return
        for directory in directories:
            try:
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                continue


class S3RawPayloadStore:
    """Private S3-compatible store, including Cloudflare R2."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        region_name: str = "auto",
        prefix: str = "prediction-market",
        max_payload_bytes: int = 0,
        retention_days: int = 0,
        client=None,
    ) -> None:
        if not bucket.strip() or not endpoint_url.strip():
            raise RawStoreError("bucket and endpoint_url are required")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.max_payload_bytes = max_payload_bytes
        self.retention_days = retention_days
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RawStoreError(
                    "boto3 is required for the s3 raw store; it ships in "
                    "worker/requirements.txt, not the backend image"
                ) from exc
            client = boto3.client(
                "s3", endpoint_url=endpoint_url, region_name=region_name
            )
        self.client = client
        self._verify_lifecycle()

    def _verify_lifecycle(self) -> None:
        """Refuse to write unless the bucket really expires objects.

        The worker cannot delete remote objects on a schedule, so retention
        there is the bucket's job. Assuming a lifecycle rule exists is how an
        archive grows without limit for a year -- the assumption is checked
        once, at construction, and a missing or too-long rule is a refusal
        rather than a warning.
        """
        if not self.retention_days:
            raise RawStoreError(
                "s3 raw store requires an explicit retention horizon; set "
                "MARKET_CAPTURE_RAW_RETENTION_DAYS"
            )
        try:
            config = self.client.get_bucket_lifecycle_configuration(Bucket=self.bucket)
        except Exception as exc:
            raise RawStoreError(
                f"cannot read the lifecycle configuration for bucket "
                f"{self.bucket!r}, so retention cannot be guaranteed: {exc}"
            ) from exc
        rules = config.get("Rules") if isinstance(config, Mapping) else None
        horizons = [
            rule.get("Expiration", {}).get("Days")
            for rule in (rules or [])
            if isinstance(rule, Mapping)
            and str(rule.get("Status", "")).casefold() == "enabled"
            and self._rule_covers_prefix(rule)
        ]
        usable = [days for days in horizons if isinstance(days, int) and days > 0]
        if not usable:
            raise RawStoreError(
                f"bucket {self.bucket!r} has no enabled expiration rule covering "
                f"prefix {self.prefix!r}; refusing to write an archive nothing "
                "will ever delete"
            )
        if min(usable) > self.retention_days:
            raise RawStoreError(
                f"bucket {self.bucket!r} expires objects after {min(usable)} days, "
                f"longer than the configured {self.retention_days}-day retention"
            )

    def _rule_covers_prefix(self, rule: Mapping) -> bool:
        """Does this rule expire everything we write?

        The rule's prefix must be a prefix OF OURS, compared as whole strings.
        AWS supplies `Filter.And.Prefix` as a single string; iterating it
        yields characters, and a one-character candidate makes any sibling
        prefix look covered -- a rule for `market-other` would have been
        accepted as covering `market-intel` on the strength of a shared "m".
        """
        candidates: list[object] = [rule.get("Prefix")]
        rule_filter = rule.get("Filter")
        if isinstance(rule_filter, Mapping):
            candidates.append(rule_filter.get("Prefix"))
            nested = rule_filter.get("And")
            if isinstance(nested, Mapping):
                candidates.append(nested.get("Prefix"))
        for candidate in candidates:
            if candidate is None:
                continue
            text = str(candidate)
            # S3 semantics: the rule covers every key starting with its
            # prefix, so it covers us when its prefix is a prefix of ours.
            if text == "" or self.prefix.startswith(text):
                return True
        return False

    def prune(self, *, now: datetime) -> int:
        """No-op: the verified bucket lifecycle rule is the enforcement."""
        return 0

    def put(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> RawObject:
        body, digest = _encode(payload, self.max_payload_bytes)
        return self._put_object(venue, venue_key, kind, captured_at, body, digest,
                                "", "application/json")

    def put_document(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        document: RawDocument,
    ) -> RawObject:
        """Write the venue's exact bytes. Nothing is parsed or re-encoded."""
        body, digest = _check_size(document.body, self.max_payload_bytes)
        return self._put_object(venue, venue_key, kind, captured_at, body, digest,
                                document.name, document.content_type)

    def _put_object(self, venue, venue_key, kind, captured_at, body, digest,
                    name, content_type) -> RawObject:
        captured_at = _utc(captured_at)
        parts = (self.prefix,
                 *_path_parts(venue, venue_key, kind, captured_at, digest, name))
        key = "/".join(part for part in parts if part)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type or "application/json",
                ServerSideEncryption="AES256",
                Metadata={"sha256": digest},
            )
        except Exception as exc:
            raise RawStoreError(f"raw payload object write failed: {exc}") from exc
        return RawObject(
            reference=f"s3://{self.bucket}/{key}", sha256=digest, size_bytes=len(body)
        )
