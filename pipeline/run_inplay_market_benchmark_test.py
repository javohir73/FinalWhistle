import json

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Match, Team, Tournament, VenueMarket, VenuePriceTick
from pipeline.run_inplay_market_benchmark import PureModelLedgerPoint, load_observations, load_observations_from_db, run


def row():
    return {
        "match_id": 1, "venue": "kalshi", "market_type": "btts",
        "minute": 20, "period": "first_half", "model_probs": [.6, .4],
        "venue_probs": [.5, .5], "label": 0,
        "tick_ts": "2026-10-02T00:00:00+00:00",
        "model_state_ts": "2026-10-02T00:00:00+00:00",
        "quote_source_ts": "2026-10-02T00:00:00+00:00",
        "model_score": [0, 0], "venue_score": [0, 0],
        "model_cards": [0, 0], "venue_cards": [0, 0], "competition": "World Cup",
    }


def test_loader_reports_row_specific_errors(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([{"match_id": 1}]))
    with pytest.raises(ValueError, match="row 1"):
        load_observations(path)


def test_one_command_emits_machine_human_and_evidence_outputs(tmp_path):
    input_path = tmp_path / "rows.json"
    precommit = tmp_path / "precommit.json"
    output = tmp_path / "evidence"
    input_path.write_text(json.dumps([row()]))
    precommit.write_text(json.dumps({
        "held_out_cutoff": "2026-10-01T00:00:00+00:00",
        "max_alignment_seconds": 10, "max_quote_age_seconds": 30,
        "minimum_matches": 2, "bootstrap_samples": 50, "bootstrap_seed": 7,
    }))
    result = run(input_path, precommit, output)
    assert result["groups"][0]["status"] == "insufficient"
    assert json.loads((output / "results.json").read_text()) == result
    assert "insufficient" in (output / "report.txt").read_text()
    assert "match-clustered" in (output / "EVIDENCE-CARD.md").read_text()


def test_db_loader_joins_settled_mapped_tick_to_pure_model_ledger():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tournament = Tournament(name="World Cup", year=2026)
    home, away = Team(name="France"), Team(name="Morocco")
    db.add_all([tournament, home, away]); db.flush()
    match = Match(tournament_id=tournament.id, stage="group", team_home_id=home.id, team_away_id=away.id, status="finished", score_home=1, score_away=0)
    db.add(match); db.flush()
    market = VenueMarket(venue="kalshi", venue_key="K1", sport="football", market_type="match_winner", raw_title="France", mapping_status="mapped", canonical_event_id=match.id, canonical_outcome="home", status="settled", settled_at=now + timedelta(hours=1), settled_outcome="yes", first_seen=now, last_seen=now)
    db.add(market); db.flush()
    db.add(VenuePriceTick(venue_market_id=market.id, ts=now, source_ts=now, transport="streaming", observation_key="event:1", mid=.55, clock_state="score:1-0;cards:0-0;minute:60", raw_payload_ref="raw/1"))
    db.commit()
    ledger = [PureModelLedgerPoint(event_id=match.id, observed_at=now, minute=60, period="second_half", score=(1, 0), outcome_probs={"home": .60, "draw": .25, "away": .15}, competition="World Cup")]
    observations, exclusions = load_observations_from_db(db, ledger)
    assert exclusions == {}
    assert len(observations) == 1
    assert observations[0].model_probs == (.6, .4)
    assert observations[0].venue_probs == pytest.approx((.55, .45))
    assert observations[0].label == 0
