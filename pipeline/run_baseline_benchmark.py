"""Score the promoted params against the ones they replaced, on finished matches.

The live receipt behind the club v0.1 -> v0.2 per-league refit. That promotion
rests on one offline confirmation season (docs/MODEL-EXPERIMENTS.md, "Club
program"); this accrues the real out-of-sample record as league matches finish.

Pulls, per finished match, the latest published prediction (is_shadow=False)
and the latest "+baseline" twin tagged under that published row's OWN ledger
(baseline_model_version_for), labels each by the final score, and prints the
paired benchmark. Prints an honest-empty notice until matches carry both rows.

Run: `PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_baseline_benchmark`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.models import Match, Prediction
from ml.evaluation.baseline_benchmark import benchmark_baseline
from pipeline.generate_predictions import baseline_model_version_for

__all__ = ["baseline_record"]


def _latest(db, match_id: int, *, version: str | None = None) -> Prediction | None:
    """Latest published row (version=None) or latest twin row tagged `version`."""
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == version) if version is not None
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def _verdict(diff_ci95) -> str:
    """Sign convention: negative favours the SERVED (promoted) params."""
    lo, hi = diff_ci95
    if hi < 0:
        return "promotion_confirmed_live"
    if lo > 0:
        return "previous_params_were_better"
    return "no_credible_difference"


def _label(match: Match) -> str | None:
    if match.score_home is None or match.score_away is None:
        return None
    if match.score_home > match.score_away:
        return "H"
    return "A" if match.score_home < match.score_away else "D"


def _probs(row: Prediction) -> tuple[float, float, float]:
    return (row.prob_home_win, row.prob_draw, row.prob_away_win)


def baseline_record(db) -> dict:
    """Paired served-vs-previous-params record over finished matches.

    Compute-on-read over frozen Prediction rows — no persistence, consistent
    with the other twin records. Groups by the published row's model version so
    two production families never pool into one comparison, the same leak the
    shadow/availability ledgers close.
    """
    by_version: dict[str, dict[str, list]] = {}
    finished = (
        db.query(Match)
        .filter(Match.status == "finished")
        .filter(Match.score_home.isnot(None), Match.score_away.isnot(None))
        .all()
    )
    for match in finished:
        label = _label(match)
        if label is None:
            continue
        served = _latest(db, match.id)
        if served is None:
            continue
        twin = _latest(db, match.id,
                       version=baseline_model_version_for(served.model_version))
        if twin is None:
            continue
        bucket = by_version.setdefault(
            served.model_version, {"served": [], "baseline": [], "labels": []}
        )
        bucket["served"].append(_probs(served))
        bucket["baseline"].append(_probs(twin))
        bucket["labels"].append(label)

    out: dict[str, dict] = {}
    for version, b in sorted(by_version.items()):
        res = benchmark_baseline(b["served"], b["baseline"], b["labels"])
        res["verdict"] = _verdict(res["diff_ci95"])
        out[version] = res

    if not out:
        return {"n_matches": 0, "verdict": "insufficient", "by_model_version": {}}
    return {
        "n_matches": sum(r["n_matches"] for r in out.values()),
        "verdict": "see by_model_version",
        "by_model_version": out,
    }


def format_record(record: dict) -> str:
    if not record["by_model_version"]:
        return ("No finished match yet carries BOTH a published prediction and a "
                "+baseline twin. Nothing to compare — this is the expected state "
                "before the first league matches finish.")
    lines = ["Promoted params vs the params they replaced (negative favours the "
             "promotion):", ""]
    for version, r in record["by_model_version"].items():
        lo, hi = r["diff_ci95"]
        lines += [
            f"{version}  (n={r['n_matches']})",
            f"  served   log loss : {r['served']['log_loss']:.4f}",
            f"  baseline log loss : {r['baseline']['log_loss']:.4f}",
            f"  paired diff       : {r['diff_log_loss']:+.4f}  "
            f"CI95 [{lo:+.4f}, {hi:+.4f}]",
            f"  served win rate   : {r['served_win_rate']:.1%}",
            f"  verdict           : {r['verdict']}",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        record = baseline_record(db)
    finally:
        db.close()

    print(format_record(record))
    if args.emit_json:
        args.emit_json.write_text(json.dumps(record, indent=2))
        print(f"wrote {args.emit_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
