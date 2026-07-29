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


def test_the_artifact_is_served_verbatim_and_marked_experimental(tmp_path, monkeypatch):
    artifact = {
        "experimental": True,
        "generated_at": "2026-08-02T12:00:00+00:00",
        "coverage": {"eligible_observations": 0},
        "benchmark": {"groups": []},
    }
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
