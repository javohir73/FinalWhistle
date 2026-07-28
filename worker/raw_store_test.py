from datetime import datetime, timezone
import json

import pytest

from worker.raw_store import FileRawPayloadStore, RawStoreError, S3RawPayloadStore

NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


def test_file_store_is_deterministic_private_and_integrity_checked(tmp_path):
    store = FileRawPayloadStore(tmp_path)
    kwargs = {
        "venue": "kalshi",
        "venue_key": "KX/unsafe",
        "kind": "quote",
        "captured_at": NOW,
        "payload": {"book": {"yes": [["0.4", "3"]]}},
    }

    first = store.put(**kwargs)
    second = store.put(**kwargs)

    assert first == second
    path = tmp_path / first.reference.removeprefix(str(tmp_path) + "/")
    assert json.loads(path.read_text()) == kwargs["payload"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert first.size_bytes == path.stat().st_size
    assert "KX-unsafe" in str(path)


def test_different_payload_gets_different_integrity_key(tmp_path):
    store = FileRawPayloadStore(tmp_path)
    common = dict(venue="kalshi", venue_key="KX", kind="quote", captured_at=NOW)

    first = store.put(**common, payload={"value": 1})
    second = store.put(**common, payload={"value": 2})

    assert first.reference != second.reference
    assert first.sha256 != second.sha256


def test_store_rejects_naive_time_and_non_json_payload(tmp_path):
    store = FileRawPayloadStore(tmp_path)
    with pytest.raises(RawStoreError, match="timezone-aware"):
        store.put(
            venue="x",
            venue_key="y",
            kind="quote",
            captured_at=NOW.replace(tzinfo=None),
            payload={},
        )
    with pytest.raises(RawStoreError, match="not JSON serializable"):
        store.put(
            venue="x",
            venue_key="y",
            kind="quote",
            captured_at=NOW,
            payload={"bad": object()},
        )


def test_s3_store_writes_private_encrypted_object_with_integrity_metadata():
    class Client:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)

    client = Client()
    store = S3RawPayloadStore(
        bucket="private-capture",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        client=client,
    )

    result = store.put(
        venue="polymarket",
        venue_key="0xabc",
        kind="quote",
        captured_at=NOW,
        payload={"book": []},
    )

    call = client.calls[0]
    assert call["Bucket"] == "private-capture"
    assert call["ServerSideEncryption"] == "AES256"
    assert "ACL" not in call
    assert call["Metadata"]["sha256"] == result.sha256
    assert result.reference.startswith("s3://private-capture/prediction-market/")
