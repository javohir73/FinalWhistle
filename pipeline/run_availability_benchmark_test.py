from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.availability_benchmark import benchmark_availability
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION
from pipeline.run_availability_benchmark import (
    _verdict, availability_gate, availability_record,
)

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
    # A valid BOTH-rows match alongside a published-only (twinless) match: the
    # twinless one must be dropped WHILE the valid one survives — proving
    # exclusion, not merely an empty result an empty DB would also produce.
    db = _session()
    wc, home, away = _fixture(db)
    good = _finished(db, wc, home, away, 2, 0)
    _pred(db, good, "poisson-elo-v0.2", (0.55, 0.25, 0.20), is_shadow=False)
    _pred(db, good, AVAILABILITY_MODEL_VERSION, (0.70, 0.18, 0.12), is_shadow=True)
    twinless = _finished(db, wc, home, away, 1, 0)
    _pred(db, twinless, "poisson-elo-v0.2", (0.5, 0.3, 0.2), is_shadow=False)  # no twin
    db.commit()
    assert availability_record(db)["n_matches"] == 1


def test_honest_empty_with_no_data():
    assert availability_record(_session()) == _EMPTY


def test_verdict_covers_all_three_branches():
    assert _verdict((-0.05, -0.01)) == "availability_beats_published"  # CI hi < 0
    assert _verdict((0.01, 0.05)) == "published_beats_availability"    # CI lo > 0
    assert _verdict((-0.02, 0.03)) == "no_credible_difference"          # straddles 0


# --- availability_gate --------------------------------------------------------

def test_gate_met_with_enough_matches_and_winning_ci():
    rec = {"n_matches": 25, "diff_log_loss": -0.04, "diff_ci95": [-0.08, -0.01]}
    gate = availability_gate(rec)
    assert gate["met"] is True
    assert gate["n"] == 25 and gate["min_n"] == 20
    assert gate["delta_log_loss"] == -0.04
    assert "met" in gate["reason"]


def test_gate_not_met_below_min_n():
    rec = {"n_matches": 10, "diff_log_loss": -0.04, "diff_ci95": [-0.08, -0.01]}
    gate = availability_gate(rec)
    assert gate["met"] is False
    assert "min_n" in gate["reason"]


def test_gate_not_met_ci_straddles_zero():
    rec = {"n_matches": 30, "diff_log_loss": -0.01, "diff_ci95": [-0.05, 0.02]}
    gate = availability_gate(rec)
    assert gate["met"] is False
    assert gate["reason"] == "CI straddles zero"


def test_gate_handles_insufficient_record_shape():
    rec = {"n_matches": 0, "verdict": "insufficient", "production": None,
           "availability": None, "diff_log_loss": None, "diff_ci95": None,
           "availability_win_rate": None}
    gate = availability_gate(rec)  # must not raise
    assert gate["met"] is False
    assert gate["n"] == 0
    assert gate["reason"] == "insufficient record"


def test_gate_respects_min_n_override():
    rec = {"n_matches": 10, "diff_log_loss": -0.04, "diff_ci95": [-0.08, -0.01]}
    assert availability_gate(rec, min_n=5)["met"] is True
    assert availability_gate(rec, min_n=20)["met"] is False


def test_gate_met_at_exactly_min_n():
    rec = {"n_matches": 20, "diff_log_loss": -0.04, "diff_ci95": [-0.08, -0.01]}
    assert availability_gate(rec)["met"] is True  # n == min_n, not just >


def test_gate_not_met_ci_upper_bound_exactly_zero():
    rec = {"n_matches": 25, "diff_log_loss": -0.02, "diff_ci95": [-0.05, 0.0]}
    gate = availability_gate(rec)
    assert gate["met"] is False  # hi < 0 required; hi == 0 doesn't count
    assert gate["reason"] == "CI straddles zero"


def test_gate_not_met_ci_wrong_length():
    rec = {"n_matches": 25, "diff_log_loss": -0.02, "diff_ci95": [-0.05]}
    gate = availability_gate(rec)  # must not raise
    assert gate["met"] is False
    assert gate["reason"] == "insufficient record"
