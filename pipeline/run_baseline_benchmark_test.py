"""Tests for the served-vs-previous-params live record."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.baseline_benchmark import benchmark_baseline
from pipeline.generate_predictions import baseline_model_version_for
from pipeline.run_baseline_benchmark import baseline_record, format_record

SERVED = "poisson-elo-club-v0.2"
TWIN = baseline_model_version_for(SERVED)


def _match(db, tournament, idx: int, score: tuple[int, int]) -> Match:
    home = Team(name=f"H{idx}", is_host=False)
    away = Team(name=f"A{idx}", is_host=False)
    db.add_all([home, away])
    db.flush()
    m = Match(
        tournament_id=tournament.id, team_home_id=home.id, team_away_id=away.id,
        kickoff_utc=datetime.now(timezone.utc) - timedelta(days=2),
        status="finished", score_home=score[0], score_away=score[1], stage="group",
    )
    db.add(m)
    db.flush()
    return m


def _pred(db, match, version, probs, *, shadow: bool) -> None:
    db.add(Prediction(
        match_id=match.id, model_version=version, is_shadow=shadow,
        prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
    ))


def _seed(db, rows: list[tuple[tuple[int, int], tuple, tuple]]) -> None:
    t = Tournament(name="Test League", year=2026)
    db.add(t)
    db.flush()
    for i, (score, served, baseline) in enumerate(rows):
        m = _match(db, t, i, score)
        _pred(db, m, SERVED, served, shadow=False)
        _pred(db, m, TWIN, baseline, shadow=True)
    db.commit()


def test_returns_honest_empty_before_any_pair_exists(db_session):
    record = baseline_record(db_session)
    assert record["n_matches"] == 0
    assert record["verdict"] == "insufficient"
    assert record["by_model_version"] == {}
    assert "Nothing to compare" in format_record(record)


def test_a_match_without_a_twin_is_skipped(db_session):
    t = Tournament(name="Test League", year=2026)
    db_session.add(t)
    db_session.flush()
    m = _match(db_session, t, 0, (2, 0))
    _pred(db_session, m, SERVED, (0.6, 0.25, 0.15), shadow=False)
    db_session.commit()

    assert baseline_record(db_session)["n_matches"] == 0


def test_promotion_confirmed_when_served_params_are_credibly_better(db_session):
    """Served puts more mass on what happened, on every match."""
    _seed(db_session, [
        ((2, 0), (0.80, 0.12, 0.08), (0.50, 0.25, 0.25)),
        ((1, 0), (0.75, 0.15, 0.10), (0.45, 0.30, 0.25)),
        ((3, 1), (0.78, 0.13, 0.09), (0.48, 0.27, 0.25)),
        ((2, 1), (0.72, 0.16, 0.12), (0.44, 0.31, 0.25)),
    ] * 5)
    rec = baseline_record(db_session)["by_model_version"][SERVED]
    assert rec["diff_log_loss"] < 0
    assert rec["diff_ci95"][1] < 0
    assert rec["verdict"] == "promotion_confirmed_live"
    assert rec["served_win_rate"] == 1.0


def test_previous_params_flagged_when_they_were_better(db_session):
    """The sign convention has to catch a bad promotion, not just a good one."""
    _seed(db_session, [
        ((2, 0), (0.50, 0.25, 0.25), (0.80, 0.12, 0.08)),
        ((1, 0), (0.45, 0.30, 0.25), (0.75, 0.15, 0.10)),
        ((3, 1), (0.48, 0.27, 0.25), (0.78, 0.13, 0.09)),
        ((2, 1), (0.44, 0.31, 0.25), (0.72, 0.16, 0.12)),
    ] * 5)
    rec = baseline_record(db_session)["by_model_version"][SERVED]
    assert rec["diff_log_loss"] > 0
    assert rec["diff_ci95"][0] > 0
    assert rec["verdict"] == "previous_params_were_better"


def test_identical_predictions_give_no_credible_difference(db_session):
    same = (0.55, 0.25, 0.20)
    _seed(db_session, [((2, 0), same, same), ((0, 1), same, same)] * 6)
    rec = baseline_record(db_session)["by_model_version"][SERVED]
    assert rec["diff_log_loss"] == 0.0
    assert rec["verdict"] == "no_credible_difference"


def test_two_production_families_never_pool_into_one_comparison(db_session):
    """The leak every twin ledger in this repo has had to close."""
    t = Tournament(name="Test League", year=2026)
    db_session.add(t)
    db_session.flush()
    other = "poisson-elo-v0.5"
    for i, version in enumerate([SERVED, SERVED, other, other]):
        m = _match(db_session, t, i, (2, 0))
        _pred(db_session, m, version, (0.6, 0.25, 0.15), shadow=False)
        _pred(db_session, m, baseline_model_version_for(version),
              (0.5, 0.25, 0.25), shadow=True)
    db_session.commit()

    by_version = baseline_record(db_session)["by_model_version"]
    assert set(by_version) == {SERVED, other}
    assert by_version[SERVED]["n_matches"] == 2
    assert by_version[other]["n_matches"] == 2


def test_sign_convention_is_inverted_relative_to_the_feature_twins():
    """benchmark_baseline must report served-minus-baseline, not the reverse.

    Every other twin benchmark treats the twin as the challenger; here the twin
    is the OLD model. Getting this backwards would invert every verdict.
    """
    served_sharp = [(0.9, 0.05, 0.05)]
    baseline_flat = [(0.4, 0.3, 0.3)]
    res = benchmark_baseline(served_sharp, baseline_flat, ["H"])
    assert res["diff_log_loss"] < 0
    assert res["served_win_rate"] == 1.0
    assert res["served"]["log_loss"] < res["baseline"]["log_loss"]
