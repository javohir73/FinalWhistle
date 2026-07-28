"""Score a shadow calibrator variant against production on finished matches.

Why a dedicated benchmark rather than the learning loop: `PredictionResult` is
unique on (match_id, is_shadow), so exactly ONE shadow row per match can ever
be graded, and `evaluate_finished_shadow_predictions` already claims that slot
for the odds twin. Grading a second shadow family through it would need a
schema change. This module instead pairs the FROZEN Prediction rows directly
against realized results and computes on read — the same shape as
run_availability_benchmark / run_baseline_benchmark, and no migration.

Time validity:
  - Only `status='finished'` matches with both scores present.
  - Only the frozen pre-kickoff rows already written by the pipeline.
  - Market comparison joins ONLY `snapshot_phase='closing'` odds captured
    strictly BEFORE kickoff. A closing row stamped after kickoff is dropped,
    not clamped.
  - Market is a BENCHMARK. It is never a label and never a feature.

Isolation: every pairing is scoped to one production model_version, so a club
variant can never pool with a WC26 comparison.

Gates are pre-registered in docs/BUNDESLIGA-CALIBRATOR-LIVE-VALIDATION.md and
implemented in `verdict()`.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_calibrator_benchmark \\
        --variant cal_q3 [--emit-json out.json]
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from app.models import Match, Odds, Prediction
from ml.evaluation.club_calibration import brier_one, ece, log_loss_one, rps_one
from ml.evaluation.market_benchmark import devig
from pipeline.generate_predictions import variant_model_version_for

__all__ = ["calibrator_record", "verdict", "format_record"]

# --- pre-registered gates (docs/BUNDESLIGA-CALIBRATOR-LIVE-VALIDATION.md) ---
#: Confirm needs this many finished pairs. Derived from the T1.6 per-match SD
#: (0.1465) against the observed effect (-0.0104): ~759 matches at best-case
#: iid, more under intra-matchweek correlation. One 306-match season CANNOT
#: confirm; it can only detect harm.
MIN_PAIRS_CONFIRM = 759
#: Below this, no verdict of any kind is published.
MIN_PAIRS_MONITOR = 306
#: Rollback if the variant is this much WORSE, at any n >= MIN_PAIRS_MONITOR.
#: Set where 306 matches IS powered (95% half-width ~0.0164).
ROLLBACK_DELTA = 0.020

_EPS = 1e-12


def _label(m: Match) -> int | None:
    if m.score_home is None or m.score_away is None:
        return None
    return 0 if m.score_home > m.score_away else (1 if m.score_home == m.score_away else 2)


def _probs(p: Prediction):
    return (p.prob_home_win, p.prob_draw, p.prob_away_win)


def _frozen(db, match_id: int, *, version: str | None = None) -> Prediction | None:
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == version) if version is not None
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def _closing_market(db, match: Match):
    """De-vigged closing 1X2, or None. Strictly pre-kickoff by captured_at."""
    if match.kickoff_utc is None:
        return None
    rows = (db.query(Odds)
            .filter(Odds.match_id == match.id, Odds.snapshot_phase == "closing")
            .all())
    best = None
    for o in rows:
        if o.captured_at is None or o.captured_at >= match.kickoff_utc:
            continue  # post-kickoff or unstamped: not admissible evidence
        if best is None or o.captured_at > best.captured_at:
            best = o
    if best is None:
        return None
    if None not in (best.implied_prob_home, best.implied_prob_draw, best.implied_prob_away):
        total = best.implied_prob_home + best.implied_prob_draw + best.implied_prob_away
        if total > 0:
            return (best.implied_prob_home / total, best.implied_prob_draw / total,
                    best.implied_prob_away / total)
    if None not in (best.odds_home, best.odds_draw, best.odds_away):
        return devig(best.odds_home, best.odds_draw, best.odds_away)
    return None


def _block_bootstrap(by_block: dict[str, list[float]], *, n_boot: int = 2000,
                     seed: int = 12345):
    """Percentile CI on the mean per-match delta, resampling whole blocks."""
    keys = sorted(by_block)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for k in s for v in by_block[k]]
        if vals:
            means.append(sum(vals) / len(vals))
    if not means:
        return None
    means.sort()
    return means[int(0.025 * len(means))], means[min(len(means) - 1, int(0.975 * len(means)))]


def _block_key(m: Match) -> str:
    """Matchweek block: ISO year-week of kickoff. The pre-registered unit while
    only one live season exists (a season block would give one cluster)."""
    d = m.kickoff_utc
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def verdict(n_pairs: int, delta: float | None, ci) -> str:
    """The pre-registered decision rule. Deliberately conservative."""
    if delta is None or n_pairs < MIN_PAIRS_MONITOR:
        return "insufficient"
    if delta >= ROLLBACK_DELTA:
        return "rollback"
    if n_pairs < MIN_PAIRS_CONFIRM:
        return "continue_underpowered"
    if ci is not None and ci[1] < 0:
        return "confirm_eligible"
    return "continue"


def calibrator_record(db, variant: str) -> dict:
    """Paired variant-vs-production record, grouped by production version."""
    buckets: dict[str, dict] = defaultdict(
        lambda: {"prod": [], "var": [], "labels": [], "blocks": defaultdict(list),
                 "market": [], "market_labels": [], "prod_on_mkt": [], "var_on_mkt": [],
                 "flips": 0, "grid_mismatches": [], "n": 0})

    finished = (db.query(Match)
                .filter(Match.status == "finished")
                .filter(Match.score_home.isnot(None), Match.score_away.isnot(None))
                .all())
    for m in finished:
        label = _label(m)
        if label is None or m.kickoff_utc is None:
            continue
        prod = _frozen(db, m.id)
        if prod is None:
            continue
        var = _frozen(db, m.id, version=variant_model_version_for(prod.model_version, variant))
        if var is None:
            continue  # no pair, no comparison

        b = buckets[prod.model_version]
        b["n"] += 1
        b["prod"].append(_probs(prod))
        b["var"].append(_probs(var))
        b["labels"].append(label)
        b["blocks"][_block_key(m)].append(
            log_loss_one(_probs(var), label) - log_loss_one(_probs(prod), label))

        # A calibrator swap cannot move the grid. Any inequality is a bug in
        # the variant mechanism, not a result -- surface it, never average it.
        if (var.lambda_home, var.lambda_away, var.rho) != (
                prod.lambda_home, prod.lambda_away, prod.rho):
            b["grid_mismatches"].append(m.id)
        if (var.predicted_score_home, var.predicted_score_away) != (
                prod.predicted_score_home, prod.predicted_score_away):
            b["flips"] += 1

        mkt = _closing_market(db, m)
        if mkt:
            b["market"].append(mkt)
            b["market_labels"].append(label)
            b["prod_on_mkt"].append(_probs(prod))
            b["var_on_mkt"].append(_probs(var))

    out = {}
    for version, b in sorted(buckets.items()):
        n = b["n"]
        if not n:
            continue

        def mean(f, seq, labels):
            return sum(f(p, y) for p, y in zip(seq, labels)) / len(labels)

        deltas = [log_loss_one(v, y) - log_loss_one(p, y)
                  for p, v, y in zip(b["prod"], b["var"], b["labels"])]
        delta = sum(deltas) / n
        ci = _block_bootstrap(b["blocks"])
        rel = lambda seq: [(max(p), 1.0 if max(range(3), key=lambda z: p[z]) == y else 0.0)  # noqa: E731
                           for p, y in zip(seq, b["labels"])]

        entry = {
            "production_version": version,
            "variant_version": variant_model_version_for(version, variant),
            "n_pairs": n,
            "n_blocks": len(b["blocks"]),
            "delta_log_loss": delta,
            "ci95": ci,
            "verdict": verdict(n, delta, ci),
            "gates": {"min_monitor": MIN_PAIRS_MONITOR, "min_confirm": MIN_PAIRS_CONFIRM,
                      "rollback_delta": ROLLBACK_DELTA},
            "headline_flip_rate": b["flips"] / n,
            "grid_equality_holds": not b["grid_mismatches"],
            "grid_mismatch_match_ids": b["grid_mismatches"][:20],
            "production": {
                "log_loss": mean(log_loss_one, b["prod"], b["labels"]),
                "brier": mean(brier_one, b["prod"], b["labels"]),
                "rps": mean(rps_one, b["prod"], b["labels"]),
                "ece": ece(rel(b["prod"])), "sharpness": sum(max(p) for p in b["prod"]) / n,
            },
            "variant": {
                "log_loss": mean(log_loss_one, b["var"], b["labels"]),
                "brier": mean(brier_one, b["var"], b["labels"]),
                "rps": mean(rps_one, b["var"], b["labels"]),
                "ece": ece(rel(b["var"])), "sharpness": sum(max(p) for p in b["var"]) / n,
            },
            "market_benchmark": None,
        }
        if b["market"]:
            ml = b["market_labels"]
            entry["market_benchmark"] = {
                "n": len(ml),
                "log_loss": sum(log_loss_one(p, y) for p, y in zip(b["market"], ml)) / len(ml),
                "production_log_loss_on_same": sum(
                    log_loss_one(p, y) for p, y in zip(b["prod_on_mkt"], ml)) / len(ml),
                "variant_log_loss_on_same": sum(
                    log_loss_one(p, y) for p, y in zip(b["var_on_mkt"], ml)) / len(ml),
                "note": "benchmark only; never a label or feature",
            }
        out[version] = entry

    return {"variant": variant, "n_pairs": sum(e["n_pairs"] for e in out.values()),
            "by_production_version": out}


def format_record(rec: dict) -> str:
    if not rec["by_production_version"]:
        return (f"No finished match yet carries BOTH a production row and a "
                f"'+{rec['variant']}' twin. Nothing to compare — the expected state "
                "until league matches finish with the variant enabled.")
    L = [f"Calibrator variant '{rec['variant']}' vs production "
         f"(negative delta = variant better)", ""]
    for version, e in rec["by_production_version"].items():
        ci = e["ci95"]
        L += [
            f"{version}  ->  {e['variant_version']}",
            f"  pairs / blocks   : {e['n_pairs']} / {e['n_blocks']}",
            f"  paired d logloss : {e['delta_log_loss']:+.4f}"
            + (f"   CI95 [{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "   CI95 n/a"),
            f"  VERDICT          : {e['verdict']}"
            f"   (monitor>={e['gates']['min_monitor']}, "
            f"confirm>={e['gates']['min_confirm']}, "
            f"rollback>=+{e['gates']['rollback_delta']:.3f})",
            f"  production        LL {e['production']['log_loss']:.4f}  "
            f"Brier {e['production']['brier']:.4f}  RPS {e['production']['rps']:.4f}  "
            f"ECE {e['production']['ece']:.4f}  sharp {e['production']['sharpness']:.3f}",
            f"  variant           LL {e['variant']['log_loss']:.4f}  "
            f"Brier {e['variant']['brier']:.4f}  RPS {e['variant']['rps']:.4f}  "
            f"ECE {e['variant']['ece']:.4f}  sharp {e['variant']['sharpness']:.3f}",
            f"  headline flips   : {e['headline_flip_rate']:.1%}",
            f"  grid equality    : {'HOLDS' if e['grid_equality_holds'] else 'VIOLATED — BUG'}"
            + ("" if e["grid_equality_holds"]
               else f" match_ids={e['grid_mismatch_match_ids']}"),
        ]
        mb = e["market_benchmark"]
        if mb:
            L.append(f"  closing market   : LL {mb['log_loss']:.4f} on n={mb['n']}  "
                     f"(production {mb['production_log_loss_on_same']:.4f}, "
                     f"variant {mb['variant_log_loss_on_same']:.4f}) — benchmark only")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", default="cal_q3")
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rec = calibrator_record(db, args.variant)
    finally:
        db.close()

    print(format_record(rec))
    if args.emit_json:
        args.emit_json.write_text(json.dumps(rec, indent=2, default=str))
        print(f"wrote {args.emit_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
