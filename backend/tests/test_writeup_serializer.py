"""prediction_to_out carries the stored writeup through to the API contract,
null-safe for pre-feature rows (writeup is NULL there)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from app.serializers import prediction_to_out

WRITEUP = {
    "case_home": "The model gives England a 50% chance of winning in 90 minutes.",
    "case_away": "The model gives Norway a 24% chance of winning in 90 minutes.",
    "call": "England to win — 50% in 90 minutes, with 2–1 the single most likely scoreline (about 11%).",
    "caveat": "A draw after 90 minutes is live at roughly one in 4 (26%).",
}


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, writeup):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="England"), Team(name="Norway")
    db.add_all([wc, home, away])
    db.flush()
    m = Match(tournament_id=wc.id, stage="quarterfinal", status="scheduled",
              team_home_id=home.id, team_away_id=away.id)
    db.add(m)
    db.flush()
    pred = Prediction(match_id=m.id, model_version="poisson-elo-v0.5",
                      prob_home_win=0.5, prob_draw=0.26, prob_away_win=0.24,
                      predicted_score_home=2, predicted_score_away=1,
                      predicted_score_prob=0.11, writeup=writeup)
    db.add(pred)
    db.commit()
    return m, pred


def test_prediction_out_includes_writeup():
    db = _session()
    m, pred = _seed(db, WRITEUP)
    out = prediction_to_out(db, m, pred)
    assert out.writeup is not None
    assert out.writeup.case_home == WRITEUP["case_home"]
    assert out.writeup.call == WRITEUP["call"]
    assert out.writeup.caveat == WRITEUP["caveat"]


def test_prediction_out_writeup_is_null_safe():
    db = _session()
    m, pred = _seed(db, None)
    assert prediction_to_out(db, m, pred).writeup is None
