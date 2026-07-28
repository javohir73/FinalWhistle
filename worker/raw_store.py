"""Lossless, deterministic raw-payload storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping, Protocol

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


class RawStoreError(RuntimeError):
    pass


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
        raise RawStoreError("captured_at must be timezone-aware")
    return value.astimezone(timezone.utc)


class FileRawPayloadStore:
    """Private local raw store used in tests and non-production operation."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

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
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RawStoreError(f"raw payload is not JSON serializable: {exc}") from exc
        digest = hashlib.sha256(body).hexdigest()
        key_digest = hashlib.sha256(venue_key.encode("utf-8")).hexdigest()[:12]
        safe_venue = _SAFE.sub("-", venue.strip()).strip("-") or "unknown"
        safe_kind = _SAFE.sub("-", kind.strip()).strip("-") or "payload"
        safe_key = _SAFE.sub("-", venue_key.strip()).strip("-")[:64] or "key"
        directory = (
            self.root
            / safe_venue
            / f"{safe_key}-{key_digest}"
            / captured_at.strftime("%Y/%m/%d")
        )
        filename = (
            captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
            + f"-{safe_kind}-{digest[:16]}.json"
        )
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
        client=None,
    ) -> None:
        if not bucket.strip() or not endpoint_url.strip():
            raise RawStoreError("bucket and endpoint_url are required")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RawStoreError("boto3 is required for the s3 raw store") from exc
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
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RawStoreError(f"raw payload is not JSON serializable: {exc}") from exc
        digest = hashlib.sha256(body).hexdigest()
        key_digest = hashlib.sha256(venue_key.encode("utf-8")).hexdigest()[:12]
        safe_venue = _SAFE.sub("-", venue.strip()).strip("-") or "unknown"
        safe_kind = _SAFE.sub("-", kind.strip()).strip("-") or "payload"
        safe_key = _SAFE.sub("-", venue_key.strip()).strip("-")[:64] or "key"
        parts = [
            self.prefix,
            safe_venue,
            f"{safe_key}-{key_digest}",
            captured_at.strftime("%Y/%m/%d"),
            captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
            + f"-{safe_kind}-{digest[:16]}.json",
        ]
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
            reference=f"s3://{self.bucket}/{key}",
            sha256=digest,
            size_bytes=len(body),
        )
