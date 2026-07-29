"""Capture cycle: policy, idempotency, partial failure, replay. No network."""

from datetime import datetime, timedelta, timezone

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import CaptureHeartbeat, VenueMarket as VenueMarketRow, VenuePriceTick
from pipeline.ingest.venues.types import (
    UNSUPPORTED_IN_PLAY,
    DiscoveryResult,
    InPlayState,
    RawDocument,
    RejectedPayload,
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueMarket,
    VenuePayloadError,
)
from worker.capture import CaptureWorker
from worker.config import CaptureSettings
from worker.raw_store import RawObject, RawPayloadRejected, RawStoreError  # noqa: F401

NOW = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)


def _aware(value):
    """SQLite hands back naive datetimes; persisted timestamps are UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _market(key="KX-1", *, status="open", live=None, title="Arsenal v Chelsea"):
    return VenueMarket(
        venue="kalshi", venue_key=key, sport="football", raw_title=title,
        status=status, discovered_at=NOW, market_type="match_winner",
        raw_payload={"event": {"live": live}} if live is not None else {"event": {}},
    )


def _quote(key="KX-1", *, bid=0.44, ask=0.48, in_play=UNSUPPORTED_IN_PLAY,
           source_ts=None, observed_at=NOW):
    return Quote(
        venue="kalshi", venue_key=key, observed_at=observed_at, transport="polling",
        book=OrderBook(yes_bids=(OrderBookLevel(bid, 10),),
                       yes_asks=(OrderBookLevel(ask, 10),)),
        last=0.46, source_ts=source_ts, in_play=in_play,
        raw_payload={"orderbook": {"key": key}},
    )


class FixtureAdapter:
    """Canned adapter. Counts calls so 'captured nothing' is provable."""

    def __init__(self, venue="kalshi", *, markets=None, quotes=None,
                 settlements=None, quote_error=None, discover_error=None,
                 rejected=()):
        self.venue = venue
        self.in_play_state_fields = frozenset()
        self._markets = markets if markets is not None else [_market()]
        self._rejected = tuple(rejected)
        self._quotes = quotes or {}
        self._settlements = settlements or {}
        self._quote_error = quote_error or {}
        self._discover_error = discover_error
        self.discover_calls = 0
        self.quote_calls: list[str] = []
        self.settlement_calls: list[str] = []

    def discover_markets(self, sport):
        self.discover_calls += 1
        if self._discover_error is not None:
            raise self._discover_error
        return DiscoveryResult(markets=tuple(self._markets),
                               rejected=self._rejected)

    def fetch_quote(self, venue_key):
        self.quote_calls.append(venue_key)
        error = self._quote_error.get(venue_key)
        if error is not None:
            raise error
        return self._quotes.get(venue_key) or _quote(venue_key)

    def fetch_settlement(self, venue_key):
        self.settlement_calls.append(venue_key)
        return self._settlements.get(venue_key)


class MemoryRawStore:
    def __init__(self, *, fail_times=0, reject=False):
        self.objects: list[dict] = []
        self.fail_times = fail_times
        self.reject = reject
        self.pruned_at = None

    def put_document(self, *, venue, venue_key, kind, captured_at, document):
        return self._record(venue, venue_key, kind, captured_at,
                            body=document.body, name=document.name)

    def prune(self, *, now):
        self.pruned_at = now
        return 0

    def put(self, *, venue, venue_key, kind, captured_at, payload):
        return self._record(venue, venue_key, kind, captured_at, payload=payload)

    def _record(self, venue, venue_key, kind, captured_at, *, payload=None,
                body=None, name=""):
        if self.reject:
            raise RawPayloadRejected("raw payload is 9000000 bytes, over the bound")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RawStoreError("transient object store failure")
        self.objects.append(
            {"venue": venue, "venue_key": venue_key, "kind": kind,
             "captured_at": captured_at, "payload": payload, "body": body,
             "name": name}
        )
        return RawObject(
            reference=f"mem://{venue}/{venue_key}/{kind}/{len(self.objects)}",
            sha256="0" * 64, size_bytes=len(body or str(payload)),
        )


def _settings(**overrides):
    values = {
        "enabled": True,
        "enabled_venues": ("kalshi",),
        "market_key_allowlist": ("kalshi:KX-1",),
        "retry_limit": 2,
        "backoff_initial_seconds": 0.1,
        "backoff_max_seconds": 0.4,
    }
    values.update(overrides)
    return CaptureSettings(**values)


def _worker(db, adapter, store=None, *, settings=None, sleeps=None, **kwargs):
    return CaptureWorker(
        db=db, adapters={adapter.venue: adapter}, raw_store=store or MemoryRawStore(),
        settings=settings or _settings(), now=lambda: NOW + timedelta(seconds=1),
        monotonic=lambda: 0.0, sleep=(sleeps.append if sleeps is not None else lambda _s: None),
        jitter=lambda: 0.5, **kwargs,
    )


# --- the happy path ---------------------------------------------------------


def test_a_cycle_writes_registry_tick_raw_and_heartbeat(db_session):
    adapter = FixtureAdapter()
    store = MemoryRawStore()
    result = _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    tick = db_session.query(VenuePriceTick).one()
    assert (_aware(tick.ts), tick.observation_key) == (
        NOW, "cycle:2026-10-03T14:30:00+00:00")
    assert tick.transport == "polling"
    assert _aware(tick.scheduled_cycle_at) == NOW
    assert tick.mid == pytest.approx(0.46)
    assert tick.raw_payload_ref.startswith("mem://kalshi/KX-1/quote/")
    assert db_session.query(VenueMarketRow).one().mapping_status == "unmapped"
    heartbeat = db_session.query(CaptureHeartbeat).one()
    assert (heartbeat.success_count, heartbeat.error_count) == (1, 0)
    assert heartbeat.intended_cadence_seconds == 300
    assert result["success_count"] == 1
    assert {obj["kind"] for obj in store.objects} == {"discovery", "quote"}


def test_the_tick_carries_arrival_time_and_a_declared_state_capability(db_session):
    """Both are NOT NULL in the schema, and both come from the quote -- the
    worker never invents either."""
    arrived = NOW + timedelta(milliseconds=1800)
    adapter = FixtureAdapter(
        quotes={"KX-1": _quote(source_ts=NOW, observed_at=arrived)})
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    tick = db_session.query(VenuePriceTick).one()
    assert _aware(tick.observed_at) == arrived
    assert (tick.observed_at - tick.source_ts).total_seconds() == 1.8
    assert tick.in_play_state_supported is False
    assert tick.home_score is None and tick.clock_state is None


def test_a_venue_that_reports_state_has_it_persisted(db_session):
    """The other half of the capability: when an adapter does declare state,
    it lands in the columns as one block."""
    state = InPlayState(supported=True, is_in_play=True, period="second_half",
                        minute=63, score=(1, 1), cards=(2, 0))
    adapter = FixtureAdapter(quotes={"KX-1": _quote(in_play=state)})
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    tick = db_session.query(VenuePriceTick).one()
    assert (tick.in_play_state_supported, tick.home_score, tick.away_cards) == (
        True, 1, 0)
    assert tick.minute == 63.0


# --- fail closed ------------------------------------------------------------


def test_run_all_refuses_without_an_allowlist_and_never_calls_the_adapter(db_session):
    adapter = FixtureAdapter()
    worker = _worker(db_session, adapter,
                     settings=_settings(market_key_allowlist=()))

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert "MARKET_CAPTURE_MARKET_KEYS" in results["kalshi"]["refused"]
    assert adapter.discover_calls == 0
    assert adapter.quote_calls == []
    assert db_session.query(VenuePriceTick).count() == 0


def test_run_all_refuses_while_disabled(db_session):
    adapter = FixtureAdapter()
    worker = _worker(db_session, adapter, settings=_settings(enabled=False))

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert "MARKET_CAPTURE_ENABLED" in results["kalshi"]["refused"]
    assert adapter.discover_calls == 0


def test_an_empty_allowlist_captures_nothing_even_called_directly(db_session):
    """Second layer. Even bypassing run_all, empty is never 'capture all'."""
    adapter = FixtureAdapter(markets=[_market("KX-1"), _market("KX-2")])
    worker = _worker(db_session, adapter,
                     settings=_settings(market_key_allowlist=()))

    result = worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert adapter.quote_calls == []
    assert adapter.settlement_calls == []
    assert db_session.query(VenuePriceTick).count() == 0
    assert db_session.query(VenueMarketRow).count() == 0
    assert result["markets_eligible"] == 0


def test_allowlist_and_hard_cap_bound_remote_calls_deterministically(db_session):
    """The cap must truncate the same way every cycle. An unsorted catalogue
    would rotate which markets got captured and hole every series."""
    markets = [_market(f"KX-{n}") for n in (5, 1, 4, 2, 3)]
    adapter = FixtureAdapter(markets=markets)
    settings = _settings(
        market_key_allowlist=tuple(f"kalshi:KX-{n}" for n in range(1, 6)),
        max_markets_per_venue=2)
    _worker(db_session, adapter, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert sorted(adapter.quote_calls) == ["KX-1", "KX-2"]

    reversed_adapter = FixtureAdapter(markets=list(reversed(markets)))
    _worker(db_session, reversed_adapter, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW + timedelta(hours=1))
    assert sorted(reversed_adapter.quote_calls) == ["KX-1", "KX-2"]


def test_another_venues_allowlist_entry_does_not_unlock_this_one(db_session):
    adapter = FixtureAdapter(markets=[_market("KX-1")])
    worker = _worker(db_session, adapter,
                     settings=_settings(market_key_allowlist=("polymarket:KX-1",)))

    worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert adapter.quote_calls == []


# --- cadence ----------------------------------------------------------------


def test_polling_cadence_ignores_streaming_and_recovery_ticks(db_session):
    """A busy stream must not silence the polling fallback -- that would take
    the backup offline exactly when the primary was noisiest."""
    adapter = FixtureAdapter()
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)
    row = db_session.query(VenueMarketRow).one()
    later = NOW + timedelta(seconds=400)
    for offset, transport in ((1, "streaming"), (2, "recovery")):
        db_session.add(VenuePriceTick(
            venue_market_id=row.id, ts=later - timedelta(seconds=offset),
            observed_at=later, source_ts=later - timedelta(seconds=offset),
            transport=transport, observation_key=f"event:{transport}",
            source_event_id=transport, in_play_state_supported=False,
            raw_payload_ref="mem://stream"))
    db_session.commit()

    adapter.quote_calls.clear()
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=later)

    assert adapter.quote_calls == ["KX-1"], "stream traffic suppressed the poll"


def test_a_recent_polling_tick_does_defer_the_next_poll(db_session):
    adapter = FixtureAdapter()
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    adapter.quote_calls.clear()
    _worker(db_session, adapter).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW + timedelta(seconds=60))

    assert adapter.quote_calls == []


def test_in_play_cadence_comes_from_our_fixture_state_not_the_tick(db_session):
    adapter = FixtureAdapter(markets=[_market(live=False)])
    worker = _worker(db_session, adapter, fixture_state=lambda _m: True)

    worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    heartbeat = db_session.query(CaptureHeartbeat).one()
    assert heartbeat.intended_cadence_seconds == 30
    tick = db_session.query(VenuePriceTick).one()
    assert tick.in_play_state_supported is False
    assert tick.is_in_play is None, "cadence hint must not become match state"
    assert "fixture_venue_state_disagreement" in tick.validation_flags


# --- idempotency and replay -------------------------------------------------


def test_replaying_the_same_cycle_writes_no_second_tick(db_session):
    adapter = FixtureAdapter()
    worker = _worker(db_session, adapter)
    worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)
    worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert db_session.query(VenuePriceTick).count() == 1
    assert db_session.query(CaptureHeartbeat).count() == 1


def test_a_restarted_worker_replays_the_cycle_without_refetching(db_session):
    """Fresh process, empty in-memory catalogue cache, same scheduled cycle.

    The cadence check is the first line of defence: the cycle already has a
    polling tick, so the restarted worker makes no remote quote call at all.
    """
    first = FixtureAdapter()
    _worker(db_session, first).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    restarted = FixtureAdapter()
    _worker(db_session, restarted).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert restarted.quote_calls == []
    assert db_session.query(VenuePriceTick).count() == 1
    assert db_session.query(VenueMarketRow).count() == 1
    assert db_session.query(CaptureHeartbeat).count() == 1


def test_the_tick_key_refuses_a_second_write_for_one_cycle(db_session):
    """The second line of defence, independent of cadence: even handed the
    same quote twice, the derived key resolves to the row already there."""
    adapter = FixtureAdapter()
    worker = _worker(db_session, adapter)
    worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)
    row = db_session.query(VenueMarketRow).one()

    written = worker._write_tick(
        row, _quote(), scheduled_cycle_at=NOW, raw_payload_ref="mem://again",
        flags=[])

    assert written is False
    assert db_session.query(VenuePriceTick).count() == 1


# --- failure handling -------------------------------------------------------


def test_a_rate_limited_response_is_retried_backed_off_and_counted(db_session):
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError(response=response)
    calls = {"n": 0}

    class Limited(FixtureAdapter):
        def fetch_quote(self, venue_key):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise error
            return _quote(venue_key)

    sleeps: list[float] = []
    adapter = Limited()
    _worker(db_session, adapter, sleeps=sleeps).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    heartbeat = db_session.query(CaptureHeartbeat).one()
    assert heartbeat.rate_limit_count == 2
    assert heartbeat.retry_count >= 2
    assert sleeps == [0.1, 0.2], "bounded exponential backoff with jitter"
    assert db_session.query(VenuePriceTick).count() == 1


def test_backoff_is_capped(db_session):
    response = requests.Response()
    response.status_code = 503
    error = requests.HTTPError(response=response)
    sleeps: list[float] = []
    adapter = FixtureAdapter(quote_error={"KX-1": error})
    settings = _settings(retry_limit=4, backoff_initial_seconds=1.0,
                         backoff_max_seconds=2.0)

    _worker(db_session, adapter, settings=settings, sleeps=sleeps).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert sleeps == [1.0, 2.0, 2.0, 2.0]


def test_a_client_error_is_not_retried(db_session):
    response = requests.Response()
    response.status_code = 404
    sleeps: list[float] = []
    adapter = FixtureAdapter(
        quote_error={"KX-1": requests.HTTPError(response=response)})

    _worker(db_session, adapter, sleeps=sleeps).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert sleeps == []
    assert db_session.query(CaptureHeartbeat).one().error_count == 1


def test_a_timeout_is_retried_then_recorded(db_session):
    sleeps: list[float] = []
    adapter = FixtureAdapter(
        quote_error={"KX-1": requests.Timeout("read timed out")})

    result = _worker(db_session, adapter, sleeps=sleeps).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert len(sleeps) == 2
    assert result["errors"][0]["category"] == "network"
    assert db_session.query(VenuePriceTick).count() == 0


def test_one_bad_market_keeps_its_siblings_and_retains_the_rejected_payload(db_session):
    bad = VenuePayloadError("crossed book", raw_payload={"orderbook": "garbage"})
    adapter = FixtureAdapter(markets=[_market("KX-1"), _market("KX-2")],
                             quote_error={"KX-1": bad})
    store = MemoryRawStore()
    settings = _settings(market_key_allowlist=("kalshi:KX-1", "kalshi:KX-2"))

    result = _worker(db_session, adapter, store, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert [t.observation_key for t in db_session.query(VenuePriceTick)] == [
        "cycle:2026-10-03T14:30:00+00:00"]
    assert db_session.query(VenuePriceTick).one().venue_market_id == (
        db_session.query(VenueMarketRow).filter_by(venue_key="KX-2").one().id)
    rejected = [obj for obj in store.objects if obj["kind"] == "rejected"]
    assert [obj["payload"] for obj in rejected] == [{"orderbook": "garbage"}]
    assert result["error_count"] == 1


def test_rejected_payload_retention_is_bounded_per_cycle(db_session):
    """A venue returning garbage returns it every poll. The cap is stated and
    the overflow counted rather than silently filling the archive."""
    markets = [_market(f"KX-{n}") for n in range(1, 6)]
    errors = {
        f"KX-{n}": VenuePayloadError("bad", raw_payload={"n": n})
        for n in range(1, 6)
    }
    adapter = FixtureAdapter(markets=markets, quote_error=errors)
    store = MemoryRawStore()
    settings = _settings(
        market_key_allowlist=tuple(f"kalshi:KX-{n}" for n in range(1, 6)),
        max_markets_per_venue=5, max_rejected_payloads_per_cycle=2)

    result = _worker(db_session, adapter, store, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert result["rejected_payloads_stored"] == 2
    assert len([obj for obj in store.objects if obj["kind"] == "rejected"]) == 2
    assert result["error_count"] == 5, "every failure is still counted"


def test_an_unstorable_payload_is_not_retried(db_session):
    """RawPayloadRejected fails identically every time; retrying only burns
    the rate limit against the same error."""
    sleeps: list[float] = []
    adapter = FixtureAdapter()

    result = _worker(db_session, adapter, MemoryRawStore(reject=True),
                     sleeps=sleeps).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert sleeps == []
    assert result["errors"][0]["category"] == "raw_payload_rejected"
    assert db_session.query(VenuePriceTick).count() == 0


def test_a_transient_raw_store_outage_is_retried_then_visible(db_session):
    sleeps: list[float] = []
    adapter = FixtureAdapter()

    result = _worker(db_session, adapter, MemoryRawStore(fail_times=99),
                     sleeps=sleeps).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert len(sleeps) == 2
    assert result["errors"][0]["category"] == "raw_store"
    assert db_session.query(VenuePriceTick).count() == 0


def test_one_venue_failing_does_not_stop_the_other(db_session):
    kalshi = FixtureAdapter("kalshi", discover_error=requests.ConnectionError("down"))
    polymarket = FixtureAdapter("polymarket", markets=[
        VenueMarket(venue="polymarket", venue_key="0xaaa", sport="football",
                    raw_title="x", status="active", discovered_at=NOW,
                    market_type="moneyline", raw_payload={"event": {}})])
    polymarket._quotes = {"0xaaa": Quote(
        venue="polymarket", venue_key="0xaaa", observed_at=NOW, transport="polling",
        book=OrderBook(yes_bids=(OrderBookLevel(0.4, 5),)), raw_payload={})}
    settings = _settings(enabled_venues=("kalshi", "polymarket"),
                         market_key_allowlist=("kalshi:KX-1", "polymarket:0xaaa"))
    worker = CaptureWorker(
        db=db_session, adapters={"kalshi": kalshi, "polymarket": polymarket},
        raw_store=MemoryRawStore(), settings=settings,
        now=lambda: NOW + timedelta(seconds=1), monotonic=lambda: 0.0,
        sleep=lambda _s: None, jitter=lambda: 0.5)

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert results["kalshi"]["error_count"] == 1
    assert results["polymarket"]["success_count"] == 1
    assert db_session.query(VenuePriceTick).count() == 1


def test_credentials_are_redacted_from_recorded_errors(db_session):
    adapter = FixtureAdapter(quote_error={
        "KX-1": requests.ConnectionError(
            "GET /orderbook failed, Authorization: Bearer sk-live-9f3a")})

    result = _worker(db_session, adapter).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    message = result["errors"][0]["message"]
    assert "sk-live-9f3a" not in message
    assert "[REDACTED]" in message
    stored = db_session.query(CaptureHeartbeat).one().errors
    assert "sk-live-9f3a" not in str(stored)


# --- settlement -------------------------------------------------------------


def test_a_corrected_settlement_is_audited_without_rewriting_ticks(db_session):
    first = Settlement(venue="kalshi", venue_key="KX-1", status="settled",
                       settled_at=NOW, source="markets/KX-1", outcome="yes",
                       source_event_id="e1", raw_payload={"r": 1})
    adapter = FixtureAdapter(markets=[_market(status="finalized")],
                             settlements={"KX-1": first})
    _worker(db_session, adapter).run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    corrected = Settlement(venue="kalshi", venue_key="KX-1", status="settled",
                           settled_at=NOW + timedelta(hours=2), source="markets/KX-1",
                           outcome="no", source_event_id="e2", raw_payload={"r": 2})
    adapter._settlements = {"KX-1": corrected}
    _worker(db_session, adapter).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW + timedelta(hours=3))

    row = db_session.query(VenueMarketRow).one()
    assert row.settled_outcome == "no"
    assert len(row.settlement_history) == 1
    assert row.settlement_history[0]["previous"]["outcome"] == "yes"
    assert db_session.query(VenuePriceTick).count() == 0, "finalized: never quoted"


# --- the gate, closed at the cycle itself ------------------------------------


def test_a_direct_disabled_cycle_touches_nothing(db_session):
    """run_all was the only gate. A direct run_venue_cycle call walked past it
    and captured with enabled=False."""
    adapter = FixtureAdapter()
    store = MemoryRawStore()
    worker = _worker(db_session, adapter, store, settings=_settings(enabled=False))

    result = worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert "MARKET_CAPTURE_ENABLED" in result["refused"]
    assert adapter.discover_calls == 0
    assert adapter.quote_calls == []
    assert store.objects == []
    assert db_session.query(VenuePriceTick).count() == 0
    assert db_session.query(VenueMarketRow).count() == 0
    assert db_session.query(CaptureHeartbeat).count() == 0


def test_a_direct_cycle_with_an_empty_allowlist_never_discovers(db_session):
    """Discovery ran before eligibility was computed, so 'the allowlist bounds
    every remote call' was false: the catalogue request went out anyway."""
    adapter = FixtureAdapter()
    store = MemoryRawStore()
    worker = _worker(db_session, adapter, store,
                     settings=_settings(market_key_allowlist=()))

    result = worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert "MARKET_CAPTURE_MARKET_KEYS" in result["refused"]
    assert adapter.discover_calls == 0
    assert store.objects == []
    assert db_session.query(CaptureHeartbeat).count() == 0


def test_a_venue_with_no_allowlisted_key_is_skipped_before_discovery(db_session):
    """The subtle one. A global allowlist naming only kalshi still let the
    Polymarket catalogue request go out, because eligibility was derived from
    markets the request had already fetched."""
    kalshi = FixtureAdapter("kalshi")
    polymarket = FixtureAdapter("polymarket", markets=[
        VenueMarket(venue="polymarket", venue_key="0xaaa", sport="football",
                    raw_title="x", status="active", discovered_at=NOW,
                    market_type="moneyline", raw_payload={"event": {}})])
    settings = _settings(enabled_venues=("kalshi", "polymarket"),
                         market_key_allowlist=("kalshi:KX-1",))
    worker = CaptureWorker(
        db=db_session, adapters={"kalshi": kalshi, "polymarket": polymarket},
        raw_store=MemoryRawStore(), settings=settings,
        now=lambda: NOW + timedelta(seconds=1), monotonic=lambda: 0.0,
        sleep=lambda _s: None, jitter=lambda: 0.5)

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert polymarket.discover_calls == 0, "unlisted venue was still discovered"
    assert polymarket.quote_calls == []
    assert "no allowlisted market keys for polymarket" in results["polymarket"]["refused"]
    assert kalshi.discover_calls == 1
    assert results["kalshi"]["success_count"] == 1


# --- discovery rejects are evidence -----------------------------------------


def test_rejected_discovery_items_are_stored_and_counted(db_session):
    """Good siblings survive, and the malformed payload is retained rather
    than logged away -- a venue quietly breaking half its catalogue must not
    look like a venue with a smaller catalogue."""
    adapter = FixtureAdapter(rejected=(
        RejectedPayload(reason="conditionId must not be empty",
                        identifier="market-501", payload={"market": {"bad": True}}),
    ))
    store = MemoryRawStore()

    result = _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    rejected = [obj for obj in store.objects if obj["kind"] == "rejected"]
    assert [obj["payload"] for obj in rejected] == [{"market": {"bad": True}}]
    assert result["rejected_payloads_stored"] == 1
    assert result["error_count"] == 1
    assert db_session.query(VenuePriceTick).count() == 1, "siblings still captured"


def test_a_malformed_top_level_catalogue_still_writes_a_heartbeat(db_session):
    """It used to escape the cycle: run_all rolled back and wrote nothing, so
    a venue serving garbage was indistinguishable from a worker not running."""
    adapter = FixtureAdapter(discover_error=VenuePayloadError(
        "kalshi events response must contain a list",
        raw_payload={"events": "not-a-list"}))
    store = MemoryRawStore()

    result = _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    heartbeat = db_session.query(CaptureHeartbeat).one()
    assert heartbeat.error_count == 1
    assert result["errors"][0]["category"] == "validation"
    assert [obj["payload"] for obj in store.objects
            if obj["kind"] == "rejected"] == [{"events": "not-a-list"}]


def test_run_all_records_a_heartbeat_for_a_malformed_catalogue(db_session):
    adapter = FixtureAdapter(discover_error=VenuePayloadError("garbage"))
    worker = _worker(db_session, adapter)

    worker.run_all(scheduled_cycle_at=NOW)

    assert db_session.query(CaptureHeartbeat).count() == 1


def test_rejected_overflow_is_counted_not_silent(db_session):
    adapter = FixtureAdapter(rejected=tuple(
        RejectedPayload(reason=f"bad {n}", identifier=f"m{n}", payload={"n": n})
        for n in range(5)))
    store = MemoryRawStore()
    settings = _settings(max_rejected_payloads_per_cycle=2)

    result = _worker(db_session, adapter, store, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert result["rejected_payloads_stored"] == 2
    assert result["rejected_payloads_dropped"] == 3
    counts = [entry for entry in db_session.query(CaptureHeartbeat).one().errors
              if entry.get("category") == "raw_retention"]
    assert counts == [{"category": "raw_retention",
                       "rejected_payloads_stored": 2,
                       "rejected_payloads_dropped": 3}]


# --- lossless provenance through the worker ---------------------------------


def test_the_tick_points_at_the_venues_own_bytes(db_session):
    body = b'{"orderbook": {"z": 1, "a": "0.4400"}}\n'
    quote = Quote(
        venue="kalshi", venue_key="KX-1", observed_at=NOW, transport="polling",
        book=OrderBook(yes_bids=(OrderBookLevel(0.44, 10),),
                       yes_asks=(OrderBookLevel(0.48, 10),)),
        raw_payload={"parsed": True},
        raw_documents=(RawDocument(name="orderbook", body=body),),
    )
    adapter = FixtureAdapter(quotes={"KX-1": quote})
    store = MemoryRawStore()

    _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    written = [obj for obj in store.objects if obj["kind"] == "quote"]
    assert [obj["body"] for obj in written] == [body], "verbatim bytes stored"
    assert [obj for obj in store.objects if obj["kind"] == "quote-manifest"] == [], \
        "a single response needs no manifest"
    ref = db_session.query(VenuePriceTick).one().raw_payload_ref
    assert ref.startswith("mem://kalshi/KX-1/quote/")


def test_several_responses_are_all_kept_and_a_manifest_links_them(db_session):
    """Kalshi builds one quote from an orderbook and a market response. Both
    are evidence, so both are stored and one reference still resolves to the
    complete record."""
    quote = Quote(
        venue="kalshi", venue_key="KX-1", observed_at=NOW, transport="polling",
        book=OrderBook(yes_bids=(OrderBookLevel(0.44, 10),)),
        raw_documents=(RawDocument(name="orderbook", body=b'{"o":1}'),
                       RawDocument(name="market", body=b'{"m":2}')),
    )
    adapter = FixtureAdapter(quotes={"KX-1": quote})
    store = MemoryRawStore()

    _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    bodies = [obj["body"] for obj in store.objects if obj["kind"] == "quote"]
    assert bodies == [b'{"o":1}', b'{"m":2}']
    manifest = next(obj for obj in store.objects
                    if obj["kind"] == "quote-manifest")
    assert [entry["name"] for entry in manifest["payload"]["documents"]] == [
        "orderbook", "market"]
    assert db_session.query(VenuePriceTick).one().raw_payload_ref == (
        f"mem://kalshi/KX-1/quote-manifest/{len(store.objects)}")


# --- retention sweep --------------------------------------------------------


def test_a_completed_run_prunes_the_raw_archive(db_session):
    store = MemoryRawStore()
    _worker(db_session, FixtureAdapter(), store).run_all(scheduled_cycle_at=NOW)

    assert store.pruned_at is not None


def test_a_refused_run_does_not_touch_the_archive(db_session):
    store = MemoryRawStore()
    _worker(db_session, FixtureAdapter(), store,
            settings=_settings(enabled=False)).run_all(scheduled_cycle_at=NOW)

    assert store.pruned_at is None


# --- round 3: enabled_venues is part of the gate ----------------------------


def test_a_disabled_venue_is_refused_even_with_its_own_allowlist_entry(db_session):
    """The gate checked the master switch and the per-venue allowlist but not
    MARKET_CAPTURE_VENUES. run_all hid it by only ever iterating enabled
    venues; a direct call walked straight through. Being reachable through
    self.adapters is not being enabled."""
    adapter = FixtureAdapter("polymarket", markets=[
        VenueMarket(venue="polymarket", venue_key="0xaaa", sport="football",
                    raw_title="x", status="active", discovered_at=NOW,
                    market_type="moneyline", raw_payload={"event": {}})])
    store = MemoryRawStore()
    settings = _settings(enabled_venues=("kalshi",),
                         market_key_allowlist=("polymarket:0xaaa",))
    worker = CaptureWorker(
        db=db_session, adapters={"polymarket": adapter}, raw_store=store,
        settings=settings, now=lambda: NOW, monotonic=lambda: 0.0,
        sleep=lambda _s: None, jitter=lambda: 0.5)

    result = worker.run_venue_cycle("polymarket", scheduled_cycle_at=NOW)

    assert "not in MARKET_CAPTURE_VENUES" in result["refused"]
    assert adapter.discover_calls == 0
    assert adapter.quote_calls == []
    assert adapter.settlement_calls == []
    assert store.objects == []
    assert store.pruned_at is None
    assert db_session.query(VenueMarketRow).count() == 0
    assert db_session.query(VenuePriceTick).count() == 0
    assert db_session.query(CaptureHeartbeat).count() == 0


# --- round 3: retention is fail-closed, before capture ----------------------


class BrokenPruneStore(MemoryRawStore):
    def __init__(self):
        super().__init__()
        self.prune_calls = 0

    def prune(self, *, now):
        self.prune_calls += 1
        raise RawStoreError("[Errno 13] Permission denied: 'var/market-intel-raw'")


def test_a_retention_failure_refuses_the_cycle_before_any_capture(db_session):
    """Pruning afterwards and logging the failure is not enforcement: the next
    cycle writes anyway and the archive passes the horizon regardless."""
    adapter = FixtureAdapter()
    store = BrokenPruneStore()
    worker = _worker(db_session, adapter, store)

    result = worker.run_venue_cycle("kalshi", scheduled_cycle_at=NOW)

    assert "raw retention failed" in result["refused"]
    assert store.prune_calls == 1
    assert adapter.discover_calls == 0
    assert adapter.quote_calls == []
    assert store.objects == []
    assert db_session.query(VenueMarketRow).count() == 0
    assert db_session.query(VenuePriceTick).count() == 0
    assert db_session.query(CaptureHeartbeat).count() == 0


def test_a_retention_failure_refuses_every_venue_in_the_run(db_session):
    kalshi = FixtureAdapter("kalshi")
    polymarket = FixtureAdapter("polymarket")
    store = BrokenPruneStore()
    settings = _settings(enabled_venues=("kalshi", "polymarket"),
                         market_key_allowlist=("kalshi:KX-1", "polymarket:KX-1"))
    worker = CaptureWorker(
        db=db_session, adapters={"kalshi": kalshi, "polymarket": polymarket},
        raw_store=store, settings=settings, now=lambda: NOW,
        monotonic=lambda: 0.0, sleep=lambda _s: None, jitter=lambda: 0.5)

    results = worker.run_all(scheduled_cycle_at=NOW)

    assert all("raw retention failed" in r["refused"] for r in results.values())
    assert (kalshi.discover_calls, polymarket.discover_calls) == (0, 0)
    assert store.prune_calls == 1, "pruned once for the cycle, not per venue"
    assert db_session.query(CaptureHeartbeat).count() == 0


def test_retention_runs_before_capture_not_after(db_session):
    order = []

    class OrderedStore(MemoryRawStore):
        def prune(self, *, now):
            order.append("prune")
            return super().prune(now=now)

        def _record(self, *args, **kwargs):
            order.append("write")
            return super()._record(*args, **kwargs)

    _worker(db_session, FixtureAdapter(), OrderedStore()).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    assert order[0] == "prune"


# --- round 3: discovery bytes reach storage ---------------------------------


SERIES_BODY = b'{"series": [{"ticker": "KXEPL", "tags": ["Soccer"]}],  "z": 1}\n'
EVENTS_BODY = b'{"events": [{"series_ticker": "KXEPL"}], "n": "0.4300"}\n'


def _discovery(*, markets, documents, rejected=()):
    return DiscoveryResult(markets=tuple(markets), rejected=tuple(rejected),
                           documents=tuple(documents))


class DocumentAdapter(FixtureAdapter):
    """Returns catalogue pages the way a real adapter now does."""

    def discover_markets(self, sport):
        self.discover_calls += 1
        if self._discover_error is not None:
            raise self._discover_error
        documents = (RawDocument(name="series", body=SERIES_BODY),
                     RawDocument(name="events-1", body=EVENTS_BODY))
        return _discovery(markets=self._markets, documents=documents,
                          rejected=self._rejected)


def test_discovery_pages_are_stored_byte_for_byte(db_session):
    """_catalogue dropped DiscoveryResult.documents entirely, and markets
    carried none, so the stored 'discovery' object was a re-serialized parse.
    The venue's own catalogue bytes were never kept."""
    adapter = DocumentAdapter(markets=[_market("KX-1"), _market("KX-2")])
    store = MemoryRawStore()
    settings = _settings(market_key_allowlist=("kalshi:KX-1", "kalshi:KX-2"))

    _worker(db_session, adapter, store, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    discovery = [obj for obj in store.objects if obj["kind"] == "discovery"]
    assert [obj["body"] for obj in discovery] == [SERIES_BODY, EVENTS_BODY]
    assert b'"0.4300"' in EVENTS_BODY and b'"z": 1' in SERIES_BODY


def test_identical_pages_are_not_written_once_per_market(db_session):
    """Two markets came off the same two pages. Storing the pages per market
    would quadruple identical blobs at every discovery."""
    adapter = DocumentAdapter(markets=[_market(f"KX-{n}") for n in range(1, 4)])
    store = MemoryRawStore()
    settings = _settings(
        market_key_allowlist=tuple(f"kalshi:KX-{n}" for n in range(1, 4)))

    _worker(db_session, adapter, store, settings=settings).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    discovery = [obj for obj in store.objects if obj["kind"] == "discovery"]
    assert len(discovery) == 2, "one copy of each page for the whole cycle"
    manifests = [obj for obj in store.objects
                 if obj["kind"] == "discovery-manifest"]
    assert len(manifests) == 1
    refs = {row.raw_title_history[0]["raw_payload_ref"]
            for row in db_session.query(VenueMarketRow)}
    assert len(refs) == 1, "every market points at the one shared manifest"


def test_a_top_level_malformed_response_keeps_its_bytes(db_session):
    """_get built a RawDocument then called response.json(); a decode or
    schema failure raised without it, so the one body worth keeping was the
    one thrown away."""
    garbage = b'{"events": "not-a-list"  \n'
    adapter = FixtureAdapter(discover_error=VenuePayloadError(
        "kalshi /events response is not valid JSON",
        raw_document=RawDocument(name="events-1", body=garbage)))
    store = MemoryRawStore()

    result = _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    rejected = [obj for obj in store.objects if obj["kind"] == "rejected"]
    assert [obj["body"] for obj in rejected] == [garbage]
    assert result["rejected_payloads_stored"] == 1
    assert db_session.query(CaptureHeartbeat).one().error_count == 1
    assert db_session.query(VenueMarketRow).count() == 0


def test_an_all_invalid_catalogue_still_keeps_every_rejected_body(db_session):
    adapter = DocumentAdapter(markets=[], rejected=tuple(
        RejectedPayload(reason=f"bad {n}", identifier=f"m{n}", payload={"n": n})
        for n in range(3)))
    store = MemoryRawStore()

    result = _worker(db_session, adapter, store).run_venue_cycle(
        "kalshi", scheduled_cycle_at=NOW)

    rejected = [obj for obj in store.objects if obj["kind"] == "rejected"]
    assert [obj["payload"] for obj in rejected] == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert result["error_count"] == 3
    assert db_session.query(VenuePriceTick).count() == 0
    assert db_session.query(CaptureHeartbeat).count() == 1
