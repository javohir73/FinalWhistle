"""Match-picks API tests: the account copy of the device-local per-match picks.

Mirrors test_brackets_api.py — the auth dependency is overridden; the
Origin/CSRF check stays live, so the test client always sends an allowed
Origin header (matching the default CORS_ORIGINS).
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
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
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN}), TestingSession
    app.dependency_overrides.clear()


def _group_match_ids(SessionF, n):
    db = SessionF()
    ids = [
        m.id for m in db.query(Match).filter(Match.stage == "group").order_by(Match.id).limit(n).all()
    ]
    db.close()
    return ids


def _finish_match(SessionF, match_id):
    db = SessionF()
    m = db.get(Match, match_id)
    m.status = "finished"
    m.score_home, m.score_away = 1, 0
    db.commit()
    db.close()


def _picks_by_match(body: dict) -> dict[int, str]:
    return {p["match_id"]: p["pick"] for p in body["picks"]}


def test_save_and_restore(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 2)
    payload = {"picks": [
        {"match_id": ids[0], "pick": "home"},
        {"match_id": ids[1], "pick": "draw"},
    ]}
    r = client.post("/api/match-picks", json=payload)
    assert r.status_code == 200, r.text
    assert _picks_by_match(r.json()) == {ids[0]: "home", ids[1]: "draw"}

    restored = client.get("/api/match-picks/me")
    assert restored.status_code == 200
    assert _picks_by_match(restored.json()) == {ids[0]: "home", ids[1]: "draw"}


def test_empty_when_nothing_saved(env):
    client, _ = env
    r = client.get("/api/match-picks/me")
    assert r.status_code == 200
    assert r.json()["picks"] == []


def test_resave_upserts_and_prunes(env):
    """A re-save is the full source of truth: changed picks update, omitted
    (still-open) picks are removed."""
    client, SessionF = env
    ids = _group_match_ids(SessionF, 2)
    client.post("/api/match-picks", json={"picks": [
        {"match_id": ids[0], "pick": "home"},
        {"match_id": ids[1], "pick": "draw"},
    ]})
    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "away"}]})
    assert r.status_code == 200, r.text
    assert _picks_by_match(r.json()) == {ids[0]: "away"}
    assert _picks_by_match(client.get("/api/match-picks/me").json()) == {ids[0]: "away"}


def test_locked_match_new_pick_rejected(env):
    """No picking after kickoff: a new pick on a started match is rejected."""
    client, SessionF = env
    ids = _group_match_ids(SessionF, 1)
    _finish_match(SessionF, ids[0])

    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "home"}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_locked"


def test_locked_match_allows_unchanged_resend_but_rejects_edit(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 1)
    client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "home"}]})
    _finish_match(SessionF, ids[0])

    # Unchanged resend (the client always pushes its full state) is allowed…
    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "home"}]})
    assert r.status_code == 200, r.text
    assert _picks_by_match(r.json()) == {ids[0]: "home"}

    # …but editing the locked pick is not.
    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "away"}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_locked"


def test_locked_pick_survives_when_omitted(env):
    """Pruning omitted picks never touches locked ones (results are history)."""
    client, SessionF = env
    ids = _group_match_ids(SessionF, 2)
    client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "home"}]})
    _finish_match(SessionF, ids[0])

    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[1], "pick": "draw"}]})
    assert r.status_code == 200, r.text
    assert _picks_by_match(r.json()) == {ids[0]: "home", ids[1]: "draw"}


def test_bad_pick_value_rejected(env):
    client, SessionF = env
    ids = _group_match_ids(SessionF, 1)
    r = client.post("/api/match-picks", json={"picks": [{"match_id": ids[0], "pick": "both"}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_pick"


def test_unknown_match_ignored(env):
    client, _ = env
    r = client.post("/api/match-picks", json={"picks": [{"match_id": 10**9, "pick": "home"}]})
    assert r.status_code == 200, r.text
    assert r.json()["picks"] == []


def test_requires_auth_cookie():
    """With no session cookie (and no override), both routes return 401."""
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
        assert client.get("/api/match-picks/me").status_code == 401
        assert client.post("/api/match-picks", json={"picks": []}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_foreign_origin_rejected(env):
    """A state-changing request from a non-allowed Origin is blocked (CSRF guard)."""
    client, _ = env
    r = client.post(
        "/api/match-picks",
        json={"picks": []},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"


def test_no_store_cache_headers(env):
    """Match-pick responses are user-specific and must never be shared-cached."""
    client, _ = env
    assert client.get("/api/match-picks/me").headers["cache-control"] == "no-store"
    assert client.post("/api/match-picks", json={"picks": []}).headers["cache-control"] == "no-store"
