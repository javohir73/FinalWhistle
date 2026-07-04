from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.availability_benchmark import benchmark_availability
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION
from pipeline.run_availability_benchmark import availability_record

_EMPTY = {"n_matches": 0, "verdict": "insufficient", "production": None,
          "availability": None, "diff_log_loss": None, "diff_ci95": None,
          "availability_win_rate": None}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _finished(db, wc, home, away, sh, sa):
    m = Match(tournament_id=wc.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=sh, score_away=sa)
    db.add(m); db.flush()
    return m


def _pred(db, m, mv, probs, *, is_shadow):
    db.add(Prediction(match_id=m.id, model_version=mv,
                      prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                      predicted_score_home=2, predicted_score_away=0, is_shadow=is_shadow))
    db.flush()


def _fixture(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    return wc, home, away


def test_scores_matches_with_both_rows():
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 2, 0)  # home win
    _pred(db, m, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)   # published
    _pred(db, m, AVAILABILITY_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)  # twin, surer on H
    db.commit()

    rec = availability_record(db)
    direct = benchmark_availability([(0.55, 0.25, 0.20)], [(0.70, 0.18, 0.12)], ["H"])
    assert {k: rec[k] for k in direct} == direct          # same numbers as calling the scorer directly
    assert rec["verdict"] == "availability_beats_published"  # twin surer on the actual winner


def test_excludes_match_missing_twin():
    db = _session()
    wc, home, away = _fixture(db)
    m = _finished(db, wc, home, away, 1, 0)
    _pred(db, m, "poisson-elo-v0.2", (0.5, 0.3, 0.2), is_shadow=False)  # published only, no twin
    db.commit()
    assert availability_record(db) == _EMPTY


def test_honest_empty_with_no_data():
    assert availability_record(_session()) == _EMPTY
