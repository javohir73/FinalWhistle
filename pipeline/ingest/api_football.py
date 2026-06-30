"""Live in-game score ingestion from API-Football (api-sports.io v3).

Unlike football-data.org's free tier, api-sports carries the OFFICIAL live
minute (fixture.status.elapsed) and added time (status.extra). Rather than
re-implement the match-update logic, to_feed() translates each api-sports
fixture into the SAME football-data v4 shape that
pipeline.ingest.live_scores.update_live_scores already consumes — so all the
tested behaviour (team orientation, freshness/lifecycle guards, period
derivation, penalty tally) is reused unchanged.

api-sports v3: GET /fixtures?league={id}&season={year}, auth via the
`x-apisports-key` header.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

# api-sports status.short -> football-data v4 status (a key of live_scores._STATUS_MAP).
_STATUS = {
    "TBD": "TIMED", "NS": "TIMED",
    "1H": "IN_PLAY", "2H": "IN_PLAY", "ET": "IN_PLAY", "P": "IN_PLAY", "LIVE": "IN_PLAY",
    "HT": "PAUSED", "BT": "PAUSED",          # half-time / break before extra time
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "AWD": "AWARDED", "WO": "AWARDED",
    "SUSP": "SUSPENDED", "INT": "SUSPENDED",
    "PST": "POSTPONED",
    "CANC": "CANCELLED", "ABD": "CANCELLED",
}
# Statuses signalling extra time / a shootout — surfaced via score.duration, the
# same channel football-data uses (status stays IN_PLAY/FINISHED).
_EXTRA_TIME = frozenset({"ET", "AET", "BT"})
_SHOOTOUT = frozenset({"P", "PEN"})

# api-sports goal-event detail -> our scorer type. Other details (e.g.
# "Missed Penalty") and non-Goal events are ignored.
_GOAL_DETAIL = {"Normal Goal": "goal", "Penalty": "penalty", "Own Goal": "own_goal"}


def fetch_fixtures(api_key: str, league: int, season: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw fixture list for a league+season from api-sports.io."""
    resp = requests.get(
        f"{BASE_URL}/fixtures",
        headers={"x-apisports-key": api_key},
        params={"league": league, "season": season},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        # api-sports answers 200 with an `errors` object on auth/quota/param issues.
        log.warning("api-football returned errors: %s", data["errors"])
    return data.get("response") or []


def fetch_events(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw event list for one fixture from api-sports.io."""
    resp = requests.get(
        f"{BASE_URL}/fixtures/events",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football events errors: %s", data["errors"])
    return data.get("response") or []


def fetch_lineups(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw lineup list for one fixture from api-sports.io.

    Display-only: the lineups feature never feeds the prediction model. Real
    lineups exist only ~40 min before kickoff, so this returns an empty list for
    fixtures the provider has no lineup for yet."""
    resp = requests.get(
        f"{BASE_URL}/fixtures/lineups",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        log.warning("api-football lineups errors: %s", data["errors"])
    return data.get("response") or []


def probe_player_access(api_key: str, league: int, season: int, timeout: float = 15.0) -> dict:
    """One-shot diagnostic: does this api-sports key reach current-season PLAYER
    data (the raw material for goalscorer predictions)? Calls /status and
    /players/topscorers and reports the plan + reachability — never the key, and
    never raises. api-sports answers 200 with an `errors` object on plan/quota
    issues, so reachability is judged by the topscorers result count."""
    out: dict = {
        "plan": None, "active": None, "requests": None,
        "player_data_reachable": False, "topscorers_results": 0, "note": None,
    }
    try:
        s = requests.get(f"{BASE_URL}/status", headers={"x-apisports-key": api_key}, timeout=timeout)
        sd = s.json().get("response")
        if isinstance(sd, dict):
            sub = sd.get("subscription") or {}
            out["plan"], out["active"] = sub.get("plan"), sub.get("active")
            out["requests"] = sd.get("requests")
        else:
            out["note"] = f"status errors: {s.json().get('errors')}"
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never raise
        out["note"] = f"status error: {exc}"
    try:
        t = requests.get(
            f"{BASE_URL}/players/topscorers",
            headers={"x-apisports-key": api_key},
            params={"league": league, "season": season},
            timeout=timeout,
        )
        td = t.json()
        out["topscorers_results"] = td.get("results") or 0
        out["player_data_reachable"] = bool(out["topscorers_results"])
        if td.get("errors"):
            sep = " | " if out["note"] else ""
            out["note"] = f"{out['note'] or ''}{sep}topscorers errors: {td['errors']}"
    except Exception as exc:  # noqa: BLE001
        sep = " | " if out["note"] else ""
        out["note"] = f"{out['note'] or ''}{sep}topscorers error: {exc}"
    return out


# api-sports position letter -> our normalized position. Goalkeeper/Defender/
# Midfielder/Forward all report a single leading letter (G/D/M/F); anything else
# (or a missing pos) is left as None rather than guessed.
_POSITIONS = frozenset({"G", "D", "M", "F"})


def _position(pos: object) -> str | None:
    """First letter of an api-sports position string, normalized to G/D/M/F."""
    if not isinstance(pos, str) or not pos:
        return None
    letter = pos[0].upper()
    return letter if letter in _POSITIONS else None


def _player_row(entry: object, is_starter: bool, order: int) -> dict | None:
    """Map one api-sports {player: {...}} entry into our lineup-player row dict,
    or None if it carries no usable name (never fabricate a player)."""
    if not isinstance(entry, dict):
        return None
    player = entry.get("player")
    if not isinstance(player, dict):
        return None
    name = player.get("name")
    if not name:
        return None
    return {
        "player_id": player.get("id"),
        "name": name,
        "number": player.get("number"),
        "position": _position(player.get("pos")),
        # Grid is "row:col" for starters and null on the bench (substitutes carry
        # no grid). Kept as the provider's string; the UI lays it out.
        "grid": player.get("grid") if is_starter else None,
        "is_starter": is_starter,
        "order": order,
    }


def parse_lineups(response: list[dict]) -> list[dict]:
    """PURE mapping: api-sports /fixtures/lineups response -> our per-team
    lineup dicts. Display-only; never feeds the prediction model.

    Each output item is
    ``{team, formation, coach, players: [row, ...]}`` where every row is the
    shape persisted to ``lineup_players`` (name, number, position, grid,
    is_starter, order). startXI rows are starters (grid kept); substitutes are
    bench (grid forced to None). Malformed teams / nameless players are skipped
    rather than fabricated."""
    out: list[dict] = []
    for team_block in response or []:
        if not isinstance(team_block, dict):
            continue
        team = (team_block.get("team") or {}).get("name")
        if not team:
            continue
        coach = (team_block.get("coach") or {}).get("name")
        players: list[dict] = []
        order = 0
        for entry in team_block.get("startXI") or []:
            row = _player_row(entry, is_starter=True, order=order)
            if row is not None:
                players.append(row)
                order += 1
        for entry in team_block.get("substitutes") or []:
            row = _player_row(entry, is_starter=False, order=order)
            if row is not None:
                players.append(row)
                order += 1
        out.append({
            "team": team,
            "formation": team_block.get("formation"),
            "coach": coach,
            "players": players,
        })
    return out


def _duration(short: str) -> str:
    if short in _SHOOTOUT:
        return "PENALTY_SHOOTOUT"
    if short in _EXTRA_TIME:
        return "EXTRA_TIME"
    return "REGULAR"


def _to_item(fx: object) -> dict | None:
    """Translate one api-sports fixture into a football-data v4 match dict, or
    None if it is malformed or carries a status we don't model."""
    if not isinstance(fx, dict):
        return None
    status = (fx.get("fixture") or {}).get("status") or {}
    fd_status = _STATUS.get(status.get("short"))
    if fd_status is None:
        return None

    teams = fx.get("teams") or {}
    home = (teams.get("home") or {}).get("name")
    away = (teams.get("away") or {}).get("name")
    if not home or not away:
        return None

    goals = fx.get("goals") or {}
    short = status.get("short")
    score: dict = {
        "fullTime": {"home": goals.get("home"), "away": goals.get("away")},
        "duration": _duration(short),
    }
    if short in _SHOOTOUT:
        pen = (fx.get("score") or {}).get("penalty") or {}
        score["penalties"] = {"home": pen.get("home"), "away": pen.get("away")}

    item: dict = {
        "homeTeam": {"name": home}, "awayTeam": {"name": away},
        "status": fd_status, "score": score,
    }
    league = fx.get("league") or (fx.get("fixture") or {}).get("league") or {}
    rnd = league.get("round")
    if rnd:
        item["stage"] = rnd
    elapsed = status.get("elapsed")
    if isinstance(elapsed, int):
        item["minute"] = elapsed           # the OFFICIAL live minute
    extra = status.get("extra")
    if isinstance(extra, int):
        item["injuryTime"] = extra
    item["_fixture_id"] = (fx.get("fixture") or {}).get("id")
    item["utcDate"] = (fx.get("fixture") or {}).get("date")
    return item


def to_feed(fixtures: list[dict]) -> list[dict]:
    """Translate an api-sports fixture list into football-data v4-shaped items,
    skipping malformed/unmodelled entries."""
    return [item for fx in (fixtures or []) if (item := _to_item(fx)) is not None]


def goals_from_events(events: list[dict], home_name: str, away_name: str) -> list[dict]:
    """Translate api-sports /fixtures/events into scorer dicts in our home/away
    orientation. Own goals are credited to the opponent of the scoring player's
    team. Non-goal events and unknown teams are skipped."""
    out: list[dict] = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "Goal":
            continue
        gtype = _GOAL_DETAIL.get(e.get("detail"))
        if gtype is None:
            continue
        team = (e.get("team") or {}).get("name")
        if team == home_name:
            side = "home"
        elif team == away_name:
            side = "away"
        else:
            continue
        if gtype == "own_goal":
            side = "away" if side == "home" else "home"
        out.append({
            "minute": (e.get("time") or {}).get("elapsed"),
            "side": side,
            "player": (e.get("player") or {}).get("name") or "Unknown",
            "type": gtype,
        })
    return out


# Statuses where new goals can have happened and scorers are worth fetching.
_SCORABLE = frozenset({"IN_PLAY", "PAUSED", "FINISHED"})


def attach_scorers(db, feed: list[dict], api_key: str) -> list[dict]:
    """Enrich feed items with a `scorers` list, fetching /fixtures/events ONLY
    for in-play/finished fixtures whose goal total differs from what's stored
    (so events are fetched ~once per goal, not every refresh)."""
    from pipeline.ingest.live_scores import _index_by_pair
    from pipeline.team_mapping import normalize_team_name

    index = _index_by_pair(db)
    for item in feed:
        if item.get("status") not in _SCORABLE:
            continue
        fid = item.get("_fixture_id")
        if fid is None:
            continue
        home, away = item["homeTeam"]["name"], item["awayTeam"]["name"]
        match = index.get(frozenset((normalize_team_name(home), normalize_team_name(away))))
        if match is None:
            continue
        ft = item["score"].get("fullTime") or {}
        total = (ft.get("home") or 0) + (ft.get("away") or 0)
        stored = len(match.goal_events) if match.goal_events is not None else -1
        if stored != total:
            item["scorers"] = goals_from_events(fetch_events(api_key, fid), home, away)
    return feed
