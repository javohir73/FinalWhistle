"""Distribute a team's expected goals (lambda) across its players to rank likely
scorers. xG_p = lambda * share_p, where share_p is proportional to a club+WC+
position blended scoring rate times a playing-time weight. P(score)=1-e^-xG.
Pure functions — same scoreline distribution philosophy as the goal-total markets."""
from __future__ import annotations

import math

# Goals-per-90 base rate by our position code (G/D/M/F); the shrinkage prior.
POS_RATE = {"F": 0.45, "M": 0.12, "D": 0.04, "G": 0.005}
DEFAULT_RATE = 0.08          # unknown/None position
K_SHRINK = 10.0              # position-prior pseudo-90s (shrinkage strength)
FULL_SEASON_MINUTES = 3000.0  # a regular starter's ~season minutes (squad weight)

# Playing-time weight by announced-lineup status.
_LINEUP_WEIGHT = {"starter": 1.0, "sub": 0.25}


def player_rate(club_goals: int, club_minutes: int, wc_goals: int, wc_minutes: int,
                position: str | None) -> float:
    """Shrunk goals-per-90: observed (club+WC) goals over 90s, pulled toward the
    position prior by K_SHRINK pseudo-90s. Low-minute players lean on position."""
    pos = POS_RATE.get(position or "", DEFAULT_RATE)
    nineties = ((club_minutes or 0) + (wc_minutes or 0)) / 90.0
    goals = (club_goals or 0) + (wc_goals or 0)
    return (goals + K_SHRINK * pos) / (nineties + K_SHRINK)


def squad_minutes_weight(club_minutes: int, wc_minutes: int) -> float:
    """Pre-lineup playing-time proxy: share of a full starter season, clamped."""
    total = (club_minutes or 0) + (wc_minutes or 0)
    return max(0.0, min(1.0, total / FULL_SEASON_MINUTES))


def goalscorers(lambda_team: float, players: list[dict], mode: str) -> list[dict]:
    """Ranked likely scorers for one team. `mode` is 'lineup' (weight by announced
    status) or 'squad' (weight by season minutes). Returns dicts with xg / p_score /
    p_score_2plus, sorted by xg desc; zero-weight players are omitted."""
    weighted: list[tuple[dict, float]] = []
    for p in players:
        rate = player_rate(p.get("club_goals"), p.get("club_minutes"),
                           p.get("wc_goals"), p.get("wc_minutes"), p.get("position"))
        if mode == "lineup":
            mins = _LINEUP_WEIGHT.get(p.get("lineup_status"), 0.0)
        else:
            mins = squad_minutes_weight(p.get("club_minutes"), p.get("wc_minutes"))
        weighted.append((p, rate * mins))

    total = sum(w for _, w in weighted)
    if total <= 0.0 or lambda_team is None or lambda_team <= 0.0:
        return []

    out: list[dict] = []
    for p, w in weighted:
        if w <= 0.0:
            continue
        xg = lambda_team * (w / total)
        xg_rounded = round(xg, 4)
        out.append({
            "provider_player_id": p.get("provider_player_id"),
            "name": p.get("name"),
            "position": p.get("position"),
            "xg": xg_rounded,
            "p_score": round(1.0 - math.exp(-xg_rounded), 4),
            "p_score_2plus": round(1.0 - math.exp(-xg_rounded) * (1.0 + xg_rounded), 4),
        })
    out.sort(key=lambda r: r["xg"], reverse=True)
    return out
