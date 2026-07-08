"""Model-vs-market serving: /api/matches/{id} exposes the margin-free market
consensus when an odds snapshot exists, and reports unavailable otherwise."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Odds, Team
from pipeline.generate_predictions import _write_prediction, build_payload
from pipeline.ingest.wc26_structure import load_structure


@pytest.fixture
def odds_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    load_structure(seed)
    for i, t in enumerate(seed.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    matches = (
        seed.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .order_by(Match.id)
        .limit(2)
        .all()
    )
    priced, unpriced = matches
    seed.commit()
    for m in matches:
        _write_prediction(seed, m, build_payload(seed, m, "poisson-elo-v0.5"),
                          "poisson-elo-v0.5")
    # Two snapshots for the priced match — the FRESHER one must be served.
    seed.add(Odds(match_id=priced.id, bookmaker="consensus",
                  odds_home=2.4, odds_draw=3.3, odds_away=3.1,
                  implied_prob_home=0.40, implied_prob_draw=0.29, implied_prob_away=0.31,
                  captured_at=datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)))
    seed.add(Odds(match_id=priced.id, bookmaker="consensus",
                  odds_home=2.2, odds_draw=3.3, odds_away=3.4,
                  implied_prob_home=0.44, implied_prob_draw=0.28, implied_prob_away=0.28,
                  captured_at=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc)))
    seed.commit()
    ids = {"priced": priced.id, "unpriced": unpriced.id}
    seed.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield TestClient(app), ids
    app.dependency_overrides.clear()
    cache.clear()


def test_market_block_serves_freshest_snapshot(odds_client):
    client, ids = odds_client
    oc = client.get(f"/api/matches/{ids['priced']}").json()["odds_comparison"]
    assert oc["available"] is True
    assert oc["market"] == {"home_win": 0.44, "draw": 0.28, "away_win": 0.28}
    assert oc["captured_at"].startswith("2026-07-08")


def test_market_block_unavailable_without_snapshot(odds_client):
    client, ids = odds_client
    oc = client.get(f"/api/matches/{ids['unpriced']}").json()["odds_comparison"]
    assert oc["available"] is False
    assert oc["market"] is None
