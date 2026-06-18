"""Leak-free training rows for the gradient-boosted W/D/L challenger.

Takes the enriched leak-free Elo rows (pipeline.backtest_data.build_enriched_rows)
and runs ONE chronological sweep, emitting per match a feature row whose rolling
features (form, goals for/against, head-to-head) reflect ONLY earlier matches.
Same windowing reducer as serving (ml.features.wdl_features.window_stats), so the
training and serving feature distributions match.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date

from ml.features.wdl_features import assemble_features, window_stats
from ml.models.baseline_logistic import result_label

# Modern-era floor: pre-1994 international football is a different regime and dilutes
# the booster. Rows older than this are dropped from training.
DATE_FLOOR = date(1994, 1, 1)

WINDOW = 10        # rolling form / goals window (matches pipeline/team_stats.py intent)
H2H_WINDOW = 5     # head-to-head window (matches build_features.head_to_head default)
_HALF_LIFE_DAYS = 8 * 365.25   # recency half-life ~8 years


def build_training_rows(enriched_rows: list[dict]) -> list[dict]:
    """Chronological sweep → list of {**features, label, date, competition,
    pre_home, pre_away}.

    `enriched_rows` MUST be oldest-first (build_enriched_rows orders by date, id).
    Rolling state is read BEFORE each match is folded in, so features never see the
    match's own result or any later match. Each row also carries pre_home/pre_away
    (the gate's Poisson side reuses them) plus date/competition — none of these are
    in FEATURE_NAMES, so the booster never sees them. Rows dated before DATE_FLOOR
    are skipped.
    """
    recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=WINDOW))   # team_id -> (gf, ga)
    counts: dict[int, int] = defaultdict(int)                              # team_id -> matches seen
    h2h: dict[frozenset[int], deque] = defaultdict(lambda: deque(maxlen=H2H_WINDOW))  # pair -> winner_id|None

    out: list[dict] = []
    for r in enriched_rows:
        if r["date"] < DATE_FLOOR:
            continue
        h, a = r["home_id"], r["away_id"]
        sh, sa = r["score_home"], r["score_away"]

        form_h, gf_h, ga_h, _ = window_stats(list(recent[h]))
        form_a, gf_a, ga_a, _ = window_stats(list(recent[a]))

        pair = frozenset((h, a))
        meetings = list(h2h[pair])
        home_wins = sum(1 for w in meetings if w == h)

        feats = assemble_features(
            elo_home=r["pre_home"], elo_away=r["pre_away"], is_neutral=r["is_neutral"],
            form_home=form_h, form_away=form_a,
            gf_avg_home=gf_h, gf_avg_away=gf_a, ga_avg_home=ga_h, ga_avg_away=ga_a,
            h2h_home_wins=home_wins, h2h_matches=len(meetings),
            data_points_home=counts[h], data_points_away=counts[a],
        )
        out.append({**feats, "label": result_label(sh, sa),
                    "date": r["date"], "competition": r["competition"],
                    "pre_home": r["pre_home"], "pre_away": r["pre_away"]})

        # Fold this match into the rolling state AFTER emitting (leak-free).
        recent[h].append((sh, sa))
        recent[a].append((sa, sh))
        counts[h] += 1
        counts[a] += 1
        winner = h if sh > sa else (a if sa > sh else None)
        h2h[pair].append(winner)
    return out


def training_weight(row: dict, ref_date: date) -> float:
    """Sample weight: exponential recency decay (~8yr half-life) × competition tier.
    Friendlies carry half weight (noisier, weaker line-ups)."""
    age_days = max(0, (ref_date - row["date"]).days)
    recency = 0.5 ** (age_days / _HALF_LIFE_DAYS)
    comp = (row.get("competition") or "").lower()
    tier = 0.5 if "friendly" in comp else 1.0
    return recency * tier
