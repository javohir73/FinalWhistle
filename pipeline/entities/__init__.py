"""Canonical entity resolution for captured prediction markets."""

from .resolver import (
    CanonicalFixture,
    ExactMarketDescriptor,
    Resolution,
    suggest_entities,
    resolve_market,
)

__all__ = [
    "CanonicalFixture",
    "ExactMarketDescriptor",
    "Resolution",
    "suggest_entities",
    "resolve_market",
]
