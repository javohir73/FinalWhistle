from pathlib import Path

import pytest

from worker.config import CaptureSettings


def test_defaults_are_safe_and_separate_pre_match_from_in_play():
    settings = CaptureSettings()

    assert settings.inplay_seconds < settings.prematch_seconds
    assert settings.concurrency == 1
    assert settings.order_book_top_n == 10
    assert settings.discovery_seconds == 21_600
    assert settings.max_markets_per_venue == 5
    assert settings.registry_scope == "eligible"


def test_from_env_parses_overrides(monkeypatch):
    monkeypatch.setenv("MARKET_CAPTURE_VENUES", "kalshi")
    monkeypatch.setenv("MARKET_CAPTURE_INPLAY_SECONDS", "15")
    monkeypatch.setenv("MARKET_CAPTURE_CONCURRENCY", "4")
    monkeypatch.setenv("MARKET_CAPTURE_MARKET_KEYS", "kalshi:K1, polymarket:0xabc")
    monkeypatch.setenv("MARKET_CAPTURE_MAX_MARKETS_PER_VENUE", "2")
    monkeypatch.setenv("MARKET_CAPTURE_REGISTRY_SCOPE", "all")
    monkeypatch.setenv("MARKET_CAPTURE_RAW_STORE_PATH", "/tmp/capture-test")

    settings = CaptureSettings.from_env()

    assert settings.enabled_venues == ("kalshi",)
    assert settings.inplay_seconds == 15
    assert settings.concurrency == 4
    assert settings.market_key_allowlist == ("kalshi:K1", "polymarket:0xabc")
    assert settings.max_markets_per_venue == 2
    assert settings.registry_scope == "all"
    assert settings.raw_store_path == Path("/tmp/capture-test")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled_venues": ()},
        {"prematch_seconds": 0},
        {"retry_limit": -1},
        {"backoff_initial_seconds": 2, "backoff_max_seconds": 1},
        {"order_book_top_n": 0},
        {"max_markets_per_venue": 0},
        {"market_key_allowlist": ("missing-venue-qualifier",)},
        {"registry_scope": "everything"},
    ],
)
def test_invalid_settings_fail_fast(kwargs):
    with pytest.raises(ValueError):
        CaptureSettings(**kwargs)
