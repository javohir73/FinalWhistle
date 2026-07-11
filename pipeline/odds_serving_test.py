"""Production odds-serving path (spec Part 2): OFF is bit-identical (the null
guarantee the promotion gate depends on); ON serves exactly the anchored math
the shadow twin has been logging (_odds_anchored is shared by both paths)."""
from dataclasses import replace
from datetime import datetime, timezone

import pipeline.generate_predictions as gp
from app.models import Match, Odds, Prediction, Team
from ml.models.params import DEFAULT_PARAMS
from pipeline.ingest.wc26_structure import load_structure

MV = "poisson-elo-v0.1"


def _seed(db):
    load_structure(db)
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _first_match(db):
    return (db.query(Match)
            .filter(Match.stage == "group", Match.team_home_id.isnot(None))
            .order_by(Match.id).first())


# _store_odds: seed one Odds row for the match. Copied VERBATIM (same fields,
# same idiom) from pipeline/shadow_predictions_test.py::
# test_shadow_blends_lambda_total_toward_market — that test is the source of
# truth for a valid market snapshot.
def _store_odds(db, match):
    from ml.models.poisson import poisson_pmf

    market_total = 2.0  # OU-2.5 prices implying exactly 2.0 expected goals
    p_over = 1.0 - sum(poisson_pmf(k, market_total) for k in range(3))
    db.add(Odds(match_id=match.id, bookmaker="median",
                odds_over25=1.0 / p_over, odds_under25=1.0 / (1.0 - p_over),
                captured_at=datetime.now(timezone.utc)))
    db.commit()


def test_use_odds_off_is_bit_identical(db_session):
    """w_odds armed but use_odds False (today's shipped state): the served
    payload must not move even with a market snapshot stored."""
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    armed = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    plain = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.0, use_odds=False))
    assert armed["probabilities"] == plain["probabilities"]
    assert armed["lambda_home"] == plain["lambda_home"]
    assert armed["lambda_away"] == plain["lambda_away"]


def test_use_odds_on_moves_the_served_lambdas(db_session):
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    plain = gp.build_payload(db_session, m, MV,
                             params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    served = gp.build_payload(db_session, m, MV,
                              params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True))
    assert (served["lambda_home"], served["lambda_away"]) != (
        plain["lambda_home"], plain["lambda_away"])


def test_use_odds_without_stored_odds_is_a_no_op(db_session):
    _seed(db_session)
    m = _first_match(db_session)  # no Odds row seeded
    on = gp.build_payload(db_session, m, MV,
                          params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True))
    off = gp.build_payload(db_session, m, MV,
                           params=replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=False))
    assert on["probabilities"] == off["probabilities"]


def test_shadow_twin_mirrors_production_after_promotion(db_session, monkeypatch):
    """Post-promotion the twin must COPY production, not re-anchor already
    anchored lambdas (double blend) — record continuity for the null test."""
    _seed(db_session)
    m = _first_match(db_session)
    _store_odds(db_session, m)
    promoted = replace(DEFAULT_PARAMS, w_odds=0.4, use_odds=True)
    monkeypatch.setattr(gp, "load_params", lambda: promoted)
    gp.generate_predictions(db_session, MV, n_sims=120, tournament_sims=50)
    prod = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=False).one())
    shad = (db_session.query(Prediction)
            .filter_by(match_id=m.id, is_shadow=True,
                       model_version=gp.SHADOW_MODEL_VERSION).one())
    assert (prod.prob_home_win, prod.prob_draw, prod.prob_away_win) == (
        shad.prob_home_win, shad.prob_draw, shad.prob_away_win)
    assert (prod.lambda_home, prod.lambda_away) == (shad.lambda_home, shad.lambda_away)
