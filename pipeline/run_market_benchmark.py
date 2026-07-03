"""Benchmark the model against closing odds (docs/ROADMAP-ENGINE.md, Phase 0).

Two modes:

Historical CSV — replay Elo leak-free (same setup as pipeline.run_backtest),
predict a past World Cup, join bookmaker closing odds from a CSV and compare::

    PYTHONPATH=backend:. python -m pipeline.run_market_benchmark \
        --csv data/raw/wc2018_odds.csv --year 2018

    CSV columns: date (YYYY-MM-DD), home_team, away_team,
                 odds_home, odds_draw, odds_away  (decimal closing odds).
    Sources: football-data.co.uk-style exports, Kaggle WC odds datasets,
    OddsPortal exports. Team names pass through team_mapping.normalize.

Live DB — compare stored pre-kickoff predictions against the latest captured
odds snapshot for finished WC26 matches (run after each match day; archive
the output — the log is append-only)::

    DATABASE_URL=postgres://… PYTHONPATH=backend:. \
        python -m pipeline.run_market_benchmark --live
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def load_odds_csv(path: str) -> list[dict]:
    """Read a closing-odds CSV into join-ready records."""
    records: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            try:
                records.append(
                    {
                        "date": date.fromisoformat(row["date"].strip()[:10]),
                        "home_team": row["home_team"].strip(),
                        "away_team": row["away_team"].strip(),
                        "odds_home": float(row["odds_home"]),
                        "odds_draw": float(row["odds_draw"]),
                        "odds_away": float(row["odds_away"]),
                    }
                )
            except (KeyError, ValueError) as exc:
                log.warning("skipping CSV line %d: %s", i, exc)
    return records


def run_historical(csv_path: str, year: int) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.models  # noqa: F401
    from app.models import Team
    from ml.evaluation.backtest import is_world_cup_final_match, model_probs
    from ml.evaluation.market_benchmark import benchmark, format_report, join_odds_to_rows
    from pipeline.backtest_data import build_enriched_rows
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from pipeline.team_mapping import normalize_team_name

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    log.info("Downloading historical results …")
    load_historical(db, download_results_df())
    rows = build_enriched_rows(db)
    id_to_name = {t.id: t.name for t in db.query(Team).all()}

    target = [
        r for r in rows
        if is_world_cup_final_match(r["competition"]) and r["date"].year == year
    ]
    if not target:
        log.error("no World Cup %d matches in the historical data", year)
        return 1
    for r in target:
        r["model_probs"] = model_probs(r["pre_home"], r["pre_away"], r["is_neutral"])

    odds_records = load_odds_csv(csv_path)
    matched, unmatched = join_odds_to_rows(
        target, odds_records, id_to_name, normalize=normalize_team_name
    )
    if unmatched:
        log.warning(
            "%d/%d matches had no odds row (check team spellings/dates): %s",
            len(unmatched), len(target),
            ", ".join(
                f"{id_to_name[r['home_id']]}–{id_to_name[r['away_id']]}"
                for r in unmatched[:8]
            ),
        )
    if not matched:
        log.error("no matches joined — nothing to benchmark")
        return 1

    log.info("\n%s", format_report(benchmark(matched), f"World Cup {year} (CSV closing odds)"))
    return 0


def run_live() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Match, Odds, Prediction, Team
    from ml.evaluation.market_benchmark import MatchedMatch, benchmark, format_report

    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set")
        return 1
    db = sessionmaker(bind=create_engine(url, future=True), future=True)()

    id_to_name = {t.id: t.name for t in db.query(Team).all()}
    finished = (
        db.query(Match)
        .filter(Match.status == "finished")
        .filter(Match.team_home_id.isnot(None), Match.team_away_id.isnot(None))
        .order_by(Match.kickoff_utc.asc())
        .all()
    )

    matched: list[MatchedMatch] = []
    skipped_no_odds = skipped_no_pred = 0
    for m in finished:
        # Closing snapshot: the LAST consensus row captured before kickoff.
        odds_q = db.query(Odds).filter(
            Odds.match_id == m.id,
            Odds.implied_prob_home.isnot(None),
        )
        if m.kickoff_utc is not None:
            odds_q = odds_q.filter(Odds.captured_at <= m.kickoff_utc)
        o = odds_q.order_by(Odds.captured_at.desc()).first()
        if o is None:
            skipped_no_odds += 1
            continue

        # Serving prediction: last non-shadow row created before kickoff
        # (falls back to latest if created_at/kickoff is missing).
        pred_q = db.query(Prediction).filter(
            Prediction.match_id == m.id, Prediction.is_shadow.is_(False)
        )
        if m.kickoff_utc is not None:
            pred_q = pred_q.filter(Prediction.created_at <= m.kickoff_utc)
        p = pred_q.order_by(Prediction.created_at.desc()).first()
        if p is None:
            skipped_no_pred += 1
            continue

        sh = m.score_home_90 if m.score_home_90 is not None else m.score_home
        sa = m.score_away_90 if m.score_away_90 is not None else m.score_away
        if sh is None or sa is None:
            continue
        label = "H" if sh > sa else ("A" if sh < sa else "D")

        matched.append(
            MatchedMatch(
                date=(m.kickoff_utc or datetime.utcnow()).date(),
                home=id_to_name.get(m.team_home_id, str(m.team_home_id)),
                away=id_to_name.get(m.team_away_id, str(m.team_away_id)),
                model_probs=(p.prob_home_win, p.prob_draw, p.prob_away_win),
                market_probs=(o.implied_prob_home, o.implied_prob_draw, o.implied_prob_away),
                label=label,
            )
        )

    log.info(
        "finished matches: %d | benchmarked: %d | no odds: %d | no pre-KO prediction: %d",
        len(finished), len(matched), skipped_no_odds, skipped_no_pred,
    )
    if not matched:
        log.error("nothing to benchmark yet")
        return 1
    log.info("\n%s", format_report(benchmark(matched), "WC26 live (captured closing snapshots)"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--csv", help="closing-odds CSV for a historical World Cup")
    mode.add_argument("--live", action="store_true", help="benchmark WC26 from the live DB")
    ap.add_argument("--year", type=int, default=2018, help="World Cup year for --csv mode")
    args = ap.parse_args()
    return run_live() if args.live else run_historical(args.csv, args.year)


if __name__ == "__main__":
    raise SystemExit(main())
