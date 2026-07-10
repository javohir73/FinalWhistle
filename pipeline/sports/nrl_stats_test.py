"""Tests for pipeline/sports/nrl_stats.py — parsers run against the recorded
fixtures from the Task 1 spike (pipeline/sports/testdata/nrl_stats/). No live
HTTP anywhere in this file."""
import json
from pathlib import Path

from pipeline.sports.nrl_stats import (
    MatchStatsPayload,
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
