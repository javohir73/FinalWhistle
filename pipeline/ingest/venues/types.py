"""Shared value objects and protocol for prediction-market venue adapters.

Adapters keep venue-specific parsing and I/O, but return these normalized,
immutable objects. Validation happens here so malformed venue data cannot leak
into persistence through a different adapter implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Literal, Mapping, Protocol, runtime_checkable

JsonObject = Mapping[str, object]
MarketStatus = str
SettlementStatus = Literal["settled", "void", "cancelled"]
Transport = Literal["polling", "streaming", "recovery"]

_SETTLEMENT_STATUSES = {"settled", "void", "cancelled"}
_TRANSPORTS = {"polling", "streaming", "recovery"}


class VenuePayloadError(ValueError):
    """A venue response cannot be represented by the normalized contract."""

    def __init__(self, message: str, *, raw_payload: JsonObject | None = None) -> None:
        super().__init__(message)
        self.raw_payload = raw_payload


def _required_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise VenuePayloadError(f"{field_name} must not be empty")
    return value


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise VenuePayloadError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _probability(value: float | None, field_name: str) -> float | None:
    if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0):
        raise VenuePayloadError(f"{field_name} must be between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    """One normalized price/size level for the Yes contract."""

    price: float
    size: float

    def __post_init__(self) -> None:
        _probability(self.price, "price")
        if not math.isfinite(self.size) or self.size <= 0:
            raise VenuePayloadError("size must be finite and greater than 0")


@dataclass(frozen=True, slots=True)
class OrderBook:
    """The complete available normalized Yes-side book.

    Bids are canonicalized best-first (highest price first) and asks best-first
    (lowest price first). The untouched venue payload remains on :class:`Quote`
    for venues whose native book cannot be losslessly expressed this way.
    """

    yes_bids: tuple[OrderBookLevel, ...] = ()
    yes_asks: tuple[OrderBookLevel, ...] = ()

    def __post_init__(self) -> None:
        bids = tuple(sorted(self.yes_bids, key=lambda level: level.price, reverse=True))
        asks = tuple(sorted(self.yes_asks, key=lambda level: level.price))
        object.__setattr__(self, "yes_bids", bids)
        object.__setattr__(self, "yes_asks", asks)
        if bids and asks and bids[0].price > asks[0].price:
            raise VenuePayloadError("normalized order book is crossed")

    @property
    def yes_bid(self) -> float | None:
        return self.yes_bids[0].price if self.yes_bids else None

    @property
    def yes_ask(self) -> float | None:
        return self.yes_asks[0].price if self.yes_asks else None

    @property
    def bid_size(self) -> float | None:
        return self.yes_bids[0].size if self.yes_bids else None

    @property
    def ask_size(self) -> float | None:
        return self.yes_asks[0].size if self.yes_asks else None

    @property
    def midpoint(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2


@dataclass(frozen=True, slots=True)
class VenueMarket:
    """One market found through venue catalogue discovery."""

    venue: str
    venue_key: str
    sport: str
    raw_title: str
    status: MarketStatus
    discovered_at: datetime
    market_type: str = "unknown"
    event_key: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    raw_payload: JsonObject = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _required_text(self.venue, "venue"))
        object.__setattr__(self, "venue_key", _required_text(self.venue_key, "venue_key"))
        object.__setattr__(self, "sport", _required_text(self.sport, "sport"))
        object.__setattr__(
            self, "market_type", _required_text(self.market_type, "market_type")
        )
        object.__setattr__(self, "status", _required_text(self.status, "status"))
        object.__setattr__(
            self, "discovered_at", _as_utc(self.discovered_at, "discovered_at")
        )
        if self.opened_at is not None:
            object.__setattr__(self, "opened_at", _as_utc(self.opened_at, "opened_at"))
        if self.closed_at is not None:
            object.__setattr__(self, "closed_at", _as_utc(self.closed_at, "closed_at"))
        if self.opened_at and self.closed_at and self.closed_at < self.opened_at:
            raise VenuePayloadError("closed_at must not be earlier than opened_at")

    @property
    def identity_key(self) -> tuple[str, str]:
        """Database uniqueness key for catalogue replay."""

        return self.venue, self.venue_key


@dataclass(frozen=True, slots=True)
class Quote:
    """One full order-book observation returned by a venue adapter."""

    venue: str
    venue_key: str
    observed_at: datetime
    transport: Transport
    book: OrderBook = field(default_factory=OrderBook)
    last: float | None = None
    source_ts: datetime | None = None
    source_event_id: str | None = None
    is_in_play: bool | None = None
    clock_state: str | None = None
    raw_payload: JsonObject = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _required_text(self.venue, "venue"))
        object.__setattr__(self, "venue_key", _required_text(self.venue_key, "venue_key"))
        if self.transport not in _TRANSPORTS:
            raise VenuePayloadError(f"unsupported transport: {self.transport}")
        object.__setattr__(
            self, "observed_at", _as_utc(self.observed_at, "observed_at")
        )
        if self.source_ts is not None:
            object.__setattr__(self, "source_ts", _as_utc(self.source_ts, "source_ts"))
        if self.source_event_id is not None:
            object.__setattr__(
                self,
                "source_event_id",
                _required_text(self.source_event_id, "source_event_id"),
            )
        _probability(self.last, "last")

    @property
    def yes_bid(self) -> float | None:
        return self.book.yes_bid

    @property
    def yes_ask(self) -> float | None:
        return self.book.yes_ask

    @property
    def bid_size(self) -> float | None:
        return self.book.bid_size

    @property
    def ask_size(self) -> float | None:
        return self.book.ask_size

    @property
    def midpoint(self) -> float | None:
        return self.book.midpoint


@dataclass(frozen=True, slots=True)
class Settlement:
    """A terminal venue outcome, including explicit void/cancel states."""

    venue: str
    venue_key: str
    status: SettlementStatus
    settled_at: datetime
    source: str
    outcome: str | None = None
    source_event_id: str | None = None
    raw_payload: JsonObject = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _required_text(self.venue, "venue"))
        object.__setattr__(self, "venue_key", _required_text(self.venue_key, "venue_key"))
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        if self.status not in _SETTLEMENT_STATUSES:
            raise VenuePayloadError(f"unsupported settlement status: {self.status}")
        object.__setattr__(
            self, "settled_at", _as_utc(self.settled_at, "settled_at")
        )
        if self.status == "settled":
            if self.outcome is None:
                raise VenuePayloadError("settled outcome is required")
            object.__setattr__(self, "outcome", _required_text(self.outcome, "outcome"))
        elif self.outcome is not None:
            raise VenuePayloadError("void or cancelled settlement must not have an outcome")
        if self.source_event_id is not None:
            object.__setattr__(
                self,
                "source_event_id",
                _required_text(self.source_event_id, "source_event_id"),
            )

    @property
    def identity_key(self) -> tuple[str, str]:
        return self.venue, self.venue_key


def tick_idempotency_key(
    quote: Quote, *, scheduled_cycle_at: datetime | None = None
) -> tuple[str, str, str, str]:
    """Return the stable logical key for one captured tick.

    Streaming/recovery events use the venue event/sequence id. Polling uses
    the worker's scheduled cycle time, not completion time, so a retried cycle
    resolves to the same key. A streaming event without a stable venue id is
    unsafe to persist and is rejected.
    """

    if quote.source_event_id is not None:
        observation_key = f"event:{quote.source_event_id}"
    elif quote.transport == "polling" and scheduled_cycle_at is not None:
        observation_key = f"cycle:{_as_utc(scheduled_cycle_at, 'scheduled_cycle_at').isoformat()}"
    else:
        raise VenuePayloadError(
            "tick needs source_event_id, or scheduled_cycle_at for polling"
        )
    return quote.venue, quote.venue_key, quote.transport, observation_key


def heartbeat_idempotency_key(
    worker: str, venue: str, scheduled_cycle_at: datetime
) -> tuple[str, str, datetime]:
    """Database uniqueness key for a worker's scheduled venue cycle."""

    return (
        _required_text(worker, "worker"),
        _required_text(venue, "venue"),
        _as_utc(scheduled_cycle_at, "scheduled_cycle_at"),
    )


@runtime_checkable
class VenueAdapter(Protocol):
    """Synchronous adapter boundary used by the P0 polling worker."""

    venue: str

    def discover_markets(self, sport: str) -> list[VenueMarket]: ...

    def fetch_quote(self, venue_key: str) -> Quote: ...

    def fetch_settlement(self, venue_key: str) -> Settlement | None: ...
