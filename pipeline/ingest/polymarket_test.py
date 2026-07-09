"""Gamma parsing: binary Yes markets -> neutral rows; closed markets dropped."""
import json
from pathlib import Path

from pipeline.ingest.polymarket import parse_events

FIXTURE = Path(__file__).parent / "testdata" / "polymarket_events.json"


def _rows():
    return parse_events(json.loads(FIXTURE.read_text()))


def test_match_event_maps_three_outcomes():
    rows = [r for r in _rows() if r["kind"] == "match"]
    assert {r["outcome"] for r in rows} == {"home", "draw", "away"}
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "France" and by["home"]["price"] == 0.63
    assert by["away"]["team_name"] == "Morocco" and by["away"]["price"] == 0.15
    assert by["draw"]["team_name"] is None and by["draw"]["price"] == 0.27
    assert by["home"]["home_name"] == "France" and by["home"]["away_name"] == "Morocco"
    assert by["home"]["group"] == "fra-mar-2026-07-11"
    assert by["home"]["source"] == "polymarket"


def test_title_event_one_win_row_per_active_team():
    rows = [r for r in _rows() if r["kind"] == "title"]
    assert [(r["team_name"], r["price"]) for r in rows] == [
        ("France", 0.31), ("Argentina", 0.24),
    ]
    assert all(r["outcome"] == "win" for r in rows)


def test_closed_or_inactive_markets_are_dropped():
    assert not [r for r in _rows() if r["team_name"] == "Mexico"]
