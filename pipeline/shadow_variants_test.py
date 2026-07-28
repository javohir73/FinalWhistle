"""Opt-in shadow variants — default OFF, served bytes unchanged, fail-closed.

The live-validation vehicle for the T1.6 Bundesliga q3 recalibrator
(docs/MODEL-EXPERIMENTS.md). Nothing here promotes anything; these tests exist
to prove the mechanism cannot affect what users see.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.models import Prediction, Team
from ml.evaluation.calibration import assert_servable_calibrator, calibrate
from ml.models.params import DEFAULT_PARAMS, load_params
from pipeline.generate_predictions import (
    generate_predictions,
    variant_model_version_for,
)
from pipeline.ingest.wc26_structure import load_structure

MV = "poisson-elo-club-v0.2"
Q3 = {
    "method": "vector_scaling_segmented_edges",
    "by": "effective_elo_gap",
    "edges": [68.6, 163.4],
    "buckets": {
        "0-68.6": {"t": 1.35, "b": [0.0, 0.25, -0.10]},
        "68.6-163.4": {"t": 1.10, "b": [0.0, 0.10, 0.0]},
        "163.4+": {"t": 0.95, "b": [0.0, -0.15, 0.20]},
    },
    "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},
}


def _seed(db):
    load_structure(db)
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _served(db):
    """Every field a user could observe, per production row."""
    return {
        p.match_id: (p.prob_home_win, p.prob_draw, p.prob_away_win,
                     p.lambda_home, p.lambda_away, p.rho,
                     p.predicted_score_home, p.predicted_score_away,
                     p.predicted_score_prob)
        for p in db.query(Prediction).filter_by(model_version=MV, is_shadow=False).all()
    }


# --- fail-closed calibrator gate -------------------------------------------

def test_unservable_calibrator_method_is_rejected():
    with pytest.raises(ValueError, match="not implemented"):
        assert_servable_calibrator({"method": "totally_made_up"})


def test_edges_method_without_edges_is_rejected():
    with pytest.raises(ValueError, match="requires non-empty 'edges'"):
        assert_servable_calibrator({"method": "vector_scaling_segmented_edges",
                                    "edges": [], "buckets": {}, "default": {}})


def test_none_and_known_methods_are_servable():
    assert assert_servable_calibrator(None) is None
    assert assert_servable_calibrator({"method": "vector_scaling"}) is None
    assert assert_servable_calibrator({"method": "vector_scaling_segmented"}) is None
    assert assert_servable_calibrator(Q3) is None


def test_the_q3_blob_actually_calibrates_rather_than_silently_degrading():
    """The exact trap this gate exists for: calibrate() falls through to
    temperature on an unrecognised method, so a q3 twin would have logged the
    identity and looked healthy."""
    from ml.evaluation.calibration import apply_temperature

    p = (0.5, 0.25, 0.25)
    out = calibrate(p, Q3, 1.0, eff_gap=10.0)
    assert out != apply_temperature(p, 1.0)
    assert out != p
    assert sum(out) == pytest.approx(1.0)


def test_edges_blob_selects_the_bucket_the_gap_falls_in():
    from ml.evaluation.calibration import apply_vector_scaling

    p = (0.5, 0.25, 0.25)
    for gap, key in ((10.0, "0-68.6"), (100.0, "68.6-163.4"), (400.0, "163.4+")):
        cell = Q3["buckets"][key]
        assert calibrate(p, Q3, 1.0, eff_gap=gap) == apply_vector_scaling(
            p, cell["t"], tuple(cell["b"]))


# --- version isolation -----------------------------------------------------

def test_variant_tag_is_scoped_to_its_production_family():
    assert variant_model_version_for(MV, "cal_q3") == "poisson-elo-club-v0.2+cal_q3"
    assert (variant_model_version_for("poisson-elo-v0.5", "cal_q3")
            != variant_model_version_for(MV, "cal_q3"))


def test_variant_tag_rejects_names_that_would_corrupt_the_ledger():
    for bad in ("", "a+b", "a/b"):
        with pytest.raises(ValueError):
            variant_model_version_for(MV, bad)


# --- default OFF, served bytes unchanged -----------------------------------

def test_no_variant_rows_are_written_by_default(db_session):
    _seed(db_session)
    generate_predictions(db_session, MV, n_sims=60, tournament_sims=30)
    assert [p for p in db_session.query(Prediction).all()
            if "+cal_" in p.model_version] == []


def test_enabling_a_variant_leaves_served_predictions_byte_identical(db_session):
    """The guarantee the whole design rests on."""
    _seed(db_session)
    generate_predictions(db_session, MV, n_sims=60, tournament_sims=30)
    before = _served(db_session)

    for row in db_session.query(Prediction).all():
        db_session.delete(row)
    db_session.commit()

    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={"cal_q3": replace(load_params(), version=MV, calibrator=Q3)},
    )
    assert _served(db_session) == before


def test_variant_rows_are_shadow_and_correctly_tagged(db_session):
    _seed(db_session)
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={"cal_q3": replace(load_params(), version=MV, calibrator=Q3)},
    )
    rows = db_session.query(Prediction).filter_by(
        model_version=f"{MV}+cal_q3").all()
    assert rows
    assert all(r.is_shadow for r in rows)
    assert len(rows) == len(_served(db_session))


def test_multiple_variants_are_logged_side_by_side(db_session):
    _seed(db_session)
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        baseline_params=replace(DEFAULT_PARAMS, version=MV),
        shadow_variants={"cal_q3": replace(load_params(), version=MV, calibrator=Q3)},
    )
    tags = {p.model_version for p in db_session.query(Prediction).all()}
    assert {MV, f"{MV}+baseline", f"{MV}+cal_q3"} <= tags


# --- the totals/BTTS/exact-score regression check --------------------------

def test_a_calibrator_only_variant_cannot_move_any_market_probability(db_session):
    """Totals / BTTS / correct-score are provably untouched by calibration.

    goal_markets() is a pure function of (lambda_home, lambda_away, rho), and
    calibration acts only on the W/D/L triple. So the regression check for
    those markets is an EQUALITY assertion, which is far stronger than
    comparing two noisy estimates of them.
    """
    from ml.models.poisson import goal_markets

    _seed(db_session)
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={"cal_q3": replace(load_params(), version=MV, calibrator=Q3)},
    )
    prod = {p.match_id: p for p in db_session.query(Prediction).filter_by(
        model_version=MV, is_shadow=False).all()}
    variants = db_session.query(Prediction).filter_by(
        model_version=f"{MV}+cal_q3").all()
    assert variants

    for v in variants:
        p = prod[v.match_id]
        assert (v.lambda_home, v.lambda_away, v.rho) == (
            p.lambda_home, p.lambda_away, p.rho)
        assert (goal_markets(v.lambda_home, v.lambda_away, v.rho)
                == goal_markets(p.lambda_home, p.lambda_away, p.rho))

    # ...and the W/D/L triple genuinely differs, or the variant measures nothing.
    assert any(
        (v.prob_home_win, v.prob_draw, v.prob_away_win)
        != (prod[v.match_id].prob_home_win, prod[v.match_id].prob_draw,
            prod[v.match_id].prob_away_win)
        for v in variants
    )


def test_calibration_CAN_move_the_headline_scoreline_pick(db_session):
    """A real coupling worth knowing before anyone promotes a calibrator.

    predict_from_lambdas selects the displayed scoreline via
    `abs(p_home - p_away) <= DRAW_HEADLINE_BAND` on the CALIBRATED triple, so a
    calibration change can flip that band test and move the shown score even
    though it cannot move a single market probability. Promoting a calibrator
    is therefore a user-visible change, not a purely internal one.
    """
    _seed(db_session)
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={"cal_q3": replace(load_params(), version=MV, calibrator=Q3)},
    )
    prod = {p.match_id: p for p in db_session.query(Prediction).filter_by(
        model_version=MV, is_shadow=False).all()}
    variants = db_session.query(Prediction).filter_by(
        model_version=f"{MV}+cal_q3").all()

    moved = [v for v in variants
             if (v.predicted_score_home, v.predicted_score_away)
             != (prod[v.match_id].predicted_score_home,
                 prod[v.match_id].predicted_score_away)]
    assert moved, (
        "expected at least one headline scoreline to move under a calibrator "
        "swap; if this ever stops holding, re-check DRAW_HEADLINE_BAND before "
        "assuming calibration became display-neutral"
    )


# --- fail-closed on a bad variant ------------------------------------------

def test_a_broken_variant_is_dropped_without_touching_production(db_session):
    _seed(db_session)
    generate_predictions(db_session, MV, n_sims=60, tournament_sims=30)
    before = _served(db_session)
    for row in db_session.query(Prediction).all():
        db_session.delete(row)
    db_session.commit()

    bad = replace(load_params(), version=MV,
                  calibrator={"method": "not_a_real_method"})
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={"broken": bad},
    )
    # Production survived intact...
    assert _served(db_session) == before
    # ...and no misleading twin was logged.
    assert db_session.query(Prediction).filter_by(
        model_version=f"{MV}+broken").all() == []


def test_one_broken_variant_does_not_suppress_a_healthy_one(db_session):
    _seed(db_session)
    generate_predictions(
        db_session, MV, n_sims=60, tournament_sims=30,
        shadow_variants={
            "broken": replace(load_params(), version=MV,
                              calibrator={"method": "nope"}),
            "cal_q3": replace(load_params(), version=MV, calibrator=Q3),
        },
    )
    assert db_session.query(Prediction).filter_by(
        model_version=f"{MV}+broken").all() == []
    assert db_session.query(Prediction).filter_by(
        model_version=f"{MV}+cal_q3").all()
