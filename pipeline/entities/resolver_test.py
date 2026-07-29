"""Adversarial resolution cases. Every ambiguous case must abstain."""

from datetime import datetime, timedelta, timezone

from pipeline.entities.resolver import (
    AMBIGUOUS,
    MAPPED,
    PROPOSED,
    UNMAPPED,
    FixtureCandidate,
    MarketDescriptor,
    resolve_market,
)

ARSENAL, CHELSEA, SPURS = 1, 2, 3
LEAGUE, CUP = 10, 11

KEYS = {
    ("kalshi", "ARS"): ARSENAL,
    ("kalshi", "CHE"): CHELSEA,
    ("kalshi", "TOT"): SPURS,
    ("kalshi", "KXEPLGAME"): LEAGUE,
    ("kalshi", "KXFACUP"): CUP,
}
KINDS = {ARSENAL: "team", CHELSEA: "team", SPURS: "team",
         LEAGUE: "competition", CUP: "competition"}

SAT = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def _descriptor(**overrides):
    values = {
        "venue": "kalshi",
        "venue_key": "KX-1",
        "market_type": "match_winner",
        "home_source_key": "ARS",
        "away_source_key": "CHE",
        "outcome_source_key": "ARS",
        "competition_source_key": "KXEPLGAME",
        "kickoff_utc": SAT,
        # Dimension tests run with verified facts; the unverified cap has its
        # own tests below.
        "verification": {"by": "test-reviewer", "note": "fixture"},
    }
    values.update(overrides)
    return MarketDescriptor(**values)


def _fixture(match_id=41, *, home=ARSENAL, away=CHELSEA, competition=LEAGUE,
             kickoff=SAT, status="scheduled", season="2026"):
    return FixtureCandidate(
        match_id=match_id, home_entity_id=home, away_entity_id=away,
        competition_entity_id=competition, kickoff_utc=kickoff,
        status=status, season_label=season)


def _resolve(descriptor, fixtures):
    return resolve_market(descriptor, source_entities=KEYS,
                          entity_kinds=KINDS, fixtures=fixtures)


# --- the happy path, and what mapped requires --------------------------------


def test_a_fully_consistent_single_fixture_maps():
    resolution = _resolve(_descriptor(), [_fixture()])

    assert resolution.status == MAPPED
    assert resolution.match_id == 41
    assert resolution.canonical_outcome == "home"
    assert resolution.serveable


def test_outcome_normalizes_by_side_and_draw():
    away = _resolve(_descriptor(outcome_source_key="CHE"), [_fixture()])
    draw = _resolve(_descriptor(outcome_source_key="DRAW"), [_fixture()])

    assert away.canonical_outcome == "away"
    assert draw.canonical_outcome == "draw"


def test_non_match_winner_markets_stay_unmapped():
    """v1 normalizes match_winner only; anything else must not be approximated."""
    resolution = _resolve(
        _descriptor(market_type="btts", outcome_source_key="YES"), [_fixture()])

    assert resolution.status == UNMAPPED
    assert "market type" in resolution.reason


# --- reverse fixtures, legs, and orientation ---------------------------------


def test_the_reverse_fixture_is_never_close_enough():
    """Home/away as an unordered set was the original branch's bug. The
    reverse pairing is a DIFFERENT fixture -- the other leg."""
    reverse = _fixture(match_id=77, home=CHELSEA, away=ARSENAL)

    resolution = _resolve(_descriptor(), [reverse])

    assert resolution.status == PROPOSED
    assert resolution.proposed_match_id == 77
    assert resolution.match_id is None, "a proposal never writes a mapping"
    assert "REVERSED" in resolution.reason


def test_two_legs_resolve_by_orientation_and_date():
    leg1 = _fixture(match_id=41, home=ARSENAL, away=CHELSEA, kickoff=SAT)
    leg2 = _fixture(match_id=42, home=CHELSEA, away=ARSENAL,
                    kickoff=SAT + timedelta(days=14))

    first = _resolve(_descriptor(), [leg1, leg2])
    second = _resolve(
        _descriptor(home_source_key="CHE", away_source_key="ARS",
                    outcome_source_key="ARS",
                    kickoff_utc=SAT + timedelta(days=14)),
        [leg1, leg2])

    assert (first.status, first.match_id) == (MAPPED, 41)
    assert (second.status, second.match_id) == (MAPPED, 42)
    assert second.canonical_outcome == "away", "ARS is the away side of leg 2"


def test_a_leg1_orientation_claim_on_leg2s_date_abstains():
    """The market says Arsenal at home on the date Chelsea hosts: whatever it
    is -- stale metadata, a venue error, a neutral listing -- it is not ours
    to guess."""
    leg2 = _fixture(match_id=42, home=CHELSEA, away=ARSENAL,
                    kickoff=SAT + timedelta(days=14))

    resolution = _resolve(
        _descriptor(kickoff_utc=SAT + timedelta(days=14)), [leg2])

    assert resolution.status == PROPOSED
    assert resolution.match_id is None


def test_neutral_venue_listing_is_proposed_not_mapped():
    """A neutral-venue tournament match the venue lists in the other order:
    same behavior as any reversed orientation -- review, never auto-link."""
    fixture = _fixture(match_id=90, home=CHELSEA, away=ARSENAL)

    resolution = _resolve(_descriptor(), [fixture])

    assert resolution.status == PROPOSED
    assert "neutral" in resolution.reason


# --- same clubs, close together ----------------------------------------------


def test_cup_and_league_meetings_in_one_week_resolve_by_competition():
    league = _fixture(match_id=41, competition=LEAGUE, kickoff=SAT)
    cup = _fixture(match_id=55, competition=CUP,
                   kickoff=SAT + timedelta(days=4),
                   season="2026")

    league_market = _resolve(_descriptor(kickoff_utc=SAT), [league, cup])
    cup_market = _resolve(
        _descriptor(competition_source_key="KXFACUP",
                    kickoff_utc=SAT + timedelta(days=4)),
        [league, cup])

    assert (league_market.status, league_market.match_id) == (MAPPED, 41)
    assert (cup_market.status, cup_market.match_id) == (MAPPED, 55)


def test_same_pairing_twice_within_the_window_abstains():
    """Both fixtures satisfy every constraint: nothing distinguishes them, so
    nothing may be written."""
    first = _fixture(match_id=41, kickoff=SAT)
    replay = _fixture(match_id=43, kickoff=SAT + timedelta(hours=20))

    resolution = _resolve(_descriptor(), [first, replay])

    assert resolution.status == AMBIGUOUS
    assert resolution.match_id is None
    assert "41" in resolution.reason and "43" in resolution.reason


def test_a_market_without_competition_cannot_cross_the_cup_league_gap():
    """Same pairing, same day, two competitions, market declares none: the
    two near-misses have the same single failure -- abstain."""
    league = _fixture(match_id=41, competition=LEAGUE, kickoff=SAT)
    cup = _fixture(match_id=55, competition=CUP, kickoff=SAT,
                   season="2026")

    resolution = _resolve(
        _descriptor(competition_source_key=None), [league, cup])

    assert resolution.status == AMBIGUOUS


def test_a_market_without_competition_and_one_candidate_is_only_proposed():
    resolution = _resolve(_descriptor(competition_source_key=None), [_fixture()])

    assert resolution.status == PROPOSED
    assert "declares no" in resolution.reason


# --- seasons, reschedules, postponements -------------------------------------


def test_adjacent_seasons_are_separated_by_the_window():
    this_season = _fixture(match_id=41, kickoff=SAT)
    last_season = _fixture(match_id=12, kickoff=SAT - timedelta(days=364),
                           season="2025")

    resolution = _resolve(_descriptor(), [this_season, last_season])

    assert (resolution.status, resolution.match_id) == (MAPPED, 41)


def test_a_declared_season_mismatch_rejects_even_inside_the_window():
    fixture = _fixture(season="2026")

    resolution = _resolve(
        _descriptor(season_label="2025"), [fixture])

    assert resolution.status == PROPOSED
    assert "season" in resolution.reason


def test_a_rescheduled_fixture_is_proposed_not_mapped():
    """Venue still shows the old Saturday; the fixture moved to Tuesday."""
    moved = _fixture(match_id=41, kickoff=SAT + timedelta(days=3))

    resolution = _resolve(_descriptor(kickoff_utc=SAT), [moved])

    assert resolution.status == PROPOSED
    assert resolution.proposed_match_id == 41
    assert "rescheduled" in resolution.reason


def test_a_postponed_fixture_is_never_auto_linked():
    """CORE CONTRACT, currently inert in production: today's ingestion
    normalizes PST/SUSP to internal "scheduled" (see the through-ingest test
    in reconcile_test), so this status cannot yet reach a candidate. The
    behavior exists for the day a provider-status signal lands; it is not a
    claim that stopped fixtures are detected today."""
    postponed = _fixture(status="postponed")

    resolution = _resolve(_descriptor(), [postponed])

    assert resolution.status == PROPOSED
    assert "postponed" in resolution.reason


def test_a_cancelled_fixture_is_never_auto_linked():
    """Same honesty note as the postponed test: core contract, inert today."""
    resolution = _resolve(_descriptor(), [_fixture(status="cancelled")])

    assert resolution.status == PROPOSED
    assert "cancelled" in resolution.reason


def test_stale_metadata_with_no_nearby_fixture_stays_out_of_reach():
    """Kickoff a month off AND the wrong competition: two failures is not a
    reviewable story, it is noise."""
    fixture = _fixture(competition=CUP, kickoff=SAT + timedelta(days=30),
                       season="2026")

    resolution = _resolve(_descriptor(), [fixture])

    assert resolution.status == UNMAPPED
    assert resolution.match_id is None


# --- keys and kinds ----------------------------------------------------------


def test_unverified_keys_fail_closed_naming_the_missing_key():
    resolution = _resolve(
        _descriptor(home_source_key="XXX"), [_fixture()])

    assert resolution.status == UNMAPPED
    assert "'XXX'" in resolution.reason
    assert resolution.missing == ("team key 'XXX'",)


def test_an_unverified_competition_key_fails_closed():
    resolution = _resolve(
        _descriptor(competition_source_key="KXNOPE"), [_fixture()])

    assert resolution.status == UNMAPPED
    assert "KXNOPE" in resolution.reason


def test_keys_resolving_to_the_same_entity_fail():
    keys = dict(KEYS)
    keys[("kalshi", "AFC")] = ARSENAL
    resolution = resolve_market(
        _descriptor(away_source_key="AFC"),
        source_entities=keys, entity_kinds=KINDS, fixtures=[_fixture()])

    assert resolution.status == UNMAPPED
    assert "same entity" in resolution.reason


def test_a_team_key_pointing_at_a_competition_fails():
    keys = dict(KEYS)
    keys[("kalshi", "OOPS")] = LEAGUE
    resolution = resolve_market(
        _descriptor(home_source_key="OOPS"),
        source_entities=keys, entity_kinds=KINDS, fixtures=[_fixture()])

    assert resolution.status == UNMAPPED
    assert "non-team" in resolution.reason


# --- determinism and evidence ------------------------------------------------


def test_resolution_is_order_independent():
    fixtures = [
        _fixture(match_id=41, kickoff=SAT),
        _fixture(match_id=12, kickoff=SAT - timedelta(days=364),
                 season="2025"),
        _fixture(match_id=77, home=CHELSEA, away=ARSENAL,
                 kickoff=SAT + timedelta(days=14)),
    ]

    forward = _resolve(_descriptor(), fixtures)
    backward = _resolve(_descriptor(), list(reversed(fixtures)))

    assert forward == backward
    assert [a.match_id for a in forward.assessments] == [12, 41, 77]


def test_every_candidate_leaves_its_assessment_in_the_evidence():
    fixtures = [
        _fixture(match_id=41),
        _fixture(match_id=55, competition=CUP, season="2026"),
        _fixture(match_id=90, home=SPURS, away=CHELSEA),  # different pairing
    ]

    resolution = _resolve(_descriptor(), fixtures)

    assessed = {a.match_id: a for a in resolution.assessments}
    assert set(assessed) == {41, 55}, "unrelated pairings are not evidence"
    assert assessed[41].accepted is True
    assert assessed[55].rejections == ("competition_mismatch",)
    assert ("orientation", "exact") in assessed[41].checks


# --- the unverified-descriptor cap -------------------------------------------


def test_a_grammar_descriptor_never_maps_even_when_fully_consistent():
    """Kalshi documents ticker exceptions and says not to parse tickers to
    infer relationships. A recorded assumption is not a safe training label:
    full consistency from an unverified descriptor is a REVIEW HINT."""
    hint = _descriptor(verification=None,
                       grammar={"extractor": "kalshi-ticker-v1"})

    resolution = _resolve(hint, [_fixture()])

    assert resolution.status == PROPOSED
    assert resolution.match_id is None
    assert resolution.canonical_outcome is None
    assert resolution.proposed_match_id == 41
    assert "grammar-derived" in resolution.reason
    assert "kalshi-ticker-v1" in resolution.reason


def test_verification_lifts_the_same_descriptor_to_mapped():
    hint = _descriptor(verification=None)
    verified = _descriptor()

    assert _resolve(hint, [_fixture()]).status == PROPOSED
    mapped = _resolve(verified, [_fixture()])
    assert mapped.status == MAPPED
    assert "test-reviewer" in mapped.reason


def test_the_cap_does_not_loosen_any_other_dimension():
    """Unverified AND ambiguous is still ambiguous; unverified AND reversed
    is still the reversed-orientation proposal, not a mapping."""
    hint = _descriptor(verification=None)

    two = _resolve(hint, [_fixture(match_id=41),
                          _fixture(match_id=43,
                                   kickoff=SAT + timedelta(hours=20))])
    reversed_only = _resolve(hint, [_fixture(home=CHELSEA, away=ARSENAL)])

    assert two.status == AMBIGUOUS
    assert reversed_only.status == PROPOSED
    assert "REVERSED" in reversed_only.reason


def test_season_gate_is_stated_honestly_in_the_evidence():
    """No declared season: the check records that kickoff+competition IS the
    season gate, rather than pretending a fifth comparison ran."""
    resolution = _resolve(_descriptor(), [_fixture()])

    checks = dict(resolution.assessments[0].checks)
    assert checks["season"] == "gated_by_kickoff_and_competition"


def test_malformed_verification_is_verification_theater():
    """`is None` alone was bypassable: a direct caller could pass {} or a
    whitespace name and reach MAPPED. Both fields must be non-blank."""
    malformed = [
        {},
        {"by": ""},
        {"by": "pete"},                      # missing note
        {"note": "checked"},                 # missing by
        {"by": "   ", "note": "checked"},
        {"by": "pete", "note": "   "},
        {"by": "", "note": ""},
        {"by": None, "note": None},
    ]
    for verification in malformed:
        resolution = _resolve(_descriptor(verification=verification), [_fixture()])
        assert resolution.status == PROPOSED, verification
        assert resolution.match_id is None, verification
        assert "malformed" in resolution.reason, verification
