"""Writeup persistence through the prediction pipeline: production rows carry
the four-section narrative; shadow twins stay lean (the writeup is
presentation, twins are internal-only and never rendered)."""
from app.models import Prediction, Team
from pipeline.generate_predictions import generate_predictions
from pipeline.ingest.wc26_structure import load_structure

MV = "poisson-elo-v0.1"


def _seed(db):
    load_structure(db)
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()
    generate_predictions(db, MV, n_sims=120, tournament_sims=50)


def test_production_rows_carry_a_writeup(db_session):
    _seed(db_session)
    prods = db_session.query(Prediction).filter(Prediction.is_shadow.is_(False)).all()
    assert prods
    for p in prods:
        assert p.writeup is not None
        assert set(p.writeup) == {"case_home", "case_away", "call", "caveat"}
        assert all(isinstance(v, str) and v for v in p.writeup.values())


def test_writeup_call_agrees_with_the_stored_triple(db_session):
    _seed(db_session)
    p = db_session.query(Prediction).filter(Prediction.is_shadow.is_(False)).first()
    top = max(p.prob_home_win, p.prob_draw, p.prob_away_win)
    if top == p.prob_draw:
        assert p.writeup["call"].startswith("Too close to call")
    else:
        assert p.writeup["call"].endswith(".") and " to win — " in p.writeup["call"]


def test_shadow_rows_stay_lean(db_session):
    _seed(db_session)
    shadows = db_session.query(Prediction).filter(Prediction.is_shadow.is_(True)).all()
    assert shadows
    assert all(s.writeup is None for s in shadows)
