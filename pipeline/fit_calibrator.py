"""Fit the production calibrator and (optionally) ship it (model v2 C2).

Fits segmented vector scaling on the walk-forward validation window ending the
day before WC26 kicks off, on top of the CURRENTLY SHIPPED goals params — the
pairing that will actually serve. Dry-run by default: prints the blob and the
validation-window metrics delta. --ship writes ml/models/model_params.json with
the blob and bumps the version string (merge + deploy stay human-gated).

Ablation evidence (docs/MODEL-V2-DESIGN.md §5): "+cal" was the only variant to
improve held-out log loss consistently (WC26 replay 0.8974 vs 0.9053; best ECE
on WC2018) — the segmented buckets are also the direct lever on favorite
overconfidence in lopsided-Elo matches.

Usage:
    PYTHONPATH=backend:. python -m pipeline.fit_calibrator [--ship]
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

#: First WC26 kickoff — the validation window must end strictly before the
#: tournament so the fit never sees a match the calibrator will score. Naive
#: datetime to match the enriched rows' historical dates (tune.py convention).
WC26_START = datetime(2026, 6, 11)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ship", action="store_true",
                        help="write the blob + version bump to model_params.json")
    parser.add_argument("--version", default="poisson-elo-v0.4",
                        help="version string to ship (default: poisson-elo-v0.4)")
    args = parser.parse_args()

    from dataclasses import replace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from ml.evaluation.experiments import fit_calibrator_for_params, score_variant
    from ml.evaluation.tune import validation_window
    from ml.models.params import load_params, save_params
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)

    params = load_params()
    val_rows = validation_window(rows, WC26_START)
    log.info("Fitting on %d validation matches (730d window before %s), "
             "goals params %s", len(val_rows), WC26_START.date(), params.version)

    blob = fit_calibrator_for_params(val_rows, params.to_dict())

    before = score_variant(val_rows, {"name": "shipped", "params": params.to_dict(),
                                      "form_channels": None, "calibrator": None})
    after = score_variant(val_rows, {"name": "shipped+cal", "params": params.to_dict(),
                                     "form_channels": None, "calibrator": blob})
    for label, m in (("before", before), ("after ", after)):
        log.info("  %s  log_loss=%.4f brier=%.4f acc=%.3f ece=%.4f",
                 label, m["log_loss"], m["brier"], m["accuracy"], m["ece"])
    log.info("calibrator blob: %s", blob)

    if not args.ship:
        log.info("dry run — pass --ship to write model_params.json")
        return 0

    shipped = replace(params, calibrator=blob, version=args.version)
    save_params(shipped)
    log.info("shipped %s to model_params.json", args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
