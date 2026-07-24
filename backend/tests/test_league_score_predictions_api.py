"""POST /api/leagues/{league}/tips/submit, GET .../{mine,summary,leaderboard,
leaderboard/season,share/{matchweek}/{handle}}, and POST /api/nrl/tips/claim's
league-predictions passthrough -- League Score Predictions design doc
(2026-07-24). Mirrors test_nrl_user_tips_api.py's fixture style (direct-seed
Tournament/Team/Match/Prediction, per test_ledger_separation_api.py) plus its
Origin-header client for the device-keyed writes."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import league_score_predictions as lsp
from app.db import Base, get_db
from app.main import app
from app.models import LeagueScorePrediction, Match, Prediction, SportMatch, SportTeam, Team, Tournament, TipPlayer, UserTip

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


def _epl(db):
    t = Tournament(name="Premier League 2026-27", year=2026, home_advantage_mode="home")
    db.add(t)
    db.flush()
    return t


def _tournament(db, name):
    """Generic version of _epl for Phase 2's other two leagues -- same shape,
    just a caller-supplied name, since _epl's 30+ existing callers shouldn't
    need to change."""
    t = Tournament(name=name, year=2026, home_advantage_mode="home")
    db.add(t)
    db.flush()
    return t


def _team(db, name):
    t = Team(name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, tournament, home, away, matchweek, kickoff, **kw):
    m = Match(
        tournament_id=tournament.id, team_home_id=home.id, team_away_id=away.id,
        stage="group", matchweek=matchweek, kickoff_utc=kickoff,
        status=kw.pop("status", "scheduled"), **kw,
    )
    db.add(m)
    db.flush()
    return m


def _prediction(db, match, pred_home, pred_away, created_at=None, is_shadow=False, model_version="poisson-elo-club-v0.1"):
    p = Prediction(
        match_id=match.id, model_version=model_version,
        created_at=created_at or (match.kickoff_utc - timedelta(days=1)),
        prob_home_win=0.5, prob_draw=0.25, prob_away_win=0.25,
        predicted_score_home=pred_home, predicted_score_away=pred_away, is_shadow=is_shadow,
    )
    db.add(p)
    db.flush()
    return p


def _register(c, email):
    r = c.post("/api/auth/register", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# league resolution
# ---------------------------------------------------------------------------

def test_unknown_league_code_404s(client):
    c, _ = client
    r = c.get("/api/leagues/bogus/tips/leaderboard/season")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "league_not_found"


@pytest.mark.parametrize("league", ["epl", "laliga", "bundesliga"])
def test_registered_league_with_no_data_loaded_is_inactive_404(client, league):
    """All three Phase 2 codes are registered in _LEAGUE_TOURNAMENT_NAMES
    (derived from pipeline.leagues.LEAGUES) regardless of whether
    pipeline.leagues.ACTIVE_LEAGUES has actually ingested them yet -- a
    registered-but-not-yet-loaded league (no Tournament row in this DB) must
    404 league_inactive, never league_not_found (that code is reserved for a
    typo'd/unregistered code, see test_unknown_league_code_404s above)."""
    c, _ = client
    r = c.get(f"/api/leagues/{league}/tips/leaderboard/season")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "league_inactive"


# ---------------------------------------------------------------------------
# submit: kickoff lock + bounds + upsert-until-kickoff
# ---------------------------------------------------------------------------

def test_submit_before_kickoff_ok(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, epl, ars, che, 1, kick)
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 2, "predicted_away": 1,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["prediction"]["predicted_home"] == 2
    assert body["prediction"]["predicted_away"] == 1
    assert body["handle"]

    db2 = TestingSession()
    pred = db2.query(LeagueScorePrediction).one()
    assert (pred.predicted_home, pred.predicted_away) == (2, 1)
    assert pred.points is None and pred.graded_at is None  # ungraded until the (pipeline-owned) pass runs
    db2.close()


def test_submit_at_or_after_kickoff_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) - timedelta(seconds=1)
    m = _match(db, epl, ars, che, 1, kick)
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 1, "predicted_away": 0,
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_locked"

    db2 = TestingSession()
    assert db2.query(LeagueScorePrediction).count() == 0
    db2.close()


def test_edit_after_kickoff_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) + timedelta(seconds=2)
    m = _match(db, epl, ars, che, 1, kick)
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 1, "predicted_away": 1,
    })
    assert r.status_code == 200, r.text

    db2 = TestingSession()
    row = db2.query(Match).filter_by(id=m.id).one()
    row.kickoff_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
    db2.commit()
    db2.close()

    r2 = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 3, "predicted_away": 0,
    })
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "match_locked"

    db3 = TestingSession()
    pred = db3.query(LeagueScorePrediction).one()
    assert (pred.predicted_home, pred.predicted_away) == (1, 1)  # unchanged
    db3.close()


def test_submit_upserts_before_kickoff(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, epl, ars, che, 1, kick)
    db.commit()

    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 2, "predicted_away": 2,
    })
    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 3, "predicted_away": 1,
    })
    assert r.status_code == 200, r.text

    db2 = TestingSession()
    assert db2.query(LeagueScorePrediction).count() == 1  # same row, not a second insert
    pred = db2.query(LeagueScorePrediction).one()
    assert (pred.predicted_home, pred.predicted_away) == (3, 1)
    db2.close()


@pytest.mark.parametrize("home,away", [(-1, 0), (0, -1), (16, 0), (0, 16)])
def test_submit_bad_score_bounds_rejected(client, home, away):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": home, "predicted_away": away,
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_score"


def test_submit_score_bounds_0_and_15_are_valid(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 0, "predicted_away": 15,
    })
    assert r.status_code == 200, r.text


def test_submit_match_from_other_tournament_not_found(client):
    """Cross-league isolation at the write path: a match belonging to a
    DIFFERENT tournament than the one `epl` resolves to must 404, not silently
    accept a prediction against it."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    other = Tournament(name="La Liga 2026-27", year=2026, home_advantage_mode="home")
    db.add(other)
    db.flush()
    rma, bar = _team(db, "Real Madrid"), _team(db, "Barcelona")
    m = _match(db, other, rma, bar, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 1, "predicted_away": 0,
    })
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "match_not_found"


def test_submit_invalid_device_id_rejected(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    db.commit()

    r = c.post("/api/leagues/epl/tips/submit", json={
        "device_id": "garbage", "match_id": 1, "predicted_home": 1, "predicted_away": 0,
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_device_id"


# ---------------------------------------------------------------------------
# GET mine
# ---------------------------------------------------------------------------

def test_mine_shows_model_scoreline_and_your_prediction(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, epl, ars, che, 3, kick)
    _prediction(db, m, 2, 0)
    db.commit()

    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 1, "predicted_away": 1,
    })

    r = c.get("/api/leagues/epl/tips/mine", params={"device_id": DEVICE_A, "matchweek": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matchweek"] == 3
    row = body["matches"][0]
    assert row["model"] == {"predicted_home": 2, "predicted_away": 0, "model_version": "poisson-elo-club-v0.1"}
    assert row["your_prediction"]["predicted_home"] == 1
    assert row["your_prediction"]["predicted_away"] == 1
    assert row["your_prediction"]["points"] is None


def test_mine_ignores_shadow_prediction_twin(client):
    """Regression: generate_predictions writes ONE production row
    (is_shadow=False) plus shadow twins (odds/availability/offsets/rest) per
    match, all sharing created_at (same pipeline transaction) but the shadow
    twin lands with a HIGHER id, since it's written after production. Without
    filtering is_shadow, _kickoff_locked_prediction's created_at desc, id desc
    tiebreak would pick the shadow twin -- exactly what this proves doesn't
    happen, on a twin with a DIFFERENT scoreline so a wrong pick is visible."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    kick = datetime.now(timezone.utc) + timedelta(days=1)
    m = _match(db, epl, ars, che, 3, kick)
    same_created_at = kick - timedelta(days=1)
    _prediction(db, m, 2, 0, created_at=same_created_at, is_shadow=False)
    _prediction(db, m, 3, 3, created_at=same_created_at, is_shadow=True,
                model_version="poisson-elo-club-v0.1-shadow")  # written after -- higher id, same created_at
    db.commit()

    r = c.get("/api/leagues/epl/tips/mine", params={"device_id": DEVICE_A, "matchweek": 3})
    assert r.status_code == 200, r.text
    row = r.json()["matches"][0]
    assert row["model"] == {"predicted_home": 2, "predicted_away": 0, "model_version": "poisson-elo-club-v0.1"}


def test_mine_defaults_to_current_matchweek(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che, bha, whu = (_team(db, n) for n in ("Arsenal", "Chelsea", "Brighton", "West Ham"))
    now = datetime.now(timezone.utc)
    _match(db, epl, ars, che, 1, now - timedelta(days=7), status="finished", score_home=2, score_away=1)
    upcoming = _match(db, epl, bha, whu, 2, now + timedelta(days=1))
    db.commit()

    r = c.get("/api/leagues/epl/tips/mine", params={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    assert r.json()["matchweek"] == 2
    assert r.json()["matches"][0]["id"] == upcoming.id


def test_mine_matchweek_not_found_404(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.get("/api/leagues/epl/tips/mine", params={"device_id": DEVICE_A, "matchweek": 99})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "matchweek_not_found"


def test_mine_no_matchweek_data_404(client):
    """Tournament is loaded, but no matches have a matchweek stamped yet
    (ingestion write-side hasn't run) -- distinct from matchweek_not_found."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    _match(db, epl, ars, che, None, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    r = c.get("/api/leagues/epl/tips/mine", params={"device_id": DEVICE_A})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "no_matchweek_data"


# ---------------------------------------------------------------------------
# GET summary -- zero-state, scoring, streaks, best matchweek, AI parity
# ---------------------------------------------------------------------------

def test_summary_zero_state_unknown_device(client):
    c, TestingSession = client
    db = TestingSession()
    _epl(db)
    db.commit()

    r = c.get("/api/leagues/epl/tips/summary", params={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle"] is None
    assert body["matchweeks"] == []
    assert body["totals"] == {"your_points": 0, "model_points": 0, "matchweeks_played": 0}
    assert body["current_streak"] == 0 and body["best_streak"] == 0 and body["best_matchweek"] is None


@pytest.mark.parametrize(
    "pred_home,pred_away,actual_home,actual_away,expected_points,expected_exact",
    [
        (2, 1, 2, 1, 5, True),   # exact score
        (0, 0, 0, 0, 5, True),   # exact 0-0
        (2, 0, 3, 1, 2, False),  # correct result direction (home win), wrong score
        (1, 1, 0, 0, 2, False),  # correct result direction (draw), wrong score
        (1, 0, 0, 1, 0, False),  # wrong direction entirely
        (1, 1, 2, 1, 0, False),  # predicted draw, actual home win -- a miss
    ],
)
def test_score_prediction_matrix(pred_home, pred_away, actual_home, actual_away, expected_points, expected_exact):
    points, exact = lsp._score_prediction(pred_home, pred_away, actual_home, actual_away)
    assert (points, exact) == (expected_points, expected_exact)


def test_summary_points_streaks_and_best_matchweek(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che, bha, whu = (_team(db, n) for n in ("Arsenal", "Chelsea", "Brighton", "West Ham"))
    now = datetime.now(timezone.utc)

    m1 = _match(db, epl, ars, che, 1, now - timedelta(days=14), status="finished", score_home=2, score_away=1)
    m2 = _match(db, epl, bha, whu, 2, now - timedelta(days=7), status="finished", score_home=0, score_away=0)
    db.flush()
    player = TipPlayer(device_id=DEVICE_A, handle="TestHandle1")
    db.add(player)
    db.flush()
    # Matchweek 1: exact score -> 5 points.
    db.add(LeagueScorePrediction(
        tournament_id=epl.id, match_id=m1.id, player_id=player.id,
        predicted_home=2, predicted_away=1, updated_at=now - timedelta(days=15),
        points=5, exact=True, graded_at=now,
    ))
    # Matchweek 2: wrong scoreline, wrong direction -> 0 points (streak reset).
    db.add(LeagueScorePrediction(
        tournament_id=epl.id, match_id=m2.id, player_id=player.id,
        predicted_home=1, predicted_away=0, updated_at=now - timedelta(days=8),
        points=0, exact=False, graded_at=now,
    ))
    db.commit()

    r = c.get("/api/leagues/epl/tips/summary", params={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle"] == "TestHandle1"
    assert body["totals"] == {"your_points": 5, "model_points": 0, "matchweeks_played": 2}
    assert body["current_streak"] == 0  # the most recent graded matchweek scored 0
    assert body["best_streak"] == 1
    assert body["best_matchweek"] == {"matchweek": 1, "points": 5}


def test_summary_model_points_parity_with_score_prediction_rule(client):
    """AI scoring parity: when a player's prediction is IDENTICAL to the
    model's frozen scoreline, the two can only tie -- proving /summary's
    live model-points computation uses the exact same rule
    (_score_prediction) a grading pass would use for the player's row."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    now = datetime.now(timezone.utc)
    m = _match(db, epl, ars, che, 5, now - timedelta(days=1), status="finished", score_home=2, score_away=1)
    _prediction(db, m, pred_home=2, pred_away=0, created_at=now - timedelta(days=2))
    db.flush()

    player = TipPlayer(device_id=DEVICE_A, handle="ParityTester")
    db.add(player)
    db.flush()

    # The player copies the AI's exact scoreline (2-0) -- both are wrong vs
    # the 2-1 actual result in the same way, so both must score identically.
    expected_points, expected_exact = lsp._score_prediction(2, 0, 2, 1)
    db.add(LeagueScorePrediction(
        tournament_id=epl.id, match_id=m.id, player_id=player.id,
        predicted_home=2, predicted_away=0, updated_at=now - timedelta(days=2),
        points=expected_points, exact=expected_exact, graded_at=now,
    ))
    db.commit()

    body = c.get("/api/leagues/epl/tips/summary", params={"device_id": DEVICE_A}).json()
    week = body["matchweeks"][0]
    assert week["your_points"] == week["model_points"] == expected_points


# ---------------------------------------------------------------------------
# leaderboard: matchweek + season -- gate and exact-count tiebreak
# ---------------------------------------------------------------------------

def _seed_leaderboard_players(db, epl, match, n, points_and_exact):
    """n players with predictions on `match`; points_and_exact maps player
    index -> (points, exact) already-graded state."""
    players = []
    for i in range(n):
        p = TipPlayer(device_id=f"11111111-1111-4111-8111-11111111{i:04d}", handle=f"Player{i}")
        db.add(p)
        db.flush()
        points, exact = points_and_exact.get(i, (0, False))
        db.add(LeagueScorePrediction(
            tournament_id=epl.id, match_id=match.id, player_id=p.id,
            predicted_home=1, predicted_away=0, updated_at=datetime.now(timezone.utc),
            points=points, exact=exact, graded_at=datetime.now(timezone.utc) if points or exact else None,
        ))
        players.append(p)
    return players


def test_leaderboard_below_gate_hides_entries_but_shows_count(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) - timedelta(days=1),
               status="finished", score_home=2, score_away=1)
    db.flush()
    _seed_leaderboard_players(db, epl, m, 5, {})
    db.commit()

    r = c.get("/api/leagues/epl/tips/leaderboard", params={"matchweek": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_count"] == 5
    assert body["entries"] == []


def test_leaderboard_gate_and_exact_count_tiebreak(client):
    """Two players tie on total points (10) across multiple matches but
    differ in exact-hit count: ZebraExactTwo reaches 10 via two exact scores
    (exact_count=2), AlphaResultFive reaches the SAME 10 via five
    result-only 2-pointers (exact_count=0). Handles are deliberately
    alphabetized the OPPOSITE way round from the correct ranking -- if the
    -exact_count term were dropped (sorting on points+handle alone, e.g.
    key=lambda e: (-e["points"], e["handle"])), AlphaResultFive would sort
    first on points+handle alone, so this fails loudly instead of passing
    by accident the way the single-match, single-tied-pair version of this
    test used to (both seeded players had equal points AND equal exact_count,
    so the assertion was satisfied by handle order alone)."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    now = datetime.now(timezone.utc) - timedelta(days=1)
    matches = [
        _match(db, epl, ars, che, 1, now, status="finished", score_home=2, score_away=1)
        for _ in range(5)
    ]
    db.flush()

    def _player(i, handle):
        p = TipPlayer(device_id=f"11111111-1111-4111-8111-11111111{i:04d}", handle=handle)
        db.add(p)
        db.flush()
        return p

    def _pred(player, match, points, exact):
        db.add(LeagueScorePrediction(
            tournament_id=epl.id, match_id=match.id, player_id=player.id,
            predicted_home=1, predicted_away=0, updated_at=now,
            points=points, exact=exact, graded_at=now,
        ))

    exact_player = _player(0, "ZebraExactTwo")
    _pred(exact_player, matches[0], 5, True)
    _pred(exact_player, matches[1], 5, True)

    result_player = _player(1, "AlphaResultFive")
    for m in matches:
        _pred(result_player, m, 2, False)

    # 8 more players clear the >=10 gate with zero points -- they must rank
    # below both and never touch the comparison above. They're all fully
    # tied on points+exact, so their relative order still proves the
    # handle-asc fallback for a genuine full tie.
    for i in range(2, 10):
        p = _player(i, f"Filler{i}")
        _pred(p, matches[0], 0, False)

    db.commit()

    r = c.get("/api/leagues/epl/tips/leaderboard", params={"matchweek": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_count"] == 10
    top_two = [(e["handle"], e["points"], e["exact_count"]) for e in body["entries"][:2]]
    assert top_two == [("ZebraExactTwo", 10, 2), ("AlphaResultFive", 10, 0)]
    next_two_handles = [e["handle"] for e in body["entries"][2:4]]
    assert next_two_handles == ["Filler2", "Filler3"]  # full tie on points+exact -> handle asc


def test_leaderboard_matchweek_not_found_404(client):
    c, TestingSession = client
    db = TestingSession()
    _epl(db)
    db.commit()

    r = c.get("/api/leagues/epl/tips/leaderboard", params={"matchweek": 1})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "matchweek_not_found"


def test_leaderboard_season_only_counts_graded_players(client):
    """Season board population is GRADED-only (mirrors NRL's
    submitted-vs-graded distinction) -- a player who only ever submitted an
    ungraded prediction must not count toward the season gate."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.flush()
    # 10 players submit but NONE are graded yet (match hasn't kicked off).
    for i in range(10):
        p = TipPlayer(device_id=f"22222222-2222-4222-8222-22222222{i:04d}", handle=f"Ungraded{i}")
        db.add(p)
        db.flush()
        db.add(LeagueScorePrediction(
            tournament_id=epl.id, match_id=m.id, player_id=p.id,
            predicted_home=1, predicted_away=0, updated_at=datetime.now(timezone.utc),
        ))
    db.commit()

    r = c.get("/api/leagues/epl/tips/leaderboard/season")
    assert r.status_code == 200, r.text
    assert r.json()["participant_count"] == 0
    assert r.json()["entries"] == []


def test_leaderboard_season_gate_and_exact_count_tiebreak(client):
    """Same tiebreak proof as test_leaderboard_gate_and_exact_count_tiebreak,
    for /leaderboard/season -- which had NO tiebreak coverage at all before
    (the design doc's "points desc, then exact-count desc" applies here too,
    scored across every graded matchweek in the tournament instead of one)."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    now = datetime.now(timezone.utc) - timedelta(days=1)
    matches = [
        _match(db, epl, ars, che, week, now, status="finished", score_home=2, score_away=1)
        for week in range(1, 6)
    ]
    db.flush()

    def _player(i, handle):
        p = TipPlayer(device_id=f"33333333-3333-4333-8333-33333333{i:04d}", handle=handle)
        db.add(p)
        db.flush()
        return p

    def _pred(player, match, points, exact):
        db.add(LeagueScorePrediction(
            tournament_id=epl.id, match_id=match.id, player_id=player.id,
            predicted_home=1, predicted_away=0, updated_at=now,
            points=points, exact=exact, graded_at=now,
        ))

    # Same alphabetized-opposite handle trick as the weekly-board test, so a
    # dropped -exact_count term (falling back to points+handle) sorts these
    # the wrong way round and fails.
    exact_player = _player(0, "ZebraExactTwo")
    _pred(exact_player, matches[0], 5, True)
    _pred(exact_player, matches[1], 5, True)

    result_player = _player(1, "AlphaResultFive")
    for m in matches:
        _pred(result_player, m, 2, False)

    for i in range(2, 10):
        p = _player(i, f"Filler{i}")
        _pred(p, matches[0], 0, False)

    db.commit()

    r = c.get("/api/leagues/epl/tips/leaderboard/season")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_count"] == 10
    top_two = [(e["handle"], e["points"], e["exact_count"]) for e in body["entries"][:2]]
    assert top_two == [("ZebraExactTwo", 10, 2), ("AlphaResultFive", 10, 0)]


# ---------------------------------------------------------------------------
# share: graded-only, 404 matrix, no leak of pre-kickoff picks
# ---------------------------------------------------------------------------

def test_share_unknown_handle_404(client):
    c, TestingSession = client
    db = TestingSession()
    _epl(db)
    db.commit()

    r = c.get("/api/leagues/epl/tips/share/1/NoSuchHandle")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "share_not_found"


def test_share_ungraded_matchweek_404_never_leaks_prekickoff_pick(client):
    """A device predicts before kickoff; the match hasn't finished (or been
    graded) yet -- share must 404, never surface the pre-kickoff pick."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 4, "predicted_away": 0,
    })
    db2 = TestingSession()
    player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    handle = player.handle
    db2.close()

    r = c.get(f"/api/leagues/epl/tips/share/1/{handle}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "share_not_found"


def test_share_returns_graded_summary(client):
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    now = datetime.now(timezone.utc)
    m = _match(db, epl, ars, che, 1, now - timedelta(days=1), status="finished", score_home=2, score_away=1)
    _prediction(db, m, pred_home=1, pred_away=1, created_at=now - timedelta(days=2))
    db.flush()
    player = TipPlayer(device_id=DEVICE_A, handle="ShareTester")
    db.add(player)
    db.flush()
    db.add(LeagueScorePrediction(
        tournament_id=epl.id, match_id=m.id, player_id=player.id,
        predicted_home=2, predicted_away=1, updated_at=now - timedelta(days=2),
        points=5, exact=True, graded_at=now,
    ))
    db.commit()

    r = c.get("/api/leagues/epl/tips/share/1/ShareTester")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle_display"] == "ShareTester"
    assert body["player_points"] == 5
    assert body["model_points"] == 0  # model predicted 1-1, actual was 2-1 -- a miss
    assert body["matchweek_complete"] is True
    assert "device_id" not in body and "device" not in str(body).lower()


# ---------------------------------------------------------------------------
# cross-league isolation
# ---------------------------------------------------------------------------

def _fill_graded_players(db, tournament, match, n, offset):
    """n more graded (points=0, exact=False) players on `match`, so a
    leaderboard's >=_LEADERBOARD_MIN_PARTICIPANTS reveal gate can be cleared
    without the real test subject's own row. Distinct `offset` per league
    keeps device_id unique across the three leagues seeded in the same test
    (unlike _seed_leaderboard_players, which is single-tournament and reuses
    the same device_id family every call). graded_at is always set (unlike
    _seed_leaderboard_players' points-or-exact-gated version) since the
    season leaderboard's population filter is graded-only."""
    now = datetime.now(timezone.utc)
    for i in range(n):
        idx = offset + i
        p = TipPlayer(device_id=f"99999999-9999-4999-8999-{idx:012d}", handle=f"Filler{idx}")
        db.add(p)
        db.flush()
        db.add(LeagueScorePrediction(
            tournament_id=tournament.id, match_id=match.id, player_id=p.id,
            predicted_home=1, predicted_away=0, updated_at=now,
            points=0, exact=False, graded_at=now,
        ))


def test_three_league_isolation_matrix(client):
    """Phase 2: epl/laliga/bundesliga are simultaneously live, real registry
    entries (no monkeypatch needed, unlike the Phase-1-era two-league version
    of this test) -- predictions (summary/mine), both leaderboards (weekly +
    season), and shares must never bleed across tournaments, even for the
    SAME device/handle predicting perfectly in all three."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    laliga = _tournament(db, "La Liga 2026-27")
    bundesliga = _tournament(db, "Bundesliga 2026-27")
    now = datetime.now(timezone.utc)

    fixtures = [
        ("epl", epl, "Arsenal", "Chelsea", 0),
        ("laliga", laliga, "Real Madrid", "Barcelona", 100),
        ("bundesliga", bundesliga, "Bayern Munich", "Dortmund", 200),
    ]
    leagues = {}
    for code, tournament, home_name, away_name, offset in fixtures:
        home, away = _team(db, home_name), _team(db, away_name)
        m = _match(db, tournament, home, away, 1, now - timedelta(days=1),
                   status="finished", score_home=2, score_away=1)
        leagues[code] = {"tournament": tournament, "match": m, "home": home_name}

    # One player, one shared handle, predicts perfectly in EVERY league --
    # tip_players isn't league-scoped, so a shared identity across leagues is
    # exactly the case where isolation could accidentally leak.
    player = TipPlayer(device_id=DEVICE_A, handle="TriLeagueTester")
    db.add(player)
    db.flush()
    for code, data in leagues.items():
        db.add(LeagueScorePrediction(
            tournament_id=data["tournament"].id, match_id=data["match"].id, player_id=player.id,
            predicted_home=2, predicted_away=1, updated_at=now - timedelta(days=2),
            points=5, exact=True, graded_at=now,
        ))
    # 9 more graded players per league clear both leaderboards' reveal gate
    # (>=10 total) without inflating another league's count.
    for code, _, _, _, offset in fixtures:
        _fill_graded_players(db, leagues[code]["tournament"], leagues[code]["match"], 9, offset)
    db.commit()

    for code, data in leagues.items():
        summary = c.get(f"/api/leagues/{code}/tips/summary", params={"device_id": DEVICE_A}).json()
        assert summary["league"] == code
        assert summary["totals"] == {"your_points": 5, "model_points": 0, "matchweeks_played": 1}

        mine = c.get(f"/api/leagues/{code}/tips/mine", params={"device_id": DEVICE_A, "matchweek": 1}).json()
        assert mine["league"] == code
        assert [row["home"] for row in mine["matches"]] == [data["home"]]

        weekly = c.get(f"/api/leagues/{code}/tips/leaderboard", params={"matchweek": 1}).json()
        assert weekly["league"] == code
        assert weekly["participant_count"] == 10  # this league's 10, never the other leagues' 20 more

        season = c.get(f"/api/leagues/{code}/tips/leaderboard/season").json()
        assert season["participant_count"] == 10

        share = c.get(f"/api/leagues/{code}/tips/share/1/TriLeagueTester").json()
        assert share["league"] == code
        assert share["handle_display"] == "TriLeagueTester"
        assert share["player_points"] == 5
        assert share["matchweek_complete"] is True


# ---------------------------------------------------------------------------
# POST /api/nrl/tips/claim -- league predictions passthrough (identity reuse)
# ---------------------------------------------------------------------------

def test_claim_simple_path_carries_league_predictions(client):
    """The simple-claim branch (no prior account player) needs no
    sport-specific logic -- it just reassigns tip_players.user_id, so a
    device's league predictions are implicitly claimed too."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che = _team(db, "Arsenal"), _team(db, "Chelsea")
    m = _match(db, epl, ars, che, 1, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()

    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m.id, "predicted_home": 2, "predicted_away": 1,
    })

    _register(c, "leaguetipper1@example.com")
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    assert r.status_code == 200, r.text

    db2 = TestingSession()
    player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    assert player.user_id is not None
    pred = db2.query(LeagueScorePrediction).filter_by(player_id=player.id).one()
    assert (pred.predicted_home, pred.predicted_away) == (2, 1)  # untouched, still queryable
    db2.close()


def test_claim_merge_conflict_reassigns_league_predictions_without_crashing(client):
    """Regression for the recon-flagged bug: the merge branch used to touch
    ONLY user_tips before deleting device_player, which would either FK-
    violate or silently drop league_score_predictions rows once a device had
    played both sports and hit the two-existing-players merge path. This
    proves the second reassign/dedupe loop fixes it: the account's own
    prediction survives on conflict, the non-conflicting one moves over, and
    claimed_tips (NRL-only) is unaffected."""
    c, TestingSession = client
    db = TestingSession()
    epl = _epl(db)
    ars, che, bha, whu = (_team(db, n) for n in ("Arsenal", "Chelsea", "Brighton", "West Ham"))
    now = datetime.now(timezone.utc)
    m1 = _match(db, epl, ars, che, 1, now + timedelta(days=1))
    m2 = _match(db, epl, bha, whu, 1, now + timedelta(days=1))
    # Also give device A an NRL tip, so claimed_tips has a real NRL-only count
    # to assert against.
    storm, eels = SportTeam(sport="nrl", name="Storm"), SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels])
    db.flush()
    nrl_match = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                           home_team_id=storm.id, away_team_id=eels.id,
                           kickoff_utc=now + timedelta(days=1), status="scheduled")
    db.add(nrl_match)
    db.commit()

    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": nrl_match.id, "pick": "home"})
    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_A, "match_id": m1.id, "predicted_home": 2, "predicted_away": 0,
    })
    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_B, "match_id": m1.id, "predicted_home": 0, "predicted_away": 3,
    })
    c.post("/api/leagues/epl/tips/submit", json={
        "device_id": DEVICE_B, "match_id": m2.id, "predicted_home": 1, "predicted_away": 1,
    })

    _register(c, "leaguetipper2@example.com")
    c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})
    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_B})
    assert r.status_code == 200, r.text
    assert r.json()["claimed_tips"] == 0  # NRL-only count: device B had no NRL tips

    db2 = TestingSession()
    account_player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    preds = {
        p.match_id: (p.predicted_home, p.predicted_away)
        for p in db2.query(LeagueScorePrediction).filter_by(player_id=account_player.id).all()
    }
    assert preds[m1.id] == (2, 0)  # account's own prediction wins the conflict, untouched
    assert preds[m2.id] == (1, 1)  # non-conflicting prediction moved over
    assert db2.query(TipPlayer).filter_by(device_id=DEVICE_B).one_or_none() is None  # merged away
    assert db2.query(UserTip).filter_by(player_id=account_player.id).count() == 1  # NRL tip intact
    db2.close()


def test_claim_merge_conflict_degrades_gracefully_when_league_table_missing(client):
    """Regression for the deploy-sequencing finding: league_score_predictions
    ships in its own migration (b7c8d9e0f1a2), applied to prod via a SEPARATE
    refresh.yml dispatch AFTER this already-live claim code deploys (CLAUDE.md
    migration sequencing). If a real user hits the two-existing-players merge
    branch before that dispatch completes, the NRL-only claim must still
    succeed rather than 500ing on the missing relation -- proves the
    _has_table guard, not just the happy path where the table exists."""
    c, TestingSession = client
    db = TestingSession()
    storm, eels = SportTeam(sport="nrl", name="Storm"), SportTeam(sport="nrl", name="Eels")
    db.add_all([storm, eels])
    db.flush()
    now = datetime.now(timezone.utc)
    m1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                    home_team_id=storm.id, away_team_id=eels.id,
                    kickoff_utc=now + timedelta(days=1), status="scheduled")
    m2 = SportMatch(sport="nrl", season=2026, round=1, match_no=2,
                    home_team_id=storm.id, away_team_id=eels.id,
                    kickoff_utc=now + timedelta(days=1), status="scheduled")
    db.add_all([m1, m2])
    db.commit()

    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_A, "match_id": m1.id, "pick": "home"})
    c.post("/api/nrl/tips/submit", json={"device_id": DEVICE_B, "match_id": m2.id, "pick": "away"})

    _register(c, "predatemigration@example.com")
    c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_A})

    # league_score_predictions doesn't exist yet -- the exact window the
    # guard is for.
    db.execute(text("DROP TABLE league_score_predictions"))
    db.commit()

    r = c.post("/api/nrl/tips/claim", json={"device_id": DEVICE_B})
    assert r.status_code == 200, r.text
    assert r.json()["claimed_tips"] == 1  # B's non-conflicting NRL tip moved over

    db2 = TestingSession()
    account_player = db2.query(TipPlayer).filter_by(device_id=DEVICE_A).one()
    assert db2.query(TipPlayer).filter_by(device_id=DEVICE_B).one_or_none() is None  # merged away
    assert db2.query(UserTip).filter_by(player_id=account_player.id).count() == 2  # both tips landed on the account
    db2.close()
