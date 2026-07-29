"""Transport-neutral stream guard and normalized persistence path.

Stream and recovery ticks land through the same identity function as polling
(:func:`pipeline.ingest.venues.types.tick_identity`). That is the whole point:
the two paths in the original branch each derived their own key and disagreed,
so a redelivered event took a second row that no constraint could catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import VenueMarket, VenuePriceTick
from pipeline.ingest.venues.types import Quote, tick_identity
from worker.raw_store import RawPayloadStore


@dataclass(frozen=True)
class StreamDecision:
    accepted: bool
    duplicate: bool = False
    out_of_order: bool = False
    missing_sequence: tuple[int, int] | None = None
    reason: str = ""


@dataclass
class _Cursor:
    last_sequence: int | None = None
    last_source_ts: datetime | None = None
    seen_event_ids: set[str] = field(default_factory=set)


class StreamGuard:
    """Deduplicate and detect gaps before an update reaches persistence."""

    def __init__(self) -> None:
        self._cursors: dict[tuple[str, str], _Cursor] = {}

    def observe(self, quote: Quote, *, sequence: int | None = None) -> StreamDecision:
        key = (quote.venue, quote.venue_key)
        cursor = self._cursors.setdefault(key, _Cursor())
        event_id = quote.source_event_id
        if event_id and event_id in cursor.seen_event_ids:
            return StreamDecision(False, duplicate=True, reason="duplicate source event")
        if sequence is not None and cursor.last_sequence is not None:
            if sequence <= cursor.last_sequence:
                return StreamDecision(
                    False, out_of_order=True, reason="non-increasing sequence"
                )
            gap = (
                (cursor.last_sequence + 1, sequence - 1)
                if sequence > cursor.last_sequence + 1
                else None
            )
        else:
            gap = None
            if (
                quote.source_ts
                and cursor.last_source_ts
                and quote.source_ts < cursor.last_source_ts
            ):
                return StreamDecision(
                    False, out_of_order=True, reason="source timestamp moved backwards"
                )
        if event_id:
            cursor.seen_event_ids.add(event_id)
        if sequence is not None:
            cursor.last_sequence = sequence
        if quote.source_ts is not None:
            cursor.last_source_ts = max(
                cursor.last_source_ts or quote.source_ts, quote.source_ts
            )
        return StreamDecision(True, missing_sequence=gap, reason="accepted")


def persist_stream_quote(
    db: Session,
    raw_store: RawPayloadStore,
    quote: Quote,
    *,
    sequence: int | None = None,
    order_book_top_n: int = 10,
) -> bool:
    """Persist one stream or recovery tick. Returns False for a duplicate.

    The transport travels on the row as first-delivery provenance and takes no
    part in the key, so a gap-recovery fetch of an event the stream already
    delivered resolves to the same row and is discarded. A quote with no venue
    event id or no venue timestamp is refused by ``tick_identity`` rather than
    given an identity made up from arrival time or a payload hash.
    """
    if quote.transport not in {"streaming", "recovery"}:
        raise ValueError("stream persistence requires streaming or recovery transport")
    identity = tick_identity(quote)
    row = (
        db.query(VenueMarket)
        .filter_by(venue=quote.venue, venue_key=quote.venue_key)
        .one_or_none()
    )
    if row is None:
        raise ValueError("stream update references an undiscovered venue market")
    raw = raw_store.put(
        venue=quote.venue,
        venue_key=quote.venue_key,
        kind="stream-recovery" if quote.transport == "recovery" else "stream",
        captured_at=quote.observed_at,
        payload=quote.raw_payload,
    )
    db.add(
        VenuePriceTick(
            venue_market_id=row.id,
            ts=identity.ts,
            observed_at=quote.observed_at,
            source_ts=quote.source_ts,
            transport=identity.transport,
            observation_key=identity.observation_key,
            source_event_id=quote.source_event_id,
            yes_bid=quote.yes_bid,
            yes_ask=quote.yes_ask,
            last=quote.last,
            mid=quote.midpoint,
            bid_size=quote.bid_size,
            ask_size=quote.ask_size,
            book_top_n={
                "yes_bids": [
                    {"price": level.price, "size": level.size}
                    for level in quote.book.yes_bids[:order_book_top_n]
                ],
                "yes_asks": [
                    {"price": level.price, "size": level.size}
                    for level in quote.book.yes_asks[:order_book_top_n]
                ],
            },
            raw_payload_ref=raw.reference,
            validation_flags=[f"stream_sequence:{sequence}"] if sequence is not None else None,
            **quote.in_play.as_columns(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(VenuePriceTick)
            .filter_by(
                venue_market_id=row.id,
                ts=identity.ts,
                observation_key=identity.observation_key,
            )
            .one_or_none()
        )
        if duplicate is not None:
            return False
        raise
    return True


class StreamSupervisor:
    """Small reconnect controller; caller owns actual socket implementation."""

    def __init__(self, *, retry_limit: int, fallback_poll, backfill=None) -> None:
        self.retry_limit = retry_limit
        self.fallback_poll = fallback_poll
        self.backfill = backfill

    def recover(self, venue: str, gaps: list[tuple[str, int, int]]) -> dict:
        recovered = 0
        permanent = []
        for venue_key, start, end in gaps:
            if self.backfill is None:
                permanent.append(
                    {
                        "venue_key": venue_key,
                        "start_sequence": start,
                        "end_sequence": end,
                        "cause": "venue history endpoint unavailable",
                    }
                )
                continue
            recovered += int(self.backfill(venue, venue_key, start, end) or 0)
        return {"recovered": recovered, "permanent_gaps": permanent}

    def after_disconnect(self, venue: str, attempt: int) -> dict:
        if attempt <= self.retry_limit:
            return {"action": "reconnect", "attempt": attempt}
        result = self.fallback_poll(venue)
        return {"action": "polling_fallback", "attempt": attempt, "result": result}
