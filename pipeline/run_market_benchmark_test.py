from datetime import datetime, timezone

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
