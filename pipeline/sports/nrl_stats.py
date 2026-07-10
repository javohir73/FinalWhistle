"""NRL team-level match stats + try events (Wave 2).

StatsProvider protocol (frozen program-spec contract; Wave 3 consumes it),
frozen payload dataclasses, and pure parsers. Mirrors nrl_ingest.py
conventions: parse_* are pure (no I/O, no DB), returning None/[] for
malformed input rather than raising.

Source: decided by the Task 1 spike — NRL.com match-centre JSON (draw
endpoint for the round listing, plus each fixture's matchCentreUrl+"data"
document). See pipeline/sports/testdata/nrl_stats/SOURCE.md for full
provenance and the verified field map.

The real document shape differs from a naive "flat stats.groups title
lookup" in three ways (see SOURCE.md for the full derivation):
  - `tries`/`conversions` are NOT in `stats.groups` — they live on each
    team's `scoring.tries.made` / `scoring.conversions.made`.
  - `set_restarts` is NOT in `stats.groups` either — it's derived by
    counting `timeline` entries of type "SetRestart", split by `teamId`.
  - The remaining six stat fields are flat `stats.groups` title lookups,
    but the value lives at `stat["homeValue"]["value"]` /
    `stat["awayValue"]["value"]`, not a scalar `stat["home"]`.
  - Try events carry no minute/player-name/team-name directly: `minute` is
    derived from `gameSeconds // 60`, `player` is resolved via `playerId`
    against each team's `players[]`, `team` is resolved via `teamId`
    against `homeTeam`/`awayTeam`, and the running score is forward-filled
    across `Try`+`Goal` timeline entries sorted by `gameSeconds` (the
    home/away score keys are only present once that side has scored, and
    are absent — not zero — before that and on non-scoring event types).

Wave 2 Task 3 adds the default StatsProvider (NrlComStatsProvider):
fetch_match_stats is fully implemented (rate-limited HTTP against the
NRL.com endpoints adopted by the Task 1 spike, round-draw caching, and the
same never-raises convention as nrl_ingest.py). fetch_team_list and
fetch_live remain honest Wave 3 stubs ([] / None) — Wave 3 implements them
and the idempotent upsert/backfill CLI on top of this module.
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import requests
from sqlalchemy.orm import Session

from app.models import NrlMatchStat, NrlTryEvent, SportMatch, SportTeam

log = logging.getLogger(__name__)

SPORT = "nrl"


# --------------------------------------------------------------------------
# Payload types + StatsProvider protocol (FROZEN cross-wave contract).
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamStatsLine:
    """One team's stat line — field names match the API TeamMatchStats contract."""
    team: str                    # exact SportTeam.name spelling, e.g. "Knights"
    tries: int
    conversions: int
    penalties_conceded: int
    errors: int
    set_restarts: int
    run_metres: int
    line_breaks: int
    tackles: int
    tackle_efficiency: float     # percentage, e.g. 91.3


@dataclass(frozen=True)
class TryEventLine:
    minute: int
    team: str
    player: str
    score_home: int              # running score after this try (+conversion)
    score_away: int


@dataclass(frozen=True)
class MatchStatsPayload:
    home: TeamStatsLine
    away: TeamStatsLine
    try_events: list[TryEventLine] = field(default_factory=list)


@dataclass(frozen=True)
class TeamListEntry:
    """Shape-only in Wave 2; Wave 3's team-lists ingest populates it."""
    team: str
    jersey: int
    player: str
    position: str


@dataclass(frozen=True)
class LivePayload:
    """Shape-only in Wave 2; Wave 3's live layer populates it."""
    status: str                  # "pre" | "live" | "final"
    minute: int | None
    score_home: int
    score_away: int


class StatsProvider(Protocol):
    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None: ...
    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]: ...
    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None: ...


# --------------------------------------------------------------------------
# Pure parsers. ALL source-specific key names live in the blocks below —
# verified against the recorded fixtures per SOURCE.md's field map.
# --------------------------------------------------------------------------

# Stat-row titles as they appear in stats.groups[].stats[].title -> contract
# field, for the six fields that ARE flat title lookups. tries/conversions
# come from scoring.*.made; set_restarts is derived from the timeline — see
# module docstring and SOURCE.md.
_STAT_TITLES: dict[str, str] = {
    "penalties_conceded": "Penalties Conceded",
    "errors": "Errors",
    "run_metres": "All Run Metres",
    "line_breaks": "Line Breaks",
    "tackles": "Tackles Made",
    "tackle_efficiency": "Effective Tackle %",
}


def _num(value) -> float:
    """Best-effort numeric coercion ('1,432' / '91.3%' / 28 -> float)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _stat_lookup(doc: dict) -> dict[str, tuple[float, float]]:
    """Flatten the source's grouped stat rows into {title: (home, away)}.

    Each stat row is {"title": str, "homeValue": {"value": float, ...},
    "awayValue": {"value": float, ...}, ...} — the value is nested under
    "value", not a scalar stat["home"]/stat["away"].
    """
    out: dict[str, tuple[float, float]] = {}
    groups = (doc.get("stats") or {}).get("groups") or []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for stat in group.get("stats") or []:
            if not isinstance(stat, dict):
                continue
            title = stat.get("title")
            if not title:
                continue
            home_val = (stat.get("homeValue") or {}).get("value")
            away_val = (stat.get("awayValue") or {}).get("value")
            out[str(title)] = (_num(home_val), _num(away_val))
    return out


def _team_names(doc: dict) -> tuple[str, str] | None:
    home = (doc.get("homeTeam") or {}).get("nickName")
    away = (doc.get("awayTeam") or {}).get("nickName")
    if not home or not away:
        return None
    return str(home), str(away)


def _team_ids(doc: dict) -> tuple[object, object] | None:
    home_id = (doc.get("homeTeam") or {}).get("teamId")
    away_id = (doc.get("awayTeam") or {}).get("teamId")
    if home_id is None or away_id is None:
        return None
    return home_id, away_id


def _scoring_made(team_doc: dict, stat: str) -> int:
    """team_doc["scoring"][stat]["made"], e.g. stat="tries"/"conversions"."""
    scoring = (team_doc.get("scoring") or {}).get(stat) or {}
    return int(_num(scoring.get("made")))


def _count_set_restarts(doc: dict, home_id: object, away_id: object) -> tuple[int, int]:
    """Count timeline entries of type "SetRestart", split by teamId.

    Not a stats.groups title — no team-level "Set Restarts" stat row exists
    in the source; this is a derived count per SOURCE.md.
    """
    home = away = 0
    for entry in doc.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "SetRestart":
            continue
        team_id = entry.get("teamId")
        if team_id == home_id:
            home += 1
        elif team_id == away_id:
            away += 1
    return home, away


def _players_by_id(doc: dict) -> dict[object, str]:
    """{playerId: "First Last"} across both teams' players[]."""
    out: dict[object, str] = {}
    for side in ("homeTeam", "awayTeam"):
        for player in (doc.get(side) or {}).get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("playerId")
            if player_id is None:
                continue
            first = str(player.get("firstName") or "").strip()
            last = str(player.get("lastName") or "").strip()
            out[player_id] = f"{first} {last}".strip()
    return out


def _parse_try_events(
    doc: dict, home_id: object, home: str, away_id: object, away: str
) -> list[TryEventLine]:
    """Extract try events sorted by minute, with forward-filled running score.

    No `minutes`/`minute` field on timeline entries — minute is derived as
    `gameSeconds // 60`. No `playerName`/`teamNickName` strings — player and
    team are resolved via `playerId`/`teamId`. `homeScore`/`awayScore` are
    cumulative-at-that-instant but are absent (not 0) before a side's first
    score and on non-scoring event types, so the running score must be
    forward-filled across every Try/Goal(made) timeline entry in
    `gameSeconds` order rather than read off each Try event in isolation.
    Each Try event's own carried score already reflects the pre-conversion
    total immediately after that try (verified against SOURCE.md's
    transcribed try lists for both fixtures).
    """
    players = _players_by_id(doc)
    entries = [
        entry
        for entry in (doc.get("timeline") or [])
        if isinstance(entry, dict) and entry.get("type") in ("Try", "Goal")
    ]
    entries.sort(key=lambda entry: _num(entry.get("gameSeconds")))

    events: list[TryEventLine] = []
    score_home = 0
    score_away = 0
    for entry in entries:
        if "homeScore" in entry:
            score_home = int(_num(entry.get("homeScore")))
        if "awayScore" in entry:
            score_away = int(_num(entry.get("awayScore")))
        if entry.get("type") != "Try":
            continue
        team_id = entry.get("teamId")
        if team_id == home_id:
            team = home
        elif team_id == away_id:
            team = away
        else:
            continue  # unresolvable team id -- skip rather than guess
        minute = int(_num(entry.get("gameSeconds")) // 60)
        player = players.get(entry.get("playerId"), "")
        events.append(TryEventLine(
            minute=minute,
            team=team,
            player=player,
            score_home=score_home,
            score_away=score_away,
        ))
    events.sort(key=lambda e: e.minute)
    return events


def _stats_line(
    team: str,
    lookup: dict[str, tuple[float, float]],
    side: int,
    tries: int,
    conversions: int,
    set_restarts: int,
) -> TeamStatsLine | None:
    values: dict[str, float] = {}
    for fieldname, title in _STAT_TITLES.items():
        if title not in lookup:
            return None
        values[fieldname] = lookup[title][side]
    return TeamStatsLine(
        team=team,
        tries=tries,
        conversions=conversions,
        penalties_conceded=int(values["penalties_conceded"]),
        errors=int(values["errors"]),
        set_restarts=set_restarts,
        run_metres=int(values["run_metres"]),
        line_breaks=int(values["line_breaks"]),
        tackles=int(values["tackles"]),
        tackle_efficiency=values["tackle_efficiency"],
    )


def parse_match_stats(doc: dict) -> MatchStatsPayload | None:
    """Pure: recorded match-centre document -> MatchStatsPayload, or None if
    the document lacks team identity or any of the nine contract stat fields.
    """
    if not isinstance(doc, dict):
        return None
    names = _team_names(doc)
    ids = _team_ids(doc)
    if names is None or ids is None:
        return None
    home_name, away_name = names
    home_id, away_id = ids

    home_team_doc = doc.get("homeTeam") or {}
    away_team_doc = doc.get("awayTeam") or {}
    home_tries = _scoring_made(home_team_doc, "tries")
    away_tries = _scoring_made(away_team_doc, "tries")
    home_conversions = _scoring_made(home_team_doc, "conversions")
    away_conversions = _scoring_made(away_team_doc, "conversions")
    home_restarts, away_restarts = _count_set_restarts(doc, home_id, away_id)

    lookup = _stat_lookup(doc)
    home = _stats_line(
        home_name, lookup, side=0,
        tries=home_tries, conversions=home_conversions, set_restarts=home_restarts,
    )
    away = _stats_line(
        away_name, lookup, side=1,
        tries=away_tries, conversions=away_conversions, set_restarts=away_restarts,
    )
    if home is None or away is None:
        return None
    return MatchStatsPayload(
        home=home, away=away,
        try_events=_parse_try_events(doc, home_id, home_name, away_id, away_name),
    )


def parse_draw_fixtures(doc: dict) -> list[dict]:
    """Pure: round-draw document -> [{"home", "away", "match_path"}] for every
    fixture that has both team names and a match-centre path."""
    if not isinstance(doc, dict):
        return []
    out: list[dict] = []
    for fx in doc.get("fixtures") or []:
        if not isinstance(fx, dict):
            continue
        home = (fx.get("homeTeam") or {}).get("nickName")
        away = (fx.get("awayTeam") or {}).get("nickName")
        path = fx.get("matchCentreUrl")
        if home and away and path:
            out.append({"home": str(home), "away": str(away), "match_path": str(path)})
    return out


# --------------------------------------------------------------------------
# Default StatsProvider: rate-limited HTTP against the NRL.com endpoints
# adopted by the Task 1 spike. See SOURCE.md for full provenance.
# --------------------------------------------------------------------------

# URL shapes verified by the Task 1 spike — see SOURCE.md. If the spike found
# a different working variant (e.g. embedded q-data instead of a /data JSON
# document), adjust _MATCH_DATA_URL / _get_json here only.
_DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round_no}"
_MATCH_DATA_URL = "https://www.nrl.com{path}data"


class NrlComStatsProvider:
    """Default StatsProvider against the source adopted by the Task 1 spike.

    - team_names(season, round_no, match_no) -> (home, away) | None resolves
      OUR match identity to team names so the right source fixture is picked
      (the source has no notion of fixturedownload's match_no). The backfill
      CLI supplies a DB-backed lookup; tests supply a lambda.
    - Throttled: >= min_interval seconds between any two HTTP requests.
    - fetch_* NEVER raises (nrl_ingest convention): any failure -> None/[].
    """

    def __init__(
        self,
        team_names: Callable[[int, int, int], tuple[str, str] | None] | None = None,
        min_interval: float = 1.0,
        timeout: float = 20.0,
    ) -> None:
        self._team_names = team_names or (lambda season, round_no, match_no: None)
        self._min_interval = min_interval
        self._timeout = timeout
        self._last_request = 0.0
        self._draw_cache: dict[tuple[int, int], list[dict]] = {}

    # -- plumbing ----------------------------------------------------------

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get_json(self, url: str):
        self._throttle()
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - a feed hiccup must never abort a run
            log.warning("nrl_stats GET %s failed: %s", url, exc)
            return None

    def _round_fixtures(self, season: int, round_no: int) -> list[dict]:
        key = (season, round_no)
        if key not in self._draw_cache:
            doc = self._get_json(_DRAW_URL.format(season=season, round_no=round_no))
            if doc is None:
                # _get_json already logged the failure -- do NOT cache: a
                # transient fetch failure must not permanently zero this
                # round for the provider's lifetime. Retry on next call.
                return []
            self._draw_cache[key] = parse_draw_fixtures(doc) if isinstance(doc, dict) else []
        return self._draw_cache[key]

    # -- StatsProvider -----------------------------------------------------

    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None:
        try:
            names = self._team_names(season, round_no, match_no)
        except Exception as exc:  # noqa: BLE001 - a callback failure must never abort a run
            log.warning("nrl_stats: team_names callback raised for %s r%s m%s: %s",
                        season, round_no, match_no, exc)
            return None
        if names is None:
            log.warning("nrl_stats: no team names for %s r%s m%s", season, round_no, match_no)
            return None
        home, away = names
        fixture = next(
            (fx for fx in self._round_fixtures(season, round_no)
             if fx["home"] == home and fx["away"] == away),
            None,
        )
        if fixture is None:
            log.warning("nrl_stats: no source fixture for %s v %s (%s r%s)",
                        home, away, season, round_no)
            return None
        doc = self._get_json(_MATCH_DATA_URL.format(path=fixture["match_path"]))
        if not isinstance(doc, dict):
            return None
        return parse_match_stats(doc)

    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]:
        return []  # Wave 3 implements (team-lists ingest); honest empty until then

    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None:
        return None  # Wave 3 implements (live layer); honest None until then


# --------------------------------------------------------------------------
# Idempotent upsert: MatchStatsPayload -> nrl_match_stats + nrl_try_events.
# --------------------------------------------------------------------------

def upsert_match_stats(db: Session, match: SportMatch, payload: MatchStatsPayload) -> dict:
    """Atomically replace this match's rows in both stats tables.

    Idempotent: delete-then-insert per match_id in one transaction (try
    events have no natural unique key, so replace-all is the idempotency
    strategy). Only finished matches may carry stats — stats for a live
    match would go stale silently.
    """
    if match.status != "finished":
        raise ValueError(f"match {match.id} is not finished (status={match.status!r})")

    db.query(NrlTryEvent).filter_by(match_id=match.id).delete()
    db.query(NrlMatchStat).filter_by(match_id=match.id).delete()

    for line in (payload.home, payload.away):
        db.add(NrlMatchStat(
            match_id=match.id,
            team=line.team,
            tries=line.tries,
            conversions=line.conversions,
            penalties_conceded=line.penalties_conceded,
            errors=line.errors,
            set_restarts=line.set_restarts,
            run_metres=line.run_metres,
            line_breaks=line.line_breaks,
            tackles=line.tackles,
            tackle_efficiency=line.tackle_efficiency,
        ))
    for ev in payload.try_events:
        db.add(NrlTryEvent(
            match_id=match.id,
            team=ev.team,
            player=ev.player,
            minute=ev.minute,
            score_home=ev.score_home,
            score_away=ev.score_away,
        ))
    db.commit()
    return {"stats_rows": 2, "try_events": len(payload.try_events)}


# --------------------------------------------------------------------------
# Resumable, rate-limited backfill CLI.
# --------------------------------------------------------------------------

def _db_team_names(db: Session) -> Callable[[int, int, int], tuple[str, str] | None]:
    """team_names lookup for NrlComStatsProvider, backed by our sport_matches."""
    def lookup(season: int, round_no: int, match_no: int) -> tuple[str, str] | None:
        match = (
            db.query(SportMatch)
            .filter_by(sport=SPORT, season=season, round=round_no, match_no=match_no)
            .one_or_none()
        )
        if match is None or match.home_team_id is None or match.away_team_id is None:
            return None
        names = dict(
            db.query(SportTeam.id, SportTeam.name)
            .filter(SportTeam.id.in_([match.home_team_id, match.away_team_id]))
            .all()
        )
        home = names.get(match.home_team_id)
        away = names.get(match.away_team_id)
        if home is None or away is None:
            return None
        return home, away
    return lookup


def backfill_stats(db: Session, provider: StatsProvider, start: int, end: int) -> dict:
    """Backfill team stats for finished NRL matches, seasons start..end inclusive.

    Resumable: matches that already have nrl_match_stats rows are skipped
    before any fetch happens, so re-runs cost zero requests for done work.
    Rate limiting lives in the provider (>= 1s between requests).
    One bad match never aborts the run (rollback + continue).
    """
    summary = {"fetched": 0, "skipped_existing": 0, "missing": 0, "failed": 0}
    done_ids = {mid for (mid,) in db.query(NrlMatchStat.match_id).distinct().all()}
    matches = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.season >= start,
            SportMatch.season <= end,
            SportMatch.status == "finished",
        )
        .order_by(SportMatch.season, SportMatch.round, SportMatch.match_no)
        .all()
    )
    for match in matches:
        if match.id in done_ids:
            summary["skipped_existing"] += 1
            continue
        try:
            payload = provider.fetch_match_stats(match.season, match.round, match.match_no)
        except Exception as exc:  # noqa: BLE001 - one bad match must never abort the backfill
            log.warning("nrl_stats: fetch failed for match %s (%s r%s m%s): %s",
                        match.id, match.season, match.round, match.match_no, exc)
            summary["failed"] += 1
            continue
        if payload is None:
            summary["missing"] += 1
            continue
        try:
            upsert_match_stats(db, match, payload)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.warning("nrl_stats: upsert failed for match %s: %s", match.id, exc)
            summary["failed"] += 1
            continue
        summary["fetched"] += 1
    log.info("nrl_stats backfill %s-%s: %s", start, end, summary)
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--seasons", nargs=2, type=int, required=True, metavar=("START", "END"),
        help="inclusive season range to backfill, e.g. --seasons 2024 2026",
    )
    args = ap.parse_args()
    start, end = args.seasons

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider = NrlComStatsProvider(team_names=_db_team_names(db))
        backfill_stats(db, provider, start, end)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
