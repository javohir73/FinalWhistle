"""Tests for the shadow-calibrator benchmark. Hermetic; no network, no fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Match, Odds, Prediction, Team, Tournament
from pipeline.generate_predictions import variant_model_version_for
from pipeline.run_calibrator_benchmark import (
    MIN_PAIRS_CONFIRM,
    MIN_PAIRS_MONITOR,
    ROLLBACK_DELTA,
    calibrator_record,
    format_record,
    verdict,
)

PROD = "poisson-elo-club-v0.2"
VARIANT = "cal_q3"
TAG = variant_model_version_for(PROD, VARIANT)
KO = datetime(2026, 9, 12, 13, 30, tzinfo=timezone.utc)


def _mk(db, idx, score, *, prod_probs, var_probs=None, prod_version=PROD,
        var_version=None, kickoff=None, lam=(1.5, 1.1), rho=-0.06, ps=(1, 1)):
    t = db.query(Tournament).filter_by(name="T").one_or_none()
    if t is None:
        t = Tournament(name="T", year=2026)
        db.add(t)
        db.flush()
    h, a = Team(name=f"H{idx}", is_host=False), Team(name=f"A{idx}", is_host=False)
    db.add_all([h, a])
    db.flush()
    m = Match(tournament_id=t.id, team_home_id=h.id, team_away_id=a.id,
              kickoff_utc=(kickoff or KO) + timedelta(days=idx // 9 * 7),
              status="finished", score_home=score[0], score_away=score[1], stage="group")
    db.add(m)
    db.flush()

    def row(version, probs, shadow):
        db.add(Prediction(match_id=m.id, model_version=version, is_shadow=shadow,
                          prob_home_win=probs[0], prob_draw=probs[1],
                          prob_away_win=probs[2], lambda_home=lam[0],
                          lambda_away=lam[1], rho=rho,
                          predicted_score_home=ps[0], predicted_score_away=ps[1]))

    row(prod_version, prod_probs, False)
    if var_probs is not None:
        row(var_version or variant_model_version_for(prod_version, VARIANT),
            var_probs, True)
    return m


def _seed(db, n, prod_probs, var_probs, score=(2, 0)):
    for i in range(n):
        _mk(db, i, score, prod_probs=prod_probs, var_probs=var_probs)
    db.commit()


# --- gate arithmetic --------------------------------------------------------

def test_verdict_is_insufficient_below_the_monitoring_floor():
    assert verdict(MIN_PAIRS_MONITOR - 1, -0.05, (-0.09, -0.01)) == "insufficient"
    assert verdict(0, None, None) == "insufficient"


def test_verdict_rolls_back_on_harm_even_while_underpowered_to_confirm():
    """One season is powered to detect harm, not to confirm benefit."""
    n = MIN_PAIRS_MONITOR
    assert n < MIN_PAIRS_CONFIRM
    assert verdict(n, ROLLBACK_DELTA, (0.005, 0.040)) == "rollback"
    assert verdict(n, ROLLBACK_DELTA + 0.01, None) == "rollback"


def test_verdict_will_not_confirm_below_the_powered_sample():
    assert verdict(MIN_PAIRS_CONFIRM - 1, -0.0104, (-0.02, -0.001)) == "continue_underpowered"


def test_verdict_confirms_only_when_powered_and_ci_excludes_zero():
    assert verdict(MIN_PAIRS_CONFIRM, -0.0104, (-0.0188, -0.0036)) == "confirm_eligible"
    assert verdict(MIN_PAIRS_CONFIRM, -0.0104, (-0.0188, +0.0010)) == "continue"


def test_the_confirm_gate_matches_the_pre_registered_power_analysis():
    assert MIN_PAIRS_CONFIRM == 759
    assert MIN_PAIRS_MONITOR == 306  # one Bundesliga season
    assert MIN_PAIRS_CONFIRM > MIN_PAIRS_MONITOR


# --- pairing ----------------------------------------------------------------

def test_no_pairs_yields_an_honest_empty_record(db_session):
    rec = calibrator_record(db_session, VARIANT)
    assert rec["n_pairs"] == 0
    assert rec["by_production_version"] == {}
    assert "Nothing to compare" in format_record(rec)


def test_a_production_row_without_a_twin_is_skipped(db_session):
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15))
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)["n_pairs"] == 0


def test_an_unfinished_match_is_skipped(db_session):
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15),
            var_probs=(0.7, 0.2, 0.1))
    m.status = "scheduled"
    m.score_home = m.score_away = None
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)["n_pairs"] == 0


def test_only_matched_pairs_are_counted(db_session):
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    _mk(db_session, 1, (1, 1), prod_probs=(0.4, 0.3, 0.3))  # no twin
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)["n_pairs"] == 1


# --- version isolation ------------------------------------------------------

def test_two_production_versions_never_pool(db_session):
    other = "poisson-elo-v0.5"
    for i, ver in enumerate([PROD, PROD, other]):
        _mk(db_session, i, (2, 0), prod_probs=(0.6, 0.25, 0.15),
            var_probs=(0.7, 0.2, 0.1), prod_version=ver)
    db_session.commit()
    by = calibrator_record(db_session, VARIANT)["by_production_version"]
    assert set(by) == {PROD, other}
    assert by[PROD]["n_pairs"] == 2 and by[other]["n_pairs"] == 1


def test_a_twin_tagged_for_another_production_version_is_not_borrowed(db_session):
    """Cross-version contamination: a WC26-tagged twin must not pair with a club
    production row."""
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1),
        prod_version=PROD, var_version=variant_model_version_for("poisson-elo-v0.5", VARIANT))
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)["n_pairs"] == 0


def test_a_different_variant_name_is_not_borrowed(db_session):
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1),
        var_version=variant_model_version_for(PROD, "some_other_variant"))
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)["n_pairs"] == 0


# --- market join: strictly pre-kickoff --------------------------------------

def _odds(db, match, *, phase, offset_hours, probs=(0.5, 0.25, 0.25)):
    db.add(Odds(match_id=match.id, snapshot_phase=phase,
                captured_at=match.kickoff_utc + timedelta(hours=offset_hours),
                implied_prob_home=probs[0], implied_prob_draw=probs[1],
                implied_prob_away=probs[2]))


def test_closing_odds_captured_before_kickoff_are_used(db_session):
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    _odds(db_session, m, phase="closing", offset_hours=-0.5)
    db_session.commit()
    mb = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]["market_benchmark"]
    assert mb is not None and mb["n"] == 1


def test_closing_odds_captured_AFTER_kickoff_are_excluded(db_session):
    """Post-kickoff prices are not admissible evidence — dropped, not clamped."""
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    _odds(db_session, m, phase="closing", offset_hours=+1)
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)[
        "by_production_version"][PROD]["market_benchmark"] is None


def test_non_closing_phases_are_not_used_as_the_closing_line(db_session):
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    for phase in ("opening", "t24", "t6", "t1"):
        _odds(db_session, m, phase=phase, offset_hours=-3)
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)[
        "by_production_version"][PROD]["market_benchmark"] is None


def test_unstamped_odds_are_excluded(db_session):
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    db_session.add(Odds(match_id=m.id, snapshot_phase="closing", captured_at=None,
                        implied_prob_home=0.5, implied_prob_draw=0.25,
                        implied_prob_away=0.25))
    db_session.commit()
    assert calibrator_record(db_session, VARIANT)[
        "by_production_version"][PROD]["market_benchmark"] is None


def test_the_latest_admissible_closing_snapshot_wins(db_session):
    m = _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    _odds(db_session, m, phase="closing", offset_hours=-5, probs=(0.9, 0.05, 0.05))
    _odds(db_session, m, phase="closing", offset_hours=-0.2, probs=(0.2, 0.3, 0.5))
    db_session.commit()
    mb = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]["market_benchmark"]
    # Home happened; the later, home-pessimistic price must drive the loss up.
    assert mb["log_loss"] > 1.0


# --- end-to-end verdicts ----------------------------------------------------

def test_underpowered_sample_reports_continue_underpowered(db_session):
    _seed(db_session, 40, prod_probs=(0.50, 0.25, 0.25), var_probs=(0.70, 0.18, 0.12))
    e = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["n_pairs"] == 40
    assert e["verdict"] == "insufficient"
    assert e["delta_log_loss"] < 0


def test_a_clearly_worse_variant_triggers_rollback(db_session, monkeypatch):
    import pipeline.run_calibrator_benchmark as bench

    monkeypatch.setattr(bench, "MIN_PAIRS_MONITOR", 10)
    _seed(db_session, 20, prod_probs=(0.80, 0.12, 0.08), var_probs=(0.30, 0.35, 0.35))
    e = bench.calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["delta_log_loss"] >= bench.ROLLBACK_DELTA
    assert e["verdict"] == "rollback"


def test_a_powered_and_better_variant_is_confirm_eligible(db_session, monkeypatch):
    import pipeline.run_calibrator_benchmark as bench

    monkeypatch.setattr(bench, "MIN_PAIRS_MONITOR", 5)
    monkeypatch.setattr(bench, "MIN_PAIRS_CONFIRM", 20)
    _seed(db_session, 36, prod_probs=(0.50, 0.25, 0.25), var_probs=(0.72, 0.16, 0.12))
    e = bench.calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["n_blocks"] >= 2
    assert e["verdict"] == "confirm_eligible"
    assert e["ci95"][1] < 0


def test_a_neutral_variant_reports_continue_not_confirm(db_session, monkeypatch):
    import pipeline.run_calibrator_benchmark as bench

    monkeypatch.setattr(bench, "MIN_PAIRS_MONITOR", 5)
    monkeypatch.setattr(bench, "MIN_PAIRS_CONFIRM", 20)
    same = (0.55, 0.25, 0.20)
    for i in range(36):
        _mk(db_session, i, (2, 0) if i % 2 else (0, 1), prod_probs=same, var_probs=same)
    db_session.commit()
    e = bench.calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["delta_log_loss"] == 0.0
    assert e["verdict"] == "continue"


# --- structural regression checks -------------------------------------------

def test_grid_equality_is_reported_and_violations_are_surfaced(db_session):
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    db_session.commit()
    e = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["grid_equality_holds"] is True

    bad = _mk(db_session, 1, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1))
    db_session.query(Prediction).filter_by(
        match_id=bad.id, model_version=TAG).one().lambda_home = 9.9
    db_session.commit()
    e = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["grid_equality_holds"] is False
    assert bad.id in e["grid_mismatch_match_ids"]
    assert "VIOLATED" in format_record(calibrator_record(db_session, VARIANT))


def test_headline_flip_rate_is_measured(db_session):
    _mk(db_session, 0, (2, 0), prod_probs=(0.6, 0.25, 0.15), var_probs=(0.7, 0.2, 0.1),
        ps=(1, 1))
    flipped = _mk(db_session, 1, (2, 0), prod_probs=(0.6, 0.25, 0.15),
                  var_probs=(0.7, 0.2, 0.1), ps=(1, 1))
    db_session.query(Prediction).filter_by(
        match_id=flipped.id, model_version=TAG).one().predicted_score_home = 2
    db_session.commit()
    e = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    assert e["headline_flip_rate"] == 0.5


def test_all_reported_metrics_are_present(db_session):
    _seed(db_session, 12, prod_probs=(0.5, 0.25, 0.25), var_probs=(0.6, 0.22, 0.18))
    e = calibrator_record(db_session, VARIANT)["by_production_version"][PROD]
    for side in ("production", "variant"):
        assert set(e[side]) == {"log_loss", "brier", "rps", "ece", "sharpness"}
