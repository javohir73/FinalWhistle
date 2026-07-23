import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Odds, Prediction, Team, Tournament
from pipeline.run_market_benchmark import market_record


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _finished_match(db, wc, home, away, ko):
    m = Match(tournament_id=wc.id, team_home_id=home.id, team_away_id=away.id,
              stage="group", status="finished", score_home=2, score_away=0, kickoff_utc=ko)
    db.add(m); db.flush()
    return m


def test_market_record_scores_matches_with_odds_and_prediction():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.add(Odds(match_id=m.id, bookmaker="median",
                odds_home=1.6, odds_draw=3.8, odds_away=6.0,
                implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
                captured_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)))
    db.commit()

    rec = market_record(db)
    assert rec["status"] == "ready"
    assert rec["n_matches"] == 1
    assert rec["model"] is not None and rec["market"] is not None
    assert isinstance(rec["diff_ci95"], list) and len(rec["diff_ci95"]) == 2
    assert rec["verdict"]  # a non-empty verdict string
    assert "closing line" not in (rec["dataset"] or "").lower()  # honest label


def test_market_record_is_honest_empty_without_odds():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)
    db.add(Prediction(match_id=m.id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)))
    db.commit()  # no Odds row -> nothing benchmarkable

    rec = market_record(db)
    assert rec["status"] == "pending"
    assert rec["n_matches"] == 0
    assert rec["model"] is None and rec["market"] is None
    assert rec["diff_ci95"] is None and rec["verdict"] is None


# --- phased archive: closing-line preference + opening-line comparison -----------

def _prediction(match_id, ko):
    return Prediction(match_id=match_id, model_version="poisson-elo-v0.1",
                      prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
                      predicted_score_home=2, predicted_score_away=0, is_shadow=False,
                      created_at=ko - timedelta(hours=12))


def test_market_record_prefers_closing_row_regardless_of_capture_order():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)  # score 2-0 -> label H
    db.add(_prediction(m.id, ko))
    # The closing row is captured EARLIER than the t6 row (unusual ordering,
    # on purpose) — selection must key off snapshot_phase, not recency.
    db.add(Odds(match_id=m.id, bookmaker="median", snapshot_phase="closing",
                implied_prob_home=0.90, implied_prob_draw=0.07, implied_prob_away=0.03,
                captured_at=ko - timedelta(hours=5)))
    db.add(Odds(match_id=m.id, bookmaker="median", snapshot_phase="t6",
                implied_prob_home=0.10, implied_prob_draw=0.30, implied_prob_away=0.60,
                captured_at=ko - timedelta(hours=1)))
    db.commit()

    rec = market_record(db)

    assert rec["status"] == "ready"
    # n=1, label H -> market log-loss is exactly -log(implied_prob_home) of
    # whichever row was picked; asserting it matches the CLOSING row (0.90),
    # not the more-recently-captured t6 row (0.10), proves the preference.
    assert rec["market"]["log_loss"] == pytest.approx(-math.log(0.90), abs=1e-4)


def test_market_record_falls_back_to_latest_row_without_a_closing_snapshot():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    m = _finished_match(db, wc, home, away, ko)
    db.add(_prediction(m.id, ko))
    # No closing phase captured — two legacy (NULL-phase) rows; the latest
    # pre-kickoff one wins, same as before this feature existed.
    db.add(Odds(match_id=m.id, bookmaker="median",
                implied_prob_home=0.50, implied_prob_draw=0.30, implied_prob_away=0.20,
                captured_at=ko - timedelta(hours=10)))
    db.add(Odds(match_id=m.id, bookmaker="median",
                implied_prob_home=0.80, implied_prob_draw=0.14, implied_prob_away=0.06,
                captured_at=ko - timedelta(hours=2)))
    db.commit()

    rec = market_record(db)

    assert rec["status"] == "ready"
    assert rec["market"]["log_loss"] == pytest.approx(-math.log(0.80), abs=1e-4)


def _match_with_opening_and_closing(db, wc, home, away, ko):
    m = _finished_match(db, wc, home, away, ko)
    db.add(_prediction(m.id, ko))
    db.add(Odds(match_id=m.id, bookmaker="median", snapshot_phase="closing",
                implied_prob_home=0.60, implied_prob_draw=0.26, implied_prob_away=0.14,
                captured_at=ko - timedelta(minutes=20)))
    db.add(Odds(match_id=m.id, bookmaker="median", snapshot_phase="opening",
                implied_prob_home=0.50, implied_prob_draw=0.30, implied_prob_away=0.20,
                captured_at=ko - timedelta(hours=40)))
    return m


def test_opening_comparison_present_once_ten_matches_qualify():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    for i in range(10):
        ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc) + timedelta(days=i)
        _match_with_opening_and_closing(db, wc, home, away, ko)
    db.commit()

    rec = market_record(db)

    assert rec["n_matches"] == 10
    assert "opening_comparison" in rec
    assert rec["opening_comparison"]["status"] == "ready"
    assert rec["opening_comparison"]["n_matches"] == 10
    # Additive only — the primary comparison keeps using the closing row.
    assert rec["market"]["log_loss"] != rec["opening_comparison"]["market"]["log_loss"]


def test_opening_comparison_absent_below_ten_matches():
    db = _session()
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    for i in range(9):
        ko = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc) + timedelta(days=i)
        _match_with_opening_and_closing(db, wc, home, away, ko)
    db.commit()

    rec = market_record(db)

    assert rec["n_matches"] == 9
    assert "opening_comparison" not in rec
