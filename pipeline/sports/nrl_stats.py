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

Wave 3 implements the fetchers (fetch_match_stats/fetch_team_list/
fetch_live) and the idempotent upsert/backfill CLI on top of this module;
Wave 2 only ships the frozen contract and the pure parsers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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
