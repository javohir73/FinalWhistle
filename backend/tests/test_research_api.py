"""Research API: experimental-only, artifact-served, honest empty states."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import research
from app.db import Base, get_db
from app.main import app
from app.research_store import DatabaseArtifactStore, FileArtifactStore

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def db_app():
    """Bind the API to a throwaway database for the duration of one test.

    AUTOUSE deliberately: without it a test reaches whatever Postgres happens
    to be running on the developer's machine. That passed locally and failed
    on a clean runner -- and failed *correctly*, as `unreadable`, because a
    database the endpoint cannot reach is now reported honestly rather than as
    "no data". The endpoint behaviour is right; the ambient dependency was the
    bug. Every test in this module gets its own empty database, so the ones
    below exercise the file branch because nothing is published, not because
    no database exists.
    """
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()


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


# --- the persistence boundary, end to end ------------------------------------


def test_an_artifact_published_to_the_database_is_served(db_app, tmp_path, monkeypatch):
    """The point of the whole slice: CI publishes to Postgres, the deployed
    API reads it -- no shared filesystem anywhere in the path."""
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "absent.json")
    DatabaseArtifactStore(db_app).publish(VALID_ARTIFACT, published_by="pete")

    body = client.get("/api/research/market-benchmark").json()

    assert body["status"] == "ok"
    assert body["source"] == "database"
    assert body["artifact"]["generated_at"] == VALID_ARTIFACT["generated_at"]


def test_the_database_wins_over_a_stale_image_baked_file(db_app, tmp_path, monkeypatch):
    """A file could only reach production by being committed into the image,
    where it would be frozen at build time. Fresh data must win."""
    path = tmp_path / "market_benchmark.json"
    FileArtifactStore(path).publish(
        {**VALID_ARTIFACT, "coverage": {"eligible_observations": 1}},
        published_by="stale")
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)
    DatabaseArtifactStore(db_app).publish(
        {**VALID_ARTIFACT, "coverage": {"eligible_observations": 99}},
        published_by="pete")

    body = client.get("/api/research/market-benchmark").json()

    assert body["source"] == "database"
    assert body["artifact"]["coverage"]["eligible_observations"] == 99


def test_a_poisoned_database_row_gets_no_more_trust_than_a_poisoned_file(
        db_app, tmp_path, monkeypatch):
    """The allowlist is the boundary regardless of which backend supplied the
    bytes -- publishing to the database is not a way around it."""
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "absent.json")
    DatabaseArtifactStore(db_app).publish(
        {**VALID_ARTIFACT, "benchmark": {"groups": [None]}},
        published_by="pete")

    body = client.get("/api/research/market-benchmark").json()

    assert body["status"] == "invalid"
    assert "groups[0] must be an object" in body["detail"]


def test_an_empty_database_and_no_file_is_a_clean_no_data(db_app, tmp_path, monkeypatch):
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "absent.json")

    body = client.get("/api/research/market-benchmark").json()

    assert body["status"] == "no_data"
    assert "--publish-db" in body["detail"]


def test_the_endpoint_survives_the_table_not_existing_yet(db_app, tmp_path, monkeypatch):
    """Migrations land via refresh.yml, not on deploy. Between merge and the
    next migration run the table is absent -- that must be 'no data', not a
    500 on a public endpoint."""
    db_app.execute(text("DROP TABLE research_artifact"))
    db_app.commit()
    monkeypatch.setattr(research, "ARTIFACT_PATH", tmp_path / "absent.json")

    response = client.get("/api/research/market-benchmark")

    assert response.status_code == 200
    assert response.json()["status"] == "no_data"


def test_a_database_outage_is_reported_not_papered_over(db_app, tmp_path, monkeypatch):
    """The counterpart to the fallback above, and the reason the fallback is
    narrow: a reachable-but-broken database must never render as "no data".

    A valid file is present here on purpose. Serving it would look like a
    graceful degradation and would in fact hide an outage behind whatever
    stale bytes were baked into the image -- the operator would read a number
    and never learn the database was down.
    """
    path = tmp_path / "market_benchmark.json"
    FileArtifactStore(path).publish(VALID_ARTIFACT, published_by="stale")
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)

    def _refused(*_args, **_kwargs):
        # Shaped like what psycopg2 actually raises, because the thin version
        # of this test could not have noticed the endpoint echoing any of it.
        raise OperationalError(
            "SELECT research_artifact.id, research_artifact.payload "
            "FROM research_artifact ORDER BY research_artifact.generated_at DESC",
            {},
            ConnectionError(
                'connection to server at "db.internal.example" (10.0.0.7), '
                'port 5432 failed: FATAL:  password authentication failed '
                'for user "wc26_reader"'),
        )

    monkeypatch.setattr(db_app, "query", _refused)

    response = client.get("/api/research/market-benchmark")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreadable"
    assert "cannot be read" in body["detail"]
    assert "no benchmark artifact has been published" not in body["detail"]
    # The status is public; the driver's account of WHY is not. Connect-time
    # failures name the host, port and role, mid-query failures name the
    # statement and its columns -- none of it belongs in an anonymous
    # response from an endpoint whose whole design is an allowlist.
    whole_body = json.dumps(body)
    for internal in ["db.internal.example", "10.0.0.7", "5432", "wc26_reader",
                     "password authentication", "SELECT", "research_artifact",
                     "psycopg2", "OperationalError"]:
        assert internal not in whole_body, internal


def test_the_table_not_existing_yet_still_falls_back_to_the_file(
        db_app, tmp_path, monkeypatch):
    """The one accepted fallback, proven to actually deliver: table absent,
    file present, file served."""
    path = tmp_path / "market_benchmark.json"
    FileArtifactStore(path).publish(VALID_ARTIFACT, published_by="local")
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)
    db_app.execute(text("DROP TABLE research_artifact"))
    db_app.commit()

    body = client.get("/api/research/market-benchmark").json()

    assert body["status"] == "ok"
    assert body["source"] == "file"
