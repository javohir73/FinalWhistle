"""Try-scorer projection model (Wave 3).

Empirical anytime-try frequency, blended with a position prior and an
opponent position-concession rate. Outputs PROBABILITIES ONLY -- no odds,
no value badges (program-wide constraint).

WAVE 2 DEPENDENCY: reads history from NrlTryEvent
(backend/app/models) which was merged in Wave 2.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.models import NrlTeamList, NrlTryEvent

# Fallback anytime-try-per-game priors by position, used until enough
# nrl_team_lists-tagged try history accumulates to compute a real one (team
# lists only start being ingested this wave -- older nrl_try_events rows
# have no position tag yet). Ballpark NRL figures: fullback/wing/centre
# score often, forwards rarely.
FALLBACK_POSITION_PRIOR = {
    "FB": 0.55, "WG": 0.60, "CE": 0.45, "FE": 0.25, "HB": 0.20,
    "HK": 0.12, "PR": 0.10, "2R": 0.15, "LK": 0.18,
}
DEFAULT_PRIOR = 0.20  # unrecognised/unknown position code

W_EMPIRICAL = 0.5
W_POSITION_PRIOR = 0.3
W_OPPONENT_CONCESSION = 0.2


def player_empirical_rate(last10_tries: list[int], tries_season: int, games_season: int) -> float:
    """Fraction of games with >=1 try, with the last 10 games weighted 2x
    relative to earlier games in the season.

    Games before the last-10 window don't have individual try counts in the
    scorers payload (only last10 does) -- their "scored at least once" rate
    is approximated from the season aggregate via a Poisson-occupancy
    estimate (1 - e^-rate), the standard way to turn a per-game try RATE
    into a "scored at least once" PROBABILITY when only the total is known.
    """
    recent_n = len(last10_tries)
    recent_scored = sum(1 for t in last10_tries if t >= 1)
    older_games = max(games_season - recent_n, 0)

    if older_games <= 0:
        return recent_scored / recent_n if recent_n else 0.0

    recent_tries = sum(last10_tries)
    older_tries = max(tries_season - recent_tries, 0)
    older_scored_rate = 1 - math.exp(-older_tries / older_games)

    weighted_scored = 2 * recent_scored + older_games * older_scored_rate
    weighted_games = 2 * recent_n + older_games
    return weighted_scored / weighted_games if weighted_games else 0.0


def position_prior(db: Session, position: str) -> float:
    """League-wide anytime-try signal for `position`: share of
    nrl_team_lists rows at that position that are matched by a
    (match_id, team, player)-joined try event. Falls back to
    FALLBACK_POSITION_PRIOR when no team-list row at that position has been
    tagged yet (a simple relative-frequency signal, not a per-game rate --
    precise enough to blend, not precise enough to stand alone)."""
    total_tagged = db.query(NrlTeamList.id).filter(NrlTeamList.position == position).count()
    if total_tagged == 0:
        return FALLBACK_POSITION_PRIOR.get(position, DEFAULT_PRIOR)

    tries_at_position = (
        db.query(NrlTryEvent.id)
        .join(
            NrlTeamList,
            (NrlTeamList.match_id == NrlTryEvent.match_id)
            & (NrlTeamList.team == NrlTryEvent.team)
            & (NrlTeamList.player == NrlTryEvent.player),
        )
        .filter(NrlTeamList.position == position)
        .count()
    )
    if tries_at_position == 0:
        return FALLBACK_POSITION_PRIOR.get(position, DEFAULT_PRIOR)
    return min(tries_at_position / total_tagged, 1.0)


def _match_team_pairs(db: Session) -> dict[int, list[str]]:
    """match_id -> distinct team names appearing in that match's team list."""
    pairs: dict[int, list[str]] = {}
    for match_id, team in db.query(NrlTeamList.match_id, NrlTeamList.team).distinct():
        pairs.setdefault(match_id, [])
        if team not in pairs[match_id]:
            pairs[match_id].append(team)
    return pairs


def opponent_concession_rate(db: Session, opponent_team: str, position: str) -> float:
    """Rate at which `opponent_team` has conceded a try to `position`, among
    team-list-tagged matches where `opponent_team` faced the scoring team.
    Falls back to the league-wide position_prior when `opponent_team` has no
    tagged concession history yet (team-list tagging only starts this wave)."""
    pairs = _match_team_pairs(db)
    tries = (
        db.query(NrlTryEvent.match_id, NrlTryEvent.team, NrlTeamList.position)
        .join(
            NrlTeamList,
            (NrlTeamList.match_id == NrlTryEvent.match_id)
            & (NrlTeamList.team == NrlTryEvent.team)
            & (NrlTeamList.player == NrlTryEvent.player),
        )
        .all()
    )
    faced = conceded = 0
    for match_id, scoring_team, pos in tries:
        other = next((t for t in pairs.get(match_id, []) if t != scoring_team), None)
        if other != opponent_team:
            continue
        faced += 1
        if pos == position:
            conceded += 1
    if faced == 0:
        return position_prior(db, position)
    return conceded / faced


def project_p_anytime(
    empirical: float, position_prior_rate: float, opponent_rate: float,
    w_empirical: float = W_EMPIRICAL, w_position: float = W_POSITION_PRIOR,
    w_opponent: float = W_OPPONENT_CONCESSION,
) -> float:
    """Blend the three signals into a single probability, clamped to [0,1]."""
    p = w_empirical * empirical + w_position * position_prior_rate + w_opponent * opponent_rate
    return max(0.0, min(1.0, p))


def project_scorer(
    db: Session, opponent_team: str, position: str,
    last10_tries: list[int], tries_season: int, games_season: int,
) -> float:
    empirical = player_empirical_rate(last10_tries, tries_season, games_season)
    prior = position_prior(db, position)
    concession = opponent_concession_rate(db, opponent_team, position)
    return project_p_anytime(empirical, prior, concession)
