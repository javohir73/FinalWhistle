"""Compare stream and polling observations over the same captured markets."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import VenueMarket, VenuePriceTick


def stream_control_report(db: Session, *, start: datetime, end: datetime) -> dict:
    rows = (
        db.query(VenuePriceTick, VenueMarket)
        .join(VenueMarket, VenueMarket.id == VenuePriceTick.venue_market_id)
        .filter(VenuePriceTick.ts >= start, VenuePriceTick.ts < end)
        .all()
    )
    by_transport = Counter(tick.transport for tick, _market in rows)
    markets = {}
    latencies = []
    for tick, market in rows:
        state = markets.setdefault((market.venue, market.venue_key), set())
        state.add(tick.transport)
        if tick.source_ts is not None:
            latencies.append(max(0.0, (tick.ts - tick.source_ts).total_seconds() * 1000))
    parallel = sum("polling" in transports and ("streaming" in transports or "recovery" in transports) for transports in markets.values())
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "ticks_by_transport": dict(sorted(by_transport.items())),
        "markets_observed": len(markets),
        "markets_with_parallel_control": parallel,
        "source_latency_ms": {
            "n": len(latencies),
            "median": sorted(latencies)[len(latencies) // 2] if latencies else None,
            "max": max(latencies) if latencies else None,
        },
    }
