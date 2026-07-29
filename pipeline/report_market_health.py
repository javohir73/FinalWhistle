"""Capture/mapping health with honest denominators. Read-only.

The denominator is always FIXTURES or MARKETS, never ticks. A market quoted
every 30 seconds writes ~3,000 ticks per day; tick-denominated "coverage"
would let one liquid market drown fifty silent ones. Here a market counts
once whether it ticked once or ten thousand times.

Freshness is grouped by (venue, worker) for heartbeats -- one worker falling
over must not hide behind another's cadence -- and by (venue, transport) for
quotes, because polling going quiet is a different failure from a stream
going quiet.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import CaptureHeartbeat, Match, VenueMarket, VenuePriceTick

HEALTH_VERSION = "market-health-v1"


def _db_aware(value: datetime | None, *, sqlite_naive_ok: bool) -> datetime | None:
    """SQLite drops tz metadata on UTC-defined columns and is re-tagged; a
    naive timestamp from any other dialect is corrupt and fails closed."""
    if value is None:
        return None
    if value.tzinfo is None:
        if sqlite_naive_ok:
            return value.replace(tzinfo=timezone.utc)
        raise ValueError(
            "naive timestamp from a non-SQLite database; refusing to assume UTC")
    return value.astimezone(timezone.utc)


def build_health(db: Session, *, now: datetime) -> dict:
    """Deterministic health snapshot. Writes nothing.

    ``now`` must be timezone-aware: a naive clock silently compared against
    aware capture times is exactly the class of bug this report exists to
    surface in others.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    sqlite_naive_ok = db.get_bind().dialect.name == "sqlite"
    markets = (
        db.query(VenueMarket)
        .order_by(VenueMarket.venue, VenueMarket.venue_key)
        .all()
    )

    venues: dict[str, dict] = {}
    by_venue: dict[str, list[VenueMarket]] = defaultdict(list)
    for market in markets:
        by_venue[market.venue].append(market)

    for venue in sorted(by_venue):
        rows = by_venue[venue]
        mapping_counts: dict[str, int] = defaultdict(int)
        for market in rows:
            mapping_counts[market.mapping_status] += 1

        # Fixture-denominated 1X2 completeness over MAPPED markets only.
        fixtures: dict[int, set[str]] = defaultdict(set)
        conflicting: dict[int, list[str]] = defaultdict(list)
        for market in rows:
            if market.mapping_status != "mapped":
                continue
            if market.canonical_event_id is None or market.canonical_outcome is None:
                continue
            if market.canonical_outcome in fixtures[market.canonical_event_id]:
                conflicting[market.canonical_event_id].append(
                    market.canonical_outcome)
            fixtures[market.canonical_event_id].add(market.canonical_outcome)
        # Complete means EXACTLY {home, draw, away}: an extra outcome is not
        # "complete plus a bonus", it is a mapping problem to name.
        expected = {"home", "draw", "away"}
        extras = {
            match_id: sorted(outcomes - expected)
            for match_id, outcomes in fixtures.items()
            if outcomes - expected
        }
        complete = {
            match_id for match_id, outcomes in fixtures.items()
            if outcomes == expected
            and match_id not in conflicting
        }
        incomplete = sorted(
            set(fixtures) - complete - set(conflicting) - set(extras))

        # Quote presence per MARKET (once each), pre-kickoff only where the
        # fixture kickoff is known.
        markets_with_quote = 0
        markets_without_quote: list[str] = []
        market_ids = [m.id for m in rows]
        # Two aggregates, deliberately separate: latest-ANY answers "is the
        # feed alive" (freshness); latest-PRE-KICKOFF answers "does the
        # benchmark have a closing quote" (eligibility). Folding them was the
        # bug -- a post-kickoff update made an earlier valid pre-match quote
        # look missing.
        kickoff_by_market: dict[int, datetime] = {}
        for market in rows:
            if market.canonical_event_id is None:
                continue
            match = db.get(Match, market.canonical_event_id)
            kickoff = _db_aware(match.kickoff_utc,
                                sqlite_naive_ok=sqlite_naive_ok) if match else None
            if kickoff is not None:
                kickoff_by_market[market.id] = kickoff
        latest_any_by_market: dict[int, datetime] = {}
        latest_prekick_by_market: dict[int, datetime] = {}
        latest_by_transport: dict[str, datetime] = {}
        if market_ids:
            ticks = (
                db.query(
                    VenuePriceTick.venue_market_id,
                    VenuePriceTick.transport,
                    VenuePriceTick.ts,
                )
                .filter(VenuePriceTick.venue_market_id.in_(market_ids))
                .all()
            )
            for market_id, transport, ts in ticks:
                ts = _db_aware(ts, sqlite_naive_ok=sqlite_naive_ok)
                if ts is None:
                    continue
                if (market_id not in latest_any_by_market
                        or ts > latest_any_by_market[market_id]):
                    latest_any_by_market[market_id] = ts
                kickoff = kickoff_by_market.get(market_id)
                if kickoff is not None and ts <= kickoff and (
                        market_id not in latest_prekick_by_market
                        or ts > latest_prekick_by_market[market_id]):
                    latest_prekick_by_market[market_id] = ts
                if (transport not in latest_by_transport
                        or ts > latest_by_transport[transport]):
                    latest_by_transport[transport] = ts
        for market in rows:
            if market.id in latest_any_by_market:
                markets_with_quote += 1
            else:
                markets_without_quote.append(market.venue_key)

        # Missing pre-match quotes for complete mapped fixtures: the exact
        # set the benchmark will want.
        fixtures_missing_prematch: list[int] = []
        for match_id in sorted(complete):
            fixture_markets = [
                m for m in rows
                if m.canonical_event_id == match_id and m.mapping_status == "mapped"
            ]
            if not fixture_markets or fixture_markets[0].id not in kickoff_by_market:
                continue
            for market in fixture_markets:
                if market.id not in latest_prekick_by_market:
                    fixtures_missing_prematch.append(match_id)
                    break

        venues[venue] = {
            "markets_total": len(rows),
            "mapping": dict(sorted(mapping_counts.items())),
            "mapped_fixtures": len(fixtures),
            "fixtures_with_complete_1x2": len(complete),
            "fixtures_incomplete_1x2": incomplete,
            "fixtures_with_unexpected_outcomes": {
                str(match_id): names for match_id, names in sorted(extras.items())
            },
            "fixtures_with_conflicting_outcomes": sorted(conflicting),
            "markets_with_any_quote": markets_with_quote,
            "markets_without_any_quote": sorted(markets_without_quote),
            "fixtures_missing_prematch_quote": sorted(
                set(fixtures_missing_prematch)),
            "quote_freshness_by_transport": {
                transport: {
                    "latest_quote_at": ts.isoformat(),
                    "age_seconds": int((now - ts).total_seconds()),
                }
                for transport, ts in sorted(latest_by_transport.items())
            },
        }

    heartbeats = (
        db.query(CaptureHeartbeat)
        .order_by(CaptureHeartbeat.venue, CaptureHeartbeat.worker,
                  CaptureHeartbeat.scheduled_cycle_at)
        .all()
    )
    freshness: dict[str, dict] = {}
    grouped: dict[tuple[str, str], list[CaptureHeartbeat]] = defaultdict(list)
    for heartbeat in heartbeats:
        grouped[(heartbeat.venue, heartbeat.worker)].append(heartbeat)
    for (venue, worker), rows in sorted(grouped.items()):
        last = rows[-1]
        completed = _db_aware(last.completed_at,
                              sqlite_naive_ok=sqlite_naive_ok)
        freshness[f"{venue}/{worker}"] = {
            "cycles": len(rows),
            "last_cycle_at": _db_aware(
                last.scheduled_cycle_at,
                sqlite_naive_ok=sqlite_naive_ok).isoformat(),
            "last_completed_at": completed.isoformat(),
            "age_seconds": int((now - completed).total_seconds()),
            "last_errors": last.error_count,
            "last_rate_limits": last.rate_limit_count,
        }

    return {
        "health_version": HEALTH_VERSION,
        "generated_at": now.isoformat(),
        "denominator": "fixtures and markets, never ticks",
        "venues": venues,
        "heartbeat_freshness_by_venue_worker": freshness,
    }
