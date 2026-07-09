"""prob-history returns up to 7 public prediction points, oldest first."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), TestingSession()


def test_prob_history_orders_and_caps_points():
    client, db = _client()
    # Minimal non-null Match columns (app/models/__init__.py:88-155):
    # tournament_id and stage have no default and are NOT NULL.
    m = Match(tournament_id=1, stage="group")
    db.add(m); db.flush()
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(9):
        db.add(Prediction(match_id=m.id, model_version="v1",
                          prob_home_win=0.4 + i * 0.01, prob_draw=0.3,
                          prob_away_win=0.3 - i * 0.01,
                          created_at=base + timedelta(days=i)))
    db.commit()

    res = client.get(f"/api/matches/{m.id}/prob-history")
    assert res.status_code == 200
    body = res.json()
    pts = body["points"]
    assert len(pts) == 7
    assert pts[0]["date"] < pts[-1]["date"]
    # Most recent 7 of 9 rows kept, ascending: days 2..8.
    assert pts[0]["date"].startswith("2026-07-03")
    assert pts[-1]["date"].startswith("2026-07-09")
    assert round(pts[-1]["p_home"], 2) == 0.48
    assert round(pts[-1]["p_away"], 2) == 0.22
    assert "Not betting advice" in body["disclaimer"]
    assert body["match_id"] == m.id
    app.dependency_overrides.clear()


def test_prob_history_excludes_shadow_rows():
    client, db = _client()
    m = Match(tournament_id=1, stage="group")
    db.add(m); db.flush()
    db.add(Prediction(match_id=m.id, model_version="v1", prob_home_win=0.5,
                      prob_draw=0.25, prob_away_win=0.25, is_shadow=True))
    db.commit()

    res = client.get(f"/api/matches/{m.id}/prob-history")
    assert res.status_code == 200
    assert res.json()["points"] == []
    app.dependency_overrides.clear()


def test_prob_history_404_for_missing_match():
    client, _db = _client()
    res = client.get("/api/matches/999999/prob-history")
    assert res.status_code == 404
    # Global exception handler normalizes to {"error": {"code", "message"}}
    # (app/main.py's http_exception_handler, PRD §11).
    assert res.json()["error"]["code"] == "match_not_found"
    app.dependency_overrides.clear()
