"""Hard model-promotion gate: is a candidate ModelParams set safe to ship?

Wraps pipeline.experiment_model_eval.run_candidate_gate (the paired,
edition-clustered historical backtest of candidate vs baseline) in a pure
rule engine and a report, so promotion is a mechanical decision instead of
an eyeballed one:

  - HARD FAIL if the candidate is credibly WORSE on log-loss, or credibly
    worse on pooled/draw calibration (ECE) beyond a small tolerance.
  - Soft warnings (never fail the gate) for RPS/Brier/exact-score-NLL/top5
    regressions and close-match top1 regressions — worth a human's eye, not
    a blocker on their own.
  - PASS requires the log-loss CI to exclude 0 in the candidate's favor AND
    every differing ModelParams lever to be one this harness can actually
    measure AND validate. wdl_and_grid only applies the goals/calibration
    levers (base, beta, home_adv, rho, temperature, calibrator) — those,
    and only those, can clear the way to PASS. Every other lever caps the
    verdict at NEUTRAL:
      * use_availability, w_odds, use_odds, wdl_blend, form_channels,
        suspensions, rest_days, pk_beta, et_tempo, pk_keeper_delta only
        take effect on the live serving path — this harness can't see
        their effect at all.
      * team_offsets is different in kind: it DOES have a dedicated
        historical backtest (run_team_offsets_gate), but that backtest
        re-fits fresh walk-forward offsets from history — it certifies the
        per-team attack/defence OFFSETTING MECHANISM on this data, never
        the candidate's actual shipped team_offsets FILE CONTENT. A stale
        or corrupt offsets file would still show SHIP. So a team_offsets
        diff always caps the verdict at NEUTRAL too; its backtest result
        is included in the report as an ADVISORY block only (see
        `team_offsets_gate` below). A team_offsets change ships by running
        run_team_offsets_gate directly plus owner judgment — never via an
        evaluate_candidate PASS.

This gate does not evaluate market/odds-anchoring behavior (no historical
odds coverage) — see the `market` block in the report.

Report shape (build_report): everything run_candidate_gate returns
(candidate_version, baseline_version, since_year, n_boot, editions,
matches, summary, deltas, close_match) plus:
  - `rules`: the verdict + per-check breakdown + warnings (evaluate_rules).
  - `market`: always {"status": "not_evaluated", ...} — see above.
  - `levers`: the raw which_levers_differ classification ("historical",
    the team_offsets tag, or NOT_HISTORICALLY_EVALUABLE) per differing field.
  - `levers_resolved`: the same map, but team_offsets's entry is annotated
    with its advisory backtest verdict — e.g. "...(advisory: SHIP)" or
    "...(advisory: do-not-ship)" — so a reader can see the outcome without
    cross-referencing `notes`. It is still NOT_HISTORICALLY_EVALUABLE for
    rule-engine purposes either way.
  - `team_offsets_gate`: the full run_team_offsets_gate() result, present
    only when team_offsets differs. Advisory only — see above.
  - `notes`: free-text caveats (calibrator fit-window overlap, the
    team_offsets advisory disclaimer, etc).

Usage:
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.evaluate_candidate \\
        --candidate <params.json|current|default> [--baseline <params.json|current>] \\
        [--set key=value ...] [--since 2004] [--boot 2000] [--report PATH] [--allow-neutral]

Exit code: 0 on PASS (or NEUTRAL with --allow-neutral), 1 otherwise.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from ml.models.params import DEFAULT_PARAMS, ModelParams, load_params, params_from_dict
from pipeline.experiment_model_eval import run_candidate_gate, run_team_offsets_gate

#: Levers wdl_and_grid actually applies — a candidate that differs from the
#: baseline ONLY here is fully evaluable by run_candidate_gate.
HISTORICAL_LEVERS = frozenset({"base", "beta", "home_adv", "rho", "temperature", "calibrator"})

#: The gate's refusal tag: a lever the historical harness cannot measure at
#: all. evaluate_rules caps the verdict at NEUTRAL whenever this tag appears.
NOT_HISTORICALLY_EVALUABLE = "not_historically_evaluable — gate via live path"


def load_candidate(spec: str, overrides: dict[str, str]) -> ModelParams:
    """Resolve a --candidate/--baseline spec to a ModelParams, then apply
    --set overrides. `spec` is "current" (load_params()), "default" (the
    v0.1 constants), or a path to a params.json-shaped file."""
    if spec == "current":
        params = load_params()
    elif spec == "default":
        params = DEFAULT_PARAMS
    else:
        params = params_from_dict(json.loads(Path(spec).read_text()))
    return apply_overrides(params, overrides)


def apply_overrides(params: ModelParams, overrides: dict[str, str]) -> ModelParams:
    """dataclasses.replace with typed coercion inferred from each field's
    declared annotation (bools accept true/false, floats coerce, dict fields
    parse JSON). Unknown key raises ValueError."""
    if not overrides:
        return params
    field_types = {f.name: f.type for f in dataclasses.fields(params)}
    coerced: dict[str, object] = {}
    for key, raw in overrides.items():
        if key not in field_types:
            raise ValueError(f"unknown ModelParams field: {key!r}")
        coerced[key] = _coerce(raw, field_types[key])
    return dataclasses.replace(params, **coerced)


def _coerce(raw: str, type_str: str):
    # `from __future__ import annotations` makes dataclass field.type a bare
    # string (e.g. "bool", "float", "dict | None") rather than a real type.
    type_str = type_str.strip()
    if type_str == "bool":
        low = raw.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
        raise ValueError(f"cannot coerce {raw!r} to bool (expected true/false)")
    if type_str == "float":
        return float(raw)
    if type_str == "str":
        return raw
    if "dict" in type_str:
        return json.loads(raw)
    raise ValueError(f"unsupported field type for override: {type_str}")


def which_levers_differ(candidate: ModelParams, baseline: ModelParams) -> dict[str, str]:
    """Classify every ModelParams field where candidate != baseline (ignoring
    `version`): "historical" (fully evaluable by run_candidate_gate — can
    clear the way to PASS), "team_offsets" (has a dedicated backtest,
    run_team_offsets_gate, but that backtest validates the offsetting
    MECHANISM on fresh walk-forward fits, not the candidate's actual
    shipped file — so it is folded into the report as advisory-only and
    NEVER clears PASS, same as an unmeasurable lever), or
    NOT_HISTORICALLY_EVALUABLE for every other lever — those only run on
    the live serving path, so this harness has no way to measure their
    effect at all."""
    out: dict[str, str] = {}
    for f in dataclasses.fields(candidate):
        if f.name == "version":
            continue
        if getattr(candidate, f.name) == getattr(baseline, f.name):
            continue
        if f.name in HISTORICAL_LEVERS:
            out[f.name] = "historical"
        elif f.name == "team_offsets":
            out[f.name] = "team_offsets (dedicated backtest: run_team_offsets_gate)"
        else:
            out[f.name] = NOT_HISTORICALLY_EVALUABLE
    return out


def assert_leakfree(rows: list[dict]) -> None:
    """Sanity check, not a leak-free proof: assert rows are date-ascending
    and every row carries pre-match rating keys (pre_home/pre_away, the
    backtest_data schema). This can only catch gross mistakes — rows fed in
    out of order, or a row shape that never went through the real pipeline
    — it cannot verify that pre_home/pre_away actually reflect only
    strictly earlier matches. That guarantee is built by construction in
    pipeline.backtest_data.build_enriched_rows / ml.ratings.elo's
    replay_with_prematch, which this function does not (and cannot)
    re-derive. Raises AssertionError with a clear message on failure."""
    from ml.features.training_rows import _as_date

    prev = None
    for i, r in enumerate(rows):
        if "pre_home" not in r or "pre_away" not in r:
            raise AssertionError(
                f"row {i} is missing pre-match ratings (pre_home/pre_away) — "
                "not safe to score for leakage")
        d = _as_date(r["date"])
        if prev is not None and d < prev:
            raise AssertionError(
                f"rows are not date-ascending: row {i} ({d}) precedes row {i - 1} ({prev})")
        prev = d


@dataclass(frozen=True)
class Thresholds:
    ECE_TOL: float = 0.010
    DRAW_ECE_TOL: float = 0.015


def evaluate_rules(gate: dict, thresholds: Thresholds = Thresholds()) -> dict:
    """Pure rule engine over a run_candidate_gate()-shaped dict (optionally
    carrying a `levers` key — see which_levers_differ — so the NEUTRAL cap
    can be evaluated here too). No I/O, no randomness: same input, same
    verdict, always."""
    d = gate["deltas"]
    checks: list[dict] = []
    warnings: list[str] = []
    hard_fail = False

    def check(name: str, tier: str, value, threshold, ok: bool) -> None:
        nonlocal hard_fail
        checks.append({"name": name, "tier": tier, "value": value, "threshold": threshold, "ok": ok})
        if tier == "hard" and not ok:
            hard_fail = True

    ll_ci = d["log_loss"]["ci"]
    check("log_loss_not_worse", "hard", ll_ci, 0.0, ll_ci[0] <= 0)

    ece_d = d["ece"]["d"]
    check("ece_delta", "hard", ece_d, thresholds.ECE_TOL, ece_d <= thresholds.ECE_TOL)

    draw_ece_d = d["draw_ece"]["d"]
    check("draw_ece_delta", "hard", draw_ece_d, thresholds.DRAW_ECE_TOL,
          draw_ece_d <= thresholds.DRAW_ECE_TOL)

    for key in ("rps", "brier", "exact_nll"):
        ci = d[key]["ci"]
        ok = ci[0] <= 0
        check(f"{key}_regression", "soft", ci, 0.0, ok)
        if not ok:
            warnings.append(f"{key} credibly regressed vs baseline: CI [{ci[0]:+.4f}, {ci[1]:+.4f}]")

    top5_ci = d["top5"]["ci"]
    ok = top5_ci[1] >= 0
    check("top5_regression", "soft", top5_ci, 0.0, ok)
    if not ok:
        warnings.append(f"top5 hit rate credibly regressed vs baseline: CI [{top5_ci[0]:+.4f}, {top5_ci[1]:+.4f}]")

    d_top1 = gate.get("close_match", {}).get("d_top1", 0.0)
    ok = d_top1 >= 0
    check("close_match_top1", "soft", d_top1, 0.0, ok)
    if not ok:
        warnings.append(f"close-match (effective gap < 50) top1 regressed: d_top1={d_top1:+.4f}")

    levers = gate.get("levers") or {}
    unmeasured = [k for k, v in levers.items() if v == NOT_HISTORICALLY_EVALUABLE]
    if unmeasured:
        warnings.append("unmeasured lever(s) differ from baseline (verdict capped at NEUTRAL): "
                        + ", ".join(unmeasured))

    if hard_fail:
        verdict = "FAIL"
    elif ll_ci[1] < 0 and not unmeasured:
        verdict = "PASS"
    else:
        verdict = "NEUTRAL"

    return {"verdict": verdict, "checks": checks, "warnings": warnings}


def build_report(rows: list[dict], candidate: ModelParams, baseline: ModelParams,
                 since_year: int = 2004, n_boot: int = 2000,
                 thresholds: Thresholds = Thresholds()) -> dict:
    """The full gate report: run_candidate_gate's metrics, the pure rule
    verdict, and lever bookkeeping so a lever the gate can't measure — or,
    for team_offsets, can't fully validate — never slips through as a
    silent PASS. See the module docstring's "Report shape" section for the
    full key list."""
    gate = run_candidate_gate(rows, candidate, baseline, since_year=since_year, n_boot=n_boot)
    levers = which_levers_differ(candidate, baseline)

    notes: list[str] = []
    if candidate.calibrator is not None:
        notes.append(
            "candidate carries a calibrator — recent editions in this window may overlap its "
            "fit window (e.g. pipeline/fit_calibrator's 730-day lookback); confirm it was fit "
            "strictly before the earliest evaluated edition before trusting a close call.")

    # team_offsets has a dedicated backtest (run_team_offsets_gate), but that
    # backtest re-fits fresh walk-forward offsets from history — it never
    # validates the candidate's actual shipped team_offsets FILE, so a SHIP
    # verdict there cannot be trusted to clear a corrupt/stale file (review
    # M1). A pure-offsets candidate also can't PASS on log-loss alone: its
    # run_candidate_gate log-loss CI is (0, 0) because wdl_and_grid never
    # reads params.team_offsets (M2). So a team_offsets diff ALWAYS caps the
    # verdict at NEUTRAL — same treatment as an unmeasurable lever — and its
    # backtest result is surfaced as an ADVISORY block only. Promoting a
    # team_offsets change is a run-run_team_offsets_gate-directly-plus-owner
    # decision, never an evaluate_candidate PASS.
    rule_levers = dict(levers)
    levers_resolved = dict(levers)
    team_offsets_gate = None
    if "team_offsets" in levers:
        team_offsets_gate = run_team_offsets_gate(rows, n_boot=n_boot, served_params=baseline)
        notes.append(
            f"team_offsets lever differs from baseline — ran the dedicated "
            f"run_team_offsets_gate backtest as an ADVISORY signal only "
            f"(verdict: {team_offsets_gate['verdict']}). That backtest certifies the "
            f"offsetting MECHANISM on this data, not the candidate's actual shipped "
            f"team_offsets file, so it can never clear the NEUTRAL cap here — a "
            f"team_offsets promotion ships via run_team_offsets_gate + owner judgment, "
            f"never via this gate's PASS.")
        rule_levers["team_offsets"] = NOT_HISTORICALLY_EVALUABLE
        levers_resolved["team_offsets"] = NOT_HISTORICALLY_EVALUABLE + (
            " (advisory: SHIP)" if team_offsets_gate["verdict"] == "SHIP"
            else " (advisory: do-not-ship)")

    rules = evaluate_rules({**gate, "levers": rule_levers}, thresholds)

    report = dict(gate)
    report["rules"] = rules
    report["market"] = {"status": "not_evaluated", "reason": "no odds coverage for historical window"}
    report["levers"] = levers
    report["levers_resolved"] = levers_resolved
    if team_offsets_gate is not None:
        report["team_offsets_gate"] = team_offsets_gate
    report["notes"] = notes
    return report


def exit_code_for(verdict: str, allow_neutral: bool) -> int:
    """Pure exit-code decision, factored out of main() so --allow-neutral is
    unit-testable without spinning up the full data path."""
    return 0 if (verdict == "PASS" or (allow_neutral and verdict == "NEUTRAL")) else 1


def _parse_overrides(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for kv in pairs:
        if "=" not in kv:
            raise ValueError(f"--set expects key=value, got {kv!r}")
        key, value = kv.split("=", 1)
        out[key] = value
    return out


def _print_summary(report: dict) -> None:
    print(f"\nCandidate {report['candidate_version']!r} vs baseline {report['baseline_version']!r}  "
          f"({report['matches']} matches / {report['editions']} editions since {report['since_year']}, "
          f"boot={report['n_boot']})")

    hdr = (f"{'':10s} {'log_loss':>9s} {'rps':>7s} {'brier':>7s} {'exact_nll':>10s} "
          f"{'top1':>6s} {'top3':>6s} {'top5':>6s} {'ece':>6s}")
    print(hdr); print("-" * len(hdr))
    for who in ("candidate", "baseline"):
        m = report["summary"][who]
        print(f"{who:10s} {m['log_loss']:9.4f} {m['rps']:7.4f} {m['brier']:7.4f} "
              f"{m['exact_nll']:10.4f} {m['top1']:6.3f} {m['top3']:6.3f} {m['top5']:6.3f} {m['ece']:6.3f}")

    print("\nPaired deltas (candidate - baseline; CI excluding 0 = credible):")
    d = report["deltas"]
    for key in ("log_loss", "rps", "brier", "exact_nll", "top5"):
        v = d[key]
        print(f"  {key:10s} d={v['d']:+.4f}  CI[{v['ci'][0]:+.4f},{v['ci'][1]:+.4f}]")
    print(f"  {'ece':10s} d={d['ece']['d']:+.4f}  (point estimate, no CI)")
    print(f"  {'draw_ece':10s} d={d['draw_ece']['d']:+.4f}  (point estimate, no CI)")

    cm = report["close_match"]
    fmt_ll = lambda v: f"{v:.4f}" if v is not None else "n/a (no draws in subset)"
    print(f"\nClose-match (effective gap < 50, n={cm['n']}): d_top1={cm['d_top1']:+.4f}  "
          f"cand_draw_ll={fmt_ll(cm['cand_draw_ll'])}  base_draw_ll={fmt_ll(cm['base_draw_ll'])}")

    print("\nLevers that differ from baseline:" if report["levers"] else "\nNo levers differ from baseline.")
    for k, v in report["levers_resolved"].items():
        print(f"  {k}: {v}")

    print(f"\nMarket: {report['market']['status']} — {report['market']['reason']}")

    rules = report["rules"]
    print("\nRule checks:")
    for c in rules["checks"]:
        status = "ok" if c["ok"] else "FAIL"
        print(f"  [{c['tier']:4s}] {c['name']:22s} {status:4s}  value={c['value']}  threshold={c['threshold']}")
    if rules["warnings"]:
        print("\nWarnings:")
        for w in rules["warnings"]:
            print(f"  - {w}")

    for n in report["notes"]:
        print(f"\nNote: {n}")

    print(f"\nVERDICT: {rules['verdict']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", required=True, help="params.json path, 'current', or 'default'")
    ap.add_argument("--baseline", default="current", help="baseline: path or 'current' (default: current)")
    ap.add_argument("--set", action="append", default=[], dest="overrides", metavar="key=value",
                    help="override a candidate ModelParams field (repeatable)")
    ap.add_argument("--since", type=int, default=2004)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--report", type=Path, default=None, help="write the full JSON report to this path")
    ap.add_argument("--allow-neutral", action="store_true",
                    help="exit 0 on a NEUTRAL verdict too (default: only PASS exits 0)")
    args = ap.parse_args()

    candidate = load_candidate(args.candidate, _parse_overrides(args.overrides))
    baseline = load_candidate(args.baseline, {})

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    print("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)
    db.close()
    print(f"Replayed {len(rows)} historical matches (leak-free pre-match Elo).")

    assert_leakfree(rows)

    report = build_report(rows, candidate, baseline, since_year=args.since, n_boot=args.boot)
    _print_summary(report)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote report to {args.report}")

    return exit_code_for(report["rules"]["verdict"], args.allow_neutral)


if __name__ == "__main__":
    raise SystemExit(main())
