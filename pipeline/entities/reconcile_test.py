"""Reconciliation against a real schema: replay, locks, collisions, audit."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Team, Tournament, VenueMarket
from pipeline.entities.reconcile import (
    apply_correction,
    internal_competition_key,
    internal_team_key,
    link_entity,
    reconcile_markets,
)

NOW = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)
TICKER = "KXEPLGAME-26AUG01ARSCHE-ARS"

#: Operator-verified facts for TICKER's market: mapping requires these --
#: the ticker grammar alone is a review hint and can never auto-map.
VERIFIED_METADATA = {
    ("kalshi", TICKER): {
        "home_source_key": "ARS", "away_source_key": "CHE",
        "outcome_source_key": "ARS", "competition_source_key": "KXEPLGAME",
        "kickoff_utc": KICKOFF.isoformat(),
        "verified_by": "pete", "note": "checked the venue market page",
    }
}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _seed_fixtures(db):
    tournament = Tournament(name="Premier League 2026-27", year=2026)
    arsenal, chelsea = Team(name="Arsenal"), Team(name="Chelsea")
    db.add_all([tournament, arsenal, chelsea])
    db.flush()
    match = Match(tournament_id=tournament.id, stage="league",
                  team_home_id=arsenal.id, team_away_id=chelsea.id,
                  status="scheduled", kickoff_utc=KICKOFF)
    db.add(match)
    db.commit()
    return tournament, arsenal, chelsea, match


def _verify_keys(db, tournament, arsenal, chelsea):
    """Verification is explicit: each key written by a named person."""
    for kind, name, source, key in [
        ("team", "Arsenal", "kalshi", "ARS"),
        ("team", "Chelsea", "kalshi", "CHE"),
        ("competition", "Premier League", "kalshi", "KXEPLGAME"),
        ("team", "Arsenal", "internal", internal_team_key(arsenal.id)),
        ("team", "Chelsea", "internal", internal_team_key(chelsea.id)),
        ("competition", "Premier League", "internal",
         internal_competition_key(tournament.id)),
    ]:
        link_entity(db, kind=kind, canonical_name=name, source=source,
                    source_key=key, verified_by="pete", apply=True, now=NOW)


def _market(db, venue_key=TICKER, **overrides):
    values = {
        "venue": "kalshi", "venue_key": venue_key, "sport": "football",
        "market_type": "match_winner", "raw_title": "Arsenal v Chelsea",
        "mapping_status": "unmapped", "status": "open",
        "first_seen": NOW, "last_seen": NOW,
    }
    values.update(overrides)
    row = VenueMarket(**values)
    db.add(row)
    db.commit()
    return row


# --- dry-run gate ------------------------------------------------------------


def test_dry_run_is_the_default_and_writes_nothing(db):
    _verify_keys(db, *_seed_fixtures(db)[:3])
    _market(db)

    report = reconcile_markets(db, now=NOW, metadata_by_key=VERIFIED_METADATA)

    assert report.dry_run is True
    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "unmapped"
    assert row.canonical_event_id is None
    assert row.mapping_history is None


def test_dry_run_preserves_unrelated_pending_caller_work(db):
    """A dry run must not alter the caller's transaction state. The old code
    called db.rollback(), which silently destroyed whatever the caller had
    pending; autoflush during our reads must not emit it early either."""
    _verify_keys(db, *_seed_fixtures(db)[:3])
    _market(db)
    sentinel = Team(name="Sentinel FC")
    db.add(sentinel)  # pending, unflushed

    reconcile_markets(db, now=NOW, metadata_by_key=VERIFIED_METADATA)
    apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=1,
                     outcome="home", verified_by="pete", note="dry", now=NOW)
    link_entity(db, kind="team", canonical_name="Someone", source="kalshi",
                source_key="SOM", verified_by="pete", now=NOW)

    assert sentinel in db.new, "dry runs discarded the caller's pending work"
    db.commit()
    assert db.query(Team).filter_by(name="Sentinel FC").count() == 1


def test_idempotent_replay_also_preserves_pending_caller_work(db):
    _verify_keys(db, *_seed_fixtures(db)[:3])
    _market(db)
    reconcile_markets(db, apply=True, now=NOW, metadata_by_key=VERIFIED_METADATA)
    sentinel = Team(name="Sentinel FC")
    db.add(sentinel)

    link_entity(db, kind="team", canonical_name="Arsenal", source="kalshi",
                source_key="ARS", verified_by="pete", apply=True, now=NOW)

    assert sentinel in db.new
    db.commit()
    assert db.query(Team).filter_by(name="Sentinel FC").count() == 1


def test_ticker_grammar_alone_proposes_and_never_maps(db):
    """Kalshi documents ticker exceptions and says not to parse tickers to
    infer relationships. A fully-consistent grammar hint is a PROPOSAL with
    canonical columns NULL -- mapping needs verified metadata or a manual
    correction."""
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)

    report = reconcile_markets(db, apply=True, now=NOW)

    assert report.counts() == {"proposed": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "proposed"
    assert row.canonical_event_id is None
    assert row.canonical_outcome is None
    assert row.resolution_context["proposed_match_id"] == match.id
    assert "grammar-derived" in row.resolution_context["reason"]
    assert row.resolution_context["verification"] is None


def test_apply_writes_the_mapping_with_full_evidence(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)

    report = reconcile_markets(db, apply=True, now=NOW,
                               metadata_by_key=VERIFIED_METADATA)

    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "mapped"
    assert row.canonical_event_id == match.id
    assert row.canonical_outcome == "home"
    context = row.resolution_context
    assert context["resolver_version"] == "market-fixture-resolver-v1"
    assert context["decided_at"] == NOW.isoformat()
    assert context["grammar"]["extractor"] == "operator-metadata-v1"
    assert context["verification"] == {"by": "pete",
                                       "note": "checked the venue market page"}
    assert context["candidates"][0]["accepted"] is True
    assert row.mapping_history[0]["kind"] == "resolution"
    assert row.mapping_history[0]["from"]["status"] == "unmapped"


def test_anonymous_metadata_fails_closed_in_reconciliation(db):
    """Tampered/anonymous metadata: no verified_by, no mapping, no proposal
    built from asserted facts nobody signed."""
    tournament, arsenal, chelsea, _match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)
    tampered = {("kalshi", TICKER): {
        "home_source_key": "CHE", "away_source_key": "ARS",
        "outcome_source_key": "CHE", "competition_source_key": "KXEPLGAME",
        "kickoff_utc": KICKOFF.isoformat(),
    }}

    report = reconcile_markets(db, apply=True, now=NOW,
                               metadata_by_key=tampered)

    assert report.counts() == {"unmapped": 1}
    row = db.query(VenueMarket).one()
    assert row.canonical_event_id is None
    assert "verified_by" in row.resolution_context["reason"]


def test_metadata_cannot_override_a_manual_correction(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)
    apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=match.id,
                     outcome="draw", verified_by="pete",
                     note="manual review", apply=True, now=NOW)
    hostile = {("kalshi", TICKER): {
        **VERIFIED_METADATA[("kalshi", TICKER)],
        "outcome_source_key": "CHE", "verified_by": "someone-else",
        "note": "trying to flip it"}}

    report = reconcile_markets(db, apply=True, now=NOW + timedelta(days=1),
                               metadata_by_key=hostile)

    assert report.counts() == {"locked": 1}
    row = db.query(VenueMarket).one()
    assert row.canonical_outcome == "draw", "manual correction stands"


# --- idempotent replay -------------------------------------------------------


def test_replay_with_unchanged_inputs_rewrites_nothing(db):
    _verify_keys(db, *_seed_fixtures(db)[:3])
    _market(db)
    reconcile_markets(db, apply=True, now=NOW, metadata_by_key=VERIFIED_METADATA)

    again = reconcile_markets(db, apply=True, now=NOW + timedelta(hours=6),
                              metadata_by_key=VERIFIED_METADATA)

    assert again.counts() == {"unchanged": 1}
    row = db.query(VenueMarket).one()
    assert len(row.mapping_history) == 1, "history records transitions, not runs"
    assert row.resolution_context["decided_at"] == NOW.isoformat()


def test_unmapped_replay_is_also_idempotent(db):
    _seed_fixtures(db)  # no verified keys at all
    _market(db)
    reconcile_markets(db, apply=True, now=NOW)
    first_history = len(db.query(VenueMarket).one().mapping_history or [])

    reconcile_markets(db, apply=True, now=NOW + timedelta(hours=6))

    row = db.query(VenueMarket).one()
    assert row.mapping_status == "unmapped"
    assert len(row.mapping_history or []) == first_history


# --- proposals never touch canonical fields ----------------------------------


def test_a_proposal_reaches_review_but_never_the_canonical_columns(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    # Reversed orientation: Chelsea listed at home on the fixture's date.
    _market(db, venue_key="KXEPLGAME-26AUG01CHEARS-CHE")

    report = reconcile_markets(db, apply=True, now=NOW)

    assert report.counts() == {"proposed": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "proposed"
    assert row.canonical_event_id is None
    assert row.canonical_outcome is None
    assert row.resolution_context["proposed_match_id"] == match.id
    assert "REVERSED" in row.resolution_context["reason"]


def test_descriptor_ambiguity_is_recorded_as_ambiguous(db):
    tournament, arsenal, chelsea, _match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    for kind, name, source, key in [("team", "Arse FC", "kalshi", "ARSC"),
                                    ("team", "HE FC", "kalshi", "HE")]:
        link_entity(db, kind=kind, canonical_name=name, source=source,
                    source_key=key, verified_by="pete", apply=True, now=NOW)
    _market(db)  # ARSCHE now splits ARS/CHE and ARSC/HE

    report = reconcile_markets(db, apply=True, now=NOW)

    assert report.counts() == {"ambiguous": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "ambiguous"
    assert row.canonical_event_id is None
    assert "more than one way" in row.resolution_context["reason"]


def test_a_venue_with_no_structured_metadata_stays_unmapped_honestly(db):
    _seed_fixtures(db)
    _market(db, venue="polymarket", venue_key="0xaaa")

    report = reconcile_markets(db, apply=True, now=NOW)

    row = db.query(VenueMarket).one()
    assert row.mapping_status == "unmapped"
    assert "no deterministic descriptor" in row.resolution_context["reason"]
    assert report.counts() == {"unmapped": 1}


def _polymarket_keys(db):
    for name, key in [("Arsenal", "arsenal"), ("Chelsea", "chelsea")]:
        link_entity(db, kind="team", canonical_name=name, source="polymarket",
                    source_key=key, verified_by="pete", apply=True, now=NOW)
    link_entity(db, kind="competition", canonical_name="Premier League",
                source="polymarket", source_key="premier-league",
                verified_by="pete", apply=True, now=NOW)


def _polymarket_metadata(**overrides):
    values = {
        "home_source_key": "arsenal", "away_source_key": "chelsea",
        "outcome_source_key": "arsenal",
        "competition_source_key": "premier-league",
        "kickoff_utc": KICKOFF.isoformat(),
        "verified_by": "pete", "note": "checked the venue event page",
    }
    values.update(overrides)
    return {("polymarket", "0xaaa"): values}


def test_operator_metadata_resolves_a_structureless_venue(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _polymarket_keys(db)
    _market(db, venue="polymarket", venue_key="0xaaa")

    report = reconcile_markets(db, apply=True, now=NOW,
                               metadata_by_key=_polymarket_metadata())

    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.canonical_event_id == match.id
    assert row.resolution_context["grammar"]["extractor"] == "operator-metadata-v1"
    assert row.resolution_context["verification"]["by"] == "pete"


def test_january_fixtures_belong_to_the_starting_year_season(db):
    """Season boundary: a 2026-27 season's January fixture has season token
    '2026'. Metadata declaring '2027' is a mismatch and abstains; '2026'
    maps; the display form '2026-27' is refused at extraction."""
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _polymarket_keys(db)
    january = datetime(2027, 1, 17, 15, 0, tzinfo=timezone.utc)
    db.query(Match).filter_by(id=match.id).update({"kickoff_utc": january})
    db.commit()
    _market(db, venue="polymarket", venue_key="0xaaa")

    right = reconcile_markets(db, now=NOW, metadata_by_key=_polymarket_metadata(
        kickoff_utc=january.isoformat(), season_label="2026"))
    wrong_year = reconcile_markets(db, now=NOW, metadata_by_key=_polymarket_metadata(
        kickoff_utc=january.isoformat(), season_label="2027"))
    display_form = reconcile_markets(db, now=NOW, metadata_by_key=_polymarket_metadata(
        kickoff_utc=january.isoformat(), season_label="2026-27"))

    assert right.counts() == {"map": 1}
    assert wrong_year.counts() == {"proposed": 1}
    assert "season" in wrong_year.outcomes[0].reason
    assert display_form.counts() == {"unmapped": 1}
    assert "four-digit" in display_form.outcomes[0].reason


def test_missing_internal_entities_are_reported_as_data_gaps(db):
    """A fixture that cannot enter entity space must not vanish silently:
    the report names exactly which link-entity rows are owed."""
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    # Verify only the venue-side and Arsenal; Chelsea's internal key is owed.
    for kind, name, source, key in [
        ("team", "Arsenal", "kalshi", "ARS"),
        ("team", "Chelsea", "kalshi", "CHE"),
        ("competition", "Premier League", "kalshi", "KXEPLGAME"),
        ("team", "Arsenal", "internal", internal_team_key(arsenal.id)),
    ]:
        link_entity(db, kind=kind, canonical_name=name, source=source,
                    source_key=key, verified_by="pete", apply=True, now=NOW)
    _market(db)

    report = reconcile_markets(db, now=NOW)

    assert len(report.data_gaps) == 1
    assert f"match {match.id}" in report.data_gaps[0]
    assert internal_team_key(chelsea.id) in report.data_gaps[0]
    assert report.counts() == {"unmapped": 1}


def test_stopped_provider_statuses_never_reach_candidates_today(db):
    """THE HONESTY TEST for the stopped-fixture guard: production ingestion
    normalizes every stopped provider status to internal 'scheduled', so the
    resolver's postponed/cancelled guard cannot fire on real data. The guard
    is a core contract awaiting a provider-status column -- a recorded data
    gap, not a live protection."""
    from pipeline.ingest.league_structure import _STATUS
    from pipeline.ingest.live_scores import _STATUS_MAP

    for provider_status in ("SUSP", "PST", "CANC", "ABD"):
        assert _STATUS[provider_status] == "scheduled"
    for provider_status in ("SUSPENDED", "POSTPONED", "CANCELLED"):
        assert _STATUS_MAP[provider_status] == "scheduled"

    # And therefore a postponed match, ingested today, still auto-maps: the
    # information that would stop it does not survive ingestion.
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    db.query(Match).filter_by(id=match.id).update(
        {"status": _STATUS["PST"]})
    db.commit()
    _market(db)

    report = reconcile_markets(db, now=NOW, metadata_by_key=VERIFIED_METADATA)

    assert report.counts() == {"map": 1}, (
        "documents the gap: a postponed fixture is indistinguishable from a "
        "scheduled one after today's ingest")


# --- manual corrections and locks --------------------------------------------


def test_replay_never_overwrites_a_manual_correction(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db, venue_key="KXEPLGAME-26AUG01CHEARS-CHE")  # resolver: proposed

    apply_correction(
        db, venue="kalshi", venue_key="KXEPLGAME-26AUG01CHEARS-CHE",
        match_id=match.id, outcome="away", verified_by="pete",
        note="venue lists neutral-venue fixtures away-first; checked",
        apply=True, now=NOW)
    report = reconcile_markets(db, apply=True, now=NOW + timedelta(days=1))

    assert report.counts() == {"locked": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "mapped"
    assert row.canonical_event_id == match.id
    assert row.canonical_outcome == "away"
    assert row.resolution_context["verified"]["by"] == "pete"


def test_correction_dry_run_writes_nothing(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)

    outcome = apply_correction(
        db, venue="kalshi", venue_key=TICKER, match_id=match.id,
        outcome="home", verified_by="pete", note="dry", now=NOW)

    assert outcome.action == "correct"
    assert db.query(VenueMarket).one().mapping_status == "unmapped"


def test_corrections_demand_a_person_a_note_and_a_real_match(db):
    _seed_fixtures(db)
    _market(db)

    with pytest.raises(ValueError, match="name a person"):
        apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=1,
                         outcome="home", verified_by=" ", note="x", apply=True)
    with pytest.raises(ValueError, match="requires a note"):
        apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=1,
                         outcome="home", verified_by="pete", note=" ",
                         apply=True)
    with pytest.raises(ValueError, match="does not exist"):
        apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=999,
                         outcome="home", verified_by="pete", note="x",
                         apply=True)
    with pytest.raises(ValueError, match="home/draw/away"):
        apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=1,
                         outcome="win", verified_by="pete", note="x",
                         apply=True)


def test_rollback_is_another_audited_correction_with_full_history(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)

    apply_correction(db, venue="kalshi", venue_key=TICKER, match_id=match.id,
                     outcome="home", verified_by="pete", note="initial",
                     apply=True, now=NOW)
    apply_correction(db, venue="kalshi", venue_key=TICKER, clear=True,
                     verified_by="pete", note="rolled back: wrong market",
                     apply=True, now=NOW + timedelta(hours=1))

    row = db.query(VenueMarket).one()
    assert row.mapping_status == "unmapped"
    assert row.canonical_event_id is None
    kinds = [entry["kind"] for entry in row.mapping_history]
    assert kinds == ["manual_correction", "manual_correction"]
    assert row.mapping_history[1]["from"]["match_id"] == match.id
    assert row.mapping_history[1]["to"]["match_id"] is None


# --- collisions: no silent remap ---------------------------------------------


def test_replay_that_disagrees_flags_a_conflict_and_keeps_the_mapping(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)
    reconcile_markets(db, apply=True, now=NOW, metadata_by_key=VERIFIED_METADATA)

    # The fixture is rescheduled out of the window after mapping.
    db.query(Match).filter_by(id=match.id).update(
        {"kickoff_utc": KICKOFF + timedelta(days=5)})
    db.commit()
    report = reconcile_markets(db, apply=True, now=NOW + timedelta(days=1),
                               metadata_by_key=VERIFIED_METADATA)

    assert report.counts() == {"conflict": 1}
    row = db.query(VenueMarket).one()
    assert row.canonical_event_id == match.id, "stored mapping stands"
    conflict = row.resolution_context["conflict"]
    assert conflict["stored"]["match_id"] == match.id
    assert conflict["replay"]["status"] == "proposed"
    kinds = [entry["kind"] for entry in row.mapping_history]
    assert kinds == ["resolution", "conflict_detected"]


def test_the_same_conflict_is_recorded_once_not_per_replay(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)
    reconcile_markets(db, apply=True, now=NOW, metadata_by_key=VERIFIED_METADATA)
    db.query(Match).filter_by(id=match.id).update(
        {"kickoff_utc": KICKOFF + timedelta(days=5)})
    db.commit()

    reconcile_markets(db, apply=True, now=NOW + timedelta(days=1),
                      metadata_by_key=VERIFIED_METADATA)
    reconcile_markets(db, apply=True, now=NOW + timedelta(days=2),
                      metadata_by_key=VERIFIED_METADATA)

    row = db.query(VenueMarket).one()
    kinds = [entry["kind"] for entry in row.mapping_history]
    assert kinds == ["resolution", "conflict_detected"]


# --- entity linking ----------------------------------------------------------


def test_link_entity_is_dry_run_by_default_and_refuses_remaps(db):
    message = link_entity(db, kind="team", canonical_name="Arsenal",
                          source="kalshi", source_key="ARS",
                          verified_by="pete", now=NOW)
    assert message.startswith("DRY RUN")

    link_entity(db, kind="team", canonical_name="Arsenal", source="kalshi",
                source_key="ARS", verified_by="pete", apply=True, now=NOW)
    repeat = link_entity(db, kind="team", canonical_name="Arsenal",
                         source="kalshi", source_key="ARS",
                         verified_by="pete", apply=True, now=NOW)
    assert repeat.startswith("already linked")

    with pytest.raises(ValueError, match="refusing to remap"):
        link_entity(db, kind="team", canonical_name="Arsenal Women",
                    source="kalshi", source_key="ARS", verified_by="pete",
                    apply=True, now=NOW)


def test_deterministic_report_ordering(db):
    tournament, arsenal, chelsea, _match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db, venue_key="KXEPLGAME-26AUG01ARSCHE-DRAW")
    _market(db, venue_key="KXEPLGAME-26AUG01ARSCHE-ARS")
    _market(db, venue="polymarket", venue_key="0xaaa")

    report = reconcile_markets(db, now=NOW)

    keys = [(o.venue, o.venue_key) for o in report.outcomes]
    assert keys == sorted(keys)
