"""Raw store: lossless bytes, safe paths, bounded growth, honest failures."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from pipeline.ingest.venues.types import RawDocument
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


LIFECYCLE = {"Rules": [{"Status": "Enabled", "Filter": {"Prefix": ""},
                        "Expiration": {"Days": 90}}]}


class _FakeS3:
    def __init__(self, lifecycle=LIFECYCLE):
        self.objects = {}
        self._lifecycle = lifecycle

    def get_bucket_lifecycle_configuration(self, Bucket):  # noqa: N803 - boto3 API
        if self._lifecycle is None:
            raise RuntimeError("NoSuchLifecycleConfiguration")
        return self._lifecycle

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs


def test_s3_store_writes_encrypted_json_under_a_deterministic_key():
    client = _FakeS3()
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              retention_days=90, client=client)

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
                              max_payload_bytes=100, retention_days=90,
                              client=_FakeS3())

    with pytest.raises(RawPayloadRejected):
        store.put(venue="polymarket", venue_key="0xaaa", kind="quote",
                  captured_at=NOW, payload={"filler": "x" * 500})


def test_s3_outage_is_a_transient_error():
    class Broken(_FakeS3):
        def put_object(self, **_kwargs):
            raise RuntimeError("connection reset")

    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              retention_days=90, client=Broken())

    with pytest.raises(RawStoreError) as excinfo:
        store.put(venue="polymarket", venue_key="0xaaa", kind="quote",
                  captured_at=NOW, payload=PAYLOAD)
    assert not isinstance(excinfo.value, RawPayloadRejected)


# --- lossless bytes ---------------------------------------------------------

AWKWARD = (b'{\n  "z": 1,\n  "a": "0.4300",\n  "a": "0.4301",\n'
           b'  "unicode": "Bayern M\xc3\xbcnchen"\n}\n')


def test_a_document_is_written_byte_for_byte(tmp_path):
    """The whole point of the raw store. Every one of these survives only
    because the bytes are never parsed: key order (z before a), indentation,
    the duplicate `a`, the trailing newline, and `0.4300` rather than 0.43."""
    store = FileRawPayloadStore(tmp_path)
    document = RawDocument(name="orderbook", body=AWKWARD,
                           url="https://venue.example/orderbook")

    stored = store.put_document(venue="kalshi", venue_key="KX-1", kind="quote",
                                captured_at=NOW, document=document)

    with open(stored.reference, "rb") as handle:
        assert handle.read() == AWKWARD
    assert stored.sha256 == document.sha256
    assert stored.size_bytes == len(AWKWARD)


def test_re_serializing_would_have_destroyed_that_evidence():
    """States the loss the byte path avoids, so the guarantee is not folklore."""
    reserialized = json.dumps(json.loads(AWKWARD), sort_keys=True,
                              separators=(",", ":")).encode()

    assert reserialized != AWKWARD
    assert b"0.4300" not in reserialized
    assert reserialized.count(b'"a"') == 1  # the duplicate key is gone


def test_document_name_reaches_the_filename(tmp_path):
    store = FileRawPayloadStore(tmp_path)

    stored = store.put_document(
        venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
        document=RawDocument(name="orderbook", body=b"{}"))

    assert "-quote-orderbook-" in stored.reference


def test_an_oversized_document_is_rejected_before_it_is_written(tmp_path):
    store = FileRawPayloadStore(tmp_path, max_payload_bytes=10)

    with pytest.raises(RawPayloadRejected, match="over the 10 byte bound"):
        store.put_document(venue="kalshi", venue_key="KX-1", kind="quote",
                           captured_at=NOW,
                           document=RawDocument(name="q", body=b"x" * 50))
    assert list(tmp_path.rglob("*.json")) == []


# --- retention --------------------------------------------------------------


def test_local_retention_deletes_past_the_horizon_and_keeps_the_rest(tmp_path):
    """The byte ceiling bounds each object; only this bounds the total. At a
    30-second cadence an unpruned archive grows forever."""
    import os as _os
    from datetime import timedelta

    store = FileRawPayloadStore(tmp_path, retention_days=30)
    old = store.put(venue="kalshi", venue_key="KX-1", kind="quote",
                    captured_at=NOW, payload={"n": 1})
    fresh = store.put(venue="kalshi", venue_key="KX-2", kind="quote",
                      captured_at=NOW, payload={"n": 2})
    stale = (NOW - timedelta(days=31)).timestamp()
    _os.utime(old.reference, (stale, stale))

    removed = store.prune(now=NOW)

    assert removed == 1
    assert not type(tmp_path)(old.reference).exists()
    assert type(tmp_path)(fresh.reference).exists()


def test_retention_of_zero_keeps_everything_and_must_be_deliberate(tmp_path):
    store = FileRawPayloadStore(tmp_path, retention_days=0)
    store.put(venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
              payload={"n": 1})

    assert store.prune(now=NOW) == 0
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_pruning_an_absent_root_is_not_an_error(tmp_path):
    assert FileRawPayloadStore(tmp_path / "missing", retention_days=1).prune(
        now=NOW) == 0


@pytest.mark.parametrize("lifecycle,message", [
    (None, "cannot read the lifecycle configuration"),
    ({"Rules": []}, "no enabled expiration rule"),
    ({"Rules": [{"Status": "Disabled", "Expiration": {"Days": 30}}]},
     "no enabled expiration rule"),
    ({"Rules": [{"Status": "Enabled", "Filter": {"Prefix": ""},
                 "Expiration": {"Days": 365}}]}, "longer than the configured"),
])
def test_object_storage_refuses_to_write_without_verified_expiry(lifecycle, message):
    """The worker cannot delete remote objects, so the bucket lifecycle is the
    only enforcement there is. Assuming it exists is how an archive quietly
    grows for a year -- so it is read once and a miss is a refusal."""
    with pytest.raises(RawStoreError, match=message):
        S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                          retention_days=90, client=_FakeS3(lifecycle))


def test_object_storage_refuses_an_unbounded_horizon():
    with pytest.raises(RawStoreError, match="explicit retention horizon"):
        S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                          retention_days=0, client=_FakeS3())


def test_object_storage_accepts_a_rule_that_meets_the_horizon():
    store = S3RawPayloadStore(
        bucket="raw", endpoint_url="https://r2.example", retention_days=90,
        client=_FakeS3({"Rules": [{"Status": "Enabled",
                                   "Prefix": "prediction-market",
                                   "Expiration": {"Days": 30}}]}))

    assert store.prune(now=NOW) == 0  # the bucket does the deleting


def test_object_storage_writes_documents_verbatim():
    client = _FakeS3()
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              retention_days=90, client=client)

    stored = store.put_document(
        venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
        document=RawDocument(name="orderbook", body=AWKWARD))

    written = client.objects[stored.reference.removeprefix("s3://raw/")]
    assert written["Body"] == AWKWARD


# --- credential-looking keys ------------------------------------------------


@pytest.mark.parametrize("venue_key", [
    "api_key_live_sk_1234", "Bearer_xyz", "APIKEY-9f3a", "my_secret_market",
])
def test_plain_but_credential_looking_keys_get_no_readable_path(tmp_path, venue_key):
    """Character shape is not enough. These are all alphanumeric with
    underscores and contain no separator for a scrubber to find."""
    store = FileRawPayloadStore(tmp_path)

    stored = store.put(venue="kalshi", venue_key=venue_key, kind="quote",
                       captured_at=NOW, payload=PAYLOAD)

    assert venue_key not in stored.reference
    for fragment in ("api_key", "Bearer", "APIKEY", "secret", "sk_1234"):
        assert fragment not in stored.reference


# --- round 3: And-prefix is a string, and prune fails loudly ----------------

def _and_rule(prefix, days=30):
    return {"Rules": [{"Status": "Enabled",
                       "Filter": {"And": {"Prefix": prefix,
                                          "Tag": {"Key": "k", "Value": "v"}}},
                       "Expiration": {"Days": days}}]}


def test_a_sibling_and_prefix_sharing_a_first_character_is_rejected():
    """`Filter.And.Prefix` is a STRING. Iterating it yielded characters, so a
    rule for `market-other` contributed the candidate "m" and any prefix
    starting with "m" looked covered."""
    with pytest.raises(RawStoreError, match="no enabled expiration rule"):
        S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                          prefix="market-intel", retention_days=90,
                          client=_FakeS3(_and_rule("market-other")))


def test_a_matching_and_prefix_is_accepted():
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              prefix="market-intel", retention_days=90,
                              client=_FakeS3(_and_rule("market-intel")))

    assert store.prefix == "market-intel"


def test_a_broader_and_prefix_still_covers_us():
    store = S3RawPayloadStore(bucket="raw", endpoint_url="https://r2.example",
                              prefix="market-intel/kalshi", retention_days=90,
                              client=_FakeS3(_and_rule("market-intel")))

    assert store.prefix == "market-intel/kalshi"


def test_a_prune_permission_failure_is_raised_not_swallowed(tmp_path):
    """Catching every OSError as a vanished-file race meant a read-only mount
    or a permission problem silently pruned nothing while reporting success."""
    store = FileRawPayloadStore(tmp_path, retention_days=1)
    store.put(venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
              payload=PAYLOAD)

    def boom(self):
        raise PermissionError(13, "Permission denied")

    original = type(tmp_path).unlink
    try:
        type(tmp_path).unlink = boom
        with pytest.raises(RawStoreError, match="could not delete"):
            store.prune(now=NOW + timedelta(days=400))
    finally:
        type(tmp_path).unlink = original


def test_a_vanished_file_is_still_a_benign_race(tmp_path):
    """The one case that really is harmless: another prune got there first."""
    store = FileRawPayloadStore(tmp_path, retention_days=1)
    store.put(venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
              payload=PAYLOAD)

    def vanish(self):
        raise FileNotFoundError(2, "No such file")

    original = type(tmp_path).unlink
    try:
        type(tmp_path).unlink = vanish
        assert store.prune(now=NOW + timedelta(days=400)) == 0
    finally:
        type(tmp_path).unlink = original


def test_an_unreadable_root_is_raised(tmp_path):
    store = FileRawPayloadStore(tmp_path, retention_days=1)
    store.put(venue="kalshi", venue_key="KX-1", kind="quote", captured_at=NOW,
              payload=PAYLOAD)

    def boom(self, pattern):
        raise PermissionError(13, "Permission denied")

    original = type(tmp_path).rglob
    try:
        type(tmp_path).rglob = boom
        with pytest.raises(RawStoreError, match="could not read"):
            store.prune(now=NOW)
    finally:
        type(tmp_path).rglob = original
