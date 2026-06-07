"""Tests for the health endpoint (task 1.10)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200_and_payload():
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["app"] == "FinalWhistle"
    assert "model_version" in body
