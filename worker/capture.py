"""Reliable, idempotent polling capture cycle.

The worker performs I/O and persistence only. It intentionally contains no
entity resolution, model pricing, benchmarking, or serving logic.

Identity is never computed here. Every tick key comes from
``pipeline.ingest.venues.types.tick_identity``, which is also what the stream
path uses, so the two cannot disagree about what counts as the same
observation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
import logging
import random
import time
from typing import TypeVar

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CaptureHeartbeat, VenueMarket as VenueMarketRow, VenuePriceTick
from pipeline.ingest.venues.types import (
    Quote,
    Settlement,
    VenueAdapter,
    VenueMarket,
    VenuePayloadError,
    tick_identity,
)
from worker.config import CaptureSettings
from worker.raw_store import RawPayloadRejected, RawPayloadStore, RawStoreError
from worker.redaction import redact

log = logging.getLogger(__name__)
T = TypeVar("T")
_QUOTABLE = {"open", "active", "paused"}
_SETTLEMENT_CANDIDATES = {
    "closed",
    "determined",
    "disputed",
    "amended",
    "finalized",
    "settled",
    "void",
    "cancelled",
}


class RetryExhausted(RuntimeError):
    def __init__(self, cause: Exception, retries: int, rate_limits: int) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.retries = retries
        self.rate_limits = rate_limits


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _db_utc(value: datetime) -> datetime:
    """SQLite drops timezone metadata; persisted timestamps are defined as UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _error_category(exc: Exception) -> str:
    if isinstance(exc, VenuePayloadError):
        return "validation"
    if isinstance(exc, RawPayloadRejected):
        return "raw_payload_rejected"
    if isinstance(exc, RawStoreError):
        return "raw_store"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if exc.response.status_code == 429:
            return "rate_limit"
        return f"http_{exc.response.status_code}"
    if isinstance(exc, requests.RequestException):
        return "network"
    return "unexpected"


class CaptureWorker:
    def __init__(
        self,
        *,
        db: Session,
        adapters: Mapping[str, VenueAdapter],
        raw_store: RawPayloadStore,
        settings: CaptureSettings,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        fixture_state: Callable[[VenueMarket], bool | None] | None = None,
    ) -> None:
        self.db = db
        self.adapters = dict(adapters)
        self.raw_store = raw_store
        self.settings = settings
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic
        self.sleep = sleep
        self.jitter = jitter
        self.fixture_state = fixture_state
        self._catalogues: dict[str, list[VenueMarket]] = {}
        self._catalogue_counts: dict[str, int] = {}
        self._last_discovery: dict[str, datetime] = {}
        self._rejected_stored = 0

    # --- policy ------------------------------------------------------------

    def _capture_keys(self, venue: str, markets: list[VenueMarket]) -> set[str]:
        """The bounded exact market set eligible for remote capture calls.

        An empty allowlist yields an empty set. It is never read as "capture
        everything": a missing allowlist is a decision nobody made, and the
        failure mode of guessing is a worker quietly polling an entire venue
        catalogue against a rate limit.

        Selection is sorted, so the hard cap always truncates the same way.
        Unsorted, a catalogue whose order shifted between cycles would rotate
        which markets got captured and leave every series with holes.
        """
        if not self.settings.market_key_allowlist:
            return set()
        qualified = {
            value.split(":", 1)[1]
            for value in self.settings.market_key_allowlist
            if value.split(":", 1)[0].casefold() == venue.casefold()
        }
        candidates = sorted(
            (market.venue_key for market in markets if market.venue_key in qualified)
        )
        return set(candidates[: self.settings.max_markets_per_venue])

    # --- transport ---------------------------------------------------------

    def _retry(self, operation: Callable[[], T]) -> tuple[T, int, int]:
        retries = rate_limits = 0
        for attempt in range(self.settings.retry_limit + 1):
            try:
                return operation(), retries, rate_limits
            except (requests.RequestException, RawStoreError) as exc:
                # A rejected payload fails identically every time. Retrying it
                # just multiplies the same error against the same rate limit.
                if isinstance(exc, RawPayloadRejected):
                    raise RetryExhausted(exc, retries, rate_limits) from exc
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    if exc.response.status_code == 429:
                        rate_limits += 1
                    elif exc.response.status_code < 500:
                        raise RetryExhausted(exc, retries, rate_limits) from exc
                if attempt >= self.settings.retry_limit:
                    raise RetryExhausted(exc, retries, rate_limits) from exc
                delay = min(
                    self.settings.backoff_max_seconds,
                    self.settings.backoff_initial_seconds * (2**attempt),
                )
                retries += 1
                self.sleep(delay * (0.5 + self.jitter()))
        raise AssertionError("unreachable")

    def _store(
        self,
        *,
        venue: str,
        venue_key: str,
        kind: str,
        captured_at: datetime,
        payload: Mapping[str, object],
    ) -> tuple[str, int, int]:
        stored, retries, rate_limits = self._retry(
            lambda: self.raw_store.put(
                venue=venue,
                venue_key=venue_key,
                kind=kind,
                captured_at=captured_at,
                payload=payload,
            )
        )
        return stored.reference, retries, rate_limits

    def _store_rejected(
        self, market: VenueMarket, payload: Mapping[str, object], captured_at: datetime
    ) -> bool:
        """Keep a rejected payload for diagnosis, under a per-cycle bound.

        A venue that starts returning malformed data returns it every poll.
        Without the bound the diagnostic archive grows faster than the useful
        one, so the cap is stated and the overflow is counted, not hidden.
        """
        if self._rejected_stored >= self.settings.max_rejected_payloads_per_cycle:
            return False
        try:
            self._store(
                venue=market.venue,
                venue_key=market.venue_key,
                kind="rejected",
                captured_at=captured_at,
                payload=payload,
            )
        except RetryExhausted:
            return False
        self._rejected_stored += 1
        return True

    # --- catalogue ---------------------------------------------------------

    def _catalogue(
        self, adapter: VenueAdapter, scheduled_cycle_at: datetime
    ) -> tuple[list[VenueMarket], int, int, int]:
        previous = self._last_discovery.get(adapter.venue)
        if (
            previous is not None
            and adapter.venue in self._catalogues
            and (scheduled_cycle_at - previous).total_seconds()
            < self.settings.discovery_seconds
        ):
            return (
                self._catalogues[adapter.venue],
                self._catalogue_counts[adapter.venue],
                0,
                0,
            )
        markets, retries, rate_limits = self._retry(
            lambda: adapter.discover_markets("football")
        )
        by_key = {market.identity_key: market for market in markets}
        # A market disappearing from a complete active catalogue becomes a
        # settlement candidate. Preserve it across restarts using the registry;
        # settlement lookup remains the authority for its terminal outcome.
        registry_rows = (
            self.db.query(VenueMarketRow)
            .filter(
                VenueMarketRow.venue == adapter.venue,
                VenueMarketRow.settled_at.is_(None),
            )
            .all()
        )
        for row in registry_rows:
            identity = (row.venue, row.venue_key)
            if identity in by_key:
                continue
            by_key[identity] = VenueMarket(
                venue=row.venue,
                venue_key=row.venue_key,
                sport=row.sport,
                raw_title=row.raw_title,
                status=(row.status if row.status in _SETTLEMENT_CANDIDATES else "closed"),
                discovered_at=scheduled_cycle_at,
                market_type=row.market_type,
                opened_at=_db_utc(row.opened_at) if row.opened_at else None,
                closed_at=_db_utc(row.closed_at) if row.closed_at else scheduled_cycle_at,
                raw_payload={"recovery_registry": True, "previous_status": row.status},
            )
        for previous_market in self._catalogues.get(adapter.venue, []):
            if previous_market.identity_key not in by_key:
                by_key[previous_market.identity_key] = replace(
                    previous_market,
                    status="closed",
                    discovered_at=scheduled_cycle_at,
                    closed_at=previous_market.closed_at or scheduled_cycle_at,
                )
        markets = list(by_key.values())
        discovered_count = len(markets)
        # A bounded eligible run needs the full catalogue count for operational
        # evidence, but retaining every raw market graph until the next six-hour
        # discovery wastes hundreds of MiB. Cache only the exact capture set;
        # registry_scope=all remains the explicit full-catalogue opt-in.
        if self.settings.registry_scope == "all":
            cached_markets = markets
        else:
            capture_keys = self._capture_keys(adapter.venue, markets)
            cached_markets = [
                market for market in markets if market.venue_key in capture_keys
            ]
        self._catalogues[adapter.venue] = cached_markets
        self._catalogue_counts[adapter.venue] = discovered_count
        self._last_discovery[adapter.venue] = scheduled_cycle_at
        return cached_markets, discovered_count, retries, rate_limits

    # --- persistence -------------------------------------------------------

    def _upsert_market(
        self, market: VenueMarket, *, discovery_ref: str | None
    ) -> VenueMarketRow:
        row = (
            self.db.query(VenueMarketRow)
            .filter_by(venue=market.venue, venue_key=market.venue_key)
            .one_or_none()
        )
        if row is None:
            if discovery_ref is None:
                raise ValueError("new venue market requires a discovery raw reference")
            row = VenueMarketRow(
                venue=market.venue,
                venue_key=market.venue_key,
                sport=market.sport,
                market_type=market.market_type,
                raw_title=market.raw_title,
                raw_title_history=[
                    {
                        "observed_at": market.discovered_at.isoformat(),
                        "title": market.raw_title,
                        "raw_payload_ref": discovery_ref,
                    }
                ],
                mapping_status="unmapped",
                status=market.status,
                opened_at=market.opened_at,
                closed_at=market.closed_at,
                first_seen=market.discovered_at,
                last_seen=market.discovered_at,
            )
            self.db.add(row)
            self.db.flush()
            return row

        history = list(row.raw_title_history or [])
        if market.raw_title != row.raw_title and not any(
            item.get("title") == market.raw_title for item in history
        ):
            if discovery_ref is None:
                raise ValueError("market title change requires a discovery raw reference")
            history.append(
                {
                    "observed_at": market.discovered_at.isoformat(),
                    "title": market.raw_title,
                    "raw_payload_ref": discovery_ref,
                }
            )
        row.raw_title_history = history
        row.last_seen = max(_db_utc(row.last_seen), market.discovered_at)
        if row.settled_at is None:
            row.status = market.status
        row.market_type = market.market_type
        row.opened_at = market.opened_at or row.opened_at
        row.closed_at = market.closed_at or row.closed_at
        self.db.flush()
        return row

    def _needs_discovery_raw(self, market: VenueMarket) -> bool:
        """Store discovery raw only for a new market or lifecycle change."""
        row = (
            self.db.query(VenueMarketRow)
            .filter_by(venue=market.venue, venue_key=market.venue_key)
            .one_or_none()
        )
        if row is None:
            return True
        return any(
            (
                row.raw_title != market.raw_title,
                row.status != market.status and row.settled_at is None,
                row.market_type != market.market_type,
                (_db_utc(row.opened_at) if row.opened_at else None) != market.opened_at,
                (_db_utc(row.closed_at) if row.closed_at else None) != market.closed_at,
            )
        )

    def _cadence_in_play(self, market: VenueMarket) -> tuple[bool | None, list[str]]:
        """In-play hint used ONLY to choose a polling cadence.

        Deliberately not persisted as match state. The venue's own hint rides
        on a discovery payload that can be six hours old, and a stale hint that
        makes us poll faster is harmless where a stale hint written into a tick
        would be a fabricated observation. What a tick may claim about live
        state comes from the adapter's declared capability, nothing else.
        """
        internal = self.fixture_state(market) if self.fixture_state else None
        event = market.raw_payload.get("event")
        venue_state = event.get("live") if isinstance(event, dict) else None
        if not isinstance(venue_state, bool):
            venue_state = None
        flags: list[str] = []
        if internal is not None and venue_state is not None and internal != venue_state:
            flags.append("fixture_venue_state_disagreement")
        return (internal if internal is not None else venue_state), flags

    def _due(
        self, row: VenueMarketRow, *, scheduled_cycle_at: datetime, in_play: bool | None
    ) -> bool:
        """Is this market due for a poll?

        Scoped to POLLING ticks. Streaming and recovery traffic arrives on its
        own schedule and says nothing about when we last polled; counting it
        here would let a busy stream suppress polling entirely, so the fallback
        would go quiet exactly when the stream was noisiest.
        """
        cadence = (
            self.settings.inplay_seconds if in_play else self.settings.prematch_seconds
        )
        latest = (
            self.db.query(func.max(VenuePriceTick.ts))
            .filter(
                VenuePriceTick.venue_market_id == row.id,
                VenuePriceTick.transport == "polling",
            )
            .scalar()
        )
        if latest is None:
            return True
        return (scheduled_cycle_at - _db_utc(latest)).total_seconds() >= cadence

    def _write_tick(
        self,
        row: VenueMarketRow,
        quote: Quote,
        *,
        scheduled_cycle_at: datetime,
        raw_payload_ref: str,
        flags: list[str],
    ) -> bool:
        identity = tick_identity(quote, scheduled_cycle_at=scheduled_cycle_at)
        existing = (
            self.db.query(VenuePriceTick)
            .filter_by(
                venue_market_id=row.id,
                ts=identity.ts,
                observation_key=identity.observation_key,
            )
            .one_or_none()
        )
        if existing is not None:
            return False
        if (
            quote.source_ts is not None
            and (quote.observed_at - quote.source_ts).total_seconds()
            > self.settings.stale_quote_seconds
        ):
            flags.append("stale_source_timestamp")
        top_n = self.settings.order_book_top_n
        self.db.add(
            VenuePriceTick(
                venue_market_id=row.id,
                ts=identity.ts,
                observed_at=quote.observed_at,
                source_ts=quote.source_ts,
                transport=identity.transport,
                observation_key=identity.observation_key,
                source_event_id=quote.source_event_id,
                scheduled_cycle_at=(
                    scheduled_cycle_at if identity.transport == "polling" else None
                ),
                yes_bid=quote.yes_bid,
                yes_ask=quote.yes_ask,
                last=quote.last,
                mid=quote.midpoint,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                book_top_n={
                    "yes_bids": [
                        {"price": level.price, "size": level.size}
                        for level in quote.book.yes_bids[:top_n]
                    ],
                    "yes_asks": [
                        {"price": level.price, "size": level.size}
                        for level in quote.book.yes_asks[:top_n]
                    ],
                },
                raw_payload_ref=raw_payload_ref,
                validation_flags=flags or None,
                **quote.in_play.as_columns(),
            )
        )
        self.db.flush()
        return True

    def _apply_settlement(
        self, row: VenueMarketRow, settlement: Settlement, raw_payload_ref: str
    ) -> bool:
        current = (
            row.status,
            row.settled_outcome,
            row.settled_at,
            row.settlement_source_event_id,
        )
        replacement = (
            settlement.status,
            settlement.outcome,
            settlement.settled_at,
            settlement.source_event_id,
        )
        if current == replacement:
            return False
        if row.settled_at is not None:
            history = list(row.settlement_history or [])
            history.append(
                {
                    "previous": {
                        "status": row.status,
                        "outcome": row.settled_outcome,
                        "settled_at": row.settled_at.isoformat(),
                        "source": row.settlement_source,
                        "source_event_id": row.settlement_source_event_id,
                    },
                    "replacement": {
                        "status": settlement.status,
                        "outcome": settlement.outcome,
                        "settled_at": settlement.settled_at.isoformat(),
                        "source": settlement.source,
                        "source_event_id": settlement.source_event_id,
                        "raw_payload_ref": raw_payload_ref,
                    },
                    "recorded_at": self.now().astimezone(timezone.utc).isoformat(),
                }
            )
            row.settlement_history = history
        row.status = settlement.status
        row.settled_outcome = settlement.outcome
        row.settled_at = settlement.settled_at
        row.settlement_source = settlement.source
        row.settlement_source_event_id = settlement.source_event_id
        self.db.flush()
        return True

    # --- cycle -------------------------------------------------------------

    def run_venue_cycle(
        self, venue: str, *, scheduled_cycle_at: datetime
    ) -> dict[str, object]:
        scheduled_cycle_at = _utc(scheduled_cycle_at, "scheduled_cycle_at")
        started = self.monotonic()
        adapter = self.adapters[venue]
        errors: list[dict[str, str]] = []
        success_count = error_count = retry_count = rate_limit_count = 0
        markets: list[VenueMarket] = []
        discovered_count = 0
        self._rejected_stored = 0
        try:
            markets, discovered_count, retries, rate_limits = self._catalogue(
                adapter, scheduled_cycle_at
            )
            retry_count += retries
            rate_limit_count += rate_limits
        except RetryExhausted as exc:
            retry_count += exc.retries
            rate_limit_count += exc.rate_limits
            error_count += 1
            errors.append(
                {"category": _error_category(exc.cause), "message": str(exc.cause)}
            )

        capture_keys = self._capture_keys(venue, markets)
        registry_markets = (
            markets
            if self.settings.registry_scope == "all"
            else [market for market in markets if market.venue_key in capture_keys]
        )
        any_in_play = False
        for market in registry_markets:
            state, state_flags = self._cadence_in_play(market)
            any_in_play = any_in_play or state is True
            try:
                with self.db.begin_nested():
                    discovery_ref = None
                    if self._needs_discovery_raw(market):
                        discovery_ref, retries, rate_limits = self._store(
                            venue=market.venue,
                            venue_key=market.venue_key,
                            kind="discovery",
                            captured_at=market.discovered_at,
                            payload=market.raw_payload,
                        )
                        retry_count += retries
                        rate_limit_count += rate_limits
                    row = self._upsert_market(market, discovery_ref=discovery_ref)
            except RetryExhausted as exc:
                retry_count += exc.retries
                rate_limit_count += exc.rate_limits
                error_count += 1
                errors.append(
                    {
                        "venue_key": market.venue_key,
                        "category": _error_category(exc.cause),
                        "message": str(exc.cause),
                    }
                )
                continue
            except Exception as exc:
                error_count += 1
                errors.append(
                    {
                        "venue_key": market.venue_key,
                        "category": _error_category(exc),
                        "message": str(exc),
                    }
                )
                continue

            if (
                market.venue_key in capture_keys
                and market.status in _QUOTABLE
                and self._due(
                    row, scheduled_cycle_at=scheduled_cycle_at, in_play=state
                )
            ):
                try:
                    with self.db.begin_nested():
                        quote, retries, rate_limits = self._retry(
                            lambda key=market.venue_key: adapter.fetch_quote(key)
                        )
                        retry_count += retries
                        rate_limit_count += rate_limits
                        quote_ref, retries, rate_limits = self._store(
                            venue=market.venue,
                            venue_key=market.venue_key,
                            kind="quote",
                            captured_at=scheduled_cycle_at,
                            payload=quote.raw_payload,
                        )
                        retry_count += retries
                        rate_limit_count += rate_limits
                        self._write_tick(
                            row,
                            quote,
                            scheduled_cycle_at=scheduled_cycle_at,
                            raw_payload_ref=quote_ref,
                            flags=list(state_flags),
                        )
                        success_count += 1
                except RetryExhausted as exc:
                    retry_count += exc.retries
                    rate_limit_count += exc.rate_limits
                    error_count += 1
                    errors.append(
                        {
                            "venue_key": market.venue_key,
                            "category": _error_category(exc.cause),
                            "message": str(exc.cause),
                        }
                    )
                    raw = getattr(exc.cause, "raw_payload", None)
                    if isinstance(raw, Mapping):
                        self._store_rejected(market, raw, scheduled_cycle_at)
                except Exception as exc:
                    error_count += 1
                    errors.append(
                        {
                            "venue_key": market.venue_key,
                            "category": _error_category(exc),
                            "message": str(exc),
                        }
                    )
                    raw = getattr(exc, "raw_payload", None)
                    if isinstance(raw, Mapping):
                        self._store_rejected(market, raw, scheduled_cycle_at)

            if (
                market.venue_key in capture_keys
                and market.status in _SETTLEMENT_CANDIDATES
            ):
                try:
                    with self.db.begin_nested():
                        settlement, retries, rate_limits = self._retry(
                            lambda key=market.venue_key: adapter.fetch_settlement(key)
                        )
                        retry_count += retries
                        rate_limit_count += rate_limits
                        if settlement is not None:
                            settlement_ref, retries, rate_limits = self._store(
                                venue=market.venue,
                                venue_key=market.venue_key,
                                kind="settlement",
                                captured_at=settlement.settled_at,
                                payload=settlement.raw_payload,
                            )
                            retry_count += retries
                            rate_limit_count += rate_limits
                            self._apply_settlement(row, settlement, settlement_ref)
                except RetryExhausted as exc:
                    retry_count += exc.retries
                    rate_limit_count += exc.rate_limits
                    error_count += 1
                    errors.append(
                        {
                            "venue_key": market.venue_key,
                            "category": _error_category(exc.cause),
                            "message": str(exc.cause),
                        }
                    )
                except Exception as exc:
                    error_count += 1
                    errors.append(
                        {
                            "venue_key": market.venue_key,
                            "category": _error_category(exc),
                            "message": str(exc),
                        }
                    )

        completed_at = max(_utc(self.now(), "completed_at"), scheduled_cycle_at)
        duration_ms = max(0, round((self.monotonic() - started) * 1000))
        for error in errors:
            error["message"] = redact(error["message"])
            log.warning(
                "capture operation failed",
                extra={
                    "venue": venue,
                    "venue_key": error.get("venue_key"),
                    "cycle": scheduled_cycle_at.isoformat(),
                    "retry": retry_count,
                    "error_category": error.get("category"),
                },
            )
        cadence = (
            self.settings.inplay_seconds
            if any_in_play
            else self.settings.prematch_seconds
        )
        heartbeat = (
            self.db.query(CaptureHeartbeat)
            .filter_by(
                worker=self.settings.worker_id,
                venue=venue,
                scheduled_cycle_at=scheduled_cycle_at,
            )
            .one_or_none()
        )
        if heartbeat is None:
            heartbeat = CaptureHeartbeat(
                worker=self.settings.worker_id,
                venue=venue,
                scheduled_cycle_at=scheduled_cycle_at,
                completed_at=completed_at,
                intended_cadence_seconds=cadence,
                markets_seen=discovered_count,
                success_count=success_count,
                error_count=error_count,
                retry_count=retry_count,
                rate_limit_count=rate_limit_count,
                cycle_duration_ms=duration_ms,
                errors=errors or None,
            )
            self.db.add(heartbeat)
        else:
            heartbeat.completed_at = max(_db_utc(heartbeat.completed_at), completed_at)
            heartbeat.markets_seen = max(heartbeat.markets_seen, discovered_count)
            heartbeat.success_count += success_count
            heartbeat.error_count += error_count
            heartbeat.retry_count += retry_count
            heartbeat.rate_limit_count += rate_limit_count
            heartbeat.cycle_duration_ms += duration_ms
            heartbeat.errors = list(heartbeat.errors or []) + errors
        self.db.commit()
        return {
            "venue": venue,
            "markets_seen": discovered_count,
            "markets_registered": len(registry_markets),
            "markets_eligible": len(capture_keys),
            "markets_skipped_by_policy": max(0, discovered_count - len(capture_keys)),
            "rejected_payloads_stored": self._rejected_stored,
            "success_count": success_count,
            "error_count": error_count,
            "retry_count": retry_count,
            "rate_limit_count": rate_limit_count,
            "errors": errors,
        }

    def run_all(self, *, scheduled_cycle_at: datetime) -> dict[str, dict[str, object]]:
        """Run every enabled venue in turn.

        Serial on purpose. One Session is not thread-safe, venue rate limits
        are per-account rather than per-connection, and the eligible set is
        bounded to a handful of markets -- so concurrency would buy nothing
        and cost determinism in the heartbeat. There is no concurrency setting
        rather than an unimplemented one.
        """
        refusal = self.settings.refuse_reason()
        if refusal is not None:
            log.warning("capture refused: %s", refusal)
            return {
                venue: {
                    "venue": venue,
                    "markets_seen": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "refused": refusal,
                    "errors": [],
                }
                for venue in self.settings.enabled_venues
            }
        results: dict[str, dict[str, object]] = {}
        for venue in self.settings.enabled_venues:
            if venue not in self.adapters:
                results[venue] = {
                    "venue": venue,
                    "markets_seen": 0,
                    "success_count": 0,
                    "error_count": 1,
                    "errors": [
                        {"category": "configuration", "message": "adapter missing"}
                    ],
                }
                continue
            try:
                results[venue] = self.run_venue_cycle(
                    venue, scheduled_cycle_at=scheduled_cycle_at
                )
            except Exception as exc:
                self.db.rollback()
                results[venue] = {
                    "venue": venue,
                    "markets_seen": 0,
                    "success_count": 0,
                    "error_count": 1,
                    "errors": [
                        {"category": _error_category(exc), "message": redact(str(exc))}
                    ],
                }
                log.exception("capture venue cycle failed", extra={"venue": venue})
        return results
