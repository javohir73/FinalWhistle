"""Transport-neutral stream guard and normalized persistence path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import VenueMarket, VenuePriceTick
from pipeline.ingest.venues.types import Quote
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
                return StreamDecision(False, out_of_order=True, reason="non-increasing sequence")
            gap = (cursor.last_sequence + 1, sequence - 1) if sequence > cursor.last_sequence + 1 else None
        else:
            gap = None
            if quote.source_ts and cursor.last_source_ts and quote.source_ts < cursor.last_source_ts:
                return StreamDecision(False, out_of_order=True, reason="source timestamp moved backwards")
        if event_id:
            cursor.seen_event_ids.add(event_id)
        if sequence is not None:
            cursor.last_sequence = sequence
        if quote.source_ts is not None:
            cursor.last_source_ts = max(cursor.last_source_ts or quote.source_ts, quote.source_ts)
        return StreamDecision(True, missing_sequence=gap, reason="accepted")


def persist_stream_quote(
    db: Session,
    raw_store: RawPayloadStore,
    quote: Quote,
    *,
    sequence: int | None = None,
    recovery: bool = False,
) -> bool:
    """Use the same raw-reference and normalized tick schema as polling."""
    if quote.transport not in {"streaming", "recovery"}:
        raise ValueError("stream persistence requires streaming or recovery transport")
    row = db.query(VenueMarket).filter_by(venue=quote.venue, venue_key=quote.venue_key).one_or_none()
    if row is None:
        raise ValueError("stream update references an undiscovered venue market")
    raw = raw_store.put(
        venue=quote.venue,
        venue_key=quote.venue_key,
        kind="stream-recovery" if recovery else "stream",
        captured_at=quote.observed_at,
        payload=quote.raw_payload,
    )
    event_id = quote.source_event_id or hashlib.sha256(
        json.dumps(quote.raw_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    transport = "recovery" if recovery else "streaming"
    db.add(VenuePriceTick(
        venue_market_id=row.id,
        ts=quote.observed_at.astimezone(timezone.utc),
        source_ts=quote.source_ts,
        transport=transport,
        observation_key=f"event:{event_id}",
        source_event_id=str(sequence) if sequence is not None else event_id,
        yes_bid=quote.yes_bid,
        yes_ask=quote.yes_ask,
        last=quote.last,
        mid=quote.midpoint,
        bid_size=quote.bid_size,
        ask_size=quote.ask_size,
        book_top_n={
            "yes_bids": [[level.price, level.size] for level in quote.book.yes_bids],
            "yes_asks": [[level.price, level.size] for level in quote.book.yes_asks],
        },
        is_in_play=quote.is_in_play,
        clock_state=quote.clock_state,
        raw_payload_ref=raw.reference,
        validation_flags=None,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.query(VenuePriceTick).filter_by(
            venue_market_id=row.id,
            ts=quote.observed_at.astimezone(timezone.utc),
            transport=transport,
            observation_key=f"event:{event_id}",
        ).one_or_none()
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
                permanent.append({"venue_key": venue_key, "start_sequence": start, "end_sequence": end, "cause": "venue history endpoint unavailable"})
                continue
            recovered += int(self.backfill(venue, venue_key, start, end) or 0)
        return {"recovered": recovered, "permanent_gaps": permanent}

    def after_disconnect(self, venue: str, attempt: int) -> dict:
        if attempt <= self.retry_limit:
            return {"action": "reconnect", "attempt": attempt}
        result = self.fallback_poll(venue)
        return {"action": "polling_fallback", "attempt": attempt, "result": result}
