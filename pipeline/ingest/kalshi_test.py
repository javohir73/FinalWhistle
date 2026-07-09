"""Kalshi parsing: cent mid-prices -> neutral rows; zero-quote rows dropped."""
import json
from pathlib import Path

from pipeline.ingest.kalshi import parse_markets

FIXTURE = Path(__file__).parent / "testdata" / "kalshi_markets.json"


def _markets():
    return json.loads(FIXTURE.read_text())["markets"]


def test_match_markets_mid_price_and_outcomes():
    rows = parse_markets([m for m in _markets() if m["ticker"].startswith("KXWCGAME")],
                         kind="match")
    by = {r["outcome"]: r for r in rows}
    assert by["home"]["team_name"] == "France" and by["home"]["price"] == 0.63
    assert by["away"]["team_name"] == "Morocco" and by["away"]["price"] == 0.15
    assert by["draw"]["price"] == 0.26 and by["draw"]["team_name"] is None
    assert by["home"]["home_name"] == "France" and by["home"]["away_name"] == "Morocco"
    assert by["home"]["group"] == "KXWCGAME-26JUL11FRAMAR"
    assert by["home"]["source"] == "kalshi"


def test_title_markets_and_zero_quotes_dropped():
    rows = parse_markets([m for m in _markets() if m["ticker"].startswith("KXWC-")],
                         kind="title")
    assert [(r["team_name"], r["price"], r["outcome"]) for r in rows] == [
        ("France", 0.31, "win"),
    ]
