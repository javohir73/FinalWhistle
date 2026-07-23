"""Gamma parsing: binary Yes markets -> neutral rows; closed markets dropped."""
import json
from pathlib import Path

from pipeline.ingest.polymarket import WC_TAG_SLUG, parse_events

FIXTURE = Path(__file__).parent / "testdata" / "polymarket_events.json"


def _rows():
    return parse_events(json.loads(FIXTURE.read_text()), WC_TAG_SLUG)


def test_match_event_maps_three_outcomes():
    rows = [r for r in _rows() if r["kind"] == "match" and r["group"] == "fra-mar-2026-07-11"]
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


def test_ancillary_winner_events_are_not_title_events():
    """Only the championship event may produce title rows. The fifa-world-cup
    tag also carries group-winner, qualifying-group and award events whose
    titles all contain 'winner' and whose questions all read 'Will <team>
    win ...' — the Fair Play Award event put Netherlands at 87.9% into
    title_winner the day after Spain won the final (incident 2026-07-20)."""
    titles = [r for r in _rows() if r["kind"] == "title"]
    assert {r["group"] for r in titles} == {"2026-fifa-world-cup-winner"}
    assert not [r for r in titles if r["team_name"] == "Netherlands"]
    assert not [r for r in titles if "group" in r["external_id"]]


def test_unknown_tag_yields_no_title_rows():
    """A tag with no vetted title pattern must skip title events entirely
    (wrong mapping is worse than no mapping) while match events still parse."""
    events = json.loads(FIXTURE.read_text())
    rows = parse_events(events, "some-future-tag")
    assert not [r for r in rows if r["kind"] == "title"]
    assert [r for r in rows if r["kind"] == "match"]


def test_aliased_team_name_maps_against_raw_question_text():
    """'Korea' (home) must map even though the question says 'Will Korea
    win?' verbatim — normalize(home) alias-expands to 'korea republic' but
    the question text doesn't unless it's alias-expanded too (regression for
    the 'unmapped match market' drop on Korea/USA/Iran markets)."""
    rows = [r for r in _rows() if r["group"] == "kor-bra-2026-07-12"]
    assert {r["outcome"] for r in rows} == {"home", "draw", "away"}
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "Korea" and by["home"]["price"] == 0.12
    assert by["away"]["team_name"] == "Brazil" and by["away"]["price"] == 0.63
