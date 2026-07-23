"""Tests for the phased odds snapshot CLI (pipeline/snapshot_odds.py) —
just the exit-code contract; snapshot_phased_odds itself is covered by
pipeline/ingest/odds_test.py."""
import sys

import app.db
from app.config import settings
import pipeline.ingest.odds as odds_mod
import pipeline.snapshot_odds as snapshot_odds


def test_main_returns_0_when_api_key_is_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "api_football_api_key", "")
    monkeypatch.setattr(sys, "argv", ["snapshot_odds.py"])

    assert snapshot_odds.main() == 0


def test_main_returns_1_on_a_whole_pass_failure(monkeypatch, db_session, capsys):
    monkeypatch.setattr(settings, "api_football_api_key", "key")
    db_session.close = lambda: None  # the fixture owns teardown, not main()
    monkeypatch.setattr(app.db, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(odds_mod, "snapshot_phased_odds",
                        lambda *a, **k: {"matches_priced": 0, "matches_skipped": 0,
                                          "budget_skipped": 0, "error": "db gone"})
    monkeypatch.setattr(sys, "argv", ["snapshot_odds.py"])

    rc = snapshot_odds.main()

    assert rc == 1
    assert "error" in capsys.readouterr().out  # printed for the Action's log


def test_main_returns_0_when_the_pass_completes_without_an_error_key(monkeypatch, db_session):
    monkeypatch.setattr(settings, "api_football_api_key", "key")
    db_session.close = lambda: None
    monkeypatch.setattr(app.db, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(odds_mod, "snapshot_phased_odds",
                        lambda *a, **k: {"matches_priced": 0, "matches_skipped": 3,
                                          "budget_skipped": 0})  # per-match misses only
    monkeypatch.setattr(sys, "argv", ["snapshot_odds.py"])

    assert snapshot_odds.main() == 0
