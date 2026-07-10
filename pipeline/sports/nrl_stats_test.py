"""Tests for pipeline/sports/nrl_stats.py — parsers run against the recorded
fixtures from the Task 1 spike (pipeline/sports/testdata/nrl_stats/). No live
HTTP anywhere in this file."""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam
from pipeline.sports.nrl_stats import (
    MatchStatsPayload,
    NrlComStatsProvider,
    TeamStatsLine,
    TryEventLine,
    parse_draw_fixtures,
    parse_match_stats,
    upsert_match_stats,
)

TESTDATA = Path(__file__).parent / "testdata" / "nrl_stats"


def _load(name: str) -> dict:
    with (TESTDATA / name).open() as f:
        return json.load(f)


# ---- transcribed from the real recorded fixtures (Task 1 spike / SOURCE.md) --
# match_2025_r01_a.json = Raiders 30 v Warriors 8 (Allegiant Stadium, Las Vegas).
# NOTE: the brief's illustrative placeholders ("Knights"/"Cowboys"/etc.) do not
# match the actually-recorded fixture and were corrected here — see
# task-2-report.md for the full list of corrections with SOURCE.md line refs.
EXPECTED_HOME_TEAM = "Raiders"          # <- exact team string in match_2025_r01_a.json
EXPECTED_AWAY_TEAM = "Warriors"         # <- exact away team string
EXPECTED_HOME_TRIES = 5                 # <- real value from the fixture
EXPECTED_AWAY_RUN_METRES = 1565         # <- real value from the fixture
EXPECTED_TRY_COUNT = 7                  # <- total try events in the fixture
EXPECTED_FIRST_TRY_MINUTE = 5           # <- minute of the first try event
EXPECTED_FIRST_TRY_PLAYER = "Sebastian Kris"  # <- exact player string
# -----------------------------------------------------------------------------


def test_parse_match_stats_full_document():
    payload = parse_match_stats(_load("match_2025_r01_a.json"))
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team == EXPECTED_HOME_TEAM
    assert payload.away.team == EXPECTED_AWAY_TEAM
    assert payload.home.tries == EXPECTED_HOME_TRIES
    assert payload.away.run_metres == EXPECTED_AWAY_RUN_METRES
    # every one of the nine contract fields is populated with a sane value
    for line in (payload.home, payload.away):
        assert line.tries >= 0
        assert line.conversions >= 0
        assert line.penalties_conceded >= 0
        assert line.errors >= 0
        assert line.set_restarts >= 0
        assert line.run_metres > 0
        assert line.line_breaks >= 0
        assert line.tackles > 0
        assert 0.0 < line.tackle_efficiency <= 100.0


def test_parse_match_stats_try_events_ordered_with_running_score():
    payload = parse_match_stats(_load("match_2025_r01_a.json"))
    events = payload.try_events
    assert len(events) == EXPECTED_TRY_COUNT
    assert events[0].minute == EXPECTED_FIRST_TRY_MINUTE
    assert events[0].player == EXPECTED_FIRST_TRY_PLAYER
    minutes = [e.minute for e in events]
    assert minutes == sorted(minutes)
    for e in events:
        assert isinstance(e, TryEventLine)
        assert e.team in (EXPECTED_HOME_TEAM, EXPECTED_AWAY_TEAM)
        assert e.score_home >= 0 and e.score_away >= 0


def test_parse_match_stats_second_fixture_also_parses():
    payload = parse_match_stats(_load("match_2025_r01_b.json"))
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team != payload.away.team


def test_parse_match_stats_returns_none_on_garbage():
    assert parse_match_stats({}) is None
    assert parse_match_stats({"stats": None}) is None


def test_parse_draw_fixtures_lists_round_matches():
    fixtures = parse_draw_fixtures(_load("draw_2025_r01.json"))
    assert len(fixtures) >= 4  # a normal NRL round has 8; never fewer than 4
    for fx in fixtures:
        assert set(fx) == {"home", "away", "match_path"}
        assert fx["home"] and fx["away"] and fx["match_path"]


def test_parse_draw_fixtures_returns_empty_on_garbage():
    assert parse_draw_fixtures({}) == []


# --- StatsProvider: rate-limited default provider (Task 3) -----------------

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def _provider_with_recorded_http(monkeypatch, sleeps: list | None = None):
    """Provider whose HTTP layer serves the recorded fixtures by URL shape."""
    draw = _load("draw_2025_r01.json")
    match_doc = _load("match_2025_r01_a.json")
    fixtures = parse_draw_fixtures(draw)
    target = fixtures[0]
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        assert headers == {"User-Agent": "Mozilla/5.0"}
        if "draw/data" in url:
            return _Resp(draw)
        if target["match_path"] in url:
            return _Resp(match_doc)
        return _Resp({}, status=404)

    monkeypatch.setattr(requests, "get", fake_get)
    if sleeps is not None:
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    lookup = lambda season, rnd, no: (target["home"], target["away"])  # noqa: E731
    return NrlComStatsProvider(team_names=lookup, min_interval=1.0), calls, target


def test_provider_fetches_and_parses_match_stats(monkeypatch):
    provider, calls, target = _provider_with_recorded_http(monkeypatch, sleeps=[])
    payload = provider.fetch_match_stats(2025, 1, 1)
    assert isinstance(payload, MatchStatsPayload)
    assert payload.home.team == target["home"]
    assert len(calls) == 2  # one draw fetch + one match fetch


def test_provider_caches_round_draw_across_matches(monkeypatch):
    provider, calls, target = _provider_with_recorded_http(monkeypatch, sleeps=[])
    provider.fetch_match_stats(2025, 1, 1)
    provider.fetch_match_stats(2025, 1, 1)
    draw_calls = [c for c in calls if "draw/data" in c]
    assert len(draw_calls) == 1  # round listing fetched once, then cached


def test_round_fixtures_does_not_cache_failed_draw_fetch(monkeypatch):
    """Important review finding F1: a transient draw-fetch failure must not
    permanently poison the cache for that (season, round_no) -- a retry must
    hit the network again, not be silently served a cached []."""
    draw = _load("draw_2025_r01.json")
    expected = parse_draw_fixtures(draw)
    calls: list[str] = []
    attempts = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        assert "draw/data" in url  # this test never reaches a match-doc fetch
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise requests.exceptions.ConnectionError("boom")
        return _Resp(draw)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    provider = NrlComStatsProvider(min_interval=1.0)

    # first call: draw fetch fails -> [] returned, nothing cached, no
    # match-doc requests made at all (the only call was the failed draw one).
    first = provider._round_fixtures(2025, 1)
    assert first == []
    assert (2025, 1) not in provider._draw_cache
    assert len(calls) == 1

    # second call: retries (not served from a poisoned cached []) and
    # succeeds -> proves no poisoning.
    second = provider._round_fixtures(2025, 1)
    assert second == expected
    assert (2025, 1) in provider._draw_cache
    assert len(calls) == 2


def test_provider_returns_none_when_teams_unresolvable(monkeypatch):
    provider, _, _ = _provider_with_recorded_http(monkeypatch, sleeps=[])
    provider._team_names = lambda season, rnd, no: ("Nonexistent", "AlsoNot")
    assert provider.fetch_match_stats(2025, 1, 1) is None


def test_provider_never_raises_on_http_error(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(requests, "get", boom)
    provider = NrlComStatsProvider(team_names=lambda *a: ("Knights", "Cowboys"))
    assert provider.fetch_match_stats(2025, 1, 1) is None


def test_provider_never_raises_when_team_names_callback_raises(caplog):
    """Important review finding F2: a future DB-backed team_names callback
    that raises must not violate the class's documented "fetch_* never
    raises" contract."""
    def boom(season, round_no, match_no):
        raise RuntimeError("db down")

    provider = NrlComStatsProvider(team_names=boom)
    with caplog.at_level(logging.WARNING, logger="pipeline.sports.nrl_stats"):
        result = provider.fetch_match_stats(2025, 1, 1)
    assert result is None
    assert any("team_names" in rec.message for rec in caplog.records)


def test_provider_throttles_at_least_one_second_between_requests(monkeypatch):
    sleeps: list = []
    provider, calls, _ = _provider_with_recorded_http(monkeypatch, sleeps=sleeps)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)  # freeze the clock
    provider.fetch_match_stats(2025, 1, 1)
    # 2 HTTP calls with a frozen clock -> the 2nd must have slept ~min_interval
    assert len(calls) == 2
    assert any(s >= 0.99 for s in sleeps)


def test_wave3_stubs_are_honest():
    provider = NrlComStatsProvider()
    assert provider.fetch_team_list(2025, 1) == []
    assert provider.fetch_live(2025, 1, 1) is None


# --- idempotent upsert (Task 5) --------------------------------------------

def _mk_match(db, status="finished") -> SportMatch:
    home = SportTeam(sport="nrl", name="Knights")
    away = SportTeam(sport="nrl", name="Cowboys")
    db.add_all([home, away])
    db.flush()
    match = SportMatch(
        sport="nrl", season=2025, round=1, match_no=1,
        kickoff_utc=datetime(2025, 3, 6, 9, 0, tzinfo=timezone.utc),
        venue="McDonald Jones Stadium",
        home_team_id=home.id, away_team_id=away.id,
        score_home=28, score_away=18, status=status,
    )
    db.add(match)
    db.commit()
    return match


def _payload() -> MatchStatsPayload:
    return MatchStatsPayload(
        home=TeamStatsLine(team="Knights", tries=5, conversions=4,
                           penalties_conceded=6, errors=8, set_restarts=4,
                           run_metres=1650, line_breaks=6, tackles=310,
                           tackle_efficiency=91.3),
        away=TeamStatsLine(team="Cowboys", tries=3, conversions=3,
                           penalties_conceded=8, errors=11, set_restarts=6,
                           run_metres=1432, line_breaks=3, tackles=345,
                           tackle_efficiency=88.7),
        try_events=[
            TryEventLine(minute=7, team="Knights", player="K. Ponga",
                         score_home=6, score_away=0),
            TryEventLine(minute=23, team="Cowboys", player="S. Drinkwater",
                         score_home=6, score_away=6),
        ],
    )


def test_upsert_writes_two_stat_rows_and_events(db_session):
    match = _mk_match(db_session)
    counts = upsert_match_stats(db_session, match, _payload())
    assert counts == {"stats_rows": 2, "try_events": 2}
    rows = db_session.query(NrlMatchStat).filter_by(match_id=match.id).all()
    assert {r.team for r in rows} == {"Knights", "Cowboys"}
    knights = next(r for r in rows if r.team == "Knights")
    assert knights.run_metres == 1650
    assert knights.tackle_efficiency == 91.3
    events = (db_session.query(NrlTryEvent).filter_by(match_id=match.id)
              .order_by(NrlTryEvent.minute).all())
    assert [e.player for e in events] == ["K. Ponga", "S. Drinkwater"]
    assert events[1].score_away == 6


def test_upsert_is_idempotent_replace(db_session):
    match = _mk_match(db_session)
    upsert_match_stats(db_session, match, _payload())
    upsert_match_stats(db_session, match, _payload())  # second run: replace, not duplicate
    assert db_session.query(NrlMatchStat).filter_by(match_id=match.id).count() == 2
    assert db_session.query(NrlTryEvent).filter_by(match_id=match.id).count() == 2


def test_upsert_rejects_unfinished_match(db_session):
    match = _mk_match(db_session, status="scheduled")
    with pytest.raises(ValueError):
        upsert_match_stats(db_session, match, _payload())
    assert db_session.query(NrlMatchStat).count() == 0
