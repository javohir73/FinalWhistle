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


def test_the_artifact_is_served_verbatim_and_marked_experimental(tmp_path, monkeypatch):
    artifact = dict(VALID_ARTIFACT)
    path = tmp_path / "market_benchmark.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setattr(research, "ARTIFACT_PATH", path)

    response = client.get("/api/research/market-benchmark")

    body = response.json()
    assert body["status"] == "ok"
    assert body["experimental"] is True
    assert body["artifact"] == artifact


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



def test_valid_json_that_is_not_a_valid_artifact_is_refused(tmp_path, monkeypatch):
    """{} parses fine and would have crashed the page. Shape is validated
    where the honest answer is still possible."""
    for bad, fragment in [
        ({}, "artifact_version"),
        ({**VALID_ARTIFACT, "artifact_version": "v999"}, "artifact_version"),
        ({**VALID_ARTIFACT, "experimental": False}, "experimental"),
        ({**VALID_ARTIFACT, "benchmark": {}}, "benchmark.groups"),
        ({k: v for k, v in VALID_ARTIFACT.items() if k != "health"}, "health"),
        ([1, 2, 3], "not an object"),
    ]:
        path = tmp_path / "market_benchmark.json"
        path.write_text(json.dumps(bad))
        monkeypatch.setattr(research, "ARTIFACT_PATH", path)

        body = client.get("/api/research/market-benchmark").json()

        assert body["status"] == "invalid", bad
        assert fragment in body["detail"], bad


def test_the_generator_and_api_agree_on_the_artifact_version():
    from pipeline.run_market_benchmark_report import ARTIFACT_VERSION

    assert research.EXPECTED_ARTIFACT_VERSION == ARTIFACT_VERSION
