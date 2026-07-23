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
import json
import logging
import os
from datetime import date, datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

_EMPTY_MARKET_RECORD = {
    "status": "pending", "dataset": None, "n_matches": 0, "updated_at": None,
    "model": None, "market": None, "diff_log_loss": None, "diff_ci95": None,
    "model_win_rate": None, "mean_edge": None, "verdict": None,
}


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


def _write_json(path: str, result: dict, title: str) -> None:
    """Write the page-ready benchmark JSON (reproducible publish path)."""
    from ml.evaluation.market_benchmark import result_to_json

    payload = result_to_json(result, title, datetime.now(timezone.utc).isoformat())
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2))
    log.info("wrote benchmark JSON -> %s", path)


def run_historical(csv_path: str, year: int, emit_json: str | None = None) -> int:
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

    title = f"World Cup {year} (CSV closing odds)"
    result = benchmark(matched)
    log.info("\n%s", format_report(result, title))
    if emit_json:
        _write_json(emit_json, result, title)
    return 0


#: A second benchmark (model vs. the OPENING line) is only worth reporting
#: once enough matches carry an opening-phase snapshot to say something.
_MIN_OPENING_COMPARISON_MATCHES = 10


def market_record(db) -> dict:
    """Model-vs-market comparison from the live DB, page-ready. Honest-empty
    (status='pending') when no finished match has both a pre-kickoff prediction
    and a captured odds snapshot. Pure of HTTP."""
    from app.models import Match, Odds, Prediction, Team
    from ml.evaluation.market_benchmark import MatchedMatch, benchmark, result_to_json

    id_to_name = {t.id: t.name for t in db.query(Team).all()}
    finished = (
        db.query(Match)
        .filter(Match.status == "finished")
        .filter(Match.team_home_id.isnot(None), Match.team_away_id.isnot(None))
        .order_by(Match.kickoff_utc.asc())
        .all()
    )

    matched: list[MatchedMatch] = []
    opening_matched: list[MatchedMatch] = []
    skipped_no_odds = skipped_no_pred = 0
    for m in finished:
        odds_q = db.query(Odds).filter(
            Odds.match_id == m.id, Odds.implied_prob_home.isnot(None)
        )
        if m.kickoff_utc is not None:
            odds_q = odds_q.filter(Odds.captured_at <= m.kickoff_utc)
        candidates = odds_q.order_by(Odds.captured_at.desc()).all()
        # Prefer the closing-line snapshot when we have one; else the latest
        # pre-kickoff row (legacy behavior — NULL-phase rows keep working).
        o = next((c for c in candidates if c.snapshot_phase == "closing"), None)
        if o is None:
            o = candidates[0] if candidates else None
        if o is None:
            skipped_no_odds += 1
            continue

        pred_q = db.query(Prediction).filter(
            Prediction.match_id == m.id, Prediction.is_shadow.is_(False)
        )
        if m.kickoff_utc is not None:
            pred_q = pred_q.filter(Prediction.created_at <= m.kickoff_utc)
        p = pred_q.order_by(Prediction.created_at.desc()).first()
        if p is None:
            skipped_no_pred += 1
            continue
        # Ledger separation (league pivot): this record is WC26/international
        # only (the "WC26 live" label below is not just cosmetic) — skip a
        # match whose frozen production prediction belongs to a different
        # ledger, e.g. the EPL "poisson-elo-club-v..." family.
        if not p.model_version.startswith("poisson-elo-v"):
            continue

        sh = m.score_home_90 if m.score_home_90 is not None else m.score_home
        sa = m.score_away_90 if m.score_away_90 is not None else m.score_away
        if sh is None or sa is None:
            continue
        label = "H" if sh > sa else ("A" if sh < sa else "D")
        date = (m.kickoff_utc or datetime.now(timezone.utc)).date()
        home = id_to_name.get(m.team_home_id, str(m.team_home_id))
        away = id_to_name.get(m.team_away_id, str(m.team_away_id))
        model_probs = (p.prob_home_win, p.prob_draw, p.prob_away_win)
        matched.append(MatchedMatch(
            date=date, home=home, away=away, model_probs=model_probs,
            market_probs=(o.implied_prob_home, o.implied_prob_draw, o.implied_prob_away),
            label=label,
        ))

        opening = next((c for c in candidates if c.snapshot_phase == "opening"), None)
        if opening is not None:
            opening_matched.append(MatchedMatch(
                date=date, home=home, away=away, model_probs=model_probs,
                market_probs=(opening.implied_prob_home, opening.implied_prob_draw,
                             opening.implied_prob_away),
                label=label,
            ))

    log.info(
        "market record: finished=%d benchmarked=%d no_odds=%d no_pred=%d opening=%d",
        len(finished), len(matched), skipped_no_odds, skipped_no_pred, len(opening_matched),
    )
    if not matched:
        return dict(_EMPTY_MARKET_RECORD)
    result = benchmark(matched)
    payload = result_to_json(
        result,
        "WC26 live (final pre-kickoff consensus we captured)",
        datetime.now(timezone.utc).isoformat(),
    )
    if len(opening_matched) >= _MIN_OPENING_COMPARISON_MATCHES:
        payload["opening_comparison"] = result_to_json(
            benchmark(opening_matched),
            "WC26 live (opening line vs model)",
            datetime.now(timezone.utc).isoformat(),
        )
    return payload


def run_live(emit_json: str | None = None) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set")
        return 1
    db = sessionmaker(bind=create_engine(url, future=True), future=True)()

    rec = market_record(db)
    log.info("status=%s n_matches=%s verdict=%s",
             rec["status"], rec["n_matches"], rec.get("verdict"))
    if emit_json:
        with open(emit_json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, indent=2))
        log.info("wrote benchmark JSON -> %s", emit_json)
    return 0 if rec["status"] == "ready" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--csv", help="closing-odds CSV for a historical World Cup")
    mode.add_argument("--live", action="store_true", help="benchmark WC26 from the live DB")
    ap.add_argument("--year", type=int, default=2018, help="World Cup year for --csv mode")
    ap.add_argument(
        "--emit-json",
        metavar="PATH",
        help="also write the page-ready benchmark JSON to PATH "
        "(e.g. frontend/lib/market-benchmark-data.json)",
    )
    args = ap.parse_args()
    if args.live:
        return run_live(args.emit_json)
    return run_historical(args.csv, args.year, args.emit_json)


if __name__ == "__main__":
    raise SystemExit(main())
