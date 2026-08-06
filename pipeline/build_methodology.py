"""Generate frontend/lib/methodology-data.json — reproducible & honest.

Replays leak-free Elo over all historical results, evaluates the **v0.1 baseline
engine** (base=1.35, beta=0.0019, home_adv=60, raw Poisson — no Dixon-Coles, no
calibrator) against the naive baselines on each past World Cup, and builds the
reliability curve.

This is DELIBERATELY not the served engine, and the page says so out loud
(frontend/app/methodology/page.tsx, "Does it beat the obvious guesses?"). The
served parameters and the segmented calibrator were selected by walk-forward
over these same tournaments, so re-scoring 2014/2018/2022 with them would score
a model on its own selection data and publish a flattering number. The untuned
baseline is the honest floor; the forward-looking evidence is the live record
at /record, which no offline replay can launder.

An earlier docstring here claimed these numbers "always match the model that's
actually serving predictions". They never did, and by v0.6 (odds anchoring,
availability, suspensions) they could not — hence the explicit
``backtest_engine`` field below rather than a bare version string that reads
like a claim about production.

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

# NOTE: there used to be a CHANGELOG constant emitted here under the
# "changelog" output key. It hard-coded v0.1 as "current" long after v0.2/
# v0.4/v0.5 shipped, and nothing consumed the JSON key any more — the
# methodology page (frontend/app/methodology/page.tsx) renders its own
# hand-written, up-to-date changelog directly in JSX instead of reading
# `data.changelog`. Removed rather than relabeled so it can't drift again.


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
        # NOT the served version — see the module docstring. Named
        # "backtest_engine" precisely so nothing downstream can mistake it for
        # "what production runs"; the served version lives in
        # ml/models/model_params.json (internationals) and pipeline/leagues.py
        # (per club competition).
        "backtest_engine": "poisson-elo-v0.1",
        "backtest_engine_note": (
            "Untuned v0.1 baseline. The served engine's parameters and calibrator "
            "were selected using these same tournaments, so scoring them here "
            "would be selection leakage."
        ),
        "params": {"base": P_BASE, "beta": P_BETA, "home_adv": P_HOME},
        "training_matches": len(rows),
        "backtest_years": [y["year"] for y in years_out],
        "years": years_out,
        "reliability": reliability_curve(agg_probs, agg_labels, bins=10),
        "reliability_n": len(agg_labels),
    }
    _OUT.write_text(json.dumps(out, indent=2) + "\n")
    log.info("Wrote %s (%d World Cups, %d reliability pairs)", _OUT, len(years_out), len(agg_labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
