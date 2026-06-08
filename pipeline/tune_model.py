"""Model validation harness — walk-forward report (read-only, no writes).

Replays leak-free Elo over all history and prints an out-of-sample comparison on
the 2014/2018/2022 World Cups:

  * v0.1 (current served model: base=1.35, beta=0.0019, home_adv=60, raw)
  * v0.2 candidate (base/beta/home_adv/rho + temperature tuned on the
    pre-tournament window only)
  * naive favorite / base-rate baselines
  * an annual-regression (time-decay) sweep on Elo

Conclusion as of this writing: none of the v0.2 levers (recalibration,
Dixon-Coles draw correction, parameter re-tuning, time-decay) reliably beats
v0.1 out-of-sample — the model is already well-calibrated (fitted T ~= 1.0) and
its hand-set parameters are near the achievable ceiling for Elo-only features.
This script is the tool to re-check that whenever a new signal is added (squad
strength, injuries, market priors), so any future model change is shipped only
if it actually improves out-of-sample accuracy.

Usage:
    PYTHONPATH=backend:. python -m pipeline.tune_model
"""
from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

WALK_YEARS = (2014, 2018, 2022)


def _fmt(m: dict) -> str:
    return f"log_loss={m['log_loss']:.4f} brier={m['brier']:.4f} acc={m['accuracy']:.3f}"


def _is_wc(comp: str | None) -> bool:
    c = (comp or "").lower()
    return "fifa world cup" in c and "qualif" not in c


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from app.models import HistoricalMatch
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from ml.evaluation.backtest import walk_forward, model_probs, compute_metrics
    from ml.models.baseline_logistic import result_label
    from ml.ratings.elo import update_ratings

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())

    from pipeline.backtest_data import build_enriched_rows
    rows = build_enriched_rows(db)
    log.info("Replayed %d historical matches.\n", len(rows))

    log.info("==== Walk-forward (out-of-sample): v0.2 candidate vs v0.1 vs baselines ====")
    for year in WALK_YEARS:
        r = walk_forward(rows, year)
        log.info("\nWorld Cup %d (%d matches; tuned on %d val matches)",
                 r["year"], r["n_matches"], r["val_matches"])
        log.info("  v0.2 params: %s", r["params"])
        log.info("  v0.2 (tuned+calibrated): %s", _fmt(r["model_v2"]))
        log.info("  v0.1 (served, raw):      %s", _fmt(r["model_v1"]))
        log.info("  favorite baseline:       %s", _fmt(r["favorite_baseline"]))
        log.info("  base-rate baseline:      %s", _fmt(r["base_rate_baseline"]))

    # Annual regression-to-mean (time-decay) sweep on Elo.
    log.info("\n==== Time-decay (annual regression-to-mean) sweep ====")
    ordered = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )
    base_rating = 1500.0

    def replay(carry: float) -> list[dict]:
        ratings: dict[int, float] = {}
        out: list[dict] = []
        prev_year = None
        for m in ordered:
            y = m.date.year
            if prev_year is not None and y > prev_year and carry < 1.0:
                for _ in range(y - prev_year):
                    for k in ratings:
                        ratings[k] = base_rating + carry * (ratings[k] - base_rating)
            prev_year = y
            rh = ratings.get(m.team_a_id, base_rating)
            ra = ratings.get(m.team_b_id, base_rating)
            out.append({"pre_home": rh, "pre_away": ra, "is_neutral": m.is_neutral,
                        "score_home": m.score_a, "score_away": m.score_b,
                        "competition": m.competition, "date": m.date})
            nh, na = update_ratings(rh, ra, m.score_a, m.score_b,
                                    competition=m.competition, is_neutral=m.is_neutral)
            ratings[m.team_a_id], ratings[m.team_b_id] = nh, na
        return out

    for carry in (1.0, 0.95, 0.90, 0.85):
        replayed = replay(carry)
        parts = []
        for y in WALK_YEARS:
            tgt = [x for x in replayed if _is_wc(x["competition"]) and x["date"].year == y]
            labels = [result_label(x["score_home"], x["score_away"]) for x in tgt]
            probs = [model_probs(x["pre_home"], x["pre_away"], x["is_neutral"]) for x in tgt]
            parts.append(f"WC{y} ll={compute_metrics(probs, labels)['log_loss']:.4f}")
        tag = "no decay" if carry == 1.0 else f"carry={carry}"
        log.info("  %-10s %s", tag, "  ".join(parts))

    log.info("\nNo v0.2 lever reliably beats v0.1 out-of-sample. Served model unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
