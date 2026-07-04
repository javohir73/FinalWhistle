"""Score the xG-offsets twin vs the published prediction on finished matches.

Best-effort operational script (not unit-tested): pulls, per finished match, the
latest published prediction (is_shadow=False) and the latest xG-offsets twin
(model_version == OFFSETS_MODEL_VERSION), labels each by the final score, and
prints the paired benchmark. Prints a friendly notice until enough matches carry
both rows. Run: `.venv/bin/python -m pipeline.run_offsets_benchmark`.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Match, Prediction
from ml.evaluation.offsets_benchmark import benchmark_offsets
from pipeline.generate_predictions import OFFSETS_MODEL_VERSION


def _latest(db, match_id, *, offsets: bool) -> Prediction | None:
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == OFFSETS_MODEL_VERSION) if offsets
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def _verdict(diff_ci95) -> str:
    lo, hi = diff_ci95
    if hi < 0:
        return "offsets_beats_published"
    if lo > 0:
        return "published_beats_offsets"
    return "no_credible_difference"


def offsets_record(db) -> dict:
    """Paired offsets-twin-vs-published record over finished matches.

    Compute-on-read over frozen Prediction rows (no persistence). Returns the
    benchmark_offsets payload plus a machine-readable verdict, or the
    honest-empty dict when no finished match yet carries BOTH a published
    prediction and an xG-offsets twin."""
    prod_probs, offsets_probs, labels = [], [], []
    finished = (db.query(Match)
                .filter(Match.status == "finished",
                        Match.score_home.isnot(None), Match.score_away.isnot(None))
                .all())
    for m in finished:
        prod = _latest(db, m.id, offsets=False)
        off = _latest(db, m.id, offsets=True)
        if prod is None or off is None:
            continue
        label = "H" if m.score_home > m.score_away else ("A" if m.score_home < m.score_away else "D")
        prod_probs.append((prod.prob_home_win, prod.prob_draw, prod.prob_away_win))
        offsets_probs.append((off.prob_home_win, off.prob_draw, off.prob_away_win))
        labels.append(label)
    if not labels:
        return {"n_matches": 0, "verdict": "insufficient", "production": None,
                "offsets": None, "diff_log_loss": None, "diff_ci95": None,
                "offsets_win_rate": None}
    res = benchmark_offsets(prod_probs, offsets_probs, labels)
    res["verdict"] = _verdict(res["diff_ci95"])
    return res


def main() -> None:
    db = SessionLocal()
    try:
        rec = offsets_record(db)
        if rec["n_matches"] == 0:
            print("No finished matches yet carry both a published prediction and an "
                  "xG-offsets twin. Nothing to benchmark.")
            return
        lo, hi = rec["diff_ci95"]
        print(f"=== xG-offsets twin vs published ({rec['n_matches']} matches) ===")
        print(f"  production log-loss: {rec['production']['log_loss']:.4f}")
        print(f"  offsets    log-loss: {rec['offsets']['log_loss']:.4f}")
        print(f"  paired mean LL diff (offsets - prod): {rec['diff_log_loss']:+.4f}  "
              f"CI95 [{lo:+.4f}, {hi:+.4f}]")
        print(f"  offsets win rate: {rec['offsets_win_rate']:.1%}")
        print(f"  verdict: {rec['verdict']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
