"""One-time State of Origin history seed builder (design 2026-07-11).

Pulls 1982-2024 series results from TheSportsDB (league 5835,
eventsseason.php) and writes the committed seed file
data/raw/state_of_origin_history.json. Run ONCE, verify, commit the output;
serving never touches TheSportsDB — pipeline.sports.origin_ingest --seed
reads the committed file.

Unlike the ingest adapters this is strict, not best-effort: the seed must be
complete and clean, so any missing season, unknown team name, or malformed
field ABORTS the run (nonzero exit) instead of being skipped.

CLI: python -m pipeline.sports.origin_seed \
        --start 1982 --end 2024 --out data/raw/state_of_origin_history.json
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

import requests

from pipeline.sports.origin_names import CANONICAL, NSW, QLD

log = logging.getLogger(__name__)

API_URL = "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=5835&s={year}"
# TheSportsDB's dateEvent is date-only; Origin is an evening-AEST fixture, so
# pin a nominal 09:30 UTC kickoff. Only within-season ordering matters to the
# Elo replay and the three games are weeks apart, so the exact hour is moot.
_NOMINAL_TIME = "09:30:00Z"

# TheSportsDB league 5835 returns {"events": null} for 2016 (verified
# 2026-07-11, including alt season-string formats and a per-round query);
# results backfilled from the public record (Wikipedia: 2016 State of Origin
# series), QLD won 2-1.
_MANUAL_SEASONS: dict[int, list[dict]] = {
    2016: [
        {
            "season": 2016, "round": 1, "match_no": 1,
            "kickoff_utc": "2016-06-01 09:30:00Z",
            "venue": "ANZ Stadium",
            "home_team": NSW, "away_team": QLD,
            "score_home": 4, "score_away": 6,
        },
        {
            "season": 2016, "round": 2, "match_no": 2,
            "kickoff_utc": "2016-06-22 09:30:00Z",
            "venue": "Suncorp Stadium",
            "home_team": QLD, "away_team": NSW,
            "score_home": 26, "score_away": 16,
        },
        {
            "season": 2016, "round": 3, "match_no": 3,
            "kickoff_utc": "2016-07-13 09:30:00Z",
            "venue": "ANZ Stadium",
            "home_team": NSW, "away_team": QLD,
            "score_home": 18, "score_away": 14,
        },
    ],
}


def fetch_events(year: int, timeout: float = 20.0) -> list[dict]:
    """One season's raw events. Raises on any HTTP/JSON problem (strict).

    A single 429 gets one retry after a 30s cooldown — the free tier's
    per-minute window is short enough that a lone rate-limit hit is
    transient, not a reason to abort a 43-season run. A second 429 in a
    row is treated as real and raises.
    """
    resp = requests.get(
        API_URL.format(year=year), headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout
    )
    if resp.status_code == 429:
        time.sleep(30)
        resp = requests.get(
            API_URL.format(year=year), headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout
        )
    resp.raise_for_status()
    return resp.json().get("events") or []


def transform_events(events: list[dict], season: int) -> list[dict]:
    """TheSportsDB events -> seed match dicts (canonical names, feed-format
    kickoff string). Raises ValueError on anything unexpected."""
    matches = []
    for e in events:
        home = CANONICAL.get((e.get("strHomeTeam") or "").strip())
        away = CANONICAL.get((e.get("strAwayTeam") or "").strip())
        if home is None or away is None or home == away:
            raise ValueError(
                f"{season}: unrecognized teams "
                f"{e.get('strHomeTeam')!r} vs {e.get('strAwayTeam')!r}"
            )
        datetime.strptime(e["dateEvent"], "%Y-%m-%d")  # validate, keep string
        round_no = int(e["intRound"])
        matches.append({
            "season": season, "round": round_no, "match_no": round_no,
            "kickoff_utc": f"{e['dateEvent']} {_NOMINAL_TIME}",
            "venue": (e.get("strVenue") or "").strip() or None,
            "home_team": home, "away_team": away,
            "score_home": int(e["intHomeScore"]),
            "score_away": int(e["intAwayScore"]),
        })
    matches.sort(key=lambda m: m["round"])
    validate_season(matches, season)
    return matches


def validate_season(matches: list[dict], season: int) -> None:
    if len(matches) != 3:
        raise ValueError(f"{season}: expected 3 games, got {len(matches)}")
    rounds = [m["round"] for m in matches]
    if rounds != [1, 2, 3]:
        raise ValueError(f"{season}: rounds are {rounds}, expected [1, 2, 3]")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=1982)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    all_matches: list[dict] = []
    for year in range(args.start, args.end + 1):
        if year in _MANUAL_SEASONS:
            matches = _MANUAL_SEASONS[year]
            validate_season(matches, year)
            all_matches.extend(matches)
            log.info("%s: %d games (manual override — TheSportsDB gap)", year, len(matches))
            continue
        events = fetch_events(year)
        matches = transform_events(events, year)
        all_matches.extend(matches)
        log.info("%s: %d games", year, len(matches))
        time.sleep(2.5)  # free tier allows ~30 req/min

    draws = sum(1 for m in all_matches if m["score_home"] == m["score_away"])
    payload = {
        "source": (
            "TheSportsDB eventsseason.php, league 5835 (State of Origin); "
            "2016 backfilled from public record (Wikipedia)"
        ),
        "fetched": date.today().isoformat(),
        "matches": all_matches,
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    log.info(
        "wrote %s: %d matches, %d seasons, %d drawn games",
        args.out, len(all_matches), args.end - args.start + 1, draws,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
