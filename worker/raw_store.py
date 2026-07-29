"""Lossless, deterministic raw-payload storage.

The normalized tick is a lossy view; this is the record of what the venue
actually said. Payloads are written byte-exact with a content digest, never
rewritten, and never parsed on the way in.

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

#: Path components we control (venue, kind). Anything outside this set is
#: replaced, so no separator or traversal can appear.
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")

#: A venue key is only allowed into a path VERBATIM when it is already plain:
#: alphanumerics, dot, dash, underscore, not starting with a dot, at most 64
#: characters. Real market tickers qualify. Anything else -- a key carrying a
#: separator, whitespace, a query string, or credential-looking text -- is
#: filed under its digest alone rather than sanitized into something that
#: merely looks harmless. Sanitizing is a guess; refusing is not.
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RawPayloadRejected("captured_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _encode(payload: Mapping[str, object], max_bytes: int) -> tuple[bytes, str]:
    try:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawPayloadRejected(f"raw payload is not JSON serializable: {exc}") from exc
    if max_bytes and len(body) > max_bytes:
        raise RawPayloadRejected(
            f"raw payload is {len(body)} bytes, over the {max_bytes} byte bound"
        )
    return body, hashlib.sha256(body).hexdigest()


def _key_component(venue_key: str) -> str:
    """Directory name for a market. Identity is always the digest.

    The readable prefix is a convenience and is only added when the key was
    already plain, so nothing venue-controlled has to be rewritten to be made
    safe. Two distinct keys never collide: the digest is always present.
    """
    plain = venue_key.strip()
    digest = hashlib.sha256(venue_key.encode("utf-8")).hexdigest()[:12]
    return f"{plain}-{digest}" if _PLAIN_KEY.fullmatch(plain) else digest


def _path_parts(venue: str, venue_key: str, kind: str, captured_at: datetime,
                digest: str) -> tuple[str, str, str, str]:
    safe_venue = _SAFE.sub("-", venue.strip()).strip("-.") or "unknown"
    safe_kind = _SAFE.sub("-", kind.strip()).strip("-.") or "payload"
    return (
        safe_venue,
        _key_component(venue_key),
        captured_at.strftime("%Y/%m/%d"),
        captured_at.strftime("%Y%m%dT%H%M%S.%fZ") + f"-{safe_kind}-{digest[:16]}.json",
    )


class FileRawPayloadStore:
    """Private local raw store used in tests and non-production operation."""

    def __init__(self, root: Path | str, *, max_payload_bytes: int = 0) -> None:
        self.root = Path(root)
        self.max_payload_bytes = max_payload_bytes

    def put(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> RawObject:
        captured_at = _utc(captured_at)
        body, digest = _encode(payload, self.max_payload_bytes)
        venue_part, key_part, date_part, filename = _path_parts(
            venue, venue_key, kind, captured_at, digest
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
        client=None,
    ) -> None:
        if not bucket.strip() or not endpoint_url.strip():
            raise RawStoreError("bucket and endpoint_url are required")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.max_payload_bytes = max_payload_bytes
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

    def put(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> RawObject:
        captured_at = _utc(captured_at)
        body, digest = _encode(payload, self.max_payload_bytes)
        parts = (self.prefix, *_path_parts(venue, venue_key, kind, captured_at, digest))
        key = "/".join(part for part in parts if part)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
                ServerSideEncryption="AES256",
                Metadata={"sha256": digest},
            )
        except Exception as exc:
            raise RawStoreError(f"raw payload object write failed: {exc}") from exc
        return RawObject(
            reference=f"s3://{self.bucket}/{key}", sha256=digest, size_bytes=len(body)
        )
