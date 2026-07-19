"""Tests for the hard model-promotion gate (pipeline/evaluate_candidate.py).

The rule engine is tested against small synthetic `gate` dicts rather than
running the full historical pipeline — same style as
experiment_model_eval_gate_test.py's smoke tests.
"""
from datetime import date

import pytest

from ml.models.params import DEFAULT_PARAMS, ModelParams
from pipeline.evaluate_candidate import (
    NOT_HISTORICALLY_EVALUABLE,
    Thresholds,
    apply_overrides,
    assert_leakfree,
    evaluate_rules,
    exit_code_for,
    which_levers_differ,
)


def _gate(ll_ci, ece_d=0.0, draw_ece_d=0.0, rps_ci=(-0.01, -0.001), brier_ci=(-0.01, -0.001),
         exact_nll_ci=(-0.01, -0.001), top5_ci=(0.001, 0.01), d_top1=0.01, levers=None) -> dict:
    """A minimal run_candidate_gate()-shaped dict for exercising evaluate_rules
    in isolation."""
    def m(ci):
        return {"d": sum(ci) / 2.0, "ci": list(ci)}

    gate = {
        "deltas": {
            "log_loss": {"d": sum(ll_ci) / 2.0, "ci": list(ll_ci)},
            "rps": m(rps_ci),
            "brier": m(brier_ci),
            "exact_nll": m(exact_nll_ci),
            "top5": m(top5_ci),
            "ece": {"d": ece_d},
            "draw_ece": {"d": draw_ece_d},
        },
        "close_match": {"n": 10, "d_top1": d_top1, "cand_draw_ll": 0.9, "base_draw_ll": 0.95},
    }
    if levers is not None:
        gate["levers"] = levers
    return gate


# --- evaluate_rules ----------------------------------------------------------

def test_evaluate_rules_pass_when_log_loss_credibly_better():
    gate = _gate(ll_ci=(-0.01, -0.001))
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "PASS"
    assert not res["warnings"]


def test_evaluate_rules_fail_when_log_loss_credibly_worse():
    gate = _gate(ll_ci=(0.001, 0.01))
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "FAIL"
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["log_loss_not_worse"]["ok"] is False


def test_evaluate_rules_neutral_when_log_loss_ci_straddles_zero():
    gate = _gate(ll_ci=(-0.01, 0.005))
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "NEUTRAL"


def test_evaluate_rules_fail_on_ece_delta_over_tolerance():
    gate = _gate(ll_ci=(-0.01, -0.001), ece_d=0.011)
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "FAIL"
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["ece_delta"]["ok"] is False


def test_evaluate_rules_fail_on_draw_ece_delta_over_tolerance():
    gate = _gate(ll_ci=(-0.01, -0.001), draw_ece_d=0.016)
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "FAIL"
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["draw_ece_delta"]["ok"] is False


def test_evaluate_rules_ece_delta_at_exact_tolerance_is_not_a_hard_fail():
    """ECE_TOL is a <= bound: exactly 0.010 must pass the check."""
    gate = _gate(ll_ci=(-0.02, -0.005), ece_d=0.010)
    res = evaluate_rules(gate, Thresholds())
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["ece_delta"]["ok"] is True
    assert res["verdict"] == "PASS"


def test_evaluate_rules_draw_ece_delta_at_exact_tolerance_is_not_a_hard_fail():
    """DRAW_ECE_TOL is a <= bound: exactly 0.015 must pass the check."""
    gate = _gate(ll_ci=(-0.02, -0.005), draw_ece_d=0.015)
    res = evaluate_rules(gate, Thresholds())
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["draw_ece_delta"]["ok"] is True
    assert res["verdict"] == "PASS"


def test_evaluate_rules_log_loss_ci_upper_exactly_zero_is_neutral_not_pass():
    """PASS needs ci[1] < 0 (strict); an upper bound of exactly 0 is not a
    credible win, so the verdict must stay NEUTRAL."""
    gate = _gate(ll_ci=(-0.01, 0.0))
    res = evaluate_rules(gate, Thresholds())
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["log_loss_not_worse"]["ok"] is True  # ci[0] <= 0, not a hard fail
    assert res["verdict"] == "NEUTRAL"


def test_evaluate_rules_log_loss_ci_lower_exactly_zero_is_neutral_not_fail():
    """HARD FAIL needs ci[0] > 0 (strict); a lower bound of exactly 0 is not a
    credible loss, so the verdict must stay NEUTRAL (not FAIL)."""
    gate = _gate(ll_ci=(0.0, 0.01))
    res = evaluate_rules(gate, Thresholds())
    checks = {c["name"]: c for c in res["checks"]}
    assert checks["log_loss_not_worse"]["ok"] is True  # ci[0] == 0, not > 0
    assert res["verdict"] == "NEUTRAL"


def test_evaluate_rules_neutral_capped_when_unmeasured_lever_differs():
    """Even a winning log-loss CI cannot PASS if a lever the harness can't
    measure (e.g. use_availability) differs from the baseline."""
    gate = _gate(ll_ci=(-0.02, -0.005),
                levers={"use_availability": NOT_HISTORICALLY_EVALUABLE})
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "NEUTRAL"
    assert any("unmeasured lever" in w for w in res["warnings"])


def test_evaluate_rules_pass_when_only_historical_lever_differs():
    gate = _gate(ll_ci=(-0.02, -0.005), levers={"rho": "historical"})
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "PASS"


def test_evaluate_rules_soft_regressions_never_fail():
    gate = _gate(ll_ci=(-0.02, -0.005), rps_ci=(0.001, 0.01), top5_ci=(-0.01, -0.001), d_top1=-0.02)
    res = evaluate_rules(gate, Thresholds())
    assert res["verdict"] == "PASS"  # soft warnings alone never block PASS
    assert len(res["warnings"]) >= 2


# --- exit_code_for -----------------------------------------------------------

def test_exit_code_for_pass_is_always_zero():
    assert exit_code_for("PASS", allow_neutral=False) == 0
    assert exit_code_for("PASS", allow_neutral=True) == 0


def test_exit_code_for_neutral_flips_with_allow_neutral():
    assert exit_code_for("NEUTRAL", allow_neutral=False) == 1
    assert exit_code_for("NEUTRAL", allow_neutral=True) == 0


def test_exit_code_for_fail_is_always_nonzero():
    assert exit_code_for("FAIL", allow_neutral=True) == 1


# --- apply_overrides ----------------------------------------------------------

def test_apply_overrides_coerces_bool():
    out = apply_overrides(DEFAULT_PARAMS, {"use_availability": "true"})
    assert out.use_availability is True


def test_apply_overrides_coerces_float():
    out = apply_overrides(DEFAULT_PARAMS, {"rho": "0.5"})
    assert out.rho == 0.5
    assert isinstance(out.rho, float)


def test_apply_overrides_unknown_key_raises():
    with pytest.raises(ValueError):
        apply_overrides(DEFAULT_PARAMS, {"not_a_real_field": "1"})


def test_apply_overrides_bad_bool_raises():
    with pytest.raises(ValueError):
        apply_overrides(DEFAULT_PARAMS, {"use_availability": "yes"})


# --- which_levers_differ -------------------------------------------------------

def test_which_levers_differ_flags_use_availability_as_not_evaluable():
    baseline = DEFAULT_PARAMS
    candidate = ModelParams(**{**baseline.to_dict(), "use_availability": True})
    levers = which_levers_differ(candidate, baseline)
    assert levers["use_availability"] == NOT_HISTORICALLY_EVALUABLE


def test_which_levers_differ_flags_rho_as_historical():
    baseline = DEFAULT_PARAMS
    candidate = ModelParams(**{**baseline.to_dict(), "rho": -0.1})
    levers = which_levers_differ(candidate, baseline)
    assert levers["rho"] == "historical"


def test_which_levers_differ_ignores_version():
    baseline = DEFAULT_PARAMS
    candidate = ModelParams(**{**baseline.to_dict(), "version": "some-other-version"})
    levers = which_levers_differ(candidate, baseline)
    assert "version" not in levers


def test_which_levers_differ_empty_when_identical():
    assert which_levers_differ(DEFAULT_PARAMS, DEFAULT_PARAMS) == {}


# --- assert_leakfree -----------------------------------------------------------

def _row(d, home=1500.0, away=1500.0):
    return {"pre_home": home, "pre_away": away, "date": d}


def test_assert_leakfree_passes_on_ascending_rows_with_pre_ratings():
    rows = [_row(date(2020, 1, 1)), _row(date(2020, 1, 2)), _row(date(2020, 1, 3))]
    assert_leakfree(rows)  # no raise


def test_assert_leakfree_raises_on_shuffled_rows():
    rows = [_row(date(2020, 1, 3)), _row(date(2020, 1, 1)), _row(date(2020, 1, 2))]
    with pytest.raises(AssertionError):
        assert_leakfree(rows)


def test_assert_leakfree_raises_on_missing_pre_ratings():
    rows = [_row(date(2020, 1, 1)), {"date": date(2020, 1, 2)}]
    with pytest.raises(AssertionError):
        assert_leakfree(rows)


# --- build_report shape --------------------------------------------------------

def _edition_rows() -> list[dict]:
    rows = []
    for yr in range(2004, 2024):
        comp = "FIFA World Cup" if yr % 4 == 2 else "Friendly"
        for i in range(30):
            rows.append({
                "home_id": 1 + (i % 8), "away_id": 1 + ((i + 3) % 8),
                "pre_home": 1800.0, "pre_away": 1500.0, "is_neutral": True,
                "competition": comp, "score_home": 2, "score_away": 0,
                "date": date(yr, 6, 1 + (i % 20)),
            })
    return rows


def test_build_report_has_all_documented_top_level_keys():
    from pipeline.evaluate_candidate import build_report

    report = build_report(_edition_rows(), DEFAULT_PARAMS, DEFAULT_PARAMS, since_year=2004, n_boot=10)
    for key in ("candidate_version", "baseline_version", "since_year", "n_boot", "editions",
                "matches", "summary", "deltas", "close_match", "rules", "market", "levers",
                "levers_resolved", "notes"):
        assert key in report, f"missing {key}"
    assert report["rules"]["verdict"] in ("PASS", "FAIL", "NEUTRAL")
    assert report["market"]["status"] == "not_evaluated"


# --- build_report: team_offsets is ALWAYS advisory-only (review M1/M2) --------

@pytest.mark.parametrize("advisory_verdict", ["SHIP", "do-not-ship"])
def test_build_report_caps_neutral_when_only_team_offsets_differs(monkeypatch, advisory_verdict):
    """A team_offsets diff must NEVER unblock PASS, no matter what the dedicated
    run_team_offsets_gate backtest says — that backtest re-fits fresh offsets
    from history, it does not validate the candidate's actual shipped
    team_offsets file. Pins the write side of the levers coupling: build_report
    must always fold team_offsets to NOT_HISTORICALLY_EVALUABLE regardless of
    the advisory verdict, and surface the advisory result for a human to read."""
    import pipeline.evaluate_candidate as ec
    from dataclasses import replace

    def _stub_team_offsets_gate(rows, n_boot=2000, served_params=None, **kwargs):
        return {"verdict": advisory_verdict, "test_n": 42, "editions": 3}

    monkeypatch.setattr(ec, "run_team_offsets_gate", _stub_team_offsets_gate)

    baseline = DEFAULT_PARAMS
    candidate = replace(baseline, team_offsets={"file": "team_offsets.json"})

    report = ec.build_report(_edition_rows(), candidate, baseline, since_year=2004, n_boot=10)

    assert "team_offsets_gate" in report
    assert report["team_offsets_gate"]["verdict"] == advisory_verdict
    assert report["rules"]["verdict"] == "NEUTRAL"
    assert report["levers"]["team_offsets"] != NOT_HISTORICALLY_EVALUABLE  # raw tag, unresolved
    resolved = report["levers_resolved"]["team_offsets"]
    assert resolved.startswith(NOT_HISTORICALLY_EVALUABLE)
    assert advisory_verdict in resolved
    assert any("advisory" in n.lower() for n in report["notes"])
