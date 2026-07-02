"""Shadow prediction generation + scoring (exact-score program FR-4.4/4.5/4.6).

Every production prediction gets a shadow twin tagged
``poisson-elo-v0.3-shadow`` / ``is_shadow=True``. With no stored odds (or
``w_odds`` = 0, the shipped default) the twin carries IDENTICAL numbers — the
production-vs-shadow comparison is then a clean null test. With a market
total stored and ``w_odds`` > 0 the twin's lambda SUM moves toward the market
while the Elo split is preserved (FR-4.3). The learning loop scores shadow
rows into their own PredictionResult records without ever touching the
production record.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Match, Odds, Prediction, PredictionResult, Team
from ml.models.params import DEFAULT_PARAMS
from pipeline.generate_predictions import SHADOW_MODEL_VERSION, generate_predictions
from pipeline.ingest.wc26_structure import load_structure
from pipeline.learning_loop import (
    _frozen_prediction,
    evaluate_finished_shadow_predictions,
    run_learning_loop,
)

MV = "poisson-elo-v0.1"


def _set_elos(db):
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _seed(db, n_sims=120):
    load_structure(db)
    _set_elos(db)
    generate_predictions(db, MV, n_sims=n_sims, tournament_sims=50)


def _finish(db, match: Match, score_home: int, score_away: int):
    kickoff = datetime.now(timezone.utc) - timedelta(hours=3)
    match.kickoff_utc = kickoff
    for p in db.query(Prediction).filter_by(match_id=match.id).all():
        p.created_at = kickoff - timedelta(days=1)
    match.status = "finished"
    match.score_home = score_home
    match.score_away = score_away
    db.commit()


def _first_group_match(db) -> Match:
    return (
        db.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .order_by(Match.id)
        .first()
    )


# --- generation (FR-4.4) ------------------------------------------------------

def test_every_production_prediction_gets_a_shadow_twin(db_session):
    _seed(db_session)
    prod = db_session.query(Prediction).filter(Prediction.is_shadow.is_(False)).count()
    shadow = db_session.query(Prediction).filter(Prediction.is_shadow.is_(True)).all()
    assert prod == 72 and len(shadow) == 72
    assert {s.model_version for s in shadow} == {SHADOW_MODEL_VERSION}


def test_shadow_equals_production_without_odds(db_session):
    """No Odds row -> pure Elo lambdas: the twin must be numerically identical,
    so any later divergence in the record is attributable to the blend alone."""
    _seed(db_session)
    m = _first_group_match(db_session)
    prod = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=False).one())
    shad = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=True).one())
    assert (shad.prob_home_win, shad.prob_draw, shad.prob_away_win) == (
        prod.prob_home_win, prod.prob_draw, prod.prob_away_win)
    assert (shad.predicted_score_home, shad.predicted_score_away) == (
        prod.predicted_score_home, prod.predicted_score_away)
    assert (shad.lambda_home, shad.lambda_away) == (prod.lambda_home, prod.lambda_away)


def test_shadow_blends_lambda_total_toward_market(db_session, monkeypatch):
    """Odds stored + w_odds > 0: the shadow twin's lambda SUM moves toward the
    market total, the Elo split survives, and production stays untouched."""
    import pipeline.generate_predictions as gp
    from ml.models.poisson import poisson_pmf

    load_structure(db_session)
    _set_elos(db_session)
    m = _first_group_match(db_session)

    market_total = 2.0  # OU-2.5 prices implying exactly 2.0 expected goals
    p_over = 1.0 - sum(poisson_pmf(k, market_total) for k in range(3))
    db_session.add(Odds(match_id=m.id, bookmaker="median",
                        odds_over25=1.0 / p_over, odds_under25=1.0 / (1.0 - p_over),
                        captured_at=datetime.now(timezone.utc)))
    db_session.commit()

    w = 0.5
    monkeypatch.setattr(gp, "load_params", lambda: replace(DEFAULT_PARAMS, w_odds=w))
    generate_predictions(db_session, n_sims=120, tournament_sims=50)

    prod = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=False).one()
    shad = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=True).one()
    prod_total = prod.lambda_home + prod.lambda_away
    expected_total = (1 - w) * prod_total + w * market_total
    assert shad.lambda_home + shad.lambda_away == pytest.approx(expected_total, abs=1e-3)
    assert shad.lambda_home / shad.lambda_away == pytest.approx(
        prod.lambda_home / prod.lambda_away, abs=1e-3)
    # Production numbers are the pure Elo engine's — the blend never leaks in.
    assert prod.model_version != SHADOW_MODEL_VERSION

    # Anchoring a high-scoring card down to 2.0 total must soften the triple.
    if prod_total > market_total:
        assert shad.prob_draw >= prod.prob_draw


def test_shadow_with_odds_but_weight_zero_is_identical(db_session):
    """FR-4.8 safety: stored odds with the shipped w_odds=0 must change nothing
    — the served default cannot silently activate the blend."""
    load_structure(db_session)
    _set_elos(db_session)
    m = _first_group_match(db_session)
    db_session.add(Odds(match_id=m.id, bookmaker="median",
                        odds_over25=1.8, odds_under25=2.1,
                        captured_at=datetime.now(timezone.utc)))
    db_session.commit()

    generate_predictions(db_session, MV, n_sims=120, tournament_sims=50)

    prod = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=False).one()
    shad = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=True).one()
    assert (shad.lambda_home, shad.lambda_away) == (prod.lambda_home, prod.lambda_away)
    assert (shad.prob_home_win, shad.prob_draw, shad.prob_away_win) == (
        prod.prob_home_win, prod.prob_draw, prod.prob_away_win)


# --- frozen-prediction exclusion (FR-4.5) --------------------------------------

def test_frozen_prediction_never_picks_a_shadow_row(db_session):
    """Exclusion (evaluation): the frozen snapshot is the latest PRODUCTION row
    before kickoff — a newer shadow row must not corrupt the audited record."""
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 1, 0)
    # Make the shadow twin the NEWEST pre-kickoff row.
    shad = db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=True).one()
    shad.created_at = m.kickoff_utc - timedelta(minutes=1)
    db_session.commit()

    frozen = _frozen_prediction(db_session, m)
    assert frozen is not None
    assert frozen.is_shadow is False


# --- shadow scoring (FR-4.6) ----------------------------------------------------

def test_learning_loop_scores_shadow_rows_separately(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 1, 0)

    summary = run_learning_loop(db_session, MV)
    assert summary["evaluated_new"] == 1
    assert summary["shadow_evaluated_new"] == 1

    prod = db_session.query(PredictionResult).filter_by(is_shadow=False).one()
    shad = db_session.query(PredictionResult).filter_by(is_shadow=True).one()
    assert prod.match_id == shad.match_id == m.id
    assert shad.model_version == SHADOW_MODEL_VERSION
    assert prod.model_version != SHADOW_MODEL_VERSION
    # Identical twins (no odds) -> identical evaluation numbers: the null test.
    assert shad.brier == prod.brier
    assert shad.exact_score_correct == prod.exact_score_correct

    # Idempotent, exactly like the production path.
    again = run_learning_loop(db_session, MV)
    assert again["evaluated_new"] == 0
    assert again["shadow_evaluated_new"] == 0
    assert db_session.query(PredictionResult).count() == 2


def test_shadow_scoring_skips_matches_without_shadow_rows(db_session):
    """Pre-Phase-4 matches have no shadow twin: shadow scoring must skip them
    silently rather than inventing a comparison."""
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 1, 0)
    for s in db_session.query(Prediction).filter_by(match_id=m.id, is_shadow=True).all():
        db_session.delete(s)
    db_session.commit()

    assert evaluate_finished_shadow_predictions(db_session) == 0
    assert db_session.query(PredictionResult).filter_by(is_shadow=True).count() == 0
