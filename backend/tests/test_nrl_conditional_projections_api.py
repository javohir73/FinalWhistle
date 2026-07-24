"""GET /api/nrl/projections/conditional (Slice 3, "the finals-race machine"):
picks-as-forced-outcomes inside the same Monte Carlo the nightly
nrl_projections job runs, never touching NrlProjection. Mirrors
test_nrl_intel_api.py's fixture style."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.nrl_intel as nrl_intel_api
from app.db import Base, get_db
from app.main import app
from app.models import EmailActionAttempt, SportMatch, SportTeam


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t); db.flush()
    return t


@pytest.fixture
def seeded(client):
    """One season, one finished match, TWO remaining (scheduled) matches
    between the same two teams -- 2 remaining fixtures so the duplicate-pick
    check (2 tokens, same id) can be exercised without also tripping the
    too-many-picks cap."""
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    finished = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                          home_team_id=home.id, away_team_id=away.id,
                          status="finished", score_home=20, score_away=10)
    scheduled_1 = SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                             home_team_id=home.id, away_team_id=away.id, status="scheduled")
    scheduled_2 = SportMatch(sport="nrl", season=2026, round=3, match_no=3,
                             home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add_all([finished, scheduled_1, scheduled_2]); db.commit()
    return c, finished.id, scheduled_1.id


def test_conditional_no_nrl_data_404s(client):
    c, _ = client
    r = c.get("/api/nrl/projections/conditional")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "no_nrl_data"


def test_conditional_unknown_season_404s(seeded):
    c, _, _ = seeded
    r = c.get("/api/nrl/projections/conditional", params={"season": 1999})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "season_not_found"


def test_conditional_empty_picks_runs_the_unconditioned_simulation(seeded):
    c, _, _ = seeded
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026
    assert body["picks_applied"] == 0
    assert body["n_sims"] > 0
    assert {t["team"] for t in body["teams"]} == {"Storm", "Eels"}
    for t in body["teams"]:
        assert 0.0 <= t["top8"] <= 1.0
        assert t["expected_points"] >= 0


def test_conditional_bad_picks_encoding_422s(seeded):
    c, _, _ = seeded
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026, "picks": "abc"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_picks_encoding"


def test_conditional_bad_picks_encoding_never_touches_rate_limit_or_db(client, monkeypatch):
    """The `picks` encoding is validated BEFORE the rate-limit check and
    before load_season_state's DB round-trip -- a malformed `picks` string
    must 422 for free, not cost a rate-limit SELECT, an EmailActionAttempt
    row, or a season-state load (defense-in-depth on an unauthenticated,
    per-request-Monte-Carlo route). No NRL data is seeded at all here, to
    prove the season load never happens either. Mirrors
    test_activity_api.py's test_malformed_device_id_never_touches_rate_limit_or_attempts."""
    c, TestingSession = client

    def _boom(*args, **kwargs):
        raise AssertionError("rate limit check must not run for malformed picks")

    monkeypatch.setattr(nrl_intel_api, "_email_action_rate_limited", _boom)

    r = c.get("/api/nrl/projections/conditional", params={"season": 2026, "picks": "abc"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bad_picks_encoding"

    db = TestingSession()
    assert db.query(EmailActionAttempt).count() == 0
    db.close()


def test_conditional_rate_limited_per_ip_after_cap(seeded, monkeypatch):
    """Unauthenticated, per-request Monte Carlo with no other guard -- mirrors
    app.api.activity's test_rate_limited_per_ip_after_cap. Keyed on IP alone
    (there's no device_id on this anonymous route)."""
    c, _, _ = seeded
    monkeypatch.setattr(nrl_intel_api, "_CONDITIONAL_MAX", 2, raising=False)
    assert c.get("/api/nrl/projections/conditional", params={"season": 2026}).status_code == 200
    assert c.get("/api/nrl/projections/conditional", params={"season": 2026}).status_code == 200
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"


def test_conditional_unknown_match_id_422s(seeded):
    c, _, _ = seeded
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026, "picks": "999999h"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unknown_match_id"


def test_conditional_finished_match_not_pickable_422s(seeded):
    c, finished_id, _ = seeded
    r = c.get("/api/nrl/projections/conditional",
              params={"season": 2026, "picks": f"{finished_id}h"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "match_not_remaining"


def test_conditional_duplicate_pick_422s(seeded):
    c, _, scheduled_id = seeded
    r = c.get("/api/nrl/projections/conditional",
              params={"season": 2026, "picks": f"{scheduled_id}h,{scheduled_id}a"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "duplicate_pick"


def test_conditional_too_many_picks_422s(seeded):
    c, _, _ = seeded  # this season has exactly 2 remaining fixtures
    r = c.get("/api/nrl/projections/conditional",
              params={"season": 2026, "picks": "111111h,222222a,333333h"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "too_many_picks"


@pytest.fixture
def single_fixture_season(client):
    """One season with exactly ONE remaining match -- isolates the effect of
    forcing that single pick (no second unforced fixture left to reshuffle
    the standings)."""
    c, TestingSession = client
    db = TestingSession()
    home = _team(db, "Storm")
    away = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                  home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.commit()
    return c, m.id


def test_conditional_forced_pick_flips_minor_premiership_to_certain(single_fixture_season):
    """The whole point of `forced`: a pick strictly raises the picked
    team's title chance versus the unconditioned baseline, and -- since
    this is the ONLY remaining fixture -- forcing it makes the outcome
    exactly certain, not just more likely."""
    c, match_id = single_fixture_season
    baseline = c.get("/api/nrl/projections/conditional", params={"season": 2026}).json()
    storm_baseline = next(t for t in baseline["teams"] if t["team"] == "Storm")
    assert 0.0 < storm_baseline["minor_premiership"] < 1.0

    forced = c.get("/api/nrl/projections/conditional",
                   params={"season": 2026, "picks": f"{match_id}h"}).json()
    storm_forced = next(t for t in forced["teams"] if t["team"] == "Storm")
    assert storm_forced["minor_premiership"] == 1.0
    assert storm_forced["minor_premiership"] > storm_baseline["minor_premiership"]
    assert forced["picks_applied"] == 1
    assert forced["n_sims"] == baseline["n_sims"]


def test_conditional_same_request_is_deterministic_with_multiple_remaining_fixtures(seeded):
    """test_conditional_same_request_is_deterministic (below) uses
    single_fixture_season, which has only ONE remaining match -- fixture
    order can't matter there. `seeded` has two, so this actually exercises
    load_season_state's ORDER BY: without it, the cache-determinism promise
    (identical request -> identical body) would rest on undefined DB row
    order (see pipeline/sports/nrl_projections_test.py's
    test_load_season_state_orders_remaining_matches_deterministically)."""
    c, _, scheduled_id = seeded
    params = {"season": 2026, "picks": f"{scheduled_id}h"}
    r1 = c.get("/api/nrl/projections/conditional", params=params)
    r2 = c.get("/api/nrl/projections/conditional", params=params)
    assert r1.json() == r2.json()


def test_conditional_same_request_is_deterministic(single_fixture_season):
    """Identical (season, picks) must return an identical body -- required
    for the 60s public Cache-Control (and any CDN) to serve repeats without
    re-simulating."""
    c, match_id = single_fixture_season
    params = {"season": 2026, "picks": f"{match_id}h"}
    r1 = c.get("/api/nrl/projections/conditional", params=params)
    r2 = c.get("/api/nrl/projections/conditional", params=params)
    assert r1.json() == r2.json()


def test_conditional_uses_the_default_public_cache_control(seeded):
    c, _, _ = seeded
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026})
    assert r.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=300"


def test_conditional_perf_guard_completes_quickly(client):
    """n_sims default over a realistically-sized remaining fixture list must
    comfortably clear a request-timeout budget (recon benchmark on this
    machine: ~0.5s for 5000 runs x ~100 fixtures, so 2000 runs x 20 here
    should be well under a second)."""
    c, TestingSession = client
    db = TestingSession()
    teams = [_team(db, f"Team{i}") for i in range(16)]
    for rnd in range(20):
        h, a = teams[rnd % 16], teams[(rnd + 1) % 16]
        db.add(SportMatch(sport="nrl", season=2026, round=rnd, match_no=1,
                          home_team_id=h.id, away_team_id=a.id, status="scheduled"))
    db.commit()

    start = time.perf_counter()
    r = c.get("/api/nrl/projections/conditional", params={"season": 2026})
    elapsed = time.perf_counter() - start
    assert r.status_code == 200
    assert elapsed < 5.0
