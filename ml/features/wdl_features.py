"""Canonical feature schema for the gradient-boosted W/D/L challenger.

This module is PURE (no DB, no model imports) and is the single source of truth
for the booster's feature vector. Both the training-row builder
(ml/features/training_rows.py) and the serving path (pipeline/generate_predictions.py)
assemble features through `assemble_features`/`to_vector`, so train/serve parity is
guaranteed by construction. `window_stats` is the shared last-N rolling reducer used
by both sides.

Deliberately excluded (see spec §2): FIFA rank (no leak-free history), is_home_host
(host advantage already lives in Elo home_adv; ~constant in training), and competition
tier (constant for WC matches at serve — it is used as a training sample weight in
training_rows.py instead of as a feature).
"""
from __future__ import annotations

# Average international goals per team per match — the cold-start fallback for a
# team with no recent history. Matches the spirit of poisson.BASE_GOALS.
DEFAULT_GOALS_AVG = 1.3

# Fixed feature order. NEVER reorder without retraining — fit and predict both
# rely on this order via to_vector().
FEATURE_NAMES = [
    "elo_diff", "elo_home", "elo_away", "is_neutral",
    "form_home", "form_away", "form_diff",
    "gf_avg_home", "gf_avg_away", "ga_avg_home", "ga_avg_away",
    "h2h_home_winrate", "h2h_matches",
    "data_points_home", "data_points_away",
]


def assemble_features(
    *, elo_home: float, elo_away: float, is_neutral: bool,
    form_home: float, form_away: float,
    gf_avg_home: float, gf_avg_away: float, ga_avg_home: float, ga_avg_away: float,
    h2h_home_wins: int, h2h_matches: int,
    data_points_home: int, data_points_away: int,
) -> dict[str, float]:
    """Build the ordered feature dict from raw, leak-free inputs."""
    winrate = h2h_home_wins / h2h_matches if h2h_matches else 0.5
    return {
        "elo_diff": elo_home - elo_away,
        "elo_home": elo_home,
        "elo_away": elo_away,
        "is_neutral": 1.0 if is_neutral else 0.0,
        "form_home": form_home,
        "form_away": form_away,
        "form_diff": form_home - form_away,
        "gf_avg_home": gf_avg_home,
        "gf_avg_away": gf_avg_away,
        "ga_avg_home": ga_avg_home,
        "ga_avg_away": ga_avg_away,
        "h2h_home_winrate": winrate,
        "h2h_matches": float(h2h_matches),
        "data_points_home": float(data_points_home),
        "data_points_away": float(data_points_away),
    }


def to_vector(feats: dict) -> list[float]:
    """Flatten a feature dict into the model's fixed-order vector."""
    return [feats[name] for name in FEATURE_NAMES]


def window_stats(appearances: list[tuple[int, int]]) -> tuple[float, float, float, int]:
    """Reduce a team's recent (goals_for, goals_against) appearances to
    (form_points, gf_avg, ga_avg, n). Empty history → (0, DEFAULT, DEFAULT, 0).

    form_points = sum of 3/1/0 per match (win/draw/loss). The SAME reducer is used
    by training (deque sweep) and serving (DB query), so the two paths cannot drift.
    """
    n = len(appearances)
    if n == 0:
        return 0.0, DEFAULT_GOALS_AVG, DEFAULT_GOALS_AVG, 0
    form = gf_sum = ga_sum = 0.0
    for gf, ga in appearances:
        gf_sum += gf
        ga_sum += ga
        form += 3 if gf > ga else (1 if gf == ga else 0)
    return float(form), gf_sum / n, ga_sum / n, n
