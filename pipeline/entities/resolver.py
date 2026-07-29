"""Deterministic venue-market -> fixture resolution. Pure: no I/O, no DB.

The one rule everything here serves: **a mapping is written only when every
dimension agrees, and anything short of that abstains out loud.** The original
branch matched fixtures on ``{home, away}`` as an unordered set with no
competition, season or kickoff constraint -- which silently conflates the two
legs of a tie, a reverse fixture, a cup meeting in league week, and the same
pairing a season later. All four appear in real football every month.

Five dimensions must be POSITIVELY consistent before an auto-link:

1. **participants** -- both venue keys resolve through verified
   ``entity_source_map`` rows; no similarity, ever;
2. **orientation** -- descriptor home is fixture home AND descriptor away is
   fixture away. A reversed match is a different fixture (the other leg), so
   it is never "close enough";
3. **competition** -- the market's competition key resolves to the fixture's
   competition entity;
4. **kickoff window** -- the venue's declared date/time within a bounded
   tolerance of the fixture kickoff;
5. **season** -- declared and equal when the descriptor carries one;
   otherwise kickoff-within-window plus competition IS the season gate, and
   the evidence says so rather than pretending a fifth check ran.

Missing metadata is not consistency. It downgrades the best possible outcome
to ``proposed`` -- a review candidate with its explanation attached -- and a
tie between surviving candidates is ``ambiguous``, never a coin flip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

RESOLVER_VERSION = "market-fixture-resolver-v1"

#: Kickoff tolerance for auto-linking. Wide enough for timezone skew between
#: a venue's local match date and the UTC kickoff; far narrower than the gap
#: between two meetings of the same clubs (legs are a week+ apart, cup and
#: league meetings days apart). Two survivors inside one window abstain.
DEFAULT_KICKOFF_TOLERANCE = timedelta(hours=36)

#: Fixture statuses that must never be auto-linked: the venue may still be
#: quoting a match our data says is not happening as scheduled.
#:
#: HONESTY NOTE: today's ingestion (league_structure._STATUS,
#: live_scores._STATUS_MAP) normalizes SUSP/PST/CANC/ABD to internal
#: "scheduled", so these values never reach a fixture candidate and this
#: guard is INERT in production. It is a contract for the resolver core, kept
#: so the day a provider-status column lands the behavior already exists --
#: not a claim that stopped fixtures are currently detected. The gap is
#: recorded in docs/PREDICTION-MARKET-RESOLUTION.md.
_UNLINKABLE_FIXTURE_STATUSES = frozenset({"postponed", "cancelled", "abandoned"})

_DRAW_KEYS = frozenset({"draw", "tie", "x"})

MAPPED = "mapped"
PROPOSED = "proposed"
AMBIGUOUS = "ambiguous"
UNMAPPED = "unmapped"


@dataclass(frozen=True)
class MarketDescriptor:
    """Structured venue metadata for one market, extracted deterministically.

    Every field is either exact venue data or absent. A descriptor never
    carries a guess: extractors that cannot parse structure return None
    rather than a partial descriptor.
    """

    venue: str
    venue_key: str
    market_type: str
    home_source_key: str
    away_source_key: str
    outcome_source_key: str
    competition_source_key: str | None = None
    kickoff_utc: datetime | None = None
    season_label: str | None = None
    #: Which extractor produced this and from which raw fields -- evidence,
    #: because grammar assumptions (e.g. "home team listed first") must be
    #: auditable when a venue changes conventions.
    grammar: Mapping[str, object] = field(default_factory=dict)
    #: Named human verification of the ASSERTED FACTS (orientation, kickoff,
    #: competition): ``{"by": ..., "note": ...}``. None means the descriptor
    #: was derived by grammar from venue strings -- and Kalshi's own docs say
    #: tickers have exceptions and must not be parsed to infer relationships
    #: (docs.kalshi.com/getting_started/terms). An unverified descriptor can
    #: therefore NEVER produce a mapping, only a review hint: full consistency
    #: caps at ``proposed``.
    verification: Mapping[str, str] | None = None


@dataclass(frozen=True)
class FixtureCandidate:
    """One of our Match rows, lifted into entity space by the caller."""

    match_id: int
    home_entity_id: int
    away_entity_id: int
    competition_entity_id: int | None
    kickoff_utc: datetime | None
    status: str = "scheduled"
    season_label: str | None = None


@dataclass(frozen=True)
class CandidateAssessment:
    """Every check run against one fixture, kept whether it passed or not."""

    match_id: int
    checks: tuple[tuple[str, str], ...]
    accepted: bool
    rejections: tuple[str, ...]


@dataclass(frozen=True)
class Resolution:
    status: str
    match_id: int | None = None
    canonical_outcome: str | None = None
    reason: str = ""
    assessments: tuple[CandidateAssessment, ...] = ()
    #: For PROPOSED: the single candidate under review, with the explanation
    #: in `reason`. Never written to canonical_event_id -- review only.
    proposed_match_id: int | None = None
    missing: tuple[str, ...] = ()

    @property
    def serveable(self) -> bool:
        return (
            self.status == MAPPED
            and self.match_id is not None
            and self.canonical_outcome is not None
        )


def valid_verification(verification: Mapping[str, str] | None) -> bool:
    """Is this a usable verification: a non-blank person AND a non-blank note?

    The cap is only as strong as this check. Testing ``is None`` alone lets a
    direct caller reach MAPPED with ``{}``, ``{"by": ""}``, a missing note, or
    whitespace -- verification theater, not verification. Anything short of
    both fields non-blank is treated as unverified.
    """
    if verification is None:
        return False
    by = str(verification.get("by") or "").strip()
    note = str(verification.get("note") or "").strip()
    return bool(by) and bool(note)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_outcome(
    descriptor: MarketDescriptor,
) -> str | None:
    """Map the venue's outcome key onto home/draw/away, or refuse.

    Resolution v1 handles ``match_winner`` only; other market types have no
    canonical outcome yet and must stay unmapped rather than be approximated.
    """
    if descriptor.market_type != "match_winner":
        return None
    key = descriptor.outcome_source_key.strip().casefold()
    if key in _DRAW_KEYS:
        return "draw"
    if key == descriptor.home_source_key.strip().casefold():
        return "home"
    if key == descriptor.away_source_key.strip().casefold():
        return "away"
    return None


def resolve_market(
    descriptor: MarketDescriptor,
    *,
    source_entities: Mapping[tuple[str, str], int],
    entity_kinds: Mapping[int, str],
    fixtures: Sequence[FixtureCandidate],
    kickoff_tolerance: timedelta = DEFAULT_KICKOFF_TOLERANCE,
) -> Resolution:
    """Resolve one descriptor against fixture candidates. Pure and total.

    ``source_entities`` maps verified ``(source, source_key)`` pairs to
    entity ids -- venue keys AND the internal side (``("internal",
    "team:<id>")``), so comparison happens entirely in entity space.
    """
    missing = []
    home_id = source_entities.get((descriptor.venue, descriptor.home_source_key))
    away_id = source_entities.get((descriptor.venue, descriptor.away_source_key))
    if home_id is None:
        missing.append(f"team key {descriptor.home_source_key!r}")
    if away_id is None:
        missing.append(f"team key {descriptor.away_source_key!r}")
    competition_id = None
    if descriptor.competition_source_key is not None:
        competition_id = source_entities.get(
            (descriptor.venue, descriptor.competition_source_key)
        )
        if competition_id is None:
            missing.append(
                f"competition key {descriptor.competition_source_key!r}"
            )
    if missing:
        return Resolution(
            status=UNMAPPED,
            reason="unverified source keys: " + ", ".join(sorted(missing)),
            missing=tuple(sorted(missing)),
        )
    if home_id == away_id:
        return Resolution(
            status=UNMAPPED,
            reason="home and away keys resolve to the same entity",
        )
    for entity_id, label in ((home_id, "home"), (away_id, "away")):
        if entity_kinds.get(entity_id) != "team":
            return Resolution(
                status=UNMAPPED,
                reason=f"{label} key resolves to a non-team entity",
            )
    if competition_id is not None and entity_kinds.get(competition_id) != "competition":
        return Resolution(
            status=UNMAPPED,
            reason="competition key resolves to a non-competition entity",
        )

    outcome = normalize_outcome(descriptor)
    kickoff = _utc(descriptor.kickoff_utc)

    assessments: list[CandidateAssessment] = []
    accepted: list[FixtureCandidate] = []
    near_misses: list[tuple[FixtureCandidate, str]] = []
    for fixture in sorted(
        fixtures, key=lambda f: (_utc(f.kickoff_utc) or datetime.max.replace(
            tzinfo=timezone.utc), f.match_id)
    ):
        checks: list[tuple[str, str]] = []
        rejections: list[str] = []

        exact = (fixture.home_entity_id == home_id
                 and fixture.away_entity_id == away_id)
        reversed_pair = (fixture.home_entity_id == away_id
                         and fixture.away_entity_id == home_id)
        if exact:
            checks.append(("orientation", "exact"))
        elif reversed_pair:
            checks.append(("orientation", "reversed"))
            rejections.append("reversed_orientation")
        else:
            # Not this pairing at all: not evidence, not a near miss.
            continue

        if competition_id is None:
            checks.append(("competition", "not_declared_by_market"))
            rejections.append("competition_not_declared")
        elif fixture.competition_entity_id == competition_id:
            checks.append(("competition", "match"))
        else:
            checks.append(("competition", "mismatch"))
            rejections.append("competition_mismatch")

        fixture_kickoff = _utc(fixture.kickoff_utc)
        if kickoff is None:
            checks.append(("kickoff", "not_declared_by_market"))
            rejections.append("kickoff_not_declared")
        elif fixture_kickoff is None:
            checks.append(("kickoff", "fixture_kickoff_unknown"))
            rejections.append("fixture_kickoff_unknown")
        else:
            delta = abs(fixture_kickoff - kickoff)
            if delta <= kickoff_tolerance:
                checks.append(("kickoff", f"within_window ({delta})"))
            else:
                checks.append(("kickoff", f"outside_window ({delta})"))
                rejections.append("kickoff_outside_window")

        if descriptor.season_label is not None and fixture.season_label is not None:
            if descriptor.season_label == fixture.season_label:
                checks.append(("season", "match"))
            else:
                checks.append(("season", "mismatch"))
                rejections.append("season_mismatch")
        else:
            # Stated honestly: with no declared season, kickoff-within-window
            # plus competition IS the season gate. A fixture matched inside
            # the window belongs to exactly one tournament season.
            checks.append(("season", "gated_by_kickoff_and_competition"))

        status = fixture.status.strip().casefold()
        if status in _UNLINKABLE_FIXTURE_STATUSES:
            checks.append(("fixture_status", status))
            rejections.append(f"fixture_{status}")
        else:
            checks.append(("fixture_status", status or "unknown"))

        ok = not rejections
        assessments.append(CandidateAssessment(
            match_id=fixture.match_id,
            checks=tuple(checks),
            accepted=ok,
            rejections=tuple(rejections),
        ))
        if ok:
            accepted.append(fixture)
        elif len(rejections) == 1:
            near_misses.append((fixture, rejections[0]))

    evidence = tuple(assessments)

    if len(accepted) > 1:
        return Resolution(
            status=AMBIGUOUS,
            reason=(
                "several fixtures satisfy every constraint: "
                + ", ".join(str(f.match_id) for f in accepted)
                + "; abstaining"
            ),
            assessments=evidence,
        )
    if len(accepted) == 1:
        if outcome is None:
            return Resolution(
                status=UNMAPPED,
                reason=(
                    f"outcome key {descriptor.outcome_source_key!r} cannot be "
                    f"normalized for market type {descriptor.market_type!r}"
                ),
                assessments=evidence,
            )
        if not valid_verification(descriptor.verification):
            # Grammar-derived facts are hints, not labels. Kalshi documents
            # ticker exceptions and advises against parsing tickers to infer
            # relationships; a recorded assumption does not make a training
            # label safe. And a PRESENT-but-blank verification is the same
            # thing wearing a costume: {} or a whitespace name verifies
            # nothing. Review, then verify via metadata or correction.
            extractor = str(descriptor.grammar.get("extractor", "unknown"))
            if descriptor.verification is None:
                why = (
                    f"the descriptor is grammar-derived ({extractor}) with no "
                    "named verification; the venue documents exceptions to "
                    "its naming conventions"
                )
            else:
                why = (
                    "the descriptor's verification is malformed (blank or "
                    "missing 'by'/'note'); an unsigned assertion verifies "
                    "nothing"
                )
            return Resolution(
                status=PROPOSED,
                proposed_match_id=accepted[0].match_id,
                reason=(
                    "every dimension is consistent, but " + why +
                    ", so this is a review hint, never an auto-link"
                ),
                assessments=evidence,
            )
        return Resolution(
            status=MAPPED,
            match_id=accepted[0].match_id,
            canonical_outcome=outcome,
            reason="single fixture consistent on every dimension, "
                   "descriptor facts verified by "
                   + str(descriptor.verification.get("by", "?")),
            assessments=evidence,
        )

    # Nothing fully consistent. One near-miss with a single, explainable
    # failure becomes a review candidate; several, or messier failures, do
    # not -- a proposal must have exactly one story to tell.
    if len(near_misses) == 1:
        fixture, why = near_misses[0]
        explanations = {
            "reversed_orientation": (
                "participants and window match with home/away REVERSED -- "
                "possibly the other leg, a neutral-venue listing, or a venue "
                "orientation error; requires human verification"
            ),
            "kickoff_outside_window": (
                "pairing and competition match but the kickoff is outside the "
                "window -- possibly rescheduled, or stale venue metadata; "
                "requires human verification"
            ),
            "competition_not_declared": (
                "pairing and window match but the market declares no "
                "competition; cross-competition confusion cannot be ruled out"
            ),
            "kickoff_not_declared": (
                "pairing and competition match but the market declares no "
                "kickoff; cross-date confusion cannot be ruled out"
            ),
            "fixture_postponed": (
                "the only consistent fixture is postponed; the venue may be "
                "quoting a match that is not happening as scheduled"
            ),
            "fixture_cancelled": (
                "the only consistent fixture is cancelled"
            ),
            "fixture_abandoned": (
                "the only consistent fixture was abandoned"
            ),
            "season_mismatch": (
                "pairing matches but the declared season differs from the "
                "fixture's season"
            ),
            "fixture_kickoff_unknown": (
                "pairing matches but the fixture has no kickoff to check the "
                "window against"
            ),
        }
        return Resolution(
            status=PROPOSED,
            proposed_match_id=fixture.match_id,
            reason=explanations.get(why, why),
            assessments=evidence,
        )
    if near_misses:
        return Resolution(
            status=AMBIGUOUS,
            reason=(
                "several near-miss fixtures with different single failures: "
                + ", ".join(f"{f.match_id}:{why}" for f, why in near_misses)
                + "; abstaining"
            ),
            assessments=evidence,
        )
    if assessments:
        return Resolution(
            status=UNMAPPED,
            reason="no fixture survives the constraints",
            assessments=evidence,
        )
    return Resolution(
        status=UNMAPPED,
        reason="no fixture shares this pairing in either orientation",
    )
