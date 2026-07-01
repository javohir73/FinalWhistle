"""Leaderboard ranking, percentile, and internal-account exclusion tests.

Regression coverage for the production incident where the only public bracket
(a smoke-test account) showed rank 3 with percentile -100: ranks were assigned
across ALL brackets (private included) while the percentile divided by the
public-only count.
"""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.cache import cache
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import AppUser, Bracket, BracketGroupPick, Match
from app.scoring import recompute_scores
from pipeline.ingest.wc26_structure import load_structure

ALLOWED_ORIGIN = "http://localhost:3000"


@pytest.fixture
def env():
    """Unauthenticated client + session factory, seeded with the WC26 structure."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)
    seed = TestingSession()
    load_structure(seed)
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
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN}), TestingSession
    app.dependency_overrides.clear()
    cache.clear()


def _group_match_ids(db, n):
    return [
        m.id
        for m in db.query(Match).filter(Match.stage == "group").order_by(Match.id).limit(n).all()
    ]


def _finish_home_win(db, match_id):
    m = db.get(Match, match_id)
    m.status, m.score_home, m.score_away = "finished", 2, 0


def _add_player(db, email, name, *, picks=(), visibility="public", internal=False):
    """User + bracket, with optional group picks as (match_id, outcome) pairs."""
    u = AppUser(email=email, password_hash="x", display_name=name, is_internal=internal)
    db.add(u)
    db.flush()
    b = Bracket(user_id=u.id, visibility=visibility, display_name=name)
    db.add(b)
    db.flush()
    for match_id, outcome in picks:
        db.add(BracketGroupPick(bracket_id=b.id, match_id=match_id, pick=outcome))
    return b


def test_ranks_are_contiguous_over_public_brackets_only(env):
    """Private brackets must not consume leaderboard ranks (prod showed a lone
    public row at rank 3 because two private brackets outscored it)."""
    client, SessionF = env
    db = SessionF()
    (mid,) = _group_match_ids(db, 1)
    _finish_home_win(db, mid)
    _add_player(db, "private@example.com", "Private Ace", picks=[(mid, "home")], visibility="private")
    _add_player(db, "pub1@example.com", "Pub One", picks=[(mid, "home")])
    _add_player(db, "pub2@example.com", "Pub Two", picks=[(mid, "away")])
    db.commit()
    recompute_scores(db)

    board = client.get("/api/leaderboard").json()
    assert [r["display_name"] for r in board] == ["Pub One", "Pub Two"]
    assert [r["rank"] for r in board] == [1, 2]

    db.expire_all()
    private = db.query(Bracket).filter_by(display_name="Private Ace").one()
    assert private.score.rank is None  # not on the leaderboard -> no rank
    db.close()


def test_internal_accounts_hidden_and_unranked(env):
    client, SessionF = env
    db = SessionF()
    (mid,) = _group_match_ids(db, 1)
    _finish_home_win(db, mid)
    _add_player(db, "smoke@internal.test", "Deploy Smoke", internal=True)
    _add_player(db, "real@example.com", "Real Player", picks=[(mid, "home")])
    db.commit()
    recompute_scores(db)

    board = client.get("/api/leaderboard").json()
    assert [r["display_name"] for r in board] == ["Real Player"]
    assert board[0]["rank"] == 1

    db.expire_all()
    smoke = db.query(Bracket).filter_by(display_name="Deploy Smoke").one()
    assert smoke.score.rank is None
    db.close()


def test_percentile_spans_public_population(env):
    client, SessionF = env
    db = SessionF()
    mids = _group_match_ids(db, 3)
    for mid in mids:
        _finish_home_win(db, mid)
    # 3 / 2 / 1 / 0 correct picks -> 9 / 6 / 3 / 0 points -> ranks 1..4.
    outcomes = [("home", "home", "home"), ("home", "home", "away"),
                ("home", "away", "away"), ("away", "away", "away")]
    for i, out in enumerate(outcomes, start=1):
        _add_player(db, f"p{i}@example.com", f"P{i}", picks=list(zip(mids, out)))
    db.commit()
    recompute_scores(db)
    db.close()

    board = client.get("/api/leaderboard").json()
    assert [r["rank"] for r in board] == [1, 2, 3, 4]
    assert [r["percentile"] for r in board] == [100, 75, 50, 25]


def test_percentile_omitted_for_single_entry(env):
    """A percentile over a population of one is meaningless — null, not 100."""
    client, SessionF = env
    db = SessionF()
    _add_player(db, "solo@example.com", "Solo")
    db.commit()
    recompute_scores(db)
    db.close()

    (row,) = client.get("/api/leaderboard").json()
    assert row["rank"] == 1
    assert row["percentile"] is None


def test_stale_rank_never_yields_negative_percentile(env):
    """Prod regression: a stored rank larger than the public population must
    null the percentile instead of emitting a negative value like -100."""
    client, SessionF = env
    db = SessionF()
    stale = _add_player(db, "stale@example.com", "Stale")
    _add_player(db, "fresh@example.com", "Fresh")
    db.commit()
    recompute_scores(db)
    db.expire_all()
    db.query(Bracket).filter_by(display_name="Stale").one().score.rank = 5
    db.commit()
    db.close()

    board = {r["display_name"]: r for r in client.get("/api/leaderboard").json()}
    assert board["Stale"]["percentile"] is None
    assert board["Fresh"]["percentile"] is not None
    assert all(r["percentile"] is None or 0 < r["percentile"] <= 100 for r in board.values())


def test_flag_internal_user_endpoint(env, monkeypatch):
    client, SessionF = env
    db = SessionF()
    _add_player(db, "smoke@example.com", "Deploy Smoke")
    db.commit()
    recompute_scores(db)
    db.close()
    assert len(client.get("/api/leaderboard").json()) == 1

    monkeypatch.setattr(settings, "recompute_token", "secret")
    assert client.post(
        "/api/internal/flag-internal-user",
        json={"email": "smoke@example.com"},
        headers={"X-Recompute-Token": "wrong"},
    ).status_code == 401
    assert client.post(
        "/api/internal/flag-internal-user",
        json={"email": "nobody@example.com"},
        headers={"X-Recompute-Token": "secret"},
    ).status_code == 404

    r = client.post(
        "/api/internal/flag-internal-user",
        json={"email": "Smoke@Example.com"},  # case-insensitive lookup
        headers={"X-Recompute-Token": "secret"},
    )
    assert r.status_code == 200 and r.json()["is_internal"] is True
    assert client.get("/api/leaderboard").json() == []

    r = client.post(
        "/api/internal/flag-internal-user",
        json={"email": "smoke@example.com", "internal": False},
        headers={"X-Recompute-Token": "secret"},
    )
    assert r.status_code == 200 and r.json()["is_internal"] is False
    assert len(client.get("/api/leaderboard").json()) == 1


def test_join_assigns_rank_immediately(env):
    """Joining the leaderboard rescores/reranks so the new row is never shown
    unranked (or with a rank stale against the new public population)."""
    client, SessionF = env
    db = SessionF()
    (mid,) = _group_match_ids(db, 1)
    db.add(AppUser(email="joiner@example.com", password_hash="x", display_name="Joiner"))
    db.commit()
    db.close()

    def override_user(db: Session = Depends(get_db)) -> AppUser:
        return db.query(AppUser).filter_by(email="joiner@example.com").one()

    app.dependency_overrides[get_current_user] = override_user

    r = client.post("/api/brackets", json={"group_picks": [{"match_id": mid, "pick": "home"}]})
    assert r.status_code == 200, r.text

    db = SessionF()
    _finish_home_win(db, mid)
    db.commit()
    db.close()

    r = client.post("/api/leaderboard/join", json={"display_name": "Joiner", "visibility": "public"})
    assert r.status_code == 200, r.text

    (row,) = client.get("/api/leaderboard").json()
    assert row["rank"] == 1
    assert row["total_points"] == 3
