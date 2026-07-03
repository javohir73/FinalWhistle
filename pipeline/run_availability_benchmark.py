"""Score the availability twin vs the published prediction on finished matches.

Best-effort operational script (not unit-tested): pulls, per finished match, the
latest published prediction (is_shadow=False) and the latest availability twin
(model_version == AVAILABILITY_MODEL_VERSION), labels each by the final score, and
prints the paired benchmark. Prints a friendly notice until enough matches carry
both rows. Run: `.venv/bin/python -m pipeline.run_availability_benchmark`.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Match, Prediction
from ml.evaluation.availability_benchmark import benchmark_availability
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION


def _latest(db, match_id, *, avail: bool) -> Prediction | None:
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == AVAILABILITY_MODEL_VERSION) if avail
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def main() -> None:
    db = SessionLocal()
    try:
        prod_probs, avail_probs, labels = [], [], []
        finished = (db.query(Match)
                    .filter(Match.status == "finished",
                            Match.score_home.isnot(None), Match.score_away.isnot(None))
                    .all())
        for m in finished:
            prod = _latest(db, m.id, avail=False)
            avail = _latest(db, m.id, avail=True)
            if prod is None or avail is None:
                continue
            label = "H" if m.score_home > m.score_away else ("A" if m.score_home < m.score_away else "D")
            prod_probs.append((prod.prob_home_win, prod.prob_draw, prod.prob_away_win))
            avail_probs.append((avail.prob_home_win, avail.prob_draw, avail.prob_away_win))
            labels.append(label)

        if not labels:
            print("No finished matches yet carry both a published prediction and an "
                  "availability twin. Nothing to benchmark.")
            return
        res = benchmark_availability(prod_probs, avail_probs, labels)
        lo, hi = res["diff_ci95"]
        print(f"=== Availability twin vs published ({res['n_matches']} matches) ===")
        print(f"  production   log-loss: {res['production']['log_loss']:.4f}")
        print(f"  availability log-loss: {res['availability']['log_loss']:.4f}")
        print(f"  paired mean LL diff (avail - prod): {res['diff_log_loss']:+.4f}  "
              f"CI95 [{lo:+.4f}, {hi:+.4f}]")
        print(f"  availability win rate: {res['availability_win_rate']:.1%}")
        print("  verdict:", "AVAILABILITY BEATS PUBLISHED (credible)" if hi < 0
              else "PUBLISHED BEATS AVAILABILITY (credible)" if lo > 0
              else "NO CREDIBLE DIFFERENCE (CI straddles 0)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
