"""Generate frontend/lib/methodology-data.json — reproducible & honest.

Replays leak-free Elo over all historical results, evaluates the *served* model
(production v0.1 params: base=1.35, beta=0.0019, home_adv=60, raw Poisson) against
the naive baselines on each past World Cup, and builds the reliability curve.
Also emits the model changelog.

This replaces the previously hand-authored file so the published numbers always
match the model that's actually serving predictions.

Usage:
    PYTHONPATH=backend:. python -m pipeline.build_methodology
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

YEARS = (2014, 2018, 2022)
_OUT = Path("frontend/lib/methodology-data.json")

# Production v0.1 params (must match the served model — see ml/models/poisson.py
# and ml/ratings/elo.py).
P_BASE, P_BETA, P_HOME = 1.35, 0.0019, 60.0

# Model changelog — newest first. Keep this honest: only claim improvements that
# the walk-forward actually showed.
CHANGELOG = [
    {
        "version": "poisson-elo-v0.1",
        "date": "2026-05",
        "status": "current",
        "summary": "Elo strength → expected goals → Poisson scoreline grid → W/D/L "
                   "and most-likely score. Monte-Carlo for group & knockout odds.",
        "metrics": "Beats both naive baselines on log-loss in the 2014 & 2018 "
                   "back-tests; trails the favourite baseline in the upset-heavy 2022.",
    },
    {
        "version": "v0.2 study (not shipped)",
        "date": "2026-06",
        "status": "evaluated",
        "summary": "Walk-forward tested temperature calibration, a Dixon-Coles draw "
                   "correction, re-tuned goal parameters, and time-decayed Elo.",
        "metrics": "No reliable out-of-sample gain: fitted temperature ≈ 1.0 (already "
                   "calibrated) and re-tuning landed back on v0.1 values. v0.1 retained; "
                   "the harness gates any future change. Real gains need new signal "
                   "(squad strength, injuries, market priors).",
    },
]


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from ml.evaluation.backtest import (
        model_probs, compute_metrics, is_world_cup_final_match,
    )
    from ml.evaluation.calibration import reliability_curve
    from ml.evaluation.naive_baseline import FavoriteBaseline, BaseRateBaseline
    from ml.models.baseline_logistic import result_label

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)
    log.info("Replayed %d matches.", len(rows))

    LBL = {"H": 0, "D": 1, "A": 2}
    years_out = []
    agg_probs, agg_labels = [], []

    for year in YEARS:
        target = [r for r in rows if is_world_cup_final_match(r["competition"]) and r["date"].year == year]
        if not target:
            log.warning("no matches for %d, skipping", year)
            continue
        first = min(r["date"] for r in target)
        train = [r for r in rows if r["date"] < first]

        labels = [result_label(r["score_home"], r["score_away"]) for r in target]
        model_p = [model_probs(r["pre_home"], r["pre_away"], r["is_neutral"], P_BASE, P_BETA, P_HOME) for r in target]
        fav = FavoriteBaseline().fit(train)
        bse = BaseRateBaseline().fit(train)
        fav_p = [fav.predict_proba(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target]
        base_p = [bse.predict_proba(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target]

        m = compute_metrics(model_p, labels)
        f = compute_metrics(fav_p, labels)
        b = compute_metrics(base_p, labels)
        pick = lambda d: {k: round(d[k], 4) for k in ("log_loss", "brier", "accuracy")}
        years_out.append({
            "year": year, "n_matches": len(target),
            "model": pick(m), "favorite": pick(f), "base_rate": pick(b),
        })
        agg_probs.extend(model_p)
        agg_labels.extend(LBL[x] for x in labels)
        log.info("WC%d: model ll=%.4f | fav ll=%.4f | base ll=%.4f",
                 year, m["log_loss"], f["log_loss"], b["log_loss"])

    out = {
        "model_version": "poisson-elo-v0.1",
        "params": {"base": P_BASE, "beta": P_BETA, "home_adv": P_HOME},
        "training_matches": len(rows),
        "backtest_years": [y["year"] for y in years_out],
        "years": years_out,
        "reliability": reliability_curve(agg_probs, agg_labels, bins=10),
        "reliability_n": len(agg_labels),
        "changelog": CHANGELOG,
    }
    _OUT.write_text(json.dumps(out, indent=2) + "\n")
    log.info("Wrote %s (%d World Cups, %d reliability pairs)", _OUT, len(years_out), len(agg_labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
