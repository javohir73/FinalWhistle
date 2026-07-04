"""Tests for the xG-offsets shadow twin (Phase 6, StatsBomb xG team offsets).

Mirrors pipeline/generate_predictions_test.py's availability-twin tests: an
in-memory SQLite DB, a scheduled match, and a monkeypatched load_team_offsets
so the twin logic is exercised without touching the real (possibly absent)
ml/models/team_offsets_xg.json store.
"""
import math

from app.models import Match, Prediction, Team
from ml.models.params import DEFAULT_PARAMS
from pipeline import generate_predictions
from pipeline.generate_predictions import (
    AVAILABILITY_MODEL_VERSION,
    OFFSETS_MODEL_VERSION,
    write_offsets_prediction,
)


def _payload(match_id):
    return {"match_id": match_id, "lambda_home": 2.0, "lambda_away": 1.0, "rho": -0.1,
            "probabilities": {"home_win": 0.55, "draw": 0.27, "away_win": 0.18},
            "predicted_score": {"home": 2, "away": 1, "probability": 0.12},
            "confidence": "Medium", "reasons": ["a", "b", "c"], "top_features": []}


def _scheduled_match(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    h.elo_rating = a.elo_rating = 1700.0
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    return m, h, a


def test_no_offsets_writes_no_row(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    monkeypatch.setattr(generate_predictions, "load_team_offsets", lambda path=None: {})
    write_offsets_prediction(db_session, m, _payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=OFFSETS_MODEL_VERSION).count() == 0)


def test_scales_lambdas_and_tags(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    store = {
        "France": {"atk": 0.05, "def": -0.02, "n_matches": 40},
        "Senegal": {"atk": -0.03, "def": 0.01, "n_matches": 40},
    }
    monkeypatch.setattr(generate_predictions, "load_team_offsets", lambda path=None: store)
    payload = _payload(m.id)
    write_offsets_prediction(db_session, m, payload, {}, DEFAULT_PARAMS)
    db_session.commit()
    twin = (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=OFFSETS_MODEL_VERSION).one())
    assert twin.is_shadow is True
    # atk_h + def_a = 0.05 + 0.01 = 0.06 ; atk_a + def_h = -0.03 + (-0.02) = -0.05
    expected_lam_h = payload["lambda_home"] * math.exp(0.05 + 0.01)
    expected_lam_a = payload["lambda_away"] * math.exp(-0.03 + -0.02)
    assert twin.lambda_home == round(expected_lam_h, 4) or abs(twin.lambda_home - expected_lam_h) < 0.01
    assert twin.lambda_away == round(expected_lam_a, 4) or abs(twin.lambda_away - expected_lam_a) < 0.01
    assert twin.lambda_home > payload["lambda_home"]  # net positive cross-term for home
    assert twin.lambda_away < payload["lambda_away"]  # net negative cross-term for away


def test_production_and_other_twins_untouched(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    payload = _payload(m.id)
    generate_predictions._write_prediction(db_session, m, payload, "poisson-elo-v0.1")
    generate_predictions.write_availability_prediction(db_session, m, payload, {}, DEFAULT_PARAMS)
    db_session.commit()
    prod_before = (db_session.query(Prediction)
                   .filter_by(match_id=m.id, model_version="poisson-elo-v0.1").one())
    prod_lambda_before = prod_before.lambda_home

    store = {"France": {"atk": 0.05, "def": -0.02, "n_matches": 40},
             "Senegal": {"atk": -0.03, "def": 0.01, "n_matches": 40}}
    monkeypatch.setattr(generate_predictions, "load_team_offsets", lambda path=None: store)
    write_offsets_prediction(db_session, m, payload, {}, DEFAULT_PARAMS)
    db_session.commit()

    prod_after = (db_session.query(Prediction)
                  .filter_by(match_id=m.id, model_version="poisson-elo-v0.1").one())
    assert prod_after.lambda_home == prod_lambda_before

    avail_count = (db_session.query(Prediction)
                   .filter_by(match_id=m.id, model_version=AVAILABILITY_MODEL_VERSION).count())
    assert avail_count == 0  # no lineups stored -> availability twin never wrote a row (unchanged)

    offsets_count = (db_session.query(Prediction)
                     .filter_by(match_id=m.id, model_version=OFFSETS_MODEL_VERSION).count())
    assert offsets_count == 1


def test_independent_of_team_offsets_flag(db_session, monkeypatch):
    m, h, a = _scheduled_match(db_session)
    store = {"France": {"atk": 0.05, "def": -0.02, "n_matches": 40},
             "Senegal": {"atk": -0.03, "def": 0.01, "n_matches": 40}}
    monkeypatch.setattr(generate_predictions, "load_team_offsets", lambda path=None: store)
    assert DEFAULT_PARAMS.team_offsets is None
    write_offsets_prediction(db_session, m, _payload(m.id), {}, DEFAULT_PARAMS)
    db_session.commit()
    assert (db_session.query(Prediction)
            .filter_by(match_id=m.id, model_version=OFFSETS_MODEL_VERSION).count() == 1)
