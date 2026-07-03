"""SANDBOX API-key gate for the versioned public API (/v1, ROADMAP Phase 4).

Proves the gate is backward-compatible:
  - OFF by default (API_KEYS_ALLOWED unset) => /v1 stays public, no header needed.
  - ON  (allow-list configured) => X-API-Key required; missing/wrong key => 401.

The gate reads `settings.allowed_api_keys`, a property derived from the
`api_keys_allowed` string. Tests flip it via monkeypatch on that source string
so the singleton self-heals (empty => gate OFF) for every other test.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, Team, Tournament

# Same stored triple/engine params as test_markets_api — the gate is orthogonal
# to the payload; a 200 just has to be a well-formed markets response.
P_HOME, P_DRAW, P_AWAY = 0.55, 0.27, 0.18
LAM_HOME, LAM_AWAY, RHO = 1.7, 1.05, -0.03

KEY = "sandbox-key-abc123"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    seed.add(Tournament(id=1, name="WC26", year=2026))
    seed.add_all([Team(id=10, name="Mexico"), Team(id=20, name="South Africa")])
    seed.add(
        Match(id=1, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="scheduled")
    )
    seed.add(
        Prediction(match_id=1, model_version="poisson-elo-v0.3", is_shadow=False,
                   prob_home_win=P_HOME, prob_draw=P_DRAW, prob_away_win=P_AWAY,
                   predicted_score_home=2, predicted_score_away=1, predicted_score_prob=0.12,
                   lambda_home=LAM_HOME, lambda_away=LAM_AWAY, rho=RHO,
                   confidence="Medium", reasons=["Home edge on Elo"],
                   top_features=[{"name": "elo_diff", "weight": 0.4}])
    )
    seed.commit()
    seed.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    cache.clear()


@pytest.fixture
def gate_on(monkeypatch):
    """Turn the sandbox gate ON for one test; monkeypatch auto-reverts the source
    string afterwards so the singleton's allowed_api_keys is empty again (gate OFF)
    for every other test."""
    monkeypatch.setattr(settings, "api_keys_allowed", KEY)
    assert settings.allowed_api_keys == {KEY}
    yield
    # Sanity: monkeypatch tears down the override; the gate is OFF once more.


def test_gate_off_by_default_no_header_succeeds(client):
    # Shipped default: API_KEYS_ALLOWED unset => allow-list empty => public /v1.
    assert settings.allowed_api_keys == set()
    res = client.get("/v1/markets/1")
    assert res.status_code == 200
    assert res.json()["match_id"] == 1


def test_gate_on_missing_header_is_401(client, gate_on):
    res = client.get("/v1/markets/1")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_api_key"


def test_gate_on_wrong_key_is_401(client, gate_on):
    res = client.get("/v1/markets/1", headers={"X-API-Key": "not-the-key"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_api_key"


def test_gate_on_correct_key_is_200(client, gate_on):
    res = client.get("/v1/markets/1", headers={"X-API-Key": KEY})
    assert res.status_code == 200
    assert res.json()["match_id"] == 1


def test_gate_reverts_off_after_gate_on_fixture(client):
    # Guards the teardown contract: with the fixture gone the gate is OFF, so a
    # bare request (no header) succeeds — other tests in the suite see it public.
    assert settings.allowed_api_keys == set()
    assert client.get("/v1/markets/1").status_code == 200
