"""On-demand match-lineup fetch + persist (display-only).

The lineups feature is DISPLAY-ONLY: it never feeds the prediction model. It also
degrades gracefully — a missing API key, a future fixture, or any provider/network
error resolves to a clean ``{ available: false }`` placeholder (never a 5xx, never
fabricated player data).

Flow (single entry point ``get_match_lineups``):
1. If lineups for the match are already stored -> serialize and return them.
2. Else if the match is within the lineup window (kickoff-75min .. finished) AND an
   API key is configured AND a provider fixture id resolves (stored, else by
   team-pair + kickoff date) -> fetch /fixtures/lineups, persist, return.
3. Else -> { available: false, message: <announced ~40 min before kickoff> } and
   make NO external call when out of window.

Mirrors live ingestion: reads the API-Football key the same way (settings) and
resolves the provider fixture id by the normalized team pair, like
``live_scores._index_by_pair``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import schemas
from app.config import settings
from app.models import LineupPlayer, Match, MatchLineup, Team

log = logging.getLogger(__name__)

PROVIDER = "api_football"

# Lineups are announced ~40 min before kickoff; we open the window a little
# earlier (75 min) to catch early team-sheet drops, and keep it open through the
# finished state so a completed match still serves its XI.
_WINDOW_BEFORE_KICKOFF = timedelta(minutes=75)

# Future fixture: lineups simply haven't dropped yet.
_PLACEHOLDER_UPCOMING = "Lineups are announced ~40 minutes before kickoff."
# Finished match with no lineup on file: nothing is "about to" be announced, so
# say so plainly rather than implying a future kickoff (honesty over a misleading
# "before kickoff" line on a match that's already over).
_PLACEHOLDER_UNAVAILABLE = "No official lineup was published for this match."


def _placeholder_message(match: Match) -> str:
    """The honest unavailable-message for a match's state."""
    return _PLACEHOLDER_UNAVAILABLE if match.status == "finished" else _PLACEHOLDER_UPCOMING


def _iso(dt: datetime | None) -> str | None:
    """ISO-8601 UTC string. SQLite drops tzinfo, so a naive value is assumed UTC
    (matches serializers._kickoff_iso)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _unavailable(message: str | None = _PLACEHOLDER_UPCOMING) -> schemas.MatchLineupsOut:
    return schemas.MatchLineupsOut(
        available=False, message=message, home=None, away=None, fetched_at=None
    )


def in_lineup_window(match: Match, now: datetime | None = None) -> bool:
    """True when official lineups could exist: the match is finished, or kickoff
    is within the next 75 minutes or already passed. A future fixture (kickoff
    more than 75 min away) is out of window -> no external call."""
    if match.status == "finished":
        return True
    if match.kickoff_utc is None:
        return False
    kickoff = match.kickoff_utc
    if kickoff.tzinfo is None:  # SQLite drops tzinfo; naive means UTC here
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now >= kickoff - _WINDOW_BEFORE_KICKOFF


def _side_team_name(match: Match, side: str) -> str:
    """Our canonical display name for a match side, from the home/away
    relationship; falls back to the side label if the team is unset."""
    team = match.home_team if side == "home" else match.away_team
    return team.name if team else side


def _team_lineup_out(match: Match, lineup: MatchLineup) -> schemas.TeamLineupOut:
    """Serialize a stored MatchLineup (+ its players) into the wire shape."""
    players = sorted(lineup.players, key=lambda p: p.order)
    start_xi = [
        schemas.LineupPlayerOut(
            name=p.name, number=p.number, position=p.position, grid=p.grid, is_starter=True
        )
        for p in players
        if p.is_starter
    ]
    bench = [
        schemas.LineupPlayerOut(
            name=p.name, number=p.number, position=p.position, grid=p.grid, is_starter=False
        )
        for p in players
        if not p.is_starter
    ]
    return schemas.TeamLineupOut(
        team=_side_team_name(match, lineup.side),
        formation=lineup.formation,
        coach=lineup.coach,
        start_xi=start_xi,
        bench=bench,
    )


def _serialize_stored(db: Session, match: Match) -> schemas.MatchLineupsOut | None:
    """Build the response from already-stored lineups, or None if none stored."""
    stored = {lu.side: lu for lu in match.lineups}
    if not stored:
        return None
    home = stored.get("home")
    away = stored.get("away")
    fetched = [lu.fetched_at for lu in match.lineups if lu.fetched_at is not None]
    return schemas.MatchLineupsOut(
        available=True,
        message=None,
        home=_team_lineup_out(match, home) if home is not None else None,
        away=_team_lineup_out(match, away) if away is not None else None,
        fetched_at=_iso(max(fetched)) if fetched else None,
    )


def _parse_iso(raw: object) -> datetime | None:
    """Parse an API-Football fixture ISO date (UTC-aware), or None if absent/bad."""
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _closest_by_date(candidates: list[tuple[int, object]], kickoff: datetime | None) -> int:
    """Pick the fixture id whose date is nearest our kickoff. Falls back to the
    first candidate when kickoff is unknown or no candidate has a parsable date —
    so a single-pair feed (or one without dates) still resolves correctly."""
    if kickoff is None:
        return candidates[0][0]
    if kickoff.tzinfo is None:  # SQLite drops tzinfo; naive means UTC here
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    best_fid, best_delta = candidates[0][0], None
    for fid, raw in candidates:
        dt = _parse_iso(raw)
        if dt is None:
            continue
        delta = abs((dt - kickoff).total_seconds())
        if best_delta is None or delta < best_delta:
            best_fid, best_delta = fid, delta
    return best_fid


def _resolve_fixture_id(db: Session, match: Match, api_key: str) -> int | None:
    """Provider fixture id for this match: the stored one if present, else
    resolved by the normalized home/away team pair against the season's fixtures
    (disambiguated by kickoff date when a pair recurs) and cached on the match.
    Returns None if it can't be resolved."""
    if match.provider_fixture_id is not None:
        return match.provider_fixture_id

    from pipeline.ingest.api_football import fetch_fixtures
    from pipeline.team_mapping import normalize_team_name

    home = db.get(Team, match.team_home_id) if match.team_home_id else None
    away = db.get(Team, match.team_away_id) if match.team_away_id else None
    if home is None or away is None:
        return None
    want = frozenset((normalize_team_name(home.name), normalize_team_name(away.name)))

    fixtures = fetch_fixtures(api_key, settings.api_football_league, settings.api_football_season)
    candidates: list[tuple[int, object]] = []  # (fixture_id, raw_date)
    for fx in fixtures or []:
        if not isinstance(fx, dict):
            continue
        teams = fx.get("teams") or {}
        fx_home = (teams.get("home") or {}).get("name")
        fx_away = (teams.get("away") or {}).get("name")
        if not fx_home or not fx_away:
            continue
        if frozenset((normalize_team_name(fx_home), normalize_team_name(fx_away))) != want:
            continue
        fid = (fx.get("fixture") or {}).get("id")
        if isinstance(fid, int):
            candidates.append((fid, (fx.get("fixture") or {}).get("date")))

    if not candidates:
        return None
    chosen = _closest_by_date(candidates, match.kickoff_utc)
    match.provider_fixture_id = chosen
    db.commit()
    return chosen


def _persist(db: Session, match: Match, parsed: list[dict]) -> None:
    """Persist parsed per-team lineups, mapping each provider team to our home/away
    side by the normalized team name. Idempotent on (match_id, side)."""
    from pipeline.team_mapping import normalize_team_name

    home = db.get(Team, match.team_home_id) if match.team_home_id else None
    away = db.get(Team, match.team_away_id) if match.team_away_id else None
    by_name: dict[str, str] = {}
    if home is not None:
        by_name[normalize_team_name(home.name)] = "home"
    if away is not None:
        by_name[normalize_team_name(away.name)] = "away"

    # Sides already on file (idempotent fill of a missing side) plus a guard for
    # the degenerate same-name case — never insert a duplicate (match_id, side)
    # and so never trip the UNIQUE constraint.
    taken = {lu.side for lu in match.lineups}
    now = datetime.now(timezone.utc)
    for team_block in parsed:
        side = by_name.get(normalize_team_name(team_block["team"]))
        if side is None or side in taken:
            continue  # unrecognized team, or this side is already stored — skip, never guess
        taken.add(side)
        lineup = MatchLineup(
            match_id=match.id,
            side=side,
            formation=team_block.get("formation"),
            coach=team_block.get("coach"),
            provider=PROVIDER,
            fetched_at=now,
        )
        for row in team_block["players"]:
            lineup.players.append(
                LineupPlayer(
                    name=row["name"],
                    number=row.get("number"),
                    position=row.get("position"),
                    grid=row.get("grid"),
                    is_starter=row["is_starter"],
                    order=row["order"],
                    provider_player_id=row.get("player_id"),
                )
            )
        db.add(lineup)
    db.commit()


def _resolve_lineups(db: Session, match: Match) -> schemas.MatchLineupsOut:
    """Core resolution: stored -> fetch-on-window -> placeholder. May raise;
    get_match_lineups wraps this so the page never 5xxes."""
    # 1. Both sides already cached -> authoritative, return as-is (no external
    #    call). A PARTIAL cache (one side) is NOT authoritative: team sheets drop
    #    a few minutes apart, so we try to fill the missing side below.
    stored_sides = {lu.side for lu in match.lineups}
    if {"home", "away"} <= stored_sides:
        result = _serialize_stored(db, match)
        if result is not None:
            return result

    # 2. Can't fetch (out of window, or no key) -> serve whatever partial cache we
    #    have rather than hiding it; otherwise a state-honest placeholder, NO call.
    in_window = in_lineup_window(match)
    api_key = settings.api_football_api_key
    if not in_window or not api_key:
        partial = _serialize_stored(db, match)
        if partial is not None:
            return partial
        return _unavailable(_PLACEHOLDER_UPCOMING if not in_window else _placeholder_message(match))

    # 3. In window + key set -> resolve fixture id and (re)fetch to fill missing
    #    side(s); _persist is idempotent so the already-stored side is untouched.
    fixture_id = _resolve_fixture_id(db, match, api_key)
    if fixture_id is None:
        return _serialize_stored(db, match) or _unavailable(_placeholder_message(match))
    from pipeline.ingest.api_football import fetch_lineups, parse_lineups

    parsed = parse_lineups(fetch_lineups(api_key, fixture_id))
    if not parsed:
        # Provider has no lineup yet (e.g. just inside the window) — serve any
        # partial cache, else a placeholder.
        return _serialize_stored(db, match) or _unavailable(_placeholder_message(match))
    _persist(db, match, parsed)
    db.refresh(match)
    return _serialize_stored(db, match) or _unavailable(_placeholder_message(match))


def get_match_lineups(db: Session, match: Match) -> schemas.MatchLineupsOut:
    """Resolve a match's lineups: stored -> fetch-on-window -> placeholder.

    Never raises. ANY error — a provider/network/key problem, a DB hiccup, or the
    lineups tables not existing yet (prod before the migration is applied) —
    degrades to ``available: false`` so the page is never broken by a 5xx. The
    guard wraps the whole resolution, including the first ``match.lineups`` read,
    precisely so a missing table can't escape as a 500."""
    try:
        return _resolve_lineups(db, match)
    except Exception as exc:  # noqa: BLE001 — display-only; must never 5xx the page
        log.warning("lineups unavailable for match %s: %s", match.id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 — rollback on a broken session is best-effort
            pass
        return _unavailable(_placeholder_message(match))
