"""The secret must not survive, whatever shape it arrives in."""

import pytest

from pipeline.ingest.venues.redaction import looks_like_credential, redact

SECRET = "sk-live-9f3a2b"


@pytest.mark.parametrize("message", [
    f"GET /orderbook failed, Authorization: Bearer {SECRET}",
    f"Authorization={SECRET}",
    f"api_key: {SECRET}",
    f"api-key = {SECRET}",
    f"apikey:{SECRET}",
    f"token={SECRET};retry",
    f"secret: {SECRET}",
    f"password={SECRET}",
    f"Bearer {SECRET}",
    f"connect failed (Authorization: Bearer {SECRET}) after 3 tries",
    # Structured bodies. A venue error is usually serialized, not prose.
    f'{{"apiKey":"{SECRET}"}}',
    f'{{"api_key": "{SECRET}", "retry": true}}',
    f"{{'api_key':'{SECRET}'}}",
    f"{{'token': '{SECRET}'}}",
    f'venue rejected request: {{"Authorization":"Bearer {SECRET}"}}',
])
def test_the_secret_never_survives(message):
    cleaned = redact(message)

    assert SECRET not in cleaned
    assert "[REDACTED]" in cleaned


def test_the_label_is_kept_so_the_error_stays_diagnosable():
    assert redact(f"Authorization: Bearer {SECRET}") == "Authorization: [REDACTED]"
    assert redact(f"api_key={SECRET}") == "api_key=[REDACTED]"
    assert redact(f'{{"apiKey":"{SECRET}"}}') == '{"apiKey":"[REDACTED]"}'


def test_ordinary_prose_is_left_alone():
    assert redact("read timed out after 15s") == "read timed out after 15s"
    assert redact("404 market not found") == "404 market not found"


@pytest.mark.parametrize("text", [
    "api_key_live_sk_1234", "Bearer_xyz", "APIKEY-9f3a", "my-secret-market",
    "authorization", "sk_live_abc", f"api_key={SECRET}", '{"apiKey":"x"}',
])
def test_credential_looking_strings_are_refused_a_readable_path(text):
    """Broader than redaction on purpose: `api_key_live_sk_1234` has no
    separator for a scrubber to find, and still must not become a filename."""
    assert looks_like_credential(text) is True


@pytest.mark.parametrize("text", [
    "KXEPLGAME-26AUG01ARSCHE-ARS", "0xaaa", "match_winner", "kalshi",
])
def test_ordinary_market_keys_are_allowed_a_readable_path(text):
    assert looks_like_credential(text) is False
