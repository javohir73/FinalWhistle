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

    report = reconcile_markets(db, now=NOW)

    assert report.dry_run is True
    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "unmapped"
    assert row.canonical_event_id is None
    assert row.mapping_history is None


def test_apply_writes_the_mapping_with_full_evidence(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    _market(db)

    report = reconcile_markets(db, apply=True, now=NOW)

    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.mapping_status == "mapped"
    assert row.canonical_event_id == match.id
    assert row.canonical_outcome == "home"
    context = row.resolution_context
    assert context["resolver_version"] == "market-fixture-resolver-v1"
    assert context["decided_at"] == NOW.isoformat()
    assert context["grammar"]["extractor"] == "kalshi-ticker-v1"
    assert context["candidates"][0]["accepted"] is True
    assert row.mapping_history[0]["kind"] == "resolution"
    assert row.mapping_history[0]["from"]["status"] == "unmapped"


# --- idempotent replay -------------------------------------------------------


def test_replay_with_unchanged_inputs_rewrites_nothing(db):
    _verify_keys(db, *_seed_fixtures(db)[:3])
    _market(db)
    reconcile_markets(db, apply=True, now=NOW)

    again = reconcile_markets(db, apply=True, now=NOW + timedelta(hours=6))

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


def test_operator_metadata_resolves_a_structureless_venue(db):
    tournament, arsenal, chelsea, match = _seed_fixtures(db)
    _verify_keys(db, tournament, arsenal, chelsea)
    for name, key in [("Arsenal", "arsenal"), ("Chelsea", "chelsea")]:
        link_entity(db, kind="team", canonical_name=name, source="polymarket",
                    source_key=key, verified_by="pete", apply=True, now=NOW)
    link_entity(db, kind="competition", canonical_name="Premier League",
                source="polymarket", source_key="premier-league",
                verified_by="pete", apply=True, now=NOW)
    _market(db, venue="polymarket", venue_key="0xaaa")

    report = reconcile_markets(db, apply=True, now=NOW, metadata_by_key={
        ("polymarket", "0xaaa"): {
            "home_source_key": "arsenal", "away_source_key": "chelsea",
            "outcome_source_key": "arsenal",
            "competition_source_key": "premier-league",
            "kickoff_utc": KICKOFF.isoformat(),
        }})

    assert report.counts() == {"map": 1}
    row = db.query(VenueMarket).one()
    assert row.canonical_event_id == match.id
    assert row.resolution_context["grammar"]["extractor"] == "operator-metadata-v1"


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
    reconcile_markets(db, apply=True, now=NOW)

    # The fixture is rescheduled out of the window after mapping.
    db.query(Match).filter_by(id=match.id).update(
        {"kickoff_utc": KICKOFF + timedelta(days=5)})
    db.commit()
    report = reconcile_markets(db, apply=True, now=NOW + timedelta(days=1))

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
    reconcile_markets(db, apply=True, now=NOW)
    db.query(Match).filter_by(id=match.id).update(
        {"kickoff_utc": KICKOFF + timedelta(days=5)})
    db.commit()

    reconcile_markets(db, apply=True, now=NOW + timedelta(days=1))
    reconcile_markets(db, apply=True, now=NOW + timedelta(days=2))

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
