"""Knockout advance block serving: /api/matches/{id} exposes the v0.5
`knockout` block for knockout fixtures and omits it for group games."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import Match, Team
from pipeline.generate_predictions import _write_prediction, build_payload
from pipeline.ingest.wc26_structure import load_structure


@pytest.fixture
def ko_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    load_structure(seed)
    for i, t in enumerate(seed.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    # Promote two teams into a knockout fixture (structure loads them TBD) and
    # freeze one group + one knockout prediction the endpoints can serve.
    ko = seed.query(Match).filter(Match.stage != "group").first()
    home, away = seed.query(Team).order_by(Team.id).limit(2).all()
    ko.team_home_id, ko.team_away_id = home.id, away.id
    group = (
        seed.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    seed.commit()
    for m in (ko, group):
        _write_prediction(seed, m, build_payload(seed, m, "poisson-elo-v0.5"),
                          "poisson-elo-v0.5")
    seed.commit()
    ids = {"ko": ko.id, "group": group.id}
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


def test_knockout_match_serves_advance_block(ko_client):
    client, ids = ko_client
    body = client.get(f"/api/matches/{ids['ko']}").json()
    block = body["knockout"]
    assert block is not None
    assert abs(block["p_advance_home"] + block["p_advance_away"] - 1.0) < 1e-3
    # P(extra time) is the served regulation draw probability.
    assert abs(block["p_extra_time"] - body["probabilities"]["draw"]) < 1e-3
    # Shootout is a subset of the extra-time mass.
    assert 0.0 <= block["p_shootout"] <= block["p_extra_time"]
    for side in ("home", "away"):
        paths = block["paths"][side]
        total = paths["win_90"] + paths["win_et"] + paths["win_pens"]
        assert abs(total - block[f"p_advance_{side}"]) < 1e-3


def test_group_match_has_no_advance_block(ko_client):
    client, ids = ko_client
    body = client.get(f"/api/matches/{ids['group']}").json()
    assert body["knockout"] is None
