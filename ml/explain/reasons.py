"""Explainable-AI layer: confidence level + plain-English reasons (PRD §4.2, §12).

Turns the model's features and probabilities into (a) a High/Medium/Low
confidence label and (b) at least three human-readable reasons, plus normalized
"top factor" weights for the importance chart. This is what makes predictions
trustworthy rather than a black-box number.
"""
from __future__ import annotations

from ml.features.build_features import MatchFeatures


def confidence_level(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    data_points_home: int,
    data_points_away: int,
    cold_start: bool,
) -> str:
    """High/Medium/Low from how decisive the favorite is and how much data backs it."""
    favorite = max(prob_home, prob_draw, prob_away)
    if favorite >= 0.60:
        level = "High"
    elif favorite >= 0.45:
        level = "Medium"
    else:
        level = "Low"

    # Thin data or cold-start strength estimate -> downgrade one notch.
    thin = cold_start or min(data_points_home, data_points_away) < 3
    if thin:
        level = {"High": "Medium", "Medium": "Low", "Low": "Low"}[level]
    return level


def top_features(f: MatchFeatures) -> list[dict]:
    """Normalized factor weights (sum to 1) for the importance chart."""
    raw = {
        "elo_gap": abs(f.elo_diff),
        "form_last10": abs(f.form_diff) * 8 if f.form_diff is not None else 0.0,
        "head_to_head": (abs(f.h2h["a_wins"] - f.h2h["b_wins"]) * 60) if f.h2h["matches"] else 0.0,
        "host_advantage": 60.0 if f.is_home_host else 0.0,
    }
    total = sum(raw.values())
    if total == 0:
        return [{"name": "elo_gap", "weight": 1.0}]
    ranked = sorted(raw.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": k, "weight": round(v / total, 3)} for k, v in ranked if v > 0]


def generate_reasons(
    f: MatchFeatures,
    home_name: str,
    away_name: str,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
) -> list[str]:
    """Produce >= 3 plain-English reasons, strongest first."""
    favored, underdog = (home_name, away_name) if f.elo_diff >= 0 else (away_name, home_name)
    candidates: list[tuple[float, str]] = []

    # Elo gap
    gap = abs(f.elo_diff)
    if gap >= 20:
        descriptor = "a much higher" if gap >= 150 else "a higher"
        favored_elo, underdog_elo = (
            (f.elo_home, f.elo_away) if f.elo_diff >= 0 else (f.elo_away, f.elo_home)
        )
        candidates.append(
            (gap, f"{favored} has {descriptor} Elo rating "
                  f"({favored_elo:.0f} vs {underdog_elo:.0f}).")
        )
    else:
        candidates.append((10, f"{home_name} and {away_name} are closely matched on Elo."))

    # Form
    if f.form_diff is not None and abs(f.form_diff) >= 2:
        better = home_name if f.form_diff > 0 else away_name
        candidates.append((abs(f.form_diff) * 8,
                           f"{better} is in better recent form over their last matches."))

    # Head-to-head
    h = f.h2h
    if h["matches"] > 0 and h["a_wins"] != h["b_wins"]:
        winner, n = (home_name, h["a_wins"]) if h["a_wins"] > h["b_wins"] else (away_name, h["b_wins"])
        candidates.append((n * 50, f"{winner} won {n} of the last {h['matches']} meetings."))

    # Host advantage
    if f.is_home_host:
        candidates.append((55, f"{home_name} plays at home as a tournament host."))

    # Goals profile
    if f.goals_for_avg_home is not None and f.goals_for_avg_away is not None:
        if f.goals_for_avg_home - f.goals_for_avg_away >= 0.5:
            candidates.append((20, f"{home_name} has been scoring more freely "
                                   f"({f.goals_for_avg_home:.1f} vs {f.goals_for_avg_away:.1f} per game)."))
        elif f.goals_for_avg_away - f.goals_for_avg_home >= 0.5:
            candidates.append((20, f"{away_name} has been scoring more freely "
                                   f"({f.goals_for_avg_away:.1f} vs {f.goals_for_avg_home:.1f} per game)."))

    # Cold-start caveat
    if f.strength_source_home != "elo" or f.strength_source_away != "elo":
        weak = home_name if f.strength_source_home != "elo" else away_name
        candidates.append((5, f"Limited recent data for {weak}, so confidence is lower."))

    # Filler to guarantee >= 3 reasons.
    fillers = [
        f"Model gives {favored} the edge ({max(prob_home, prob_away):.0%} win probability).",
        f"A draw is estimated at {prob_draw:.0%}.",
        f"{underdog} would need to outperform expectations to win.",
    ]
    candidates.sort(key=lambda c: c[0], reverse=True)
    reasons = [text for _, text in candidates]
    for filler in fillers:
        if len(reasons) >= 3:
            break
        if filler not in reasons:
            reasons.append(filler)
    return reasons[: max(3, min(len(reasons), 5))]
