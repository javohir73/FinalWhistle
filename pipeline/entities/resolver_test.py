from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CanonicalEntity, EntitySourceMap, Team, Tournament, VenueMarket, VenuePriceTick
from pipeline.entities.reconcile import reconcile_markets, seed_internal_entities
from pipeline.entities.resolver import CanonicalFixture, ExactMarketDescriptor, resolve_market, suggest_entities


INDEX = {("kalshi", "FRA"): 1, ("kalshi", "MAR"): 2, ("kalshi", "WC26"): 10}
FIXTURE = CanonicalFixture(104, 1, 2, 10)


def descriptor(**overrides):
    values = dict(venue="kalshi", venue_key="KX-FRA-MAR", market_type="match_winner", home_source_key="FRA", away_source_key="MAR", outcome_key="home", competition_source_key="WC26")
    values.update(overrides)
    return ExactMarketDescriptor(**values)


def test_exact_mapping_and_reversed_fixture_orientation():
    direct = resolve_market(descriptor(), source_entities=INDEX, fixtures=[FIXTURE])
    reverse = resolve_market(
        descriptor(home_source_key="MAR", away_source_key="FRA", outcome_key="home"),
        source_entities=INDEX,
        fixtures=[FIXTURE],
    )
    assert direct.status == "mapped" and direct.canonical_outcome == "home" and direct.serveable
    assert reverse.status == "mapped" and reverse.canonical_outcome == "away"


def test_ambiguous_unmapped_and_unsupported_fail_closed():
    ambiguous = resolve_market(descriptor(), source_entities=INDEX, fixtures=[FIXTURE, CanonicalFixture(105, 1, 2, 10)])
    missing = resolve_market(descriptor(away_source_key="UNKNOWN"), source_entities=INDEX, fixtures=[FIXTURE])
    unsupported = resolve_market(descriptor(market_type="fair_play_award", outcome_key="France"), source_entities=INDEX, fixtures=[FIXTURE])
    assert ambiguous.status == "ambiguous" and not ambiguous.serveable
    assert ambiguous.candidate_event_ids == (104, 105)
    assert missing.status == "unmapped" and "UNKNOWN" in missing.reason
    assert unsupported.status == "unmapped" and not unsupported.serveable


def test_entity_kinds_prevent_team_competition_confusion():
    bad_team = resolve_market(descriptor(), source_entities=INDEX, fixtures=[FIXTURE], entity_kinds={1: "competition", 2: "team", 10: "competition"})
    bad_competition = resolve_market(descriptor(), source_entities=INDEX, fixtures=[FIXTURE], entity_kinds={1: "team", 2: "team", 10: "team"})
    assert bad_team.reason == "participant key is not a team"
    assert bad_competition.reason == "competition key is not a competition"


def test_supported_outcome_patterns_and_score_reversal():
    for market_type, outcome in [
        ("first_half", "first_half:draw"),
        ("btts", "btts:yes"),
        ("total", "total:over:2.5"),
        ("spread", "home:-1.5"),
    ]:
        result = resolve_market(descriptor(market_type=market_type, outcome_key=outcome), source_entities=INDEX, fixtures=[FIXTURE])
        assert result.status == "mapped"
    reversed_score = resolve_market(
        descriptor(home_source_key="MAR", away_source_key="FRA", market_type="correct_score", outcome_key="score:2-1"),
        source_entities=INDEX,
        fixtures=[FIXTURE],
    )
    assert reversed_score.canonical_outcome == "score:1-2"


def test_similarity_suggestions_are_deterministic_and_write_nothing():
    out = suggest_entities("Manchster City", {2: "Manchester United", 1: "Manchester City"}, limit=1)
    assert out[0]["entity_id"] == 1


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_internal_seeding_is_exact_and_idempotent():
    db = _db()
    db.add_all([
        Team(name="France"), Team(name="Morocco"),
        Tournament(name="World Cup", year=2026, host_countries="", start_date=None, end_date=None),
    ])
    db.commit()
    first = seed_internal_entities(db)
    second = seed_internal_entities(db)
    assert first == {"entities_created": 3, "source_maps_created": 3}
    assert second == {"entities_created": 0, "source_maps_created": 0}
    assert db.query(EntitySourceMap).count() == 3


def test_reconciliation_is_retroactive_audited_and_never_rewrites_ticks():
    db = _db()
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    home = CanonicalEntity(sport="football", kind="team", canonical_name="France")
    away = CanonicalEntity(sport="football", kind="team", canonical_name="Morocco")
    competition = CanonicalEntity(sport="football", kind="competition", canonical_name="World Cup")
    db.add_all([home, away, competition]); db.flush()
    db.add_all([
        EntitySourceMap(entity_id=home.id, source="kalshi", source_key="FRA", confidence=1, verified_at=now, verified_by="test"),
        EntitySourceMap(entity_id=away.id, source="kalshi", source_key="MAR", confidence=1, verified_at=now, verified_by="test"),
        EntitySourceMap(entity_id=competition.id, source="kalshi", source_key="WC26", confidence=1, verified_at=now, verified_by="test"),
    ])
    market = VenueMarket(venue="kalshi", venue_key="KX", sport="football", market_type="match_winner", raw_title="France v Morocco", mapping_status="unmapped", status="closed", first_seen=now, last_seen=now)
    db.add(market); db.flush()
    db.add(VenuePriceTick(venue_market_id=market.id, ts=now, transport="polling", observation_key="cycle:1", raw_payload_ref="raw/1"))
    db.commit()
    fixture = CanonicalFixture(104, home.id, away.id, competition.id)
    provider = lambda row: descriptor(venue_key=row.venue_key)
    first = reconcile_markets(db, descriptor_for=provider, fixtures=[fixture])
    second = reconcile_markets(db, descriptor_for=provider, fixtures=[fixture])
    assert first["mapped"] == 1 and first["corrected"] == 1
    assert second["mapped"] == 1 and second["corrected"] == 0
    assert db.query(VenuePriceTick).count() == 1
    assert market.mapping_status == "mapped" and len(market.mapping_history) == 1
