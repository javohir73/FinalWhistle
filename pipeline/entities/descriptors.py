"""Deterministic descriptor extraction from stored venue-market metadata.

Grammar, not similarity. An extractor either parses the venue's own exact
structure into a :class:`MarketDescriptor` or returns an
:class:`ExtractionFailure` saying precisely what stopped it. There is no
partial credit and no string-distance anywhere.

Kalshi is fully extractable from the database row: the ticker IS structured
metadata (``KXEPLGAME-26AUG01ARSCHE-ARS``). Polymarket's stored row carries an
opaque conditionId and a display question only -- the structured slug lives in
the raw discovery payload, not the database -- so Polymarket resolution
requires operator-supplied metadata (see ``descriptor_from_metadata``) until
capture persists structure. That gap is reported, not papered over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from pipeline.entities.resolver import MarketDescriptor

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

KALSHI_GRAMMAR_VERSION = "kalshi-ticker-v1"
METADATA_GRAMMAR_VERSION = "operator-metadata-v1"


@dataclass(frozen=True)
class ExtractionFailure:
    """Why no descriptor could be built. Travels into resolution evidence."""

    reason: str
    ambiguous: bool = False


def _parse_ticker_date(token: str) -> datetime | None:
    """``26AUG01`` -> 2026-08-01 12:00 UTC.

    Tickers carry a date, not a kickoff time. Midday UTC puts the window
    symmetrically around the calendar day, so ordinary timezone skew between
    the venue's local date and the UTC kickoff stays inside the tolerance.
    """
    if len(token) != 7:
        return None
    year_part, month_part, day_part = token[:2], token[2:5], token[5:]
    if not (year_part.isdigit() and day_part.isdigit()):
        return None
    month = _MONTHS.get(month_part.upper())
    if month is None:
        return None
    try:
        return datetime(2000 + int(year_part), month, int(day_part), 12,
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def kalshi_descriptor(
    *,
    venue_key: str,
    market_type: str,
    verified_team_keys: frozenset[str],
) -> MarketDescriptor | ExtractionFailure:
    """Parse a Kalshi market ticker by its exact grammar.

    ``<SERIES>-<YY><MON><DD><HOME><AWAY>-<OUTCOME>``. The team block has no
    separator, so it is split ONLY where both halves are already verified
    team keys for this venue: the key registry, not string heuristics, does
    the disambiguation. Zero valid splits fails closed; two valid splits is a
    genuine ambiguity and abstains.

    The grammar assumes the venue lists the home side first. That assumption
    is recorded on the descriptor, because the resolver's orientation check
    is only as trustworthy as this line, and if the venue ever changes
    conventions the evidence must show which grammar made the claim.
    """
    parts = venue_key.strip().split("-")
    if len(parts) != 3:
        return ExtractionFailure(
            reason=f"ticker {venue_key!r} does not have exactly three segments"
        )
    series, event_part, outcome_part = parts
    if not series or not outcome_part:
        return ExtractionFailure(reason=f"ticker {venue_key!r} has empty segments")
    if len(event_part) <= 7:
        return ExtractionFailure(
            reason=f"ticker event segment {event_part!r} has no team block"
        )
    kickoff = _parse_ticker_date(event_part[:7])
    if kickoff is None:
        return ExtractionFailure(
            reason=f"ticker date {event_part[:7]!r} is not YYMONDD"
        )
    block = event_part[7:]
    splits = [
        (block[:i], block[i:])
        for i in range(1, len(block))
        if block[:i] in verified_team_keys and block[i:] in verified_team_keys
    ]
    if not splits:
        return ExtractionFailure(
            reason=(
                f"team block {block!r} has no split where both codes are "
                "verified kalshi team keys; add the missing entity_source_map "
                "rows rather than guessing"
            )
        )
    if len(splits) > 1:
        return ExtractionFailure(
            reason=(
                f"team block {block!r} splits validly more than one way "
                f"({', '.join('/'.join(s) for s in splits)}); abstaining"
            ),
            ambiguous=True,
        )
    home_code, away_code = splits[0]
    return MarketDescriptor(
        venue="kalshi",
        venue_key=venue_key,
        market_type=market_type,
        home_source_key=home_code,
        away_source_key=away_code,
        outcome_source_key=outcome_part,
        competition_source_key=series,
        kickoff_utc=kickoff,
        grammar={
            "extractor": KALSHI_GRAMMAR_VERSION,
            "assumption": "venue lists the home side first in the team block",
            "ticker": venue_key,
            "date_token": event_part[:7],
            "team_block": block,
        },
    )


_REQUIRED_METADATA = ("home_source_key", "away_source_key", "outcome_source_key")


def descriptor_from_metadata(
    *,
    venue: str,
    venue_key: str,
    market_type: str,
    metadata: Mapping[str, object],
) -> MarketDescriptor | ExtractionFailure:
    """Build a descriptor from explicit operator-supplied metadata.

    The escape hatch for venues whose stored rows carry no structure
    (Polymarket). Every field is taken verbatim -- the operator is asserting
    venue facts, not similarity -- and the metadata travels into the evidence
    so the assertion is auditable.
    """
    missing = [key for key in _REQUIRED_METADATA if not str(metadata.get(key) or "").strip()]
    if missing:
        return ExtractionFailure(
            reason="metadata missing required fields: " + ", ".join(missing)
        )
    kickoff_raw = metadata.get("kickoff_utc")
    kickoff = None
    if kickoff_raw is not None:
        try:
            kickoff = datetime.fromisoformat(str(kickoff_raw))
        except ValueError:
            return ExtractionFailure(
                reason=f"metadata kickoff_utc {kickoff_raw!r} is not ISO-8601"
            )
        if kickoff.tzinfo is None:
            return ExtractionFailure(
                reason="metadata kickoff_utc must be timezone-aware"
            )
    competition = metadata.get("competition_source_key")
    season = metadata.get("season_label")
    return MarketDescriptor(
        venue=venue,
        venue_key=venue_key,
        market_type=market_type,
        home_source_key=str(metadata["home_source_key"]),
        away_source_key=str(metadata["away_source_key"]),
        outcome_source_key=str(metadata["outcome_source_key"]),
        competition_source_key=str(competition) if competition else None,
        kickoff_utc=kickoff,
        season_label=str(season) if season else None,
        grammar={
            "extractor": METADATA_GRAMMAR_VERSION,
            "assumption": "operator-supplied venue facts, audited verbatim",
            "metadata": {key: str(value) for key, value in sorted(metadata.items())},
        },
    )
