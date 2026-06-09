"""Bracket + leaderboard API tests (auth dependency overridden).

The Origin/CSRF check stays live, so the test client always sends an allowed
Origin header (matching the default CORS_ORIGINS).
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import AppUser, Match
from pipeline.ingest.wc26_structure import load_structure

ALLOWED_ORIGIN = "http://localhost:3000"


def _make_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def env():
    """Authed client + session factory, seeded with the WC26 structure."""
    TestingSession = _make_engine()
    seed = TestingSession()
    load_structure(seed)
    seed.add(AppUser(email="tester@example.com", password_hash="x", display_name="Tester"))
    seed.commit()
    seed.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    def override_user(db: Session = Depends(get_db)) -> AppUser:
        return db.query(AppUser).filter_by(email="tester@example.com").one()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user
    cache.clear()
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN}), TestingSession
    app.dependency_overrides.clear()
    cache.clear()


def _group_match_ids(SessionF, n):
    db = SessionF()
    ids = [
        m.id for m in db.query(Match).filter(Match.stage == "group").order_by(Match.id).limit(n).all()
    ]
    db.close()
    return ids


def test_save_and_restore(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 2)
    payload = {
        "group_picks": [
            {"match_id": ids[0], "pick": "home"},
            {"match_id": ids[1], "pick": "draw"},
        ],
        "knockout_picks": [{"match_no": 104, "picked_team_id": 1}],
        "champion_team_id": 1,
        "encoded_state": "abc.def",
    }
    r = client.post("/api/brackets", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["champion_team_id"] == 1
    assert len(r.json()["group_picks"]) == 2

    restored = client.get("/api/brackets/me").json()
    assert {p["match_id"] for p in restored["group_picks"]} == {ids[0], ids[1]}
    assert restored["knockout_picks"][0]["match_no"] == 104


def test_locked_match_pick_rejected(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 1)
    db = SessionF()
    m = db.get(Match, ids[0])
    m.status = "finished"
    m.score_home, m.score_away = 1, 0
    db.commit()
    db.close()

    r = client.post("/api/brackets", json={"group_picks": [{"match_id": ids[0], "pick": "home"}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_locked"


def test_private_by_default_then_join_publishes(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 1)
    client.post("/api/brackets", json={"group_picks": [{"match_id": ids[0], "pick": "home"}], "champion_team_id": 1})

    assert client.get("/api/leaderboard").json() == []  # private by default

    r = client.post("/api/leaderboard/join", json={"display_name": "Ace", "visibility": "public"})
    assert r.status_code == 200
    board = client.get("/api/leaderboard").json()
    assert len(board) == 1 and board[0]["display_name"] == "Ace"


def test_recompute_reflects_results(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 2)
    client.post("/api/brackets", json={
        "group_picks": [{"match_id": ids[0], "pick": "home"}, {"match_id": ids[1], "pick": "home"}],
        "champion_team_id": 1,
    })
    client.post("/api/leaderboard/join", json={"display_name": "Ace"})

    db = SessionF()
    m = db.get(Match, ids[0])
    m.status, m.score_home, m.score_away = "finished", 2, 0  # home win -> matches the pick
    db.commit()
    from app.scoring import recompute_scores
    recompute_scores(db)
    db.close()

    board = client.get("/api/leaderboard").json()
    assert board[0]["total_points"] == 3  # one correct group outcome
    assert board[0]["rank"] == 1


def test_save_requires_auth_cookie():
    """With no session cookie (and no override), protected routes return 401."""
    TestingSession = _make_engine()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db  # but NOT get_current_user
    try:
        client = TestClient(app, headers={"Origin": ALLOWED_ORIGIN})
        assert client.get("/api/brackets/me").status_code == 401
        r = client.post("/api/brackets", json={"group_picks": []})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_foreign_origin_rejected(env):
    """A state-changing request from a non-allowed Origin is blocked (CSRF guard)."""
    client, _ = env
    r = client.post(
        "/api/brackets",
        json={"group_picks": []},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
