"""Tests for app.cache.InMemoryCache's per-key TTL override + invalidate
(league pivot: Opus review of PR #171, item 2)."""
import time

from app.cache import InMemoryCache


def test_default_ttl_entry_does_not_expire_immediately():
    c = InMemoryCache(ttl_seconds=600)
    c.set("k", "v")
    expires_at, _ = c._store["k"]
    assert expires_at - time.time() > 500  # close to the full 600s window


def test_set_accepts_a_shorter_per_key_ttl_override():
    c = InMemoryCache(ttl_seconds=600)
    c.set("short", "v", ttl_seconds=1)
    c.set("long", "v")
    short_expires, _ = c._store["short"]
    long_expires, _ = c._store["long"]
    assert short_expires < long_expires
    assert short_expires - time.time() <= 1.5


def test_short_ttl_entry_expires_and_falls_back_to_none():
    c = InMemoryCache(ttl_seconds=600)
    c.set("k", "v", ttl_seconds=0.01)
    time.sleep(0.02)
    assert c.get("k") is None


def test_invalidate_drops_one_key_without_touching_others():
    c = InMemoryCache(ttl_seconds=600)
    c.set("a", "1")
    c.set("b", "2")
    c.invalidate("a")
    assert c.get("a") is None
    assert c.get("b") == "2"


def test_invalidate_missing_key_is_a_safe_no_op():
    c = InMemoryCache(ttl_seconds=600)
    c.invalidate("nope")  # must not raise
