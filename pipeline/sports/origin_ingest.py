"""State of Origin ingest (design 2026-07-11).

Two idempotent entry points over sport="origin" rows, both flowing through
nrl_ingest.upsert_season — same parse, identity key (sport, season, round,
match_no), freshness guard (finished matches immutable) and best-effort CLI
idiom; origin passes sport= and team_name_map= instead of duplicating any of
it:

  --seed               load the committed history file (data/raw/
                       state_of_origin_history.json, 1982-2024, built once by
                       pipeline.sports.origin_seed from TheSportsDB).
  --seasons START END  fetch live seasons from fixturedownload
                       (state-of-origin-{year}, same JSON shape as nrl-{year}).

CLI: python -m pipeline.sports.origin_ingest --seed --seasons 2025 2027
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from pipeline.sports.nrl_ingest import fetch_season, upsert_season
from pipeline.sports.origin_names import CANONICAL

log = logging.getLogger(__name__)

SPORT = "origin"
FEED_URL = "https://fixturedownload.com/feed/json/state-of-origin-{year}"
SEED_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "state_of_origin_history.json"


def seed_rows_by_season(path: Path = SEED_FILE) -> dict[int, list[dict]]:
    """Committed seed matches -> feed-shape rows keyed by season, so the seed
    flows through the exact same parse/upsert path as the live feed."""
    data = json.loads(path.read_text())
    by_season: dict[int, list[dict]] = {}
    for m in data["matches"]:
        by_season.setdefault(m["season"], []).append({
            "MatchNumber": m["match_no"], "RoundNumber": m["round"],
            "DateUtc": m["kickoff_utc"], "Location": m["venue"],
            "HomeTeam": m["home_team"], "AwayTeam": m["away_team"],
            "HomeTeamScore": m["score_home"], "AwayTeamScore": m["score_away"],
        })
    return by_season


def _upsert(db, year: int, rows: list[dict]) -> None:
    """One season through upsert_season with the origin scope; best-effort
    (rollback + continue), mirroring nrl_ingest.main's per-season loop."""
    try:
        counts = upsert_season(db, year, rows, sport=SPORT, team_name_map=CANONICAL)
    except Exception as exc:  # noqa: BLE001 - one bad season must never abort the run
        db.rollback()
        log.warning("%s: upsert_season failed, skipping season: %s", year, exc)
        return
    log.info("%s: %d rows, created=%d updated=%d",
             year, len(rows), counts["created"], counts["updated"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", action="store_true", help="load the committed 1982-2024 history file")
    ap.add_argument("--seasons", nargs=2, type=int, metavar=("START", "END"),
                    help="inclusive year range to fetch from fixturedownload, e.g. --seasons 2025 2027")
    args = ap.parse_args()
    if not args.seed and not args.seasons:
        ap.error("pass --seed, --seasons, or both")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.seed:
            for year, rows in sorted(seed_rows_by_season().items()):
                _upsert(db, year, rows)
        if args.seasons:
            start, end = args.seasons
            for year in range(start, end + 1):
                rows = fetch_season(year, url_template=FEED_URL)
                if not rows:
                    log.info("%s: no data (feed empty or unavailable)", year)
                    continue
                _upsert(db, year, rows)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
