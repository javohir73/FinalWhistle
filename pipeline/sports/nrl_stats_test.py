"""Tests for pipeline/sports/nrl_stats.py — parsers run against the recorded
fixtures from the Task 1 spike (pipeline/sports/testdata/nrl_stats/). No live
HTTP anywhere in this file."""
import json
import time
from pathlib import Path

import requests

from pipeline.sports.nrl_stats import (
    MatchStatsPayload,
    NrlComStatsProvider,
    TeamStatsLine,
    TryEventLine,
    parse_draw_fixtures,
    parse_match_stats,
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
