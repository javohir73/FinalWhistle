"""Discovery-first Polymarket adapter for prediction-market capture.

The legacy :mod:`pipeline.ingest.polymarket` adapter remains unchanged for the
intel panel. This adapter resolves Polymarket's catalogue-level ``soccer`` tag,
then walks the public Gamma event catalogue with keyset pagination. Relevance
and entity mapping happen downstream; discovery keeps every addressable market.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
import re
from typing import Any
from urllib.parse import quote as url_quote

import requests

from pipeline.ingest.venues.types import (
    UNSUPPORTED_IN_PLAY,
    OrderBook,
    OrderBookLevel,
    Quote,
    Settlement,
    VenueMarket,
    VenuePayloadError,
)

log = logging.getLogger(__name__)

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
SOCCER_TAG_SLUG = "soccer"
_PAGE_LIMIT = 100
_MARKET_TYPE_SEPARATOR = re.compile(r"[^a-z0-9]+")
_ONE = Decimal("1")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _market_type(raw_market: dict[str, Any]) -> str:
    source = raw_market.get("sportsMarketType") or "unknown"
    normalized = _MARKET_TYPE_SEPARATOR.sub("_", str(source).casefold()).strip("_")
    return normalized or "unknown"


def _market_status(raw_market: dict[str, Any]) -> str:
    if raw_market.get("closed"):
        return "closed"
    if raw_market.get("active"):
        return "active"
    if raw_market.get("archived"):
        return "archived"
    return "inactive"


def _book_levels(raw_levels: object, *, side: str) -> tuple[OrderBookLevel, ...]:
    if raw_levels is None:
        return ()
    if not isinstance(raw_levels, list):
        raise VenuePayloadError(f"polymarket {side} levels must be a list")
    levels: list[OrderBookLevel] = []
    for index, raw_level in enumerate(raw_levels):
        if not isinstance(raw_level, dict):
            raise VenuePayloadError(
                f"polymarket {side} level {index} must be an object"
            )
        try:
            price = Decimal(str(raw_level.get("price")))
            size = Decimal(str(raw_level.get("size")))
        except (InvalidOperation, ValueError):
            raise VenuePayloadError(
                f"polymarket {side} level {index} is not numeric"
            ) from None
        if not price.is_finite() or not _ONE >= price >= Decimal("0"):
            raise VenuePayloadError(
                f"polymarket {side} level {index} price must be between 0 and 1"
            )
        if not size.is_finite() or size <= 0:
            raise VenuePayloadError(
                f"polymarket {side} level {index} size must be greater than 0"
            )
        levels.append(OrderBookLevel(float(price), float(size)))
    return tuple(levels)


def _probability(value: object, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise VenuePayloadError(f"polymarket {field} is not numeric") from None
    if not decimal.is_finite() or not _ONE >= decimal >= Decimal("0"):
        raise VenuePayloadError(f"polymarket {field} must be between 0 and 1")
    return float(decimal)


def _source_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        raw = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise VenuePayloadError("polymarket book timestamp is not numeric") from None
    if not raw.is_finite() or raw < 0:
        raise VenuePayloadError("polymarket book timestamp is invalid")
    # Current CLOB snapshots use Unix milliseconds; accept seconds for older
    # recorded fixtures and documentation examples.
    seconds = raw / 1000 if raw >= Decimal("100000000000") else raw
    try:
        return datetime.fromtimestamp(float(seconds), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise VenuePayloadError("polymarket book timestamp is invalid") from None


def _json_array(value: object, *, field: str) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        raise VenuePayloadError(f"polymarket {field} must be a JSON array")
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise VenuePayloadError(f"polymarket {field} must be valid JSON") from None
    if not isinstance(parsed, list):
        raise VenuePayloadError(f"polymarket {field} must be a JSON array")
    return parsed


class PolymarketAdapter:
    """Polymarket Gamma catalogue discovery, CLOB quote and settlement."""

    venue = "polymarket"

    #: Live match state this venue publishes in the payloads capture reads.
    #: Empty, and the reason is worth stating because it is not obvious.
    #:
    #: Gamma events DO carry `live`, `elapsed` and `period` -- but they arrive
    #: on the six-hourly discovery response, not on the CLOB book a quote is
    #: built from. Attaching a clock that may be hours old to a thirty-second
    #: tick would be a fabricated observation, and the fabrication would be
    #: invisible downstream. Fetching event state per quote would double the
    #: request rate against a public rate limit for a clock with no score
    #: beside it, which no state-matched comparison can use anyway.
    #:
    #: `live` is still read, for CADENCE ONLY (see CaptureWorker._cadence_in_play):
    #: a stale hint that makes us poll faster is harmless.
    in_play_state_fields: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        gamma_base_url: str = GAMMA_BASE_URL,
        clob_base_url: str = CLOB_BASE_URL,
        timeout: float = 15.0,
        session: requests.Session | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _get(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.gamma_base_url}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise VenuePayloadError(f"polymarket {path} response must be an object")
        return payload

    def _get_clob(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.clob_base_url}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise VenuePayloadError(f"polymarket CLOB {path} response must be an object")
        return payload

    def _get_gamma_list(
        self, path: str, params: dict[str, object]
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.gamma_base_url}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise VenuePayloadError(f"polymarket {path} response must be a list")
        return payload

    def _soccer_tag(self) -> dict[str, Any]:
        payload = self._get(
            f"/tags/slug/{url_quote(SOCCER_TAG_SLUG, safe='')}", {}
        )
        tag_id = payload.get("id")
        slug = payload.get("slug")
        try:
            parsed_id = int(str(tag_id))
        except (TypeError, ValueError):
            raise VenuePayloadError(
                "polymarket soccer tag must have a numeric id"
            ) from None
        if (
            parsed_id <= 0
            or not isinstance(slug, str)
            or slug.casefold() != SOCCER_TAG_SLUG
        ):
            raise VenuePayloadError("polymarket soccer tag response is inconsistent")
        return payload

    def _active_events(self, tag_id: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, object] = {
                "tag_id": tag_id,
                "active": "true",
                "closed": "false",
                "limit": _PAGE_LIMIT,
            }
            if cursor:
                params["after_cursor"] = cursor
            payload = self._get("/events/keyset", params)
            page = payload.get("events")
            if not isinstance(page, list):
                raise VenuePayloadError(
                    "polymarket keyset response must contain an events list"
                )
            for event in page:
                if isinstance(event, dict):
                    events.append(event)
                else:
                    log.warning("polymarket discovery: non-object event skipped")

            next_cursor = payload.get("next_cursor")
            if not next_cursor:
                return events
            if not isinstance(next_cursor, str):
                raise VenuePayloadError("polymarket event cursor must be a string")
            if next_cursor in seen_cursors:
                raise VenuePayloadError(
                    "polymarket event pagination repeated a cursor"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def discover_markets(self, sport: str) -> list[VenueMarket]:
        if sport != "football":
            return []
        discovered_at = self.now()
        tag = self._soccer_tag()
        tag_id = int(str(tag["id"]))
        markets: dict[tuple[str, str], VenueMarket] = {}
        for event in self._active_events(tag_id):
            nested = event.get("markets") or []
            if not isinstance(nested, list):
                log.warning(
                    "polymarket discovery: event %r has malformed markets",
                    event.get("id") or event.get("slug"),
                )
                continue
            for raw_market in nested:
                try:
                    market = self._to_market(
                        raw_market,
                        event,
                        tag,
                        discovered_at=discovered_at,
                    )
                except VenuePayloadError as exc:
                    log.warning(
                        "polymarket discovery: market %r rejected: %s",
                        raw_market.get("id")
                        if isinstance(raw_market, dict)
                        else None,
                        exc,
                    )
                    continue
                markets.setdefault(market.identity_key, market)
        return list(markets.values())

    def _to_market(
        self,
        raw_market: object,
        event: dict[str, Any],
        tag: dict[str, Any],
        *,
        discovered_at: datetime,
    ) -> VenueMarket:
        if not isinstance(raw_market, dict):
            raise VenuePayloadError("market must be an object")
        condition_id = raw_market.get("conditionId")
        if not isinstance(condition_id, str) or not condition_id.strip():
            raise VenuePayloadError("conditionId must not be empty")

        event_key = event.get("id") or event.get("slug")
        return VenueMarket(
            venue=self.venue,
            venue_key=condition_id,
            sport="football",
            raw_title=str(raw_market.get("question") or event.get("title") or ""),
            status=_market_status(raw_market),
            discovered_at=discovered_at,
            market_type=_market_type(raw_market),
            event_key=str(event_key) if event_key is not None else None,
            opened_at=_parse_time(
                raw_market.get("startDate") or raw_market.get("startDateIso")
            ),
            closed_at=_parse_time(
                raw_market.get("endDate") or raw_market.get("endDateIso")
            ),
            raw_payload={
                "tag": tag,
                "event": {key: value for key, value in event.items() if key != "markets"},
                "market": raw_market,
            },
        )

    def fetch_quote(self, venue_key: str) -> Quote:
        venue_key = venue_key.strip()
        if not venue_key:
            raise VenuePayloadError("venue_key must not be empty")
        market_info = self._get_clob(
            f"/clob-markets/{url_quote(venue_key, safe='')}", {}
        )
        raw_tokens = market_info.get("t") or market_info.get("tokens")
        if not isinstance(raw_tokens, list):
            raise VenuePayloadError(
                "polymarket CLOB market is missing tokens", raw_payload=market_info
            )
        yes_tokens = []
        for token in raw_tokens:
            if not isinstance(token, dict):
                continue
            outcome = token.get("o") or token.get("outcome")
            token_id = token.get("t") or token.get("token_id")
            if (
                isinstance(outcome, str)
                and outcome.casefold() == "yes"
                and isinstance(token_id, str)
                and token_id.strip()
            ):
                yes_tokens.append(token_id.strip())
        if len(yes_tokens) != 1:
            raise VenuePayloadError(
                "polymarket CLOB market must contain exactly one Yes token",
                raw_payload=market_info,
            )

        book_payload = self._get_clob("/book", {"token_id": yes_tokens[0]})
        raw_payload = {"market": market_info, "book": book_payload}
        if book_payload.get("market") not in {None, "", venue_key}:
            raise VenuePayloadError(
                "polymarket order book condition id does not match venue_key",
                raw_payload=raw_payload,
            )
        try:
            book = OrderBook(
                yes_bids=_book_levels(book_payload.get("bids"), side="bids"),
                yes_asks=_book_levels(book_payload.get("asks"), side="asks"),
            )
            last = _probability(
                book_payload.get("last_trade_price"), field="last_trade_price"
            )
            source_ts = _source_timestamp(book_payload.get("timestamp"))
        except VenuePayloadError as exc:
            raise VenuePayloadError(str(exc), raw_payload=raw_payload) from exc
        observed_at = self.now()
        if source_ts is not None and source_ts > observed_at:
            raise VenuePayloadError(
                "polymarket book timestamp is in the future",
                raw_payload=raw_payload,
            )
        return Quote(
            venue=self.venue,
            venue_key=venue_key,
            observed_at=observed_at,
            transport="polling",
            book=book,
            last=last,
            source_ts=source_ts,
            source_event_id=str(book_payload.get("hash") or "").strip() or None,
            in_play=UNSUPPORTED_IN_PLAY,
            raw_payload=raw_payload,
        )

    def fetch_settlement(self, venue_key: str) -> Settlement | None:
        venue_key = venue_key.strip()
        if not venue_key:
            raise VenuePayloadError("venue_key must not be empty")
        rows = self._get_gamma_list(
            "/markets", {"condition_ids": venue_key, "closed": "true", "limit": 2}
        )
        matching = [row for row in rows if row.get("conditionId") == venue_key]
        if not matching:
            return None
        if len(matching) != 1:
            raise VenuePayloadError(
                "polymarket settlement lookup returned duplicate condition ids",
                raw_payload={"markets": matching},
            )
        market = matching[0]
        resolution_status = str(
            market.get("umaResolutionStatus") or market.get("umaResolutionStatuses") or ""
        ).casefold()
        settled_at = _parse_time(
            market.get("closedTime") or market.get("updatedAt") or market.get("endDate")
        )
        if resolution_status in {"cancelled", "canceled"}:
            status, outcome = "cancelled", None
        elif resolution_status in {"void", "voided", "invalid"}:
            status, outcome = "void", None
        else:
            try:
                outcomes = _json_array(market.get("outcomes"), field="outcomes")
                raw_prices = _json_array(
                    market.get("outcomePrices"), field="outcomePrices"
                )
                prices = [Decimal(str(value)) for value in raw_prices]
            except (InvalidOperation, VenuePayloadError) as exc:
                if isinstance(exc, VenuePayloadError):
                    raise VenuePayloadError(
                        str(exc), raw_payload={"market": market}
                    ) from exc
                raise VenuePayloadError(
                    "polymarket outcomePrices contains a non-numeric value",
                    raw_payload={"market": market},
                ) from exc
            if len(outcomes) != len(prices) or not outcomes:
                raise VenuePayloadError(
                    "polymarket outcomes and outcomePrices must align",
                    raw_payload={"market": market},
                )
            if all(price == Decimal("0.5") for price in prices):
                status, outcome = "void", None
            else:
                winners = [
                    str(outcomes[index])
                    for index, price in enumerate(prices)
                    if price == _ONE
                ]
                if len(winners) != 1:
                    return None
                status, outcome = "settled", winners[0]
        if settled_at is None:
            raise VenuePayloadError(
                "polymarket resolved market is missing a settlement timestamp",
                raw_payload={"market": market},
            )
        return Settlement(
            venue=self.venue,
            venue_key=venue_key,
            status=status,
            outcome=outcome,
            settled_at=settled_at,
            source=f"markets?condition_ids={venue_key}",
            source_event_id=str(
                market.get("updatedAt")
                or market.get("closedTime")
                or settled_at.isoformat()
            ),
            raw_payload={"market": market},
        )
