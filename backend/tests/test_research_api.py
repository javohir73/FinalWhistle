"""Research API: experimental-only, artifact-served, honest empty states."""

import json

from fastapi.testclient import TestClient

from app.api import research
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_no_artifact_returns_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "missing.json")

    response = client.get("/api/research/market-benchmark")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_data"
    assert body["experimental"] is True
    assert "run" in body["detail"]


VALID_ARTIFACT = {
    "artifact_version": "market-benchmark-artifact-v1",
    "experimental": True,
    "generated_at": "2026-08-02T12:00:00+00:00",
    "coverage": {"eligible_observations": 0},
    "exclusions": {},
    "health": {"venues": {}},
    "benchmark": {"groups": []},
}


def test_the_artifact_is_served_allowlisted_and_marked_experimental(tmp_path, monkeypatch):
    """Not verbatim: the response is RECONSTRUCTED through the allowlist, so
    fields the page does not render never leave the server -- the
    public-data boundary is enforced by construction."""
    artifact = {**VALID_ARTIFACT,
                "secret_extra_field": "must never be served",
                "notes": ["internal operator scratch"]}
    path = tmp_path / "market_benchmark.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)

    response = client.get("/api/research/market-benchmark")

    body = response.json()
    assert body["status"] == "ok"
    assert body["experimental"] is True
    served = body["artifact"]
    assert served["generated_at"] == VALID_ARTIFACT["generated_at"]
    assert served["coverage"] == {"eligible_observations": 0}
    assert "secret_extra_field" not in served
    assert "notes" not in served
    assert set(served) == {"artifact_version", "experimental", "generated_at",
                           "coverage", "exclusions", "benchmark", "health"}


def test_a_corrupt_artifact_is_reported_not_served(tmp_path, monkeypatch):
    path = tmp_path / "market_benchmark.json"
    path.write_text("{not json")
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)

    response = client.get("/api/research/market-benchmark")

    assert response.json()["status"] == "unreadable"


def test_research_responses_are_never_cached(tmp_path, monkeypatch):
    """Research data must not be CDN-frozen: main.py marks /api/research
    no-store alongside the other per-caller paths."""
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "missing.json")

    response = client.get("/api/research/market-benchmark")

    assert "no-store" in response.headers.get("cache-control", "")



READY_GROUP = {
    "venue": "kalshi", "status": "READY", "n_matches": 60, "min_matches": 50,
    "model": {"log_loss": 0.98, "brier": 0.61, "n": 60},
    "venue_normalized": {"log_loss": 0.95, "brier": 0.60, "n": 60},
    "baseline_uniform": {"log_loss": 1.0986, "brier": 0.6667, "n": 60},
    "delta_log_loss_model_minus_venue": 0.03,
    "delta_ci95_match_clustered": [-0.01, 0.07],
    "verdict": "inconclusive",
}

HEALTH_VENUE = {
    "markets_total": 3, "mapping": {"mapped": 3}, "mapped_fixtures": 1,
    "fixtures_with_complete_1x2": 1, "fixtures_incomplete_1x2": [],
    "fixtures_missing_prematch_quote": [], "markets_without_any_quote": [],
    "quote_freshness_by_transport": {
        "polling": {"latest_quote_at": "2026-08-02T11:50:00+00:00",
                    "age_seconds": 600}},
}


def test_valid_json_that_is_not_a_valid_artifact_is_refused(tmp_path, monkeypatch):
    """{} parses fine and would have crashed the page. Shape AND nested
    domains are validated where the honest answer is still possible."""
    for bad, fragment in [
        ({}, "artifact_version"),
        ({**VALID_ARTIFACT, "artifact_version": "v999"}, "artifact_version"),
        ({**VALID_ARTIFACT, "experimental": False}, "experimental"),
        ({**VALID_ARTIFACT, "benchmark": {}}, "benchmark.groups"),
        ({k: v for k, v in VALID_ARTIFACT.items() if k != "health"}, "health"),
        ([1, 2, 3], "not an object"),
        # Nested poison that previously sailed through as status ok:
        ({**VALID_ARTIFACT, "benchmark": {"groups": [None]}},
         "groups[0] must be an object"),
        ({**VALID_ARTIFACT, "health": {"venues": {"kalshi": None}}},
         "health.venues[kalshi] must be an object"),
        ({**VALID_ARTIFACT, "generated_at": "not-a-date"}, "ISO-8601"),
        ({**VALID_ARTIFACT, "generated_at": "2026-08-02T12:00:00"},
         "timezone-aware"),
        ({**VALID_ARTIFACT,
          "benchmark": {"groups": [{**READY_GROUP, "verdict": "trust me"}]}},
         "verdict"),
        ({**VALID_ARTIFACT,
          "benchmark": {"groups": [{**READY_GROUP,
                                    "model": {"log_loss": float("nan"),
                                              "brier": 0.5, "n": 60}}]}},
         "finite"),
        ({**VALID_ARTIFACT,
          "benchmark": {"groups": [{**READY_GROUP,
                                    "delta_ci95_match_clustered": [0.5, -0.5]}]}},
         "inverted"),
        ({**VALID_ARTIFACT,
          "benchmark": {"groups": [{**READY_GROUP, "n_matches": -3}]}},
         ">= 0"),
        ({**VALID_ARTIFACT,
          "health": {"venues": {"kalshi": {**HEALTH_VENUE,
                                           "markets_total": "lots"}}}},
         "must be a number"),
        ({**VALID_ARTIFACT,
          "health": {"venues": {"kalshi": {
              **HEALTH_VENUE,
              "quote_freshness_by_transport": {"polling": None}}}}},
         "must be an object"),
    ]:
        path = tmp_path / "market_benchmark.json"
        path.write_text(json.dumps(bad))
        monkeypatch.setattr(research, "ARTIFACT_PATH", path)

        body = client.get("/api/research/market-benchmark").json()

        assert body["status"] == "invalid", bad
        assert fragment in body["detail"], bad


def test_a_fully_valid_nested_artifact_round_trips_through_the_allowlist(tmp_path, monkeypatch):
    artifact = {
        **VALID_ARTIFACT,
        "benchmark": {"groups": [READY_GROUP],
                      "split": {"train_matches": 140, "holdout_matches": 60}},
        "health": {"venues": {"kalshi": HEALTH_VENUE},
                   "heartbeat_freshness_by_venue_worker": {
                       "kalshi/worker-a": {
                           "last_completed_at": "2026-08-02T11:55:00+00:00",
                           "age_seconds": 300}}},
    }
    path = tmp_path / "market_benchmark.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)

    body = client.get("/api/research/market-benchmark").json()

    assert body["status"] == "ok"
    group = body["artifact"]["benchmark"]["groups"][0]
    assert group["verdict"] == "inconclusive"
    assert group["delta_ci95_match_clustered"] == [-0.01, 0.07]
    venue = body["artifact"]["health"]["venues"]["kalshi"]
    assert venue["quote_freshness_by_transport"]["polling"]["age_seconds"] == 600
    assert body["artifact"]["benchmark"]["split"]["holdout_matches"] == 60


def test_the_generator_output_passes_the_allowlist():
    """The generator and the API must agree on more than a version string:
    a real (empty-data) artifact built by build_artifact must sanitize
    cleanly, or the two halves have drifted."""
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    from pipeline.run_market_benchmark_report import build_artifact

    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    artifact = build_artifact(
        db, holdout_fraction=0.3, min_matches=50, n_bootstrap=100, seed=1,
        now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc))
    db.close()

    sanitized = research.sanitize_artifact(artifact)
    assert sanitized["benchmark"]["groups"] == []


def test_the_generator_and_api_agree_on_the_artifact_version():
    from pipeline.run_market_benchmark_report import ARTIFACT_VERSION

    assert research.EXPECTED_ARTIFACT_VERSION == ARTIFACT_VERSION
