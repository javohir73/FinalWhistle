"""Settings validation and the two fail-closed defaults."""

from dataclasses import fields
from pathlib import Path

import pytest

import worker.config
from worker.config import CaptureSettings


def test_capture_is_disabled_by_default_and_says_why():
    settings = CaptureSettings()

    assert settings.enabled is False
    assert "MARKET_CAPTURE_ENABLED" in settings.refuse_reason()


def test_an_absent_allowlist_refuses_and_is_never_read_as_capture_all():
    """The failure mode being closed off: a worker started with no market list
    quietly polling an entire venue catalogue against a public rate limit."""
    settings = CaptureSettings(enabled=True)

    reason = settings.refuse_reason()
    assert "MARKET_CAPTURE_MARKET_KEYS" in reason
    assert "never read as 'capture every market'" in reason


@pytest.mark.parametrize("allowlist", [(), ("",), ("  ", ""),])
def test_blank_allowlist_entries_do_not_count_as_a_decision(allowlist):
    assert CaptureSettings(enabled=True, market_key_allowlist=allowlist
                           ).refuse_reason() is not None


def test_a_complete_configuration_is_allowed_to_run():
    settings = CaptureSettings(enabled=True, market_key_allowlist=("kalshi:KX-1",))

    assert settings.refuse_reason() is None


def test_env_defaults_are_inert(monkeypatch):
    monkeypatch.delenv("MARKET_CAPTURE_ENABLED", raising=False)
    monkeypatch.delenv("MARKET_CAPTURE_MARKET_KEYS", raising=False)

    settings = CaptureSettings.from_env()

    assert settings.enabled is False
    assert settings.market_key_allowlist == ()
    assert settings.refuse_reason() is not None


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False), ("", False),
])
def test_enable_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("MARKET_CAPTURE_ENABLED", raw)
    assert CaptureSettings.from_env().enabled is expected


def test_ambiguous_enable_flag_is_an_error_not_a_guess(monkeypatch):
    monkeypatch.setenv("MARKET_CAPTURE_ENABLED", "maybe")
    with pytest.raises(ValueError, match="boolean"):
        CaptureSettings.from_env()


def test_allowlist_entries_must_be_venue_qualified():
    with pytest.raises(ValueError, match="venue:venue_key"):
        CaptureSettings(market_key_allowlist=("KX-1",))


def test_there_is_no_concurrency_setting(monkeypatch):
    """It was declared and never implemented. A knob that does nothing is a
    worse lie than an absent one -- run_all is serial and says so."""
    assert "concurrency" not in {f.name for f in fields(CaptureSettings)}

    monkeypatch.setenv("MARKET_CAPTURE_CONCURRENCY", "8")
    settings = CaptureSettings.from_env()
    assert not hasattr(settings, "concurrency")
    source = Path(worker.config.__file__).read_text()
    assert "MARKET_CAPTURE_CONCURRENCY" not in source


@pytest.mark.parametrize("kwargs", [
    {"enabled_venues": ()},
    {"worker_id": "  "},
    {"registry_scope": "everything"},
    {"raw_store_backend": "gcs"},
    {"raw_store_backend": "s3"},
    {"retry_limit": -1},
    {"max_raw_payload_bytes": 0},
    {"max_rejected_payloads_per_cycle": -1},
    {"backoff_initial_seconds": 9.0, "backoff_max_seconds": 8.0},
    {"inplay_seconds": 0},
])
def test_invalid_settings_are_refused(kwargs):
    with pytest.raises(ValueError):
        CaptureSettings(**kwargs)


def test_venues_are_normalized_and_deduplicated():
    settings = CaptureSettings(enabled_venues=("Kalshi", " kalshi ", "POLYMARKET"))

    assert settings.enabled_venues == ("kalshi", "polymarket")
