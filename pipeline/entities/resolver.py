"""Fail-closed, exact-key resolver for venue markets.

Display-title similarity is deliberately absent from the resolution path. A
caller must supply verified source-key mappings and structured participant /
outcome fields extracted by a venue-specific parser. Similarity is exposed as
an operator suggestion only and never persists a mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CanonicalFixture:
    event_id: int
    home_entity_id: int
    away_entity_id: int
    competition_entity_id: int | None = None


@dataclass(frozen=True)
class ExactMarketDescriptor:
    venue: str
    venue_key: str
    market_type: str
    home_source_key: str
    away_source_key: str
    outcome_key: str
    competition_source_key: str | None = None


@dataclass(frozen=True)
class Resolution:
    status: str
    canonical_event_id: int | None = None
    canonical_outcome: str | None = None
    candidate_event_ids: tuple[int, ...] = ()
    reason: str = ""

    @property
    def serveable(self) -> bool:
        return (
            self.status == "mapped"
            and self.canonical_event_id is not None
            and self.canonical_outcome is not None
        )


_SCORE = re.compile(r"^score:(\d+)-(\d+)$")
_TOTAL = re.compile(r"^total:(over|under):(\d+(?:\.5)?)$")
_SPREAD = re.compile(r"^(home|away):([+-]?\d+(?:\.5)?)$")


def _normalize_outcome(market_type: str, key: str) -> str | None:
    """Parse only explicit, lossless outcome keys from adapter metadata."""
    if market_type == "match_winner" and key in {"home", "draw", "away"}:
        return key
    if market_type == "first_half" and key in {
        "first_half:home",
        "first_half:draw",
        "first_half:away",
    }:
        return key
    if market_type == "correct_score" and _SCORE.fullmatch(key):
        return key
    if market_type == "btts" and key in {"btts:yes", "btts:no"}:
        return key
    if market_type == "total" and _TOTAL.fullmatch(key):
        return key
    if market_type == "spread" and _SPREAD.fullmatch(key):
        return f"spread:{key}"
    return None


def _reverse(outcome: str) -> str:
    swaps = {
        "home": "away",
        "away": "home",
        "first_half:home": "first_half:away",
        "first_half:away": "first_half:home",
    }
    if outcome in swaps:
        return swaps[outcome]
    score = _SCORE.fullmatch(outcome)
    if score:
        return f"score:{score.group(2)}-{score.group(1)}"
    spread = re.fullmatch(r"spread:(home|away):(.+)", outcome)
    if spread:
        side = "away" if spread.group(1) == "home" else "home"
        return f"spread:{side}:{spread.group(2)}"
    return outcome


def resolve_market(
    descriptor: ExactMarketDescriptor,
    *,
    source_entities: Mapping[tuple[str, str], int],
    fixtures: Sequence[CanonicalFixture],
    entity_kinds: Mapping[int, str] | None = None,
) -> Resolution:
    """Resolve one structured venue market using verified exact keys only."""
    home_id = source_entities.get((descriptor.venue, descriptor.home_source_key))
    away_id = source_entities.get((descriptor.venue, descriptor.away_source_key))
    if home_id is None or away_id is None:
        missing = []
        if home_id is None:
            missing.append(descriptor.home_source_key)
        if away_id is None:
            missing.append(descriptor.away_source_key)
        return Resolution(status="unmapped", reason=f"unverified participant key(s): {', '.join(missing)}")
    if home_id == away_id:
        return Resolution(status="unmapped", reason="participants resolve to the same entity")
    if entity_kinds is not None and (
        entity_kinds.get(home_id) != "team" or entity_kinds.get(away_id) != "team"
    ):
        return Resolution(status="unmapped", reason="participant key is not a team")

    competition_id = None
    if descriptor.competition_source_key is not None:
        competition_id = source_entities.get(
            (descriptor.venue, descriptor.competition_source_key)
        )
        if competition_id is None:
            return Resolution(status="unmapped", reason="unverified competition key")
        if entity_kinds is not None and entity_kinds.get(competition_id) != "competition":
            return Resolution(status="unmapped", reason="competition key is not a competition")

    candidates = [
        fixture
        for fixture in fixtures
        if {fixture.home_entity_id, fixture.away_entity_id} == {home_id, away_id}
        and (
            competition_id is None
            or fixture.competition_entity_id == competition_id
        )
    ]
    if not candidates:
        return Resolution(status="unmapped", reason="no exact canonical fixture")
    if len(candidates) > 1:
        return Resolution(
            status="ambiguous",
            candidate_event_ids=tuple(sorted(item.event_id for item in candidates)),
            reason="multiple exact canonical fixtures",
        )

    outcome = _normalize_outcome(descriptor.market_type, descriptor.outcome_key)
    if outcome is None:
        return Resolution(
            status="unmapped",
            candidate_event_ids=(candidates[0].event_id,),
            reason="unsupported or incomplete outcome key",
        )
    fixture = candidates[0]
    if fixture.home_entity_id != home_id:
        outcome = _reverse(outcome)
    return Resolution(
        status="mapped",
        canonical_event_id=fixture.event_id,
        canonical_outcome=outcome,
        candidate_event_ids=(fixture.event_id,),
        reason="exact verified source keys",
    )


def suggest_entities(
    raw_name: str,
    canonical_names: Mapping[int, str],
    *,
    limit: int = 3,
) -> list[dict[str, int | float | str]]:
    """Return review-only similarity suggestions; this function writes nothing."""
    normalized = " ".join(raw_name.casefold().split())
    ranked = sorted(
        (
            {
                "entity_id": entity_id,
                "canonical_name": name,
                "similarity": SequenceMatcher(
                    None, normalized, " ".join(name.casefold().split())
                ).ratio(),
            }
            for entity_id, name in canonical_names.items()
        ),
        key=lambda item: (-float(item["similarity"]), int(item["entity_id"])),
    )
    return ranked[:limit]
