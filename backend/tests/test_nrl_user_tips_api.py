"""POST /api/nrl/tips/submit, GET /api/nrl/tips/{mine,summary,leaderboard},
POST /api/nrl/tips/claim -- the beat-the-AI loop (design doc: NRL Round Tips,
Slice 2). Mirrors test_nrl_tips_api.py's fixture style (sport_* tables) plus
test_activity_api.py's Origin-header client for the device-keyed writes."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportPrediction, SportTeam, TipPlayer, UserTip

ALLOWED_ORIGIN = "http://localhost:3000"
DEVICE_A = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
DEVICE_B = "4fa85f64-5717-4562-b3fc-2c963f66afa7"


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_session()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, headers={"Origin": ALLOWED_ORIGIN}), TestingSession
    app.dependency_overrides.clear()


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, season, rnd, match_no, home, away, kickoff, **kw):
    m = SportMatch(sport="nrl", season=season, round=rnd, match_no=match_no,
                   kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                   status=kw.pop("status", "scheduled"), **kw)
    db.add(m)
    db.flush()
    return m


def _prediction(db, match, p_home=0.6, p_draw=0.01, created_at=None):
    p = SportPrediction(match_id=match.id, model_version="nrl-elo-v0.1",
                        created_at=created_at or (match.kickoff_utc - timedelta(days=1)),
                        p_home=p_home, p_draw=p_draw, p_away=round(1 - p_home - p_draw, 4),
                        expected_margin=4.0)
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# submit: kickoff lock + upsert-until-kickoff + margin bounds
# ---------------------------------------------------------------------------

def test_submit_before_kickoff_ok(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, 2026, 1, 1, storm, eels, kick)
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["tip"]["pick"] == "home"
    assert body["handle"]  # auto-generated, non-empty

    db2 = TestingSession()
    tip = db2.query(UserTip).one()
    assert tip.pick == "home"
    assert tip.points is None and tip.graded_at is None  # ungraded until the separate pass runs
    db2.close()


def test_submit_at_or_after_kickoff_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) - timedelta(seconds=1)  # already passed
    m = _match(db, 2026, 1, 1, storm, eels, kick)
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_locked"

    db2 = TestingSession()
    assert db2.query(UserTip).count() == 0
    db2.close()


def test_edit_after_kickoff_rejected(client):
    """A pick made before kickoff cannot be changed once kickoff passes."""
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) + timedelta(seconds=2)
    m = _match(db, 2026, 1, 1, storm, eels, kick)
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})
    assert r.status_code == 200, r.text

    # Push kickoff into the past directly (avoids a real sleep in the suite)
    # and try to change the pick -- must be rejected, never silently accepted.
    db2 = TestingSession()
    row = db2.query(SportMatch).filter_by(id=m.id).one()
    row.kickoff_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
    db2.commit()
    db2.close()

    r2 = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "away"})
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "match_locked"

    db3 = TestingSession()
    tip = db3.query(UserTip).one()
    assert tip.pick == "home"  # unchanged
    db3.close()


def test_upsert_changes_pick_until_kickoff(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, 2026, 1, 1, storm, eels, kick)
    db.commit()

    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})
    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "away"})
    assert r.status_code == 200
    assert r.json()["tip"]["pick"] == "away"

    db2 = TestingSession()
    assert db2.query(UserTip).count() == 1  # upsert, not a second row
    assert db2.query(UserTip).one().pick == "away"
    db2.close()


def test_margin_accepted_only_on_featured_match(client):
    """Featured match = earliest kickoff in the round."""
    c, TestingSession = client
    db = TestingSession()
    storm, eels, broncos, titans = (_team(db, n) for n in ("Storm", "Eels", "Broncos", "Titans"))
    now = datetime.now(timezone.utc)
    featured = _match(db, 2026, 1, 1, storm, eels, now + timedelta(hours=1))
    later = _match(db, 2026, 1, 2, broncos, titans, now + timedelta(days=1))
    db.commit()

    ok = c.post("/api/nrl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": featured.id, "pick": "home", "margin": 12,
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["tip"]["margin"] == 12

    rejected = c.post("/api/nrl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": later.id, "pick": "home", "margin": 6,
    })
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "margin_not_allowed"


def test_margin_out_of_bounds_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(hours=1))
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "pick": "home", "margin": 101,
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_margin"


def test_bad_pick_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(hours=1))
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "banana"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_pick"


def test_invalid_device_id_rejected_on_submit(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(hours=1))
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": "not-a-uuid", "match_id": m.id, "pick": "home"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"

    db2 = TestingSession()
    assert db2.query(TipPlayer).count() == 0  # rejected before any player row is created
    db2.close()


def test_foreign_origin_rejected_on_submit(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(hours=1))
    db.commit()

    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"},
              headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"


def test_unknown_match_404s(client):
    c, _ = client
    r = c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": 999, "pick": "home"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "match_not_found"


# ---------------------------------------------------------------------------
# GET /mine
# ---------------------------------------------------------------------------

def test_mine_shows_model_pick_and_your_tip_side_by_side(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, 2026, 1, 1, storm, eels, kick)
    _prediction(db, m, p_home=0.65)
    db.commit()

    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "away"})

    r = c.get("/api/nrl/tips/mine", params={"device_id": DEVICE_A, "season": 2026, "round": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["season"] == 2026 and body["round"] == 1
    assert body["handle"]
    match = body["matches"][0]
    assert match["home"] == "Storm" and match["away"] == "Eels"
    assert match["is_featured"] is True  # only match in the round
    assert match["model"]["pick"] == "home"
    assert match["your_tip"]["pick"] == "away"
    assert match["your_tip"]["points"] is None  # ungraded


def test_mine_unknown_device_returns_null_handle_no_tips(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.get("/api/nrl/tips/mine", params={"device_id": DEVICE_B, "season": 2026, "round": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["handle"] is None
    assert body["matches"][0]["your_tip"] is None


def test_mine_invalid_device_id_422s(client):
    c, _ = client
    r = c.get("/api/nrl/tips/mine", params={"device_id": "garbage", "season": 2026, "round": 1})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"


# ---------------------------------------------------------------------------
# GET /summary -- draw scoring rule (model's side, computed live)
# ---------------------------------------------------------------------------

def test_summary_applies_draw_rule_to_model_points(client):
    """The match drew; the model picked home, not draw. Comp-standard scoring
    says a draw scores EVERY tipper regardless of pick -- so the model's
    round points must still count this match, even though the model's own
    graded ledger (winner_correct, strict pick match) would not."""
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    kick = datetime.now(timezone.utc) - timedelta(days=1)
    m = _match(db, 2026, 1, 1, storm, eels, kick, status="finished", score_home=18, score_away=18)
    _prediction(db, m, p_home=0.7, created_at=kick - timedelta(days=1))
    db.flush()
    player = TipPlayer(device_id=DEVICE_A, handle="TestTipper1")
    db.add(player)
    db.flush()
    # Graded by the (separate) grading pass this builder doesn't own -- seeded
    # directly, same as test_sports_api.py seeds SportPredictionResult rows.
    db.add(UserTip(match_id=m.id, player_id=player.id, pick="away",
                   points=1, round_margin=None, graded_at=datetime.now(timezone.utc)))
    db.commit()

    r = c.get("/api/nrl/tips/summary", params={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["your_points"] == 1
    assert body["totals"]["model_points"] == 1  # draw -> model scores despite picking home
    assert body["rounds"][0] == {
        "season": 2026, "round": 1, "your_points": 1, "model_points": 1, "matches_played": 1,
    }


def test_summary_ungraded_tips_are_not_played_rounds(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})

    r = c.get("/api/nrl/tips/summary", params={"device_id": DEVICE_A})
    assert r.status_code == 200
    body = r.json()
    assert body["rounds"] == []
    assert body["totals"] == {"your_points": 0, "model_points": 0, "rounds_played": 0}


# ---------------------------------------------------------------------------
# GET /leaderboard -- participation gate + ranking (points desc, margin asc)
# ---------------------------------------------------------------------------

def _seed_leaderboard_round(db, n_players, points_and_margins):
    """points_and_margins: list of (points, round_margin) for the featured
    match tip of each of n_players devices."""
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 5, 1, storm, eels,
              datetime.now(timezone.utc) - timedelta(days=1), status="finished",
              score_home=20, score_away=10)
    db.flush()
    for i in range(n_players):
        p = TipPlayer(device_id=f"aaaaaaaa-0000-4000-8000-{i:012d}", handle=f"Player{i}")
        db.add(p)
        db.flush()
        points, margin = points_and_margins[i]
        db.add(UserTip(match_id=m.id, player_id=p.id, pick="home",
                       points=points, round_margin=margin, graded_at=datetime.now(timezone.utc)))
    db.commit()
    return m


def test_leaderboard_hidden_below_ten_participants(client):
    c, TestingSession = client
    db = TestingSession()
    _seed_leaderboard_round(db, 9, [(1, i) for i in range(9)])

    r = c.get("/api/nrl/tips/leaderboard", params={"season": 2026, "round": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_count"] == 9
    assert body["entries"] == []


def test_leaderboard_visible_at_ten_ranked_points_then_margin(client):
    c, TestingSession = client
    db = TestingSession()
    # 10 players: player 0 has the most points; players 1-2 tie on points but
    # player 2's margin is closer (better tiebreak).
    points_and_margins = [(1, 5)] + [(0, 8), (0, 3)] + [(0, None)] * 7
    _seed_leaderboard_round(db, 10, points_and_margins)

    r = c.get("/api/nrl/tips/leaderboard", params={"season": 2026, "round": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_count"] == 10
    entries = body["entries"]
    assert len(entries) == 10
    assert entries[0]["handle"] == "Player0" and entries[0]["points"] == 1
    assert entries[1]["handle"] == "Player2" and entries[1]["round_margin"] == 3
    assert entries[2]["handle"] == "Player1" and entries[2]["round_margin"] == 8
    assert all("device_id" not in e for e in entries)  # never exposed


def test_leaderboard_unknown_round_404s(client):
    c, _ = client
    r = c.get("/api/nrl/tips/leaderboard", params={"season": 2026, "round": 99})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /claim -- idempotency + merge conflict rule
# ---------------------------------------------------------------------------

def _register(c, email):
    r = c.post("/api/auth/register", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_claim_attaches_device_with_no_prior_account_player(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})

    _register(c, "tipper1@example.com")
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["claimed_tips"] == 1

    db2 = TestingSession()
    player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    assert player.user_id is not None
    db2.close()


def test_claim_is_idempotent_on_repeat_call(client):
    c, TestingSession = client
    db = TestingSession()
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    m = _match(db, 2026, 1, 1, storm, eels, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m.id, "pick": "home"})

    _register(c, "tipper2@example.com")
    first = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    second = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["claimed_tips"] == 1  # not double-counted

    db2 = TestingSession()
    assert db2.query(TipPlayer).count() == 1
    db2.close()


def test_claim_unknown_device_is_a_no_op_success(client):
    c, _ = client
    _register(c, "tipper3@example.com")
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "handle": None, "claimed_tips": 0}


def test_claim_merges_second_device_keeping_accounts_tip_on_conflict(client):
    """The account already claimed device A (with a pick for match 1). It then
    claims device B, which has picks for match 1 (conflicting) AND match 2
    (no conflict). The account's own match-1 pick must survive unchanged;
    match 2 must move over."""
    c, TestingSession = client
    db = TestingSession()
    storm, eels, broncos, titans = (_team(db, n) for n in ("Storm", "Eels", "Broncos", "Titans"))
    now = datetime.now(timezone.utc)
    m1 = _match(db, 2026, 1, 1, storm, eels, now + timedelta(days=1))
    m2 = _match(db, 2026, 1, 2, broncos, titans, now + timedelta(days=1))
    db.commit()

    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m1.id, "pick": "home"})
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_B, "match_id": m1.id, "pick": "away"})
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_B, "match_id": m2.id, "pick": "home"})

    _register(c, "tipper4@example.com")
    c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_B})
    assert r.status_code == 200, r.text
    assert r.json()["claimed_tips"] == 1  # only match 2 moved; match 1 was a conflict

    db2 = TestingSession()
    account_player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    assert account_player.user_id is not None
    tips = {t.match_id: t.pick for t in db2.query(UserTip).filter_by(player_id=account_player.id).all()}
    assert tips[m1.id] == "home"  # account's own pick wins, not overwritten by device B's "away"
    assert tips[m2.id] == "home"  # non-conflicting pick moved over
    # Device B's player row is gone -- its tips were fully migrated/dropped.
    assert db2.query(TipPlayer).filter_by(device_id=DEVICE_B).one_or_none() is None
    db2.close()


def test_claim_invalid_device_id_rejected(client):
    c, _ = client
    _register(c, "tipper5@example.com")
    r = c.post("/api/nrl/tips/claim", json={"device_id": "garbage"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"


def test_claim_requires_auth(client):
    c, _ = client
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    assert r.status_code == 401
