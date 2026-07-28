"""Discovery-first Kalshi adapter for the prediction-market capture path.

The legacy ``pipeline.ingest.kalshi`` module remains untouched for the live
intel panel. This adapter uses Kalshi's catalogue metadata instead of ticker
allow-lists: fetch all series tagged exactly ``Soccer``, then cursor-paginate
open events with nested markets and retain markets belonging to those series.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
import re
from typing import Any
from urllib.parse import quote as url_quote

import requests

from pipeline.ingest.venues.types import (
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueMarket,
    VenuePayloadError,
)

log = logging.getLogger(__name__)

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
_PAGE_LIMIT = 200
_MARKET_TYPE_SEPARATOR = re.compile(r"[^a-z0-9]+")
_ONE = Decimal("1")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _market_type(series: dict[str, Any]) -> str:
    metadata = series.get("product_metadata")
    scope = metadata.get("scope") if isinstance(metadata, dict) else None
    source = scope or series.get("title") or "unknown"
    normalized = _MARKET_TYPE_SEPARATOR.sub("_", str(source).casefold()).strip("_")
    return normalized or "unknown"


def _fixed_point_levels(
    raw_levels: object, *, native_side: str
) -> tuple[OrderBookLevel, ...]:
    """Parse Kalshi fixed-point bids into normalized Yes-side levels."""

    if raw_levels is None:
        return ()
    if not isinstance(raw_levels, list):
        raise VenuePayloadError(
            f"kalshi {native_side}_dollars levels must be a list"
        )

    levels: list[OrderBookLevel] = []
    for index, raw_level in enumerate(raw_levels):
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) != 2:
            raise VenuePayloadError(
                f"kalshi {native_side}_dollars level {index} must be [price, size]"
            )
        try:
            price = Decimal(str(raw_level[0]))
            size = Decimal(str(raw_level[1]))
        except (InvalidOperation, ValueError):
            raise VenuePayloadError(
                f"kalshi {native_side}_dollars level {index} is not numeric"
            ) from None
        if not price.is_finite() or not _ONE >= price >= Decimal("0"):
            raise VenuePayloadError(
                f"kalshi {native_side}_dollars level {index} price must be between 0 and 1"
            )
        if not size.is_finite() or size <= 0:
            raise VenuePayloadError(
                f"kalshi {native_side}_dollars level {index} size must be greater than 0"
            )

        # Kalshi returns bids on both binary contracts. A No bid at P is a Yes
        # ask at 1-P. Do the complement in decimal space before normalizing.
        yes_price = _ONE - price if native_side == "no" else price
        try:
            levels.append(OrderBookLevel(price=float(yes_price), size=float(size)))
        except VenuePayloadError as exc:
            raise VenuePayloadError(
                f"kalshi {native_side}_dollars level {index}: {exc}"
            ) from exc
    return tuple(levels)


def _fixed_point_probability(value: object, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise VenuePayloadError(f"kalshi {field} is not numeric") from None
    if not parsed.is_finite() or not _ONE >= parsed >= Decimal("0"):
        raise VenuePayloadError(f"kalshi {field} must be between 0 and 1")
    return float(parsed)


class KalshiAdapter:
    """Kalshi catalogue discovery and full-book quote capture."""

    venue = "kalshi"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
        session: requests.Session | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _get(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise VenuePayloadError(f"kalshi {path} response must be an object")
        return payload

    def _soccer_series(self) -> dict[str, dict[str, Any]]:
        payload = self._get(
            "/series",
            {
                "category": "Sports",
                "tags": "Soccer",
                "include_product_metadata": "true",
            },
        )
        rows = payload.get("series")
        if not isinstance(rows, list):
            raise VenuePayloadError("kalshi series response must contain a list")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                log.warning("kalshi discovery: non-object series skipped")
                continue
            ticker = row.get("ticker")
            tags = row.get("tags") or []
            if not isinstance(ticker, str) or not ticker.strip():
                log.warning("kalshi discovery: series without ticker skipped")
                continue
            if not isinstance(tags, list) or not any(
                isinstance(tag, str) and tag.casefold() == "soccer" for tag in tags
            ):
                continue
            result[ticker.strip()] = row
        return result

    def _open_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, object] = {
                "limit": _PAGE_LIMIT,
                "status": "open",
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/events", params)
            page = payload.get("events")
            if not isinstance(page, list):
                raise VenuePayloadError("kalshi events response must contain a list")
            for event in page:
                if isinstance(event, dict):
                    events.append(event)
                else:
                    log.warning("kalshi discovery: non-object event skipped")
            next_cursor = payload.get("cursor")
            if not next_cursor:
                return events
            if not isinstance(next_cursor, str):
                raise VenuePayloadError("kalshi event cursor must be a string")
            if next_cursor in seen_cursors:
                raise VenuePayloadError("kalshi event pagination repeated a cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def discover_markets(self, sport: str) -> list[VenueMarket]:
        if sport != "football":
            return []
        discovered_at = self.now()
        series_by_ticker = self._soccer_series()
        markets: dict[tuple[str, str], VenueMarket] = {}
        for event in self._open_events():
            series_ticker = event.get("series_ticker")
            series = series_by_ticker.get(series_ticker)
            if series is None:
                continue
            nested = event.get("markets") or []
            if not isinstance(nested, list):
                log.warning(
                    "kalshi discovery: event %r has malformed markets",
                    event.get("event_ticker"),
                )
                continue
            for raw_market in nested:
                try:
                    market = self._to_market(
                        raw_market, event, series, discovered_at=discovered_at
                    )
                except VenuePayloadError as exc:
                    log.warning(
                        "kalshi discovery: market %r rejected: %s",
                        raw_market.get("ticker") if isinstance(raw_market, dict) else None,
                        exc,
                    )
                    continue
                markets.setdefault(market.identity_key, market)
        return list(markets.values())

    def _to_market(
        self,
        raw_market: object,
        event: dict[str, Any],
        series: dict[str, Any],
        *,
        discovered_at: datetime,
    ) -> VenueMarket:
        if not isinstance(raw_market, dict):
            raise VenuePayloadError("market must be an object")
        ticker = raw_market.get("ticker")
        status = raw_market.get("status")
        if not isinstance(ticker, str):
            raise VenuePayloadError("venue_key must not be empty")
        if not isinstance(status, str):
            raise VenuePayloadError("market status must be a string")
        return VenueMarket(
            venue=self.venue,
            venue_key=ticker,
            sport="football",
            raw_title=str(raw_market.get("title") or event.get("title") or ""),
            status=status.casefold(),
            discovered_at=discovered_at,
            market_type=_market_type(series),
            event_key=str(raw_market.get("event_ticker") or event.get("event_ticker") or "")
            or None,
            opened_at=_parse_time(raw_market.get("open_time")),
            closed_at=_parse_time(raw_market.get("close_time")),
            raw_payload={
                "series": series,
                "event": {key: value for key, value in event.items() if key != "markets"},
                "market": raw_market,
            },
        )

    def fetch_quote(self, venue_key: str) -> Quote:
        venue_key = venue_key.strip()
        if not venue_key:
            raise VenuePayloadError("venue_key must not be empty")
        payload = self._get(
            f"/markets/{url_quote(venue_key, safe='')}/orderbook", {"depth": 0}
        )
        raw_book = payload.get("orderbook_fp")
        if not isinstance(raw_book, dict):
            raise VenuePayloadError(
                "kalshi orderbook response must contain an orderbook_fp object"
            )

        try:
            book = OrderBook(
                yes_bids=_fixed_point_levels(
                    raw_book.get("yes_dollars"), native_side="yes"
                ),
                yes_asks=_fixed_point_levels(
                    raw_book.get("no_dollars"), native_side="no"
                ),
            )
        except VenuePayloadError as exc:
            raise VenuePayloadError(str(exc), raw_payload=payload) from exc
        market_payload = self._get(
            f"/markets/{url_quote(venue_key, safe='')}", {}
        )
        raw_market = market_payload.get("market")
        if not isinstance(raw_market, dict):
            raise VenuePayloadError(
                "kalshi market response must contain a market object",
                raw_payload={"orderbook": payload, "market": market_payload},
            )
        raw_payload = {"orderbook": payload, "market": market_payload}
        try:
            last = _fixed_point_probability(
                raw_market.get("last_price_dollars"), field="last_price_dollars"
            )
        except VenuePayloadError as exc:
            raise VenuePayloadError(str(exc), raw_payload=raw_payload) from exc
        return Quote(
            venue=self.venue,
            venue_key=venue_key,
            observed_at=self.now(),
            transport="polling",
            book=book,
            last=last,
            raw_payload=raw_payload,
        )

    def fetch_settlement(self, venue_key: str) -> Settlement | None:
        venue_key = venue_key.strip()
        if not venue_key:
            raise VenuePayloadError("venue_key must not be empty")
        payload = self._get(f"/markets/{url_quote(venue_key, safe='')}", {})
        market = payload.get("market")
        if not isinstance(market, dict):
            raise VenuePayloadError(
                "kalshi market response must contain a market object",
                raw_payload=payload,
            )
        status = str(market.get("status") or "").casefold()
        result = str(market.get("result") or "").casefold()
        if status != "finalized":
            return None
        settled_at = _parse_time(market.get("settlement_ts"))
        if settled_at is None:
            raise VenuePayloadError(
                "kalshi finalized market is missing settlement_ts",
                raw_payload=payload,
            )
        if result in {"void", "voided"}:
            settlement_status = "void"
            outcome = None
        elif result in {"cancelled", "canceled"}:
            settlement_status = "cancelled"
            outcome = None
        elif result:
            settlement_status = "settled"
            outcome = result
        else:
            raise VenuePayloadError(
                "kalshi finalized market is missing a result",
                raw_payload=payload,
            )
        return Settlement(
            venue=self.venue,
            venue_key=venue_key,
            status=settlement_status,
            outcome=outcome,
            settled_at=settled_at,
            source=f"markets/{venue_key}",
            source_event_id=str(
                market.get("updated_time") or market.get("settlement_ts")
            ),
            raw_payload=payload,
        )
