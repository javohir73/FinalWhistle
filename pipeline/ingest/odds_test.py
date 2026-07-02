"""Tests for the pre-match odds snapshot (exact-score program FR-4.1/FR-4.2).

The BEST-EFFORT contract comes first: a failed or empty fetch leaves the DB
unchanged and never raises to callers — prediction generation must be
unblockable by a bookmaker feed. Then the consensus math: median decimal
price across bookmakers per outcome, margin-free implied 1X2 probabilities,
captured_at stamped.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Match, Odds, Team, Tournament
import pipeline.ingest.odds as odds_mod
from pipeline.ingest.odds import median_prices, refresh_odds


def _seed_match(db, *, hours_to_kickoff=12.0, fixture_id=9001) -> Match:
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home = Team(name="Mexico")
    away = Team(name="South Africa")
    db.add_all([wc, home, away])
    db.flush()
    m = Match(
        tournament_id=wc.id, stage="group", status="scheduled",
        team_home_id=home.id, team_away_id=away.id,
        kickoff_utc=datetime.now(timezone.utc) + timedelta(hours=hours_to_kickoff),
        provider_fixture_id=fixture_id,
    )
    db.add(m)
    db.commit()
    return m


def _bookmaker(name, h, d, a, over=None, under=None):
    bets = [{
        "id": 1, "name": "Match Winner",
        "values": [{"value": "Home", "odd": str(h)},
                   {"value": "Draw", "odd": str(d)},
                   {"value": "Away", "odd": str(a)}],
    }]
    if over is not None and under is not None:
        bets.append({
            "id": 5, "name": "Goals Over/Under",
            "values": [{"value": "Over 2.5", "odd": str(over)},
                       {"value": "Under 2.5", "odd": str(under)},
                       {"value": "Over 3.5", "odd": "3.10"},   # other lines ignored
                       {"value": "Under 1.5", "odd": "3.40"}],
        })
    return {"name": name, "bets": bets}


def _response(*bookmakers) -> list[dict]:
    return [{"fixture": {"id": 9001}, "bookmakers": list(bookmakers)}]


# --- FR-4.2: best-effort contract, FIRST --------------------------------------

def test_fetch_failure_leaves_db_unchanged_and_never_raises(db_session, monkeypatch):
    _seed_match(db_session)

    def boom(api_key, fixture_id, timeout=15.0):
        raise RuntimeError("bookmaker feed down")

    monkeypatch.setattr(odds_mod, "fetch_odds", boom)
    summary = refresh_odds(db_session, "key")  # must not raise
    assert summary["matches_priced"] == 0
    assert db_session.query(Odds).count() == 0


def test_empty_fetch_writes_nothing(db_session, monkeypatch):
    _seed_match(db_session)
    monkeypatch.setattr(odds_mod, "fetch_odds", lambda *a, **k: [])
    summary = refresh_odds(db_session, "key")
    assert summary["matches_priced"] == 0
    assert db_session.query(Odds).count() == 0


def test_commit_failure_rolls_back_and_never_raises(db_session, monkeypatch):
    _seed_match(db_session)
    monkeypatch.setattr(odds_mod, "fetch_odds",
                        lambda *a, **k: _response(_bookmaker("A", 2.0, 3.4, 3.8)))
    monkeypatch.setattr(db_session, "commit",
                        lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    summary = refresh_odds(db_session, "key")  # must not raise
    assert summary["matches_priced"] == 0


# --- consensus math -------------------------------------------------------------

def test_median_prices_across_bookmakers():
    med = median_prices(_response(
        _bookmaker("A", 1.90, 3.40, 4.00, over=1.80, under=2.00),
        _bookmaker("B", 2.00, 3.50, 4.20, over=1.85, under=1.95),
        _bookmaker("C", 2.10, 3.30, 4.40, over=1.95, under=1.85),
    ))
    assert med["home"] == 2.00 and med["draw"] == 3.40 and med["away"] == 4.20
    assert med["over25"] == 1.85 and med["under25"] == 1.95


def test_median_prices_handles_missing_markets():
    med = median_prices(_response(_bookmaker("A", 2.0, 3.3, 3.9)))  # no OU bet
    assert med["home"] == 2.0
    assert med["over25"] is None and med["under25"] is None
    assert median_prices([]) is None
    assert median_prices([{"fixture": {"id": 1}, "bookmakers": []}]) is None


def test_refresh_stores_median_row_with_margin_free_probs(db_session, monkeypatch):
    m = _seed_match(db_session)
    monkeypatch.setattr(odds_mod, "fetch_odds", lambda *a, **k: _response(
        _bookmaker("A", 1.90, 3.40, 4.00, over=1.80, under=2.00),
        _bookmaker("B", 2.00, 3.50, 4.20, over=1.85, under=1.95),
        _bookmaker("C", 2.10, 3.30, 4.40, over=1.95, under=1.85),
    ))

    summary = refresh_odds(db_session, "key")

    assert summary["matches_priced"] == 1
    row = db_session.query(Odds).one()
    assert row.match_id == m.id
    assert row.bookmaker == "median"
    assert (row.odds_home, row.odds_draw, row.odds_away) == (2.00, 3.40, 4.20)
    assert (row.odds_over25, row.odds_under25) == (1.85, 1.95)
    # Margin removed: implied probabilities sum to exactly 1.
    total = row.implied_prob_home + row.implied_prob_draw + row.implied_prob_away
    assert total == pytest.approx(1.0)
    assert row.implied_prob_home == pytest.approx((1 / 2.00) / (1 / 2.00 + 1 / 3.40 + 1 / 4.20))
    assert row.captured_at is not None


def test_refresh_skips_matches_outside_the_window(db_session, monkeypatch):
    _seed_match(db_session, hours_to_kickoff=100.0)  # beyond the 48h default
    calls = []
    monkeypatch.setattr(odds_mod, "fetch_odds",
                        lambda key, fid, timeout=15.0: calls.append(fid) or [])
    refresh_odds(db_session, "key")
    assert calls == []


def test_refresh_skips_unresolvable_fixture_ids(db_session, monkeypatch):
    _seed_match(db_session, fixture_id=None)
    monkeypatch.setattr(odds_mod, "_fixture_id", lambda db, m, key: None)
    calls = []
    monkeypatch.setattr(odds_mod, "fetch_odds",
                        lambda key, fid, timeout=15.0: calls.append(fid) or [])
    summary = refresh_odds(db_session, "key")
    assert calls == [] and summary["matches_priced"] == 0
