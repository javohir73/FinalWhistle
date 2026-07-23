"""Score the xG-offsets twin vs the published prediction on finished matches.

Best-effort operational script (not unit-tested): pulls, per finished match, the
latest published prediction (is_shadow=False) and the latest xG-offsets twin
(tagged by the published row's OWN ledger — offsets_model_version_for), labels
each by the final score, and prints the paired benchmark. Prints a friendly
notice until enough matches carry both rows. Run:
`.venv/bin/python -m pipeline.run_offsets_benchmark`.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Match, Prediction
from ml.evaluation.offsets_benchmark import benchmark_offsets
from pipeline.generate_predictions import offsets_model_version_for


def _latest(db, match_id, *, version: str | None = None) -> Prediction | None:
    """Latest published row (version=None) or latest twin row tagged `version`."""
    q = db.query(Prediction).filter_by(match_id=match_id)
    q = (q.filter(Prediction.model_version == version) if version is not None
         else q.filter(Prediction.is_shadow.is_(False)))
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def _verdict(diff_ci95) -> str:
    lo, hi = diff_ci95
    if hi < 0:
        return "offsets_beats_published"
    if lo > 0:
        return "published_beats_offsets"
    return "no_credible_difference"


def _ledger_record(prod_probs, offsets_probs, labels) -> dict:
    if not labels:
        return {"n_matches": 0, "verdict": "insufficient", "production": None,
                "offsets": None, "diff_log_loss": None, "diff_ci95": None,
                "offsets_win_rate": None}
    res = benchmark_offsets(prod_probs, offsets_probs, labels)
    res["verdict"] = _verdict(res["diff_ci95"])
    return res


def offsets_record(db) -> dict:
    """Paired offsets-twin-vs-published record over finished matches.

    Compute-on-read over frozen Prediction rows (no persistence). Returns the
    benchmark_offsets payload plus a machine-readable verdict, or the
    honest-empty dict when no finished match yet carries BOTH a published
    prediction and an xG-offsets twin.

    League pivot (same leak as the shadow-ledger fix, Opus review of PR #171,
    item 1): each match pairs its published row with the twin tagged under
    that row's OWN ledger (offsets_model_version_for), and the top-level keys
    stay scoped to the WC26/international family ("poisson-elo-v...") exactly
    as before — the WC26 paired sample can never move once an EPL match starts
    writing its own "+xg" twin. Any other family is reported separately under
    "club", same shape, never pooled into the keys above.
    """
    wc = ([], [], [])
    club = ([], [], [])
    finished = (db.query(Match)
                .filter(Match.status == "finished",
                        Match.score_home.isnot(None), Match.score_away.isnot(None))
                .all())
    for m in finished:
        prod = _latest(db, m.id)
        if prod is None:
            continue
        off = _latest(db, m.id, version=offsets_model_version_for(prod.model_version))
        if off is None:
            continue
        label = "H" if m.score_home > m.score_away else ("A" if m.score_home < m.score_away else "D")
        prod_probs, offsets_probs, labels = (
            wc if prod.model_version.startswith("poisson-elo-v") else club)
        prod_probs.append((prod.prob_home_win, prod.prob_draw, prod.prob_away_win))
        offsets_probs.append((off.prob_home_win, off.prob_draw, off.prob_away_win))
        labels.append(label)
    rec = _ledger_record(*wc)
    rec["club"] = _ledger_record(*club)
    return rec


def _print_ledger(name: str, rec: dict) -> None:
    lo, hi = rec["diff_ci95"]
    print(f"=== xG-offsets twin vs published — {name} ({rec['n_matches']} matches) ===")
    print(f"  production log-loss: {rec['production']['log_loss']:.4f}")
    print(f"  offsets    log-loss: {rec['offsets']['log_loss']:.4f}")
    print(f"  paired mean LL diff (offsets - prod): {rec['diff_log_loss']:+.4f}  "
          f"CI95 [{lo:+.4f}, {hi:+.4f}]")
    print(f"  offsets win rate: {rec['offsets_win_rate']:.1%}")
    print(f"  verdict: {rec['verdict']}")


def main() -> None:
    db = SessionLocal()
    try:
        rec = offsets_record(db)
        club = rec["club"]
        if rec["n_matches"] == 0 and club["n_matches"] == 0:
            print("No finished matches yet carry both a published prediction and an "
                  "xG-offsets twin. Nothing to benchmark.")
            return
        if rec["n_matches"]:
            _print_ledger("WC26/international", rec)
        if club["n_matches"]:
            _print_ledger("club", club)
    finally:
        db.close()


if __name__ == "__main__":
    main()
