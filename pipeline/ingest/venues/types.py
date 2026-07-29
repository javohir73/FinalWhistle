"""Shared value objects and protocol for prediction-market venue adapters.

Adapters keep venue-specific parsing and I/O, but return these normalized,
immutable objects. Validation happens here so malformed venue data cannot leak
into persistence through a different adapter implementation.

Two rules in this module exist because getting them wrong is silent:

* **Identity is derived here, never at the call site.** ``tick_identity``
  returns every field of the ``venue_price_tick`` natural key, including
  ``ts``. A capture path that picked its own ``ts`` would write a second row
  for a redelivered event whose arrival time differed.
* **"Venue does not report live match state" is a distinct value.** It is not
  the same as "state not observed yet", and neither is the same as "state
  observed and it disagrees". Collapsing them makes an in-play benchmark
  report zero coverage without saying why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
from typing import Literal, Mapping, Protocol, runtime_checkable

JsonObject = Mapping[str, object]
MarketStatus = str
SettlementStatus = Literal["settled", "void", "cancelled"]
Transport = Literal["polling", "streaming", "recovery"]

_SETTLEMENT_STATUSES = {"settled", "void", "cancelled"}
_TRANSPORTS = {"polling", "streaming", "recovery"}
_STREAM_TRANSPORTS = {"streaming", "recovery"}


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
    if not isinstance(value, datetime):
        raise VenuePayloadError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise VenuePayloadError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VenuePayloadError(f"{field_name} must be a number")
    if not math.isfinite(value):
        raise VenuePayloadError(f"{field_name} must be finite")
    return float(value)


def _probability(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    number = _finite(value, field_name)
    if not 0.0 <= number <= 1.0:
        raise VenuePayloadError(f"{field_name} must be between 0 and 1")
    return number


def _counter_pair(value, field_name: str) -> tuple[int, int] | None:
    """A (home, away) pair of non-negative counts, or None when unreported."""
    if value is None:
        return None
    try:
        home, away = value
    except (TypeError, ValueError):
        raise VenuePayloadError(f"{field_name} must be a (home, away) pair") from None
    pair = []
    for part, side in ((home, "home"), (away, "away")):
        if isinstance(part, bool) or not isinstance(part, int):
            raise VenuePayloadError(f"{field_name} {side} must be an integer")
        if part < 0:
            raise VenuePayloadError(f"{field_name} {side} must not be negative")
        pair.append(part)
    return (pair[0], pair[1])


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    """One normalized price/size level for the Yes contract."""

    price: float
    size: float

    def __post_init__(self) -> None:
        _probability(self.price, "price")
        if _finite(self.size, "size") <= 0:
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
class InPlayState:
    """Live match state attached to a quote, with support stated explicitly.

    ``supported=False`` means this venue/market does not publish live match
    state at all. Every detail field must then be ``None``: a source that
    cannot report a score is not permitted to imply one. ``supported=True``
    with ``score=None`` is the different, also-legitimate case of a venue that
    reports state but had none for this observation.

    Downstream comparisons must keep the two apart. An in-play benchmark that
    treats "unsupported" as "mismatched" reports zero coverage and blames the
    model for the venue's silence.
    """

    supported: bool
    is_in_play: bool | None = None
    clock_label: str | None = None
    period: str | None = None
    minute: float | None = None
    score: tuple[int, int] | None = None
    cards: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.supported, bool):
            raise VenuePayloadError("supported must be a bool")
        if self.is_in_play is not None and not isinstance(self.is_in_play, bool):
            raise VenuePayloadError("is_in_play must be a bool or None")
        for name in ("clock_label", "period"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required_text(value, name))
        if self.minute is not None:
            minute = _finite(self.minute, "minute")
            if minute < 0:
                raise VenuePayloadError("minute must not be negative")
            object.__setattr__(self, "minute", minute)
        object.__setattr__(self, "score", _counter_pair(self.score, "score"))
        object.__setattr__(self, "cards", _counter_pair(self.cards, "cards"))
        if not self.supported and any(
            value is not None
            for value in (
                self.is_in_play,
                self.clock_label,
                self.period,
                self.minute,
                self.score,
                self.cards,
            )
        ):
            raise VenuePayloadError(
                "unsupported in-play state must not carry live match detail"
            )

    def as_columns(self) -> dict[str, object]:
        """The exact ``venue_price_tick`` in-play columns for this state.

        Capture writes this mapping wholesale rather than assembling the
        columns itself, so an unsupported venue cannot reach the table with
        half a state on it.
        """
        return {
            "in_play_state_supported": self.supported,
            "is_in_play": self.is_in_play,
            "clock_state": self.clock_label,
            "period": self.period,
            "minute": self.minute,
            "home_score": self.score[0] if self.score else None,
            "away_score": self.score[1] if self.score else None,
            "home_cards": self.cards[0] if self.cards else None,
            "away_cards": self.cards[1] if self.cards else None,
        }


#: The fail-closed default. An adapter that says nothing about live state is
#: taken to not report it, which is excluded honestly rather than compared.
UNSUPPORTED_IN_PLAY = InPlayState(supported=False)


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
    #: The untouched venue responses this market was parsed from.
    raw_documents: tuple = field(default=(), repr=False, compare=False)

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
    """One full order-book observation returned by a venue adapter.

    ``observed_at`` is OUR arrival time. It is never part of a persistence key
    -- see :func:`tick_identity` -- but it IS persisted, in its own
    ``venue_price_tick.observed_at`` column. It has to be: a stream tick's
    ``ts`` is its ``source_ts``, so source-to-arrival latency cannot be
    recovered from the key, and the row's ``created_at`` is insert time, which
    drifts from arrival under buffering or replay.
    """

    venue: str
    venue_key: str
    observed_at: datetime
    transport: Transport
    book: OrderBook = field(default_factory=OrderBook)
    last: float | None = None
    source_ts: datetime | None = None
    source_event_id: str | None = None
    in_play: InPlayState = UNSUPPORTED_IN_PLAY
    raw_payload: JsonObject = field(default_factory=dict, repr=False, compare=False)
    #: The untouched venue responses this quote was parsed from.
    raw_documents: tuple = field(default=(), repr=False, compare=False)

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
        if not isinstance(self.in_play, InPlayState):
            raise VenuePayloadError("in_play must be an InPlayState")
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
    #: The untouched venue responses this settlement was parsed from.
    raw_documents: tuple = field(default=(), repr=False, compare=False)

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


@dataclass(frozen=True, slots=True)
class RawDocument:
    """One venue response exactly as it arrived, before any parsing.

    Parsed-and-reserialized JSON is not the same evidence. Round-tripping
    through ``json.loads`` then ``json.dumps(sort_keys=True)`` discards
    whitespace, key order, duplicate keys, and the lexical form of every
    number -- ``0.4300`` becomes ``0.43``, and a venue that later disputes a
    price is disputing bytes we no longer hold.

    ``body`` is what the socket delivered. Nothing here interprets it.
    """

    name: str
    body: bytes
    url: str = ""
    content_type: str = "application/json"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        if not isinstance(self.body, (bytes, bytearray)):
            raise VenuePayloadError("raw document body must be bytes")
        object.__setattr__(self, "body", bytes(self.body))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.body)


@dataclass(frozen=True, slots=True)
class RejectedPayload:
    """A venue item that could not be normalized, kept for diagnosis.

    Discovery reads a page of markets at a time. Dropping a malformed one with
    a log line loses the only copy of what the venue actually sent, and loses
    the count too -- a venue quietly breaking half its catalogue looks
    identical to a venue with a smaller catalogue.
    """

    reason: str
    identifier: str = ""
    payload: JsonObject = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Markets a venue catalogue yielded, plus what it could not yield.

    Returning only the good rows makes silent loss the default. Both halves
    travel together so the worker can persist and count the rejects.
    """

    markets: tuple[VenueMarket, ...] = ()
    rejected: tuple[RejectedPayload, ...] = ()
    documents: tuple[RawDocument, ...] = ()

    def __iter__(self):  # pragma: no cover - convenience for `for m in result`
        return iter(self.markets)

    def __len__(self) -> int:
        return len(self.markets)


@dataclass(frozen=True, slots=True)
class TickIdentity:
    """Every field of the ``venue_price_tick`` natural key, derived once.

    ``ts`` belongs here rather than at the persistence call site. It is the
    logical observation time -- the scheduled cycle for polling, the venue's
    own event time for a stream -- and is stable across replay. A caller that
    substituted arrival time would give a redelivered event a fresh key.

    ``transport`` rides along for the provenance column but is deliberately
    excluded from equality and hashing, because it is NOT identity. One venue
    event delivered over the stream and then redelivered by gap recovery is a
    single observation; if transport keyed it, the two deliveries would take
    two rows and no uniqueness constraint could tell. The ``cycle:`` /
    ``event:`` prefix on ``observation_key`` already keeps the polling and
    stream families apart, so the key needs nothing further.
    """

    venue: str
    venue_key: str
    ts: datetime
    observation_key: str
    #: First-delivery path, recorded but never compared.
    transport: Transport = field(compare=False)


@dataclass(frozen=True, slots=True)
class HeartbeatIdentity:
    """Uniqueness key for one worker's scheduled venue cycle."""

    worker: str
    venue: str
    scheduled_cycle_at: datetime


def tick_identity(
    quote: Quote, *, scheduled_cycle_at: datetime | None = None
) -> TickIdentity:
    """Return the stable logical key for one captured tick.

    Transport decides the *shape* of the key without being *part* of it. A
    polling cycle that happens to carry a venue event id still resolves to its
    cycle, so a retried cycle collapses onto the same row; and one stream event
    resolves to the same key whether it arrived by stream or by gap recovery,
    so a redelivery collapses too.

    A stream event without a venue event id, or without the venue's own
    timestamp, has no stable identity. It is rejected rather than given one
    from arrival time or a payload hash, either of which makes redelivery
    look like a new observation.
    """

    if quote.transport == "polling":
        if scheduled_cycle_at is None:
            raise VenuePayloadError(
                "polling tick needs scheduled_cycle_at: completion time is not identity"
            )
        ts = _as_utc(scheduled_cycle_at, "scheduled_cycle_at")
        observation_key = f"cycle:{ts.isoformat()}"
    elif quote.transport in _STREAM_TRANSPORTS:
        if quote.source_event_id is None:
            raise VenuePayloadError(
                f"{quote.transport} tick needs source_event_id; a payload hash or "
                "arrival time would give redelivery a new identity"
            )
        if quote.source_ts is None:
            raise VenuePayloadError(
                f"{quote.transport} tick needs source_ts; arrival time is not identity"
            )
        ts = quote.source_ts
        observation_key = f"event:{quote.source_event_id}"
    else:  # pragma: no cover - Quote rejects unknown transports first
        raise VenuePayloadError(f"unsupported transport: {quote.transport}")
    return TickIdentity(
        venue=quote.venue,
        venue_key=quote.venue_key,
        ts=ts,
        observation_key=observation_key,
        transport=quote.transport,
    )


def heartbeat_identity(
    worker: str, venue: str, scheduled_cycle_at: datetime
) -> HeartbeatIdentity:
    """Database uniqueness key for a worker's scheduled venue cycle."""

    return HeartbeatIdentity(
        worker=_required_text(worker, "worker"),
        venue=_required_text(venue, "venue"),
        scheduled_cycle_at=_as_utc(scheduled_cycle_at, "scheduled_cycle_at"),
    )


@runtime_checkable
class VenueAdapter(Protocol):
    """Synchronous adapter boundary used by the polling worker."""

    venue: str

    def discover_markets(self, sport: str) -> DiscoveryResult: ...

    def fetch_quote(self, venue_key: str) -> Quote: ...

    def fetch_settlement(self, venue_key: str) -> Settlement | None: ...
