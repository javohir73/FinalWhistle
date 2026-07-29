"""Redaction: the secret must not survive, whatever shape it arrives in."""

import pytest

from worker.redaction import redact

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
])
def test_the_secret_never_survives(message):
    cleaned = redact(message)

    assert SECRET not in cleaned
    assert "[REDACTED]" in cleaned


def test_the_label_is_kept_so_the_error_stays_diagnosable():
    assert redact(f"Authorization: Bearer {SECRET}") == "Authorization: [REDACTED]"
    assert redact(f"api_key={SECRET}") == "api_key=[REDACTED]"


def test_ordinary_prose_is_left_alone():
    """Over-redaction is safe but useless; a message that says nothing is not
    worth storing."""
    assert redact("read timed out after 15s") == "read timed out after 15s"
    assert redact("404 market not found") == "404 market not found"
