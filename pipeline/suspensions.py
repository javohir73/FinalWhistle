"""Suspension signal: who is banned for a team's next match, from card events.

FIFA World Cup discipline, minimal faithful subset:
- A red card (straight, or second-yellow — the feed collapses both to one
  "red" event) = banned for the team's NEXT tournament match. Longer
  committee-imposed bans are out of scope (one match is the floor).
- Two single yellows in DIFFERENT matches = a one-match ban served in the
  next match. Single yellows are WIPED after the quarter-finals, so
  accumulation alone can never rule a player out of the final.

Output is {provider_player_id: {"status": "out", "reason": ...}} — the exact
shape ml/models/availability.injury_availability_offset consumes, so the
suspension twin reuses the whole availability machinery (weights, clamps,
explanations). Card events store player NAMES; they're matched to squad rows
case-insensitively, and an unmatched name contributes nothing — garbled feed
data can never invent a ban.
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Match

# Single yellows are erased after the quarter-finals: for a match in one of
# these stages, accumulation only counts cards ALSO shown in these stages.
POST_WIPE_STAGES = {"SF", "third_place", "final"}


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def _team_side(m: Match, team_id: int) -> str | None:
    if m.team_home_id == team_id:
        return "home"
    if m.team_away_id == team_id:
        return "away"
    return None


def _cards(m: Match, side: str, kind: str) -> list[str]:
    """Normalized player names shown a card of ``kind`` for ``side`` in ``m``."""
    return [
        _norm(c.get("player"))
        for c in (m.card_events or [])
        if c.get("side") == side and c.get("type") == kind and c.get("player")
    ]


def _finished_before(db: Session, team_id: int, match: Match) -> list[Match]:
    """The team's finished tournament matches before ``match``, kickoff order."""
    return (
        db.query(Match)
        .filter(
            Match.status == "finished",
            Match.kickoff_utc < match.kickoff_utc,
            or_(Match.team_home_id == team_id, Match.team_away_id == team_id),
        )
        .order_by(Match.kickoff_utc)
        .all()
    )


def suspension_statuses(
    db: Session, match: Match, side: str, squad: list[dict]
) -> dict[int, dict]:
    """Suspended players for one side of an upcoming match, keyed by
    provider_player_id (injury-status shape: {"status": "out", "reason": ...}).

    Red cards ban from the team's most recent match regardless of stage; the
    yellow-accumulation window respects the post-quarter-final wipe. A ban is
    only reported when it is served in THIS match — a second yellow two games
    ago was already served and stays clear."""
    team_id = match.team_home_id if side == "home" else match.team_away_id
    if team_id is None:
        return {}
    prior = _finished_before(db, team_id, match)
    if not prior:
        return {}
    last = prior[-1]
    last_side = _team_side(last, team_id)
    if last_side is None:  # defensive: can't happen given the query filter
        return {}

    by_name = {_norm(p.get("name")): p.get("provider_player_id") for p in squad}
    out: dict[int, dict] = {}

    # Red card in the most recent match -> banned now.
    for name in _cards(last, last_side, "red"):
        pid = by_name.get(name)
        if pid is not None:
            out[pid] = {"status": "out", "reason": "suspended — red card last match"}

    # Yellow accumulation: 2 singles across matches, window wiped after the QF.
    if match.stage in POST_WIPE_STAGES:
        counted = [m for m in prior if m.stage in POST_WIPE_STAGES]
    else:
        counted = prior
    yellows_prev: dict[str, int] = {}
    yellows_last: dict[str, int] = {}
    for m in counted:
        m_side = _team_side(m, team_id)
        if m_side is None:
            continue
        tally = yellows_last if m is last else yellows_prev
        for name in _cards(m, m_side, "yellow"):
            tally[name] = tally.get(name, 0) + 1
    for name, c_last in yellows_last.items():
        c_prev = yellows_prev.get(name, 0)
        # The count reached 2 in the last match (not before) -> ban served NOW.
        if c_prev < 2 and c_prev + c_last >= 2:
            pid = by_name.get(name)
            if pid is not None and pid not in out:
                out[pid] = {"status": "out", "reason": "suspended — yellow-card accumulation"}
    return out


def suspension_offsets_for_match(db: Session, match: Match):
    """(off_home, off_away, expl_home, expl_away) from suspensions alone, or
    None when nobody is suspended on either side. Reuses the availability
    weight machinery: a suspended player is an "out" reference starter."""
    from app.availability import _squad_dicts  # lazy: avoids import cycle
    from ml.models.availability import injury_availability_offset

    squads: dict[str, list[dict]] = {}
    statuses: dict[str, dict[int, dict]] = {}
    for side in ("home", "away"):
        team_id = match.team_home_id if side == "home" else match.team_away_id
        if team_id is None:
            return None
        squads[side] = _squad_dicts(db, team_id)
        statuses[side] = suspension_statuses(db, match, side, squads[side])
    if not statuses["home"] and not statuses["away"]:
        return None
    results = []
    for side in ("home", "away"):
        res = injury_availability_offset(squads[side], statuses[side])
        if res is None:  # no tracked squad -> can't weigh the ban
            return None
        results.append(res)
    return results[0][0], results[1][0], results[0][1], results[1][1]


def keeper_pk_shift(squads: dict[str, list[dict]], statuses: dict[str, dict[int, dict]],
                    delta: float) -> float:
    """Shootout-probability shift when a first-choice goalkeeper is out.

    The starting keeper is the squad's top-minutes "G". Home keeper out ->
    -delta (home less likely to win the shootout); away keeper out -> +delta;
    both or neither -> 0. The caller feeds this to shootout_p's ``shift``,
    which clamps inside PK_BAND — delta can never escape the band."""
    if not delta:
        return 0.0

    def _keeper_out(side: str) -> bool:
        gks = [p for p in squads.get(side, []) if (p.get("position") or "") == "G"]
        if not gks:
            return False
        starter = max(
            gks, key=lambda p: (p.get("club_minutes") or 0) + (p.get("wc_minutes") or 0)
        )
        st = statuses.get(side, {}).get(starter.get("provider_player_id"))
        return bool(st and st.get("status") == "out")

    home_out, away_out = _keeper_out("home"), _keeper_out("away")
    if home_out == away_out:
        return 0.0
    return -delta if home_out else delta
