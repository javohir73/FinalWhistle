"""Raw store: lossless bytes, safe paths, bounded growth, honest failures."""

from datetime import datetime, timezone
import json

import pytest

from worker.raw_store import (
    FileRawPayloadStore,
    RawPayloadRejected,
    RawStoreError,
    S3RawPayloadStore,
)

NOW = datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc)
PAYLOAD = {"b": 2, "a": [1, {"z": None}], "unicode": "Bayern München"}


def test_payload_round_trips_byte_exact_with_its_digest(tmp_path):
    store = FileRawPayloadStore(tmp_path)

    stored = store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                       captured_at=NOW, payload=PAYLOAD)

    with open(stored.reference, "rb") as handle:
        body = handle.read()
    assert json.loads(body) == PAYLOAD
    assert len(body) == stored.size_bytes
    import hashlib
    assert hashlib.sha256(body).hexdigest() == stored.sha256


def test_the_same_payload_twice_does_not_rewrite_the_object(tmp_path):
    store = FileRawPayloadStore(tmp_path)
    first = store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                      captured_at=NOW, payload=PAYLOAD)
    second = store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                       captured_at=NOW, payload=PAYLOAD)

    assert first.reference == second.reference
    assert len(list(tmp_path.rglob("*.json"))) == 1


@pytest.mark.parametrize("venue_key", [
    "../../etc/passwd", "KX/1", "KX 1?token=abc", "Authorization: Bearer xyz",
    "..", "  ", "?api_key=live_sk_1234",
])
def test_venue_controlled_strings_never_reach_the_path_verbatim(tmp_path, venue_key):
    """Keys come from a venue. A key that is not already plain is filed under
    its digest alone -- not sanitized into something that merely looks safe.

    Sanitizing is a guess about which fragments are harmless. `Bearer xyz`
    survives a character-class filter intact, and a filename is a place
    secrets get read from.
    """
    store = FileRawPayloadStore(tmp_path)

    stored = store.put(venue="kalshi", venue_key=venue_key, kind="quote",
                       captured_at=NOW, payload=PAYLOAD)

    assert tmp_path.resolve() in list(type(tmp_path)(stored.reference).parents)
    assert ".." not in stored.reference
    for fragment in ("token", "Bearer", "xyz", "api_key", "live_sk_1234", "passwd"):
        assert fragment not in stored.reference
    # Distinct keys still get distinct homes: the digest carries the identity.
    other = store.put(venue="kalshi", venue_key=venue_key + "-2", kind="quote",
                      captured_at=NOW, payload=PAYLOAD)
    assert other.reference != stored.reference


def test_an_ordinary_ticker_stays_readable_on_disk(tmp_path):
    """Real market keys are plain, so operators keep a browsable archive."""
    store = FileRawPayloadStore(tmp_path)

    stored = store.put(venue="kalshi", venue_key="KXEPLGAME-26AUG01ARSCHE-ARS",
                       kind="quote", captured_at=NOW, payload=PAYLOAD)

    assert "KXEPLGAME-26AUG01ARSCHE-ARS-" in stored.reference


def test_stored_objects_are_private(tmp_path):
    store = FileRawPayloadStore(tmp_path)

    stored = store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                       captured_at=NOW, payload=PAYLOAD)

    path = type(tmp_path)(stored.reference)
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert oct(path.parent.stat().st_mode)[-3:] == "700"


def test_oversized_payload_is_rejected_permanently_not_retried(tmp_path):
    """A venue that starts returning multi-megabyte garbage returns it every
    poll. The bound is stated, and the refusal is the non-retryable kind."""
    store = FileRawPayloadStore(tmp_path, max_payload_bytes=200)

    with pytest.raises(RawPayloadRejected, match="over the 200 byte bound"):
        store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                  captured_at=NOW, payload={"filler": "x" * 500})

    assert list(tmp_path.rglob("*.json")) == []


def test_unserializable_payload_is_rejected_permanently(tmp_path):
    store = FileRawPayloadStore(tmp_path)

    with pytest.raises(RawPayloadRejected, match="not JSON serializable"):
        store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                  captured_at=NOW, payload={"when": object()})


def test_naive_capture_time_is_rejected(tmp_path):
    with pytest.raises(RawPayloadRejected, match="timezone-aware"):
        FileRawPayloadStore(tmp_path).put(
            venue="kalshi", venue_key="KX-1", kind="quote",
            captured_at=NOW.replace(tzinfo=None), payload=PAYLOAD)


def test_a_rejected_payload_is_also_a_raw_store_error():
    """Callers that only know about RawStoreError still catch it; the retry
    loop is what distinguishes them."""
    assert issubclass(RawPayloadRejected, RawStoreError)


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs


def test_s3_store_writes_encrypted_json_under_a_deterministic_key():
    client = _FakeS3()
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              client=client)

    stored = store.put(venue="polymarket", venue_key="0xaaa", kind="settlement",
                       captured_at=NOW, payload=PAYLOAD)

    key = stored.reference.removeprefix("s3://raw/")
    written = client.objects[key]
    assert key.startswith("prediction-market/polymarket/")
    assert written["ServerSideEncryption"] == "AES256"
    assert written["Metadata"]["sha256"] == stored.sha256
    assert json.loads(written["Body"]) == PAYLOAD


def test_s3_store_enforces_the_same_size_bound():
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              max_payload_bytes=100, client=_FakeS3())

    with pytest.raises(RawPayloadRejected):
        store.put(venue="polymarket", venue_key="0xaaa", kind="quote",
                  captured_at=NOW, payload={"filler": "x" * 500})


def test_s3_outage_is_a_transient_error():
    class Broken:
        def put_object(self, **_kwargs):
            raise RuntimeError("connection reset")

    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              client=Broken())

    with pytest.raises(RawStoreError) as excinfo:
        store.put(venue="polymarket", venue_key="0xaaa", kind="quote",
                  captured_at=NOW, payload=PAYLOAD)
    assert not isinstance(excinfo.value, RawPayloadRejected)
