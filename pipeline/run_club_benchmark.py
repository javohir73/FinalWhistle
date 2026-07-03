"""Benchmark the engine against the club closing line (docs/ROADMAP-ENGINE.md, Phase 1).

Phase 1 generalises the WC26 engine to club football via a SELF-CONTAINED,
OFFLINE pipeline that reuses the Phase-0 stack end-to-end (Elo replay ->
Poisson-Elo probabilities -> paired closing-line benchmark). It touches NO
database and makes NO network calls: it reads football-data.co.uk CSVs from
disk and prints the same closing-line report used for the World Cup.

Because Elo is path-dependent, all matches across every CSV are concatenated and
replayed oldest-first, so ratings diverge exactly as they would in a live season.
The market side always prefers the CLOSING odds columns (see
pipeline/ingest/football_data.py) — the sharpest public predictor, and the only
fair yardstick for "does the model beat the market?"

Usage::

    PYTHONPATH=backend:. python -m pipeline.run_club_benchmark \
        --csv data/raw/E0_2324.csv data/raw/E0_2223.csv \
        --league "Premier League" \
        --emit-json frontend/lib/club-benchmark-data.json

    CSV format: football-data.co.uk per-league exports (Div, Date, HomeTeam,
    AwayTeam, FTHG, FTAG, FTR, plus bookmaker odds columns). Club names pass
    through str.strip only — the national-team name mapper is NOT used, as it
    could mangle club names.

Deferred: live weekly per-league automation (a cron mirroring the WC26 --live
path) needs the 2026-27 season's fixtures and captured odds snapshots, so it is
intentionally out of scope here; this runner proves the edge offline first.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

from ml.evaluation.backtest import model_probs
from ml.evaluation.market_benchmark import (
    MatchedMatch,
    benchmark,
    devig,
    format_report,
    result_to_json,
)
from ml.ratings.elo import MatchInput, replay_with_prematch
from pipeline.ingest.football_data import load_football_data_csv

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def build_club_matched(csv_paths: list[str], league: str) -> list[MatchedMatch]:
    """Parse the CSVs and replay Elo leak-free into paired model/market matches.

    Steps: parse every CSV, concatenate, sort by date ascending (stable — so
    same-day rows keep their file order), assign a stable integer id per club,
    replay Elo recording each team's PRE-match rating, then for every match pair
    the model's Poisson-Elo probabilities with the de-vigged closing odds.
    Club matches are never at a neutral venue, so ``is_neutral=False``.
    """
    raw: list[dict] = []
    for path in csv_paths:
        raw.extend(load_football_data_csv(path))

    # Stable sort keeps same-date rows in the order they were read.
    raw.sort(key=lambda r: r["date"])

    team_ids: dict[str, int] = {}

    def _id(name: str) -> int:
        if name not in team_ids:
            team_ids[name] = len(team_ids)
        return team_ids[name]

    inputs = [
        MatchInput(
            home_id=_id(r["home_team"]),
            away_id=_id(r["away_team"]),
            score_home=r["home_score"],
            score_away=r["away_score"],
            competition=league,
            is_neutral=False,
        )
        for r in raw
    ]
    rows, _ = replay_with_prematch(inputs)

    matched: list[MatchedMatch] = []
    for rec, rep in zip(raw, rows):
        mp = model_probs(rep["pre_home"], rep["pre_away"], False)
        market = devig(rec["odds_home"], rec["odds_draw"], rec["odds_away"])
        sh, sa = rec["home_score"], rec["away_score"]
        label = "H" if sh > sa else ("A" if sh < sa else "D")
        matched.append(
            MatchedMatch(
                date=rec["date"],
                home=rec["home_team"],
                away=rec["away_team"],
                model_probs=mp,
                market_probs=market,
                label=label,
            )
        )
    return matched


def run_club_benchmark(
    csv_paths: list[str], league: str, emit_json: str | None = None
) -> int:
    """Run the club closing-line benchmark; print the report (and optional JSON)."""
    matched = build_club_matched(csv_paths, league)
    if not matched:
        log.error("no matches to benchmark — check the CSV paths / columns")
        return 1

    result = benchmark(matched)
    log.info("\n%s", format_report(result, league))
    if emit_json:
        payload = result_to_json(result, league, datetime.now(timezone.utc).isoformat())
        with open(emit_json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2))
        log.info("wrote benchmark JSON -> %s", emit_json)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--csv",
        nargs="+",
        required=True,
        metavar="PATH",
        help="one or more football-data.co.uk CSVs (concatenated, replayed oldest-first)",
    )
    ap.add_argument(
        "--league",
        required=True,
        metavar="NAME",
        help="league label for the report + JSON dataset (e.g. \"Premier League\")",
    )
    ap.add_argument(
        "--emit-json",
        metavar="PATH",
        help="also write the page-ready benchmark JSON to PATH",
    )
    args = ap.parse_args()
    return run_club_benchmark(args.csv, args.league, args.emit_json)


if __name__ == "__main__":
    raise SystemExit(main())
