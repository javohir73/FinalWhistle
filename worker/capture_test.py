from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import requests

from app.models import CaptureHeartbeat, VenueMarket as VenueMarketRow, VenuePriceTick
from pipeline.ingest.venues.types import (
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueMarket,
    VenuePayloadError,
)
from worker.capture import CaptureWorker
from worker.config import CaptureSettings
from worker.raw_store import RawObject, RawStoreError

NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parents[1] / "pipeline" / "ingest" / "testdata"


def _market(key="M1", status="open", *, live=None):
    event = {} if live is None else {"live": live}
    return VenueMarket(
        venue="fixture",
        venue_key=key,
        sport="football",
        raw_title=f"title {key}",
        status=status,
        discovered_at=NOW,
        market_type="moneyline",
        raw_payload={"event": event, "market": {"key": key}},
    )


def _quote(key="M1", *, source_ts=None):
    return Quote(
        venue="fixture",
        venue_key=key,
        observed_at=NOW,
        transport="polling",
        book=OrderBook(
            yes_bids=(OrderBookLevel(0.4, 3),),
            yes_asks=(OrderBookLevel(0.5, 4),),
        ),
        last=0.45,
        source_ts=source_ts,
        raw_payload={"book": key},
    )


class FixtureAdapter:
    venue = "fixture"

    def __init__(self, markets, *, quotes=None, settlements=None):
        self.markets = markets
        self.quotes = list(quotes or [])
        self.settlements = list(settlements or [])
        self.discover_calls = 0
        self.quote_calls = 0
        self.settlement_calls = 0

    def discover_markets(self, sport):
        self.discover_calls += 1
        if isinstance(self.markets, Exception):
            raise self.markets
        return self.markets

    def fetch_quote(self, venue_key):
        self.quote_calls += 1
        result = self.quotes.pop(0) if self.quotes else _quote(venue_key)
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_settlement(self, venue_key):
        self.settlement_calls += 1
        result = self.settlements.pop(0) if self.settlements else None
        if isinstance(result, Exception):
            raise result
        return result


class MemoryRawStore:
    def __init__(self, failure=None):
        self.failure = failure
        self.items = []

    def put(self, **kwargs):
        if self.failure:
            raise self.failure
        self.items.append(kwargs)
        return RawObject(
            reference=f"memory://{kwargs['venue']}/{kwargs['venue_key']}/{kwargs['kind']}",
            sha256="a" * 64,
            size_bytes=1,
        )


def _worker(db_session, adapter, store=None, **kwargs):
    settings = kwargs.pop(
        "settings",
        CaptureSettings(
            enabled_venues=("fixture",),
            worker_id="test-worker",
            retry_limit=0,
        ),
    )
    return CaptureWorker(
        db=db_session,
        adapters={"fixture": adapter},
        raw_store=store or MemoryRawStore(),
        settings=settings,
        now=lambda: NOW,
        monotonic=lambda: 1.0,
        sleep=kwargs.pop("sleep", lambda _seconds: None),
        jitter=lambda: 0.0,
        **kwargs,
    )


def test_successful_cycle_upserts_registry_tick_settlement_raw_and_heartbeat(db_session):
    settlement = Settlement(
        venue="fixture",
        venue_key="M2",
        status="settled",
        settled_at=NOW,
        source="fixture/M2",
        outcome="yes",
        source_event_id="resolution-1",
        raw_payload={"result": "yes"},
    )
    adapter = FixtureAdapter(
        [_market(), _market("M2", "closed")], settlements=[settlement]
    )
    store = MemoryRawStore()
    worker = _worker(db_session, adapter, store, fixture_state=lambda _market: False)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["success_count"] == 1
    assert result["error_count"] == 0
    assert db_session.query(VenueMarketRow).count() == 2
    assert db_session.query(VenuePriceTick).count() == 1
    tick = db_session.query(VenuePriceTick).one()
    assert (tick.yes_bid, tick.yes_ask, tick.mid) == (0.4, 0.5, 0.45)
    assert tick.book_top_n["yes_bids"] == [{"price": 0.4, "size": 3}]
    settled = db_session.query(VenueMarketRow).filter_by(venue_key="M2").one()
    assert (settled.status, settled.settled_outcome) == ("settled", "yes")
    heartbeat = db_session.query(CaptureHeartbeat).one()
    assert heartbeat.markets_seen == 2
    assert heartbeat.success_count == 1
    assert {item["kind"] for item in store.items} == {
        "discovery",
        "quote",
        "settlement",
    }


def test_replaying_same_cycle_is_idempotent(db_session):
    adapter = FixtureAdapter([_market()])
    store = MemoryRawStore()
    worker = _worker(db_session, adapter, store)

    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)
    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert db_session.query(VenueMarketRow).count() == 1
    assert db_session.query(VenuePriceTick).count() == 1
    assert db_session.query(CaptureHeartbeat).count() == 1
    assert adapter.discover_calls == 1
    assert adapter.quote_calls == 1
    assert [item["kind"] for item in store.items] == ["discovery", "quote"]


def test_per_market_validation_failure_keeps_siblings_and_rejected_raw(db_session):
    rejected = {"bad": "book"}
    adapter = FixtureAdapter(
        [_market("BAD"), _market("GOOD")],
        quotes=[VenuePayloadError("bad level", raw_payload=rejected), _quote("GOOD")],
    )
    store = MemoryRawStore()
    worker = _worker(db_session, adapter, store)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["success_count"] == 1
    assert result["error_count"] == 1
    assert db_session.query(VenueMarketRow).count() == 2
    assert db_session.query(VenuePriceTick).count() == 1
    assert any(item["kind"] == "rejected" for item in store.items)


def test_stale_quote_and_fixture_disagreement_are_flagged(db_session):
    adapter = FixtureAdapter(
        [_market(live=True)],
        quotes=[_quote(source_ts=NOW - timedelta(minutes=10))],
    )
    worker = _worker(db_session, adapter, fixture_state=lambda _market: False)

    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    tick = db_session.query(VenuePriceTick).one()
    assert tick.is_in_play is False
    assert set(tick.validation_flags) == {
        "fixture_venue_state_disagreement",
        "stale_source_timestamp",
    }


def test_bounded_backoff_and_retry_counts_are_recorded(db_session):
    class FlakyAdapter(FixtureAdapter):
        def discover_markets(self, sport):
            self.discover_calls += 1
            if self.discover_calls < 3:
                raise requests.ConnectionError("temporary")
            return [_market()]

    sleeps = []
    adapter = FlakyAdapter([])
    settings = CaptureSettings(
        enabled_venues=("fixture",),
        retry_limit=2,
        backoff_initial_seconds=1,
        backoff_max_seconds=2,
    )
    worker = _worker(
        db_session, adapter, settings=settings, sleep=lambda seconds: sleeps.append(seconds)
    )

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["retry_count"] == 2
    assert sleeps == [0.5, 1.0]
    assert db_session.query(CaptureHeartbeat).one().retry_count == 2


def test_raw_store_outage_is_bounded_and_visible(db_session):
    adapter = FixtureAdapter([_market()])
    store = MemoryRawStore(RawStoreError("disk offline"))
    worker = _worker(db_session, adapter, store)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["error_count"] == 1
    assert result["errors"][0]["category"] == "raw_store"
    assert db_session.query(VenuePriceTick).count() == 0


def test_settlement_correction_is_audited_without_rewriting_ticks(db_session):
    first = Settlement(
        "fixture", "M1", "settled", NOW, "fixture/M1", "yes", "r1"
    )
    corrected = Settlement(
        "fixture",
        "M1",
        "settled",
        NOW + timedelta(hours=1),
        "fixture/M1",
        "no",
        "r2",
    )
    adapter = FixtureAdapter(
        [_market(status="closed")], settlements=[first, corrected]
    )
    worker = _worker(db_session, adapter)

    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)
    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW + timedelta(minutes=15))

    row = db_session.query(VenueMarketRow).one()
    assert row.settled_outcome == "no"
    assert row.settlement_source_event_id == "r2"
    assert row.settlement_history[0]["previous"]["outcome"] == "yes"
    assert db_session.query(VenuePriceTick).count() == 0


def test_one_venue_failure_does_not_stop_other_adapter(db_session):
    broken = FixtureAdapter(requests.ConnectionError("down"))
    broken.venue = "broken"
    healthy = FixtureAdapter([_market()])
    settings = CaptureSettings(
        enabled_venues=("broken", "fixture"), retry_limit=0
    )
    worker = CaptureWorker(
        db=db_session,
        adapters={"broken": broken, "fixture": healthy},
        raw_store=MemoryRawStore(),
        settings=settings,
        now=lambda: NOW,
        monotonic=lambda: 1,
        sleep=lambda _seconds: None,
    )

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert results["broken"]["error_count"] == 1
    assert results["fixture"]["success_count"] == 1
    assert db_session.query(CaptureHeartbeat).count() == 2


def test_exact_allowlist_and_hard_cap_bound_remote_market_calls(db_session):
    adapter = FixtureAdapter([_market("M1"), _market("M2"), _market("M3")])
    settings = CaptureSettings(
        enabled_venues=("fixture",),
        market_key_allowlist=("fixture:M2", "fixture:M3"),
        max_markets_per_venue=1,
        retry_limit=0,
    )
    worker = _worker(db_session, adapter, settings=settings)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["markets_seen"] == 3
    assert result["markets_registered"] == 1
    assert result["markets_eligible"] == 1
    assert result["markets_skipped_by_policy"] == 2
    assert adapter.quote_calls == 1
    assert db_session.query(VenueMarketRow).count() == 1
    tick = db_session.query(VenuePriceTick).one()
    assert tick.market.venue_key == "M2"


def test_eligible_scope_caches_only_bounded_markets_but_keeps_catalogue_count(
    db_session, monkeypatch,
):
    adapter = FixtureAdapter([_market("M1"), _market("M2"), _market("M3")])
    settings = CaptureSettings(
        enabled_venues=("fixture",),
        market_key_allowlist=("fixture:M2",),
        max_markets_per_venue=1,
        registry_scope="eligible",
        retry_limit=0,
    )
    worker = _worker(db_session, adapter, settings=settings)
    original_capture_keys = worker._capture_keys
    capture_key_calls = 0

    def counted_capture_keys(venue, markets):
        nonlocal capture_key_calls
        capture_key_calls += 1
        return original_capture_keys(venue, markets)

    monkeypatch.setattr(worker, "_capture_keys", counted_capture_keys)

    first = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)
    second = worker.run_venue_cycle(
        "fixture", scheduled_cycle_at=NOW + timedelta(minutes=1)
    )

    assert first["markets_seen"] == 3
    assert second["markets_seen"] == 3
    assert adapter.discover_calls == 1
    assert capture_key_calls == 3
    assert [market.venue_key for market in worker._catalogues["fixture"]] == ["M2"]


def test_full_catalogue_registry_requires_explicit_scope(db_session):
    adapter = FixtureAdapter([_market("M1"), _market("M2"), _market("M3")])
    settings = CaptureSettings(
        enabled_venues=("fixture",),
        market_key_allowlist=("fixture:M2",),
        max_markets_per_venue=1,
        registry_scope="all",
        retry_limit=0,
    )
    worker = _worker(db_session, adapter, settings=settings)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["markets_seen"] == 3
    assert result["markets_registered"] == 3
    assert adapter.quote_calls == 1
    assert db_session.query(VenueMarketRow).count() == 3
    assert [item.market.venue_key for item in db_session.query(VenuePriceTick)] == ["M2"]


def test_rate_limit_response_retries_and_is_counted(db_session):
    fixture = json.loads((FIXTURES / "venue_rate_limit_429.json").read_text())
    response = requests.Response()
    response.status_code = fixture["status"]
    limited = requests.HTTPError(fixture["error"], response=response)
    adapter = FixtureAdapter([_market()], quotes=[limited, _quote()])
    settings = CaptureSettings(enabled_venues=("fixture",), retry_limit=1)
    worker = _worker(db_session, adapter, settings=settings)

    result = worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)

    assert result["success_count"] == 1
    assert result["retry_count"] == 1
    assert result["rate_limit_count"] == 1


def test_market_missing_from_later_catalogue_is_revisited_for_settlement(db_session):
    settlement = Settlement(
        "fixture", "M1", "settled", NOW + timedelta(minutes=16), "fixture/M1", "yes"
    )

    class ClosingAdapter(FixtureAdapter):
        def discover_markets(self, sport):
            self.discover_calls += 1
            return [_market()] if self.discover_calls == 1 else []

    adapter = ClosingAdapter([], settlements=[settlement])
    settings = CaptureSettings(
        enabled_venues=("fixture",), discovery_seconds=60, retry_limit=0
    )
    worker = _worker(db_session, adapter, settings=settings)

    worker.run_venue_cycle("fixture", scheduled_cycle_at=NOW)
    worker.run_venue_cycle(
        "fixture", scheduled_cycle_at=NOW + timedelta(minutes=16)
    )

    row = db_session.query(VenueMarketRow).one()
    assert row.status == "settled"
    assert row.settled_outcome == "yes"
    assert adapter.settlement_calls == 1
