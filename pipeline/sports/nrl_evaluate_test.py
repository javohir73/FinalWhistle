from __future__ import annotations

from datetime import datetime, timezone

from app.models import SportMatch, SportTeam
from ml.sports.nrl.evaluation import EvaluationConfig, evaluate
from ml.sports.nrl.model import NrlParams
from pipeline.sports.nrl_evaluate import load_matches, write_artifacts


def _add_team(db, name: str) -> SportTeam:
    team = SportTeam(sport="nrl", name=name)
    db.add(team)
    db.flush()
    return team


def test_loader_canonicalizes_historical_tigers_without_mutating_source(db_session):
    tigers = _add_team(db_session, "Tigers")
    west_tigers = _add_team(db_session, "Wests Tigers")
    storm = _add_team(db_session, "Storm")
    match = SportMatch(
        sport="nrl",
        season=2018,
        round=1,
        match_no=1,
        kickoff_utc=datetime(2018, 3, 1, tzinfo=timezone.utc),
        venue="Test Ground",
        home_team_id=tigers.id,
        away_team_id=storm.id,
        score_home=12,
        score_away=20,
        status="finished",
    )
    db_session.add(match)
    db_session.flush()

    rows, inventory = load_matches(db_session)

    assert rows[0]["home_team_id"] == west_tigers.id
    assert match.home_team_id == tigers.id
    assert inventory["canonical_aliases"][0]["source_id"] == tigers.id
    assert inventory["canonical_aliases"][0]["target_id"] == west_tigers.id


def test_artifacts_are_byte_equivalent_except_for_manifest_timestamp(tmp_path):
    rows = [
        {
            "match_id": 1,
            "season": 2022,
            "round": 1,
            "kickoff_utc": datetime(2022, 3, 1, tzinfo=timezone.utc),
            "venue": "Test Ground",
            "home_team_id": 1,
            "away_team_id": 2,
            "score_home": 20,
            "score_away": 10,
        },
        {
            "match_id": 2,
            "season": 2023,
            "round": 1,
            "kickoff_utc": datetime(2023, 3, 1, tzinfo=timezone.utc),
            "venue": "Test Ground",
            "home_team_id": 2,
            "away_team_id": 1,
            "score_home": 21,
            "score_away": 20,
        },
    ]
    config = EvaluationConfig(
        from_season=2023,
        to_season=2023,
        model_version="artifact-test",
        bootstrap_samples=20,
    )
    result = evaluate(rows, config, winner_params=NrlParams())
    inventory = {
        "source_rows": len(rows),
        "canonical_aliases": [],
        "market_source": None,
        "market_reason": "test fixture has no market data",
    }

    first = write_artifacts(
        result,
        inventory,
        tmp_path / "first",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = write_artifacts(
        result,
        inventory,
        tmp_path / "second",
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    for filename in (
        "predictions.jsonl",
        "results.json",
        "leakage_audit.json",
        "report.html",
    ):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert (first / "manifest.json").read_bytes() != (
        second / "manifest.json"
    ).read_bytes()
