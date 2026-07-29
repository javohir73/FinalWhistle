"""Deterministic venue-market -> fixture resolution and reconciliation."""

from pipeline.entities.resolver import (
    AMBIGUOUS,
    DEFAULT_KICKOFF_TOLERANCE,
    MAPPED,
    PROPOSED,
    RESOLVER_VERSION,
    UNMAPPED,
    CandidateAssessment,
    FixtureCandidate,
    MarketDescriptor,
    Resolution,
    normalize_outcome,
    resolve_market,
    valid_verification,
)

__all__ = [
    "AMBIGUOUS",
    "DEFAULT_KICKOFF_TOLERANCE",
    "MAPPED",
    "PROPOSED",
    "RESOLVER_VERSION",
    "UNMAPPED",
    "CandidateAssessment",
    "FixtureCandidate",
    "MarketDescriptor",
    "Resolution",
    "normalize_outcome",
    "resolve_market",
    "valid_verification",
]
