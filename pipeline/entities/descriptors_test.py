"""Descriptor extraction: grammar or refusal, nothing in between."""

from datetime import datetime, timezone

from pipeline.entities.descriptors import (
    ExtractionFailure,
    descriptor_from_metadata,
    kalshi_descriptor,
)

VERIFIED = frozenset({"ARS", "CHE", "TOT", "BOU"})


def _kalshi(venue_key, *, verified=VERIFIED, market_type="match_winner"):
    return kalshi_descriptor(venue_key=venue_key, market_type=market_type,
                             verified_team_keys=verified)


def test_a_well_formed_ticker_parses_completely():
    descriptor = _kalshi("KXEPLGAME-26AUG01ARSCHE-ARS")

    assert descriptor.home_source_key == "ARS"
    assert descriptor.away_source_key == "CHE"
    assert descriptor.outcome_source_key == "ARS"
    assert descriptor.competition_source_key == "KXEPLGAME"
    assert descriptor.kickoff_utc == datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    assert descriptor.grammar["extractor"] == "kalshi-ticker-v1"
    assert "home side first" in descriptor.grammar["assumption"]


def test_the_split_comes_from_the_key_registry_not_string_length():
    """'BOUTOT' could split many ways; only the registry decides."""
    descriptor = _kalshi("KXEPLGAME-26AUG01BOUTOT-DRAW")

    assert (descriptor.home_source_key, descriptor.away_source_key) == ("BOU", "TOT")


def test_an_unverified_code_fails_closed_and_names_the_block():
    failure = _kalshi("KXEPLGAME-26AUG01ARSXXX-ARS")

    assert isinstance(failure, ExtractionFailure)
    assert "ARSXXX" in failure.reason
    assert "entity_source_map" in failure.reason
    assert failure.ambiguous is False


def test_a_block_with_two_valid_splits_abstains():
    """If 'AR', 'SC', 'ARS' and 'CHE'-style overlaps ever both verify, the
    grammar cannot decide and must not guess."""
    tricky = frozenset({"AR", "SCHE", "ARS", "CHE"})

    failure = _kalshi("KXEPLGAME-26AUG01ARSCHE-ARS", verified=tricky)

    assert isinstance(failure, ExtractionFailure)
    assert failure.ambiguous is True
    assert "more than one way" in failure.reason


def test_malformed_tickers_are_refused_with_the_reason():
    for venue_key, fragment in [
        ("KXEPLGAME-26AUG01ARSCHE", "three segments"),
        ("KXEPLGAME-26XYZ01ARSCHE-ARS", "not YYMONDD"),
        ("KXEPLGAME-26AUG99ARSCHE-ARS", "not YYMONDD"),
        ("KXEPLGAME-26AUG01-ARS", "no team block"),
    ]:
        failure = _kalshi(venue_key)
        assert isinstance(failure, ExtractionFailure), venue_key
        assert fragment in failure.reason


VERIFIED_FIELDS = {"verified_by": "pete", "note": "checked the venue listing"}


def test_metadata_descriptors_take_operator_facts_verbatim():
    descriptor = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={
            "home_source_key": "arsenal", "away_source_key": "chelsea",
            "outcome_source_key": "arsenal",
            "competition_source_key": "premier-league",
            "kickoff_utc": "2026-08-01T16:00:00+00:00",
            **VERIFIED_FIELDS,
        })

    assert descriptor.home_source_key == "arsenal"
    assert descriptor.kickoff_utc == datetime(2026, 8, 1, 16, tzinfo=timezone.utc)
    assert descriptor.grammar["extractor"] == "operator-metadata-v1"
    assert descriptor.grammar["metadata"]["home_source_key"] == "arsenal"
    assert descriptor.verification == {"by": "pete",
                                       "note": "checked the venue listing"}


def test_anonymous_metadata_fails_closed():
    """Verifying entity keys does not verify the orientation someone typed
    into a file. An assertion needs a named asserter and its evidence."""
    anonymous = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "arsenal", "away_source_key": "chelsea",
                  "outcome_source_key": "arsenal"})
    unexplained = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "arsenal", "away_source_key": "chelsea",
                  "outcome_source_key": "arsenal", "verified_by": "pete",
                  "note": "   "})

    assert isinstance(anonymous, ExtractionFailure)
    assert "verified_by" in anonymous.reason
    assert isinstance(unexplained, ExtractionFailure)
    assert "note" in unexplained.reason


def test_a_kalshi_descriptor_is_never_verified():
    """The whole point of the cap: ticker grammar cannot self-verify."""
    descriptor = _kalshi("KXEPLGAME-26AUG01ARSCHE-ARS")

    assert descriptor.verification is None
    assert "review hint" in descriptor.grammar["assumption"]


def test_metadata_season_must_be_a_four_digit_starting_year():
    display_form = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "a", "away_source_key": "b",
                  "outcome_source_key": "a", "season_label": "2026-27",
                  **VERIFIED_FIELDS})
    canonical = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "a", "away_source_key": "b",
                  "outcome_source_key": "a", "season_label": "2026",
                  **VERIFIED_FIELDS})

    assert isinstance(display_form, ExtractionFailure)
    assert "four-digit" in display_form.reason
    assert canonical.season_label == "2026"


def test_metadata_missing_fields_or_bad_kickoff_is_refused():
    missing = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "arsenal", **VERIFIED_FIELDS})
    naive = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "a", "away_source_key": "b",
                  "outcome_source_key": "a",
                  "kickoff_utc": "2026-08-01T16:00:00", **VERIFIED_FIELDS})
    junk = descriptor_from_metadata(
        venue="polymarket", venue_key="0xaaa", market_type="match_winner",
        metadata={"home_source_key": "a", "away_source_key": "b",
                  "outcome_source_key": "a", "kickoff_utc": "yesterday",
                  **VERIFIED_FIELDS})

    assert isinstance(missing, ExtractionFailure)
    assert "away_source_key" in missing.reason
    assert isinstance(naive, ExtractionFailure)
    assert "timezone-aware" in naive.reason
    assert isinstance(junk, ExtractionFailure)
    assert "ISO-8601" in junk.reason
