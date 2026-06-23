"""GET /api/matches/{id}/lineups — the display-only lineups endpoint.

Covers the three branches (stored / fetch-on-window / out-of-window placeholder)
and graceful degradation (missing key, unresolvable fixture, provider error) with
the provider/network mocked. Lineups never feed the prediction model and must
never 5xx or fabricate players."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.lineups as lineups_mod
from app.cache import cache
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import LineupPlayer, Match, MatchLineup, Team, Tournament


def _now() -> datetime:
    return datetime.now(timezone.utc)


# A two-team /fixtures/lineups response (France home vs Germany away in the seed).
_LINEUPS_RESPONSE = [
    {
        "team": {"name": "France"},
        "formation": "4-3-3",
        "coach": {"name": "D. Deschamps"},
        "startXI": [
            {"player": {"name": "M. Maignan", "number": 16, "pos": "G", "grid": "1:1"}},
            {"player": {"name": "K. Mbappe", "number": 10, "pos": "F", "grid": "4:1"}},
        ],
        "substitutes": [
            {"player": {"name": "O. Giroud", "number": 9, "pos": "F", "grid": None}},
        ],
    },
    {
        "team": {"name": "Germany"},
        "formation": "4-2-3-1",
        "coach": {"name": "J. Nagelsmann"},
        "startXI": [
            {"player": {"name": "M. Neuer", "number": 1, "pos": "G", "grid": "1:1"}},
        ],
        "substitutes": [],
    },
]


@pytest.fixture
def env():
    """In-memory DB + TestClient, plus the session factory so tests can seed
    lineups directly and inspect what the endpoint persisted."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    seed = TestingSession()
    seed.add(Tournament(id=1, name="WC26", year=2026))
    seed.add_all([Team(id=10, name="France"), Team(id=20, name="Germany")])
    # match 1: in the lineup window (kicks off in 30 min). match 2: far future.
    seed.add(
        Match(id=1, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="scheduled", kickoff_utc=_now() + timedelta(minutes=30))
    )
    seed.add(
        Match(id=2, tournament_id=1, stage="group", team_home_id=10, team_away_id=20,
              status="scheduled", kickoff_utc=_now() + timedelta(days=5))
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
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()
    cache.clear()


# ---- Branch 1: lineups already stored ----

def test_stored_lineups_are_returned_without_external_call(env, monkeypatch):
    client, Session = env
    # A network call would explode this test if the stored branch reached out.
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch when stored")),
    )
    s = Session()
    lu = MatchLineup(match_id=1, side="home", formation="4-3-3", coach="D. Deschamps",
                     provider="api_football", fetched_at=_now())
    lu.players.append(LineupPlayer(name="K. Mbappe", number=10, position="F",
                                   grid="4:1", is_starter=True, order=0))
    lu.players.append(LineupPlayer(name="O. Giroud", number=9, position="F",
                                   grid=None, is_starter=False, order=1))
    s.add(lu)
    s.commit()
    s.close()

    res = client.get("/api/matches/1/lineups")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True
    assert body["message"] is None
    assert body["home"]["team"] == "France"
    assert body["home"]["formation"] == "4-3-3"
    assert body["home"]["coach"] == "D. Deschamps"
    assert [p["name"] for p in body["home"]["start_xi"]] == ["K. Mbappe"]
    assert body["home"]["start_xi"][0]["is_starter"] is True
    assert body["home"]["start_xi"][0]["grid"] == "4:1"
    assert [p["name"] for p in body["home"]["bench"]] == ["O. Giroud"]
    assert body["home"]["bench"][0]["grid"] is None
    assert body["away"] is None  # only the home side was stored
    assert body["fetched_at"] is not None


# ---- Branch 2: fetch on window + key + resolvable fixture ----

def test_fetches_persists_and_returns_when_in_window(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    # provider_fixture_id is already set on the match so no /fixtures resolve call.
    s = Session()
    s.get(Match, 1).provider_fixture_id = 555
    s.commit()
    s.close()

    calls = {}

    def fake_fetch_lineups(api_key, fixture_id, timeout=15.0):
        calls["fixture_id"] = fixture_id
        calls["api_key"] = api_key
        return _LINEUPS_RESPONSE

    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups", fake_fetch_lineups)
    # Resolution must not be hit (id already stored).
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_fixtures",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not resolve when id stored")),
    )

    res = client.get("/api/matches/1/lineups")
    assert res.status_code == 200
    body = res.json()
    assert calls == {"fixture_id": 555, "api_key": "test-key"}
    assert body["available"] is True
    assert body["home"]["team"] == "France"
    assert body["away"]["team"] == "Germany"
    assert body["home"]["formation"] == "4-3-3"
    assert body["away"]["formation"] == "4-2-3-1"
    assert [p["name"] for p in body["home"]["start_xi"]] == ["M. Maignan", "K. Mbappe"]
    assert [p["name"] for p in body["home"]["bench"]] == ["O. Giroud"]

    # Persisted: a second call returns the stored rows and makes NO fetch.
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("second call must use the cache")),
    )
    again = client.get("/api/matches/1/lineups").json()
    assert again["available"] is True
    assert again["away"]["team"] == "Germany"

    db = Session()
    assert db.query(MatchLineup).filter_by(match_id=1).count() == 2
    # France: 2 starters + 1 bench; Germany: 1 starter -> 4 players total.
    assert db.query(LineupPlayer).count() == 4
    db.close()


def test_resolves_fixture_id_by_team_pair_then_fetches(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")

    # /fixtures returns the season fixtures; the matching pair gives fixture id 909.
    fixtures = [
        {"fixture": {"id": 101}, "teams": {"home": {"name": "Brazil"}, "away": {"name": "Spain"}}},
        {"fixture": {"id": 909}, "teams": {"home": {"name": "France"}, "away": {"name": "Germany"}}},
    ]
    monkeypatch.setattr("pipeline.ingest.api_football.fetch_fixtures",
                        lambda *a, **k: fixtures)
    seen = {}
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda key, fid, timeout=15.0: seen.update(fid=fid) or _LINEUPS_RESPONSE,
    )

    res = client.get("/api/matches/1/lineups")
    assert res.status_code == 200
    assert res.json()["available"] is True
    assert seen["fid"] == 909
    # The resolved id is cached on the match for next time.
    db = Session()
    assert db.get(Match, 1).provider_fixture_id == 909
    db.close()


def test_finished_match_is_in_window(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    s = Session()
    m = s.get(Match, 2)  # the far-future fixture...
    m.status = "finished"  # ...now finished -> in window regardless of kickoff
    m.provider_fixture_id = 777
    s.commit()
    s.close()
    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups",
                        lambda *a, **k: _LINEUPS_RESPONSE)

    body = client.get("/api/matches/2/lineups").json()
    assert body["available"] is True
    assert body["home"]["team"] == "France"


# ---- Branch 3: out of window -> placeholder, NO external call ----

def test_future_fixture_returns_placeholder_without_calling_provider(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    # Any provider call out of window is a bug.
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call out of window")),
    )
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_fixtures",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call out of window")),
    )

    res = client.get("/api/matches/2/lineups")  # kicks off in 5 days
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False
    assert body["home"] is None and body["away"] is None
    assert body["fetched_at"] is None
    assert "40 minutes" in body["message"]


# ---- Graceful degradation ----

def test_missing_api_key_degrades_to_placeholder_in_window(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "")  # no key configured
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no key -> no call")),
    )
    body = client.get("/api/matches/1/lineups").json()  # in window
    assert body["available"] is False
    assert "40 minutes" in body["message"]


def test_provider_error_degrades_to_placeholder_never_5xx(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    s = Session()
    s.get(Match, 1).provider_fixture_id = 555
    s.commit()
    s.close()

    def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups", boom)
    res = client.get("/api/matches/1/lineups")
    assert res.status_code == 200  # never a 5xx
    body = res.json()
    assert body["available"] is False
    # Nothing fabricated/persisted on error.
    db = Session()
    assert db.query(MatchLineup).count() == 0
    db.close()


def test_unresolvable_fixture_degrades_to_placeholder(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    # /fixtures has no matching pair -> id can't resolve.
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_fixtures",
        lambda *a, **k: [{"fixture": {"id": 1}, "teams": {"home": {"name": "Brazil"},
                                                          "away": {"name": "Spain"}}}],
    )
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch without a fixture id")),
    )
    body = client.get("/api/matches/1/lineups").json()
    assert body["available"] is False


def test_empty_provider_lineups_degrade_to_placeholder(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    s = Session()
    s.get(Match, 1).provider_fixture_id = 555
    s.commit()
    s.close()
    # Provider returns no lineup yet (just inside the window).
    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups", lambda *a, **k: [])
    body = client.get("/api/matches/1/lineups").json()
    assert body["available"] is False
    db = Session()
    assert db.query(MatchLineup).count() == 0
    db.close()


def test_unknown_match_404(env):
    client, Session = env
    res = client.get("/api/matches/999/lineups")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "match_not_found"


# ---- Partial-cache completeness (team sheets drop a few minutes apart) ----

def test_partial_cache_refetches_missing_side(env, monkeypatch):
    """One side stored + in window + key -> re-fetch to fill the missing side
    (idempotent: the already-stored side is never duplicated)."""
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    s = Session()
    s.get(Match, 1).provider_fixture_id = 555
    lu = MatchLineup(match_id=1, side="home", formation="4-3-3", coach="D. Deschamps",
                     provider="api_football", fetched_at=_now())
    lu.players.append(LineupPlayer(name="K. Mbappe", number=10, position="F",
                                   grid="4:1", is_starter=True, order=0))
    s.add(lu)
    s.commit()
    s.close()

    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups",
                        lambda *a, **k: _LINEUPS_RESPONSE)
    body = client.get("/api/matches/1/lineups").json()
    assert body["available"] is True
    assert body["home"]["team"] == "France"   # original home retained
    assert body["away"]["team"] == "Germany"  # missing side filled in

    db = Session()
    assert db.query(MatchLineup).filter_by(match_id=1).count() == 2  # no dup home
    assert db.query(MatchLineup).filter_by(match_id=1, side="home").count() == 1
    db.close()


def test_partial_cache_out_of_window_serves_stored_side(env, monkeypatch):
    """One side stored + OUT of window -> serve what we have, no external call."""
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch out of window")),
    )
    s = Session()
    lu = MatchLineup(match_id=2, side="home", formation="4-3-3",
                     provider="api_football", fetched_at=_now())  # match 2 = far future
    lu.players.append(LineupPlayer(name="K. Mbappe", number=10, position="F",
                                   grid="4:1", is_starter=True, order=0))
    s.add(lu)
    s.commit()
    s.close()

    body = client.get("/api/matches/2/lineups").json()
    assert body["available"] is True
    assert body["home"]["team"] == "France"
    assert body["away"] is None


def test_finished_without_lineup_uses_state_honest_message(env, monkeypatch):
    """A finished match with no lineup on file must NOT say 'before kickoff'."""
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    s = Session()
    m = s.get(Match, 2)
    m.status = "finished"
    m.provider_fixture_id = 777
    s.commit()
    s.close()
    monkeypatch.setattr("pipeline.ingest.api_football.fetch_lineups", lambda *a, **k: [])

    body = client.get("/api/matches/2/lineups").json()
    assert body["available"] is False
    assert "40 minutes" not in body["message"]      # not the future-kickoff line
    assert "published" in body["message"].lower()


def test_fixture_resolution_disambiguates_by_kickoff_date(env, monkeypatch):
    """When a team pair recurs in the feed, resolve to the fixture nearest our
    kickoff rather than the first match."""
    client, Session = env
    monkeypatch.setattr(settings, "api_football_api_key", "test-key")
    near = (_now() + timedelta(minutes=30)).isoformat()   # match 1 kicks off in 30 min
    far = (_now() + timedelta(days=40)).isoformat()
    fixtures = [
        {"fixture": {"id": 111, "date": far},
         "teams": {"home": {"name": "France"}, "away": {"name": "Germany"}}},
        {"fixture": {"id": 222, "date": near},
         "teams": {"home": {"name": "France"}, "away": {"name": "Germany"}}},
    ]
    monkeypatch.setattr("pipeline.ingest.api_football.fetch_fixtures", lambda *a, **k: fixtures)
    seen = {}
    monkeypatch.setattr(
        "pipeline.ingest.api_football.fetch_lineups",
        lambda key, fid, timeout=15.0: seen.update(fid=fid) or _LINEUPS_RESPONSE,
    )

    body = client.get("/api/matches/1/lineups").json()
    assert body["available"] is True
    assert seen["fid"] == 222  # chose the fixture nearest match 1's kickoff
    db = Session()
    assert db.get(Match, 1).provider_fixture_id == 222
    db.close()


# ---- window helper unit ----

def test_in_lineup_window_boundaries():
    base = _now()
    finished = Match(status="finished", kickoff_utc=base + timedelta(days=10))
    assert lineups_mod.in_lineup_window(finished, now=base) is True  # finished always in
    soon = Match(status="scheduled", kickoff_utc=base + timedelta(minutes=30))
    assert lineups_mod.in_lineup_window(soon, now=base) is True
    far = Match(status="scheduled", kickoff_utc=base + timedelta(hours=3))
    assert lineups_mod.in_lineup_window(far, now=base) is False
    no_kickoff = Match(status="scheduled", kickoff_utc=None)
    assert lineups_mod.in_lineup_window(no_kickoff, now=base) is False
