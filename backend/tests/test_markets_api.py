"""GET /v1/markets/{match_id} — the versioned public markets API (Phase 2,
docs/ROADMAP-ENGINE.md).

Additive to serving: it reads the FROZEN Prediction row and returns derived
markets. 1X2 + double-chance come from the STORED calibrated triple; every
scoreline-grid market (totals/BTTS/correct-score/Asian-handicap) is priced off
the raw Poisson grid on the stored lambdas — calibration only touches W/D/L.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, Team, Tournament
from ml.models import markets as _markets

# Stored triple + engine params for the seeded prediction. The 1X2 is deliberately
# NOT the raw Poisson W/D/L for these lambdas, so a test that reads it back proves
# the endpoint serves the calibrated stored values rather than re-deriving them.
P_HOME, P_DRAW, P_AWAY = 0.55, 0.27, 0.18
LAM_HOME, LAM_AWAY, RHO = 1.7, 1.05, -0.03


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
    # A match with NO prediction (404 no_prediction).
    seed.add(
        Match(id=2, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="scheduled")
    )
    # An IN-PLAY match with a current score and a modellable clock — the ?live=1
    # path re-prices off this state (same frozen lambdas as match 1).
    seed.add(
        Match(id=3, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="in_play", score_home=1, score_away=0, minute=70,
              period="second_half")
    )
    seed.add(
        Prediction(match_id=1, model_version="poisson-elo-v0.3", is_shadow=False,
                   prob_home_win=P_HOME, prob_draw=P_DRAW, prob_away_win=P_AWAY,
                   predicted_score_home=2, predicted_score_away=1, predicted_score_prob=0.12,
                   lambda_home=LAM_HOME, lambda_away=LAM_AWAY, rho=RHO,
                   confidence="Medium", reasons=["Home edge on Elo"],
                   top_features=[{"name": "elo_diff", "weight": 0.4}])
    )
    seed.add(
        Prediction(match_id=3, model_version="poisson-elo-v0.3", is_shadow=False,
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


def test_markets_200_and_shape(client):
    res = client.get("/v1/markets/1")
    assert res.status_code == 200
    body = res.json()
    assert body["match_id"] == 1
    assert body["model_version"] == "poisson-elo-v0.3"
    assert body["generated_at"]  # set (frozen prediction timestamp)
    assert body["teams"] == {"home": "Mexico", "away": "South Africa"}
    assert body["disclaimer"]
    # Phase-2 default is byte-identical: the additive live fields default off.
    assert body["is_live"] is False
    assert body["live"] is None


def test_one_x_two_is_the_stored_calibrated_triple(client):
    # The published 1X2 must be the STORED calibrated probs, not a re-derivation
    # off the lambdas.
    onextwo = client.get("/v1/markets/1").json()["markets"]["one_x_two"]
    assert onextwo == {"home_win": P_HOME, "draw": P_DRAW, "away_win": P_AWAY}


def test_double_chance_matches_stored_triple(client):
    dc = client.get("/v1/markets/1").json()["markets"]["double_chance"]
    expected = _markets.double_chance_from_triple(P_HOME, P_DRAW, P_AWAY)
    assert dc["home_or_draw"] == pytest.approx(expected["home_or_draw"])
    assert dc["home_or_away"] == pytest.approx(expected["home_or_away"])
    assert dc["draw_or_away"] == pytest.approx(expected["draw_or_away"])


def test_scoreline_markets_present_and_nonempty(client):
    m = client.get("/v1/markets/1").json()["markets"]
    assert m["totals"] and isinstance(m["totals"], list)
    assert set(m["btts"]) == {"yes", "no"}
    assert m["correct_score"] and isinstance(m["correct_score"], list)
    assert m["asian_handicap"] and isinstance(m["asian_handicap"], list)


def test_scoreline_markets_come_from_the_raw_grid(client):
    # Grid markets are priced on the stored lambdas/rho — independent of the
    # calibrated 1X2. Cross-check against the pure market engine directly.
    m = client.get("/v1/markets/1").json()["markets"]
    expected = _markets.derive_scoreline_markets(LAM_HOME, LAM_AWAY, RHO)
    assert m["btts"]["yes"] == pytest.approx(expected["btts"]["yes"])
    assert m["totals"][0]["line"] == pytest.approx(expected["totals"][0]["line"])
    assert m["totals"][0]["over"] == pytest.approx(expected["totals"][0]["over"])


def test_explanation_and_calibration_metadata(client):
    body = client.get("/v1/markets/1").json()
    assert body["explanation"]["confidence"] == "Medium"
    assert body["explanation"]["reasons"] == ["Home edge on Elo"]
    assert body["explanation"]["top_features"] == [{"name": "elo_diff", "weight": 0.4}]
    assert body["calibration"]["per_market_vs_close"] is None
    assert isinstance(body["calibration"]["basis"], str) and body["calibration"]["basis"]


def test_cache_control_is_public_shared_cacheable(client):
    res = client.get("/v1/markets/1")
    assert res.status_code == 200
    assert "public" in res.headers["Cache-Control"]


def test_404_when_match_missing(client):
    res = client.get("/v1/markets/999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_404_when_no_prediction(client):
    res = client.get("/v1/markets/2")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "no_prediction"


# --- Live markets (?live=1, Phase 3) -----------------------------------------
# Live state seeded on match 3: in_play, 1-0, minute 70, second_half.
from app.live_winprob import live_win_probabilities, regulation_remaining


def test_default_no_live_param_is_frozen_even_on_in_play_match(client):
    # Without ?live the endpoint is byte-identical to Phase 2 regardless of the
    # match being in play — the default never re-prices.
    frozen = client.get("/v1/markets/3").json()
    assert frozen["is_live"] is False
    assert frozen["live"] is None
    assert frozen["markets"]["one_x_two"] == {
        "home_win": P_HOME, "draw": P_DRAW, "away_win": P_AWAY
    }
    expected = _markets.derive_scoreline_markets(LAM_HOME, LAM_AWAY, RHO)
    assert frozen["markets"]["btts"]["yes"] == pytest.approx(expected["btts"]["yes"])


def test_live_on_in_play_match_is_live_with_state_and_shifted_markets(client):
    frozen = client.get("/v1/markets/3").json()
    live = client.get("/v1/markets/3?live=1").json()

    assert live["is_live"] is True
    assert live["live"] == {"minute": 70, "current_home": 1, "current_away": 0}
    # model_version + explanation still come from the frozen prediction.
    assert live["model_version"] == "poisson-elo-v0.3"
    assert live["explanation"]["confidence"] == "Medium"

    # Home leads 1-0 with ~20' to play: live P(home) must exceed the pre-match
    # 1X2, and the whole 1X2 differs from the frozen triple.
    assert live["markets"]["one_x_two"] != frozen["markets"]["one_x_two"]
    assert live["markets"]["one_x_two"]["home_win"] > P_HOME
    # Scoreline markets are re-priced too (BTTS shifts once a goal is on the board).
    assert live["markets"]["btts"]["yes"] != pytest.approx(
        frozen["markets"]["btts"]["yes"]
    )


def test_live_one_x_two_matches_the_live_bar_exactly(client):
    # The published live 1X2 must be the SAME triple the in-play bar shows — both
    # read the shared live grid. Recompute the bar directly and compare.
    live = client.get("/v1/markets/3?live=1").json()["markets"]["one_x_two"]
    remaining = regulation_remaining(70, "second_half")
    ph, pd, pa = live_win_probabilities(1, 0, LAM_HOME, LAM_AWAY, remaining, rho=RHO)
    assert live["home_win"] == pytest.approx(ph)
    assert live["draw"] == pytest.approx(pd)
    assert live["away_win"] == pytest.approx(pa)


def test_live_double_chance_matches_live_one_x_two(client):
    m = client.get("/v1/markets/3?live=1").json()["markets"]
    onextwo = m["one_x_two"]
    dc = m["double_chance"]
    assert dc["home_or_draw"] == pytest.approx(onextwo["home_win"] + onextwo["draw"])
    assert dc["home_or_away"] == pytest.approx(onextwo["home_win"] + onextwo["away_win"])
    assert dc["draw_or_away"] == pytest.approx(onextwo["draw"] + onextwo["away_win"])


def test_live_on_scheduled_match_falls_back_to_frozen(client):
    # ?live=1 on a match that is not in play returns the frozen Phase-2 payload.
    live = client.get("/v1/markets/1?live=1").json()
    frozen = client.get("/v1/markets/1").json()
    assert live["is_live"] is False
    assert live["live"] is None
    assert live["markets"] == frozen["markets"]
    assert live["markets"]["one_x_two"] == {
        "home_win": P_HOME, "draw": P_DRAW, "away_win": P_AWAY
    }
