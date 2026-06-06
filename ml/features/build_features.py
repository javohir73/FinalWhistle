"""Feature engineering for a single match (PRD §9.3).

Produces an interpretable feature dict used by the logistic baseline (task 3.5)
and the explanation generator (task 3.6). Every feature has a cold-start fallback
so no match is ever un-predictable (PRD §8.2): team strength falls back
Elo -> FIFA-rank estimate -> confederation average.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team, TeamStats

# Rough Elo-equivalent strength per confederation, for teams with no Elo and no
# FIFA rank (last-resort cold start). Intentionally coarse.
CONFEDERATION_DEFAULT_ELO = {
    "UEFA": 1750.0,
    "CONMEBOL": 1750.0,
    "CAF": 1550.0,
    "AFC": 1500.0,
    "CONCACAF": 1500.0,
    "OFC": 1300.0,
}
GLOBAL_DEFAULT_ELO = 1500.0


def estimate_strength(team: Team) -> tuple[float, str]:
    """Return (elo-like strength, source) using the cold-start fallback chain."""
    if team.elo_rating is not None:
        return team.elo_rating, "elo"
    if team.fifa_rank is not None:
        # Crude rank->Elo: rank 1 ~ 1846, rank 50 ~ 1650, rank 100 ~ 1450.
        return 1850.0 - 4.0 * team.fifa_rank, "fifa_rank"
    if team.confederation in CONFEDERATION_DEFAULT_ELO:
        return CONFEDERATION_DEFAULT_ELO[team.confederation], "confederation"
    return GLOBAL_DEFAULT_ELO, "default"


def latest_stats(db: Session, team_id: int) -> TeamStats | None:
    return (
        db.query(TeamStats)
        .filter_by(team_id=team_id)
        .order_by(TeamStats.as_of_date.desc())
        .first()
    )


def head_to_head(db: Session, a_id: int, b_id: int, last_n: int = 5) -> dict:
    """Recent head-to-head record from team A's perspective."""
    rows = (
        db.query(HistoricalMatch)
        .filter(
            ((HistoricalMatch.team_a_id == a_id) & (HistoricalMatch.team_b_id == b_id))
            | ((HistoricalMatch.team_a_id == b_id) & (HistoricalMatch.team_b_id == a_id))
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(last_n)
        .all()
    )
    a_wins = b_wins = draws = 0
    for m in rows:
        if m.score_a == m.score_b:
            draws += 1
            continue
        winner = m.team_a_id if m.score_a > m.score_b else m.team_b_id
        if winner == a_id:
            a_wins += 1
        else:
            b_wins += 1
    return {"matches": len(rows), "a_wins": a_wins, "draws": draws, "b_wins": b_wins}


@dataclass
class MatchFeatures:
    elo_home: float
    elo_away: float
    elo_diff: float
    strength_source_home: str
    strength_source_away: str
    fifa_rank_diff: float | None
    form_home: float | None
    form_away: float | None
    form_diff: float | None
    goals_for_avg_home: float | None
    goals_for_avg_away: float | None
    is_home_host: bool
    h2h: dict
    data_points_home: int
    data_points_away: int
    raw: dict = field(default_factory=dict)


def build_match_features(
    db: Session, home: Team, away: Team, host_team_id: int | None = None
) -> MatchFeatures:
    elo_home, src_home = estimate_strength(home)
    elo_away, src_away = estimate_strength(away)

    sh = latest_stats(db, home.id)
    sa = latest_stats(db, away.id)

    form_home = sh.form_points_last10 if sh else None
    form_away = sa.form_points_last10 if sa else None
    form_diff = (
        form_home - form_away if form_home is not None and form_away is not None else None
    )

    def goals_avg(stats: TeamStats | None) -> float | None:
        if stats and stats.matches_played:
            return round(stats.goals_for / stats.matches_played, 2)
        return None

    rank_diff = (
        away.fifa_rank - home.fifa_rank
        if home.fifa_rank is not None and away.fifa_rank is not None
        else None
    )

    return MatchFeatures(
        elo_home=elo_home,
        elo_away=elo_away,
        elo_diff=elo_home - elo_away,
        strength_source_home=src_home,
        strength_source_away=src_away,
        fifa_rank_diff=rank_diff,
        form_home=form_home,
        form_away=form_away,
        form_diff=form_diff,
        goals_for_avg_home=goals_avg(sh),
        goals_for_avg_away=goals_avg(sa),
        is_home_host=(host_team_id is not None and host_team_id == home.id),
        h2h=head_to_head(db, home.id, away.id),
        data_points_home=sh.matches_played if sh else 0,
        data_points_away=sa.matches_played if sa else 0,
    )
