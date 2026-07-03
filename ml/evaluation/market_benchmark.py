"""Benchmark model probabilities against the market's closing line.

The closing line (last pre-kickoff bookmaker consensus), de-vigged to remove
the overround, is the sharpest public predictor of match outcomes. This module
answers the only question that matters commercially: **are our probabilities
closer to reality than the market's?** (docs/ROADMAP-ENGINE.md, Phase 0).

Pure module — no DB, no network, no app imports. Orchestration lives in
pipeline/run_market_benchmark.py.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date as date_type

from ml.evaluation.backtest import compute_metrics
from ml.evaluation.naive_baseline import Probs

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15


def devig(odds_home: float, odds_draw: float, odds_away: float) -> Probs:
    """De-vig decimal odds -> implied probabilities summing to 1.

    Raw implied probability is 1/odds; the three sum to >1 by the bookmaker's
    margin (overround). Proportional normalization removes it.
    """
    if min(odds_home, odds_draw, odds_away) <= 1.0:
        raise ValueError("decimal odds must be > 1.0")
    raw = (1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away)
    total = sum(raw)
    return (raw[0] / total, raw[1] / total, raw[2] / total)


@dataclass(frozen=True)
class MatchedMatch:
    """One match where both a model and a market probability triple exist."""

    date: date_type
    home: str
    away: str
    model_probs: Probs
    market_probs: Probs
    label: str  # H / D / A


def join_odds_to_rows(
    rows: list[dict],
    odds_records: list[dict],
    id_to_name: dict[int, str],
    normalize=lambda s: s,
) -> tuple[list[MatchedMatch], list[dict]]:
    """Join market odds onto enriched backtest rows by (date, home, away).

    ``rows``: enriched replay rows (pipeline.backtest_data) restricted to the
    target matches, each carrying ``model_probs`` (attach before calling) plus
    home_id/away_id/date/score_home/score_away.
    ``odds_records``: dicts with keys date (datetime.date), home_team,
    away_team, odds_home, odds_draw, odds_away.

    Team orientation on neutral venues differs between sources, so a swapped
    (away, home) key also matches — with the H/A probabilities flipped.

    Returns (matched, unmatched_rows).
    """
    by_key: dict[tuple, dict] = {}
    for rec in odds_records:
        key = (rec["date"], normalize(rec["home_team"]), normalize(rec["away_team"]))
        by_key[key] = rec

    matched: list[MatchedMatch] = []
    unmatched: list[dict] = []
    for row in rows:
        home = normalize(id_to_name[row["home_id"]])
        away = normalize(id_to_name[row["away_id"]])
        d = row["date"].date() if hasattr(row["date"], "date") else row["date"]

        rec, swapped = by_key.get((d, home, away)), False
        if rec is None:
            rec, swapped = by_key.get((d, away, home)), True
        if rec is None:
            unmatched.append(row)
            continue

        market = devig(rec["odds_home"], rec["odds_draw"], rec["odds_away"])
        if swapped:
            market = (market[2], market[1], market[0])

        sh, sa = row["score_home"], row["score_away"]
        label = "H" if sh > sa else ("A" if sh < sa else "D")
        matched.append(
            MatchedMatch(
                date=d, home=home, away=away,
                model_probs=row["model_probs"], market_probs=market, label=label,
            )
        )
    return matched, unmatched


def _log_loss_one(probs: Probs, label: str) -> float:
    p = max(_EPS, min(1.0 - _EPS, probs[_LABEL_INDEX[label]]))
    return -math.log(p)


def benchmark(
    matched: list[MatchedMatch],
    n_bootstrap: int = 2000,
    seed: int = 26,
) -> dict:
    """Paired model-vs-market comparison on the same matches.

    Returns aggregate metrics for both predictors plus the paired statistics
    that actually decide the fork:

    - ``diff_log_loss``: mean per-match (model LL - market LL). Negative =
      model beats market.
    - ``diff_ci95``: bootstrap CI for that mean; if the whole interval is
      below 0 the edge is credible, if it straddles 0 the result is noise.
    - ``model_win_rate``: share of matches where the model's log-loss was
      strictly lower than the market's.
    - ``mean_edge``: mean (model prob - market prob) assigned to the realized
      outcome. Positive = model put more weight on what actually happened.
    """
    if not matched:
        raise ValueError("no matched matches to benchmark")

    labels = [m.label for m in matched]
    model_p = [m.model_probs for m in matched]
    market_p = [m.market_probs for m in matched]

    diffs = [
        _log_loss_one(mo, lb) - _log_loss_one(mk, lb)
        for mo, mk, lb in zip(model_p, market_p, labels)
    ]
    edges = [
        mo[_LABEL_INDEX[lb]] - mk[_LABEL_INDEX[lb]]
        for mo, mk, lb in zip(model_p, market_p, labels)
    ]

    rng = random.Random(seed)
    n = len(diffs)
    boot_means = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_bootstrap)
    )
    lo = boot_means[int(0.025 * n_bootstrap)]
    hi = boot_means[int(0.975 * n_bootstrap)]

    return {
        "n_matches": n,
        "model": compute_metrics(model_p, labels),
        "market": compute_metrics(market_p, labels),
        "diff_log_loss": sum(diffs) / n,
        "diff_ci95": (lo, hi),
        "model_win_rate": sum(1 for d in diffs if d < 0) / n,
        "mean_edge": sum(edges) / n,
    }


def _verdict(lo: float, hi: float) -> str:
    """Verdict string from the paired CI95 — shared by the report and the serializer."""
    if hi < 0:
        return "MODEL BEATS MARKET (credible: CI fully below 0)"
    if lo > 0:
        return "MARKET BEATS MODEL (credible: CI fully above 0)"
    return "NO CREDIBLE DIFFERENCE (CI straddles 0)"


def result_to_json(result: dict, dataset: str, updated_at: str) -> dict:
    """Serialize a benchmark result for the methodology page (rounded, JSON-ready)."""
    lo, hi = result["diff_ci95"]
    return {
        "status": "ready",
        "dataset": dataset,
        "n_matches": result["n_matches"],
        "updated_at": updated_at,
        "model": result["model"],
        "market": result["market"],
        "diff_log_loss": round(result["diff_log_loss"], 4),
        "diff_ci95": [round(lo, 4), round(hi, 4)],
        "model_win_rate": round(result["model_win_rate"], 4),
        "mean_edge": round(result["mean_edge"], 4),
        "verdict": _verdict(lo, hi),
    }


def format_report(result: dict, title: str) -> str:
    """Human-readable benchmark report (stable format — archived per run)."""
    mo, mk = result["model"], result["market"]
    lo, hi = result["diff_ci95"]
    d = result["diff_log_loss"]
    verdict = _verdict(lo, hi)
    lines = [
        f"=== Closing-line benchmark: {title} ({result['n_matches']} matches) ===",
        f"  {'':14s}{'log-loss':>10s}{'brier':>10s}{'accuracy':>10s}",
        f"  {'model':14s}{mo['log_loss']:>10.4f}{mo['brier']:>10.4f}{mo['accuracy']:>10.3f}",
        f"  {'market':14s}{mk['log_loss']:>10.4f}{mk['brier']:>10.4f}{mk['accuracy']:>10.3f}",
        "",
        f"  paired mean LL diff (model - market): {d:+.4f}  CI95 [{lo:+.4f}, {hi:+.4f}]",
        f"  model per-match win rate vs market:   {result['model_win_rate']:.1%}",
        f"  mean prob edge on realized outcome:   {result['mean_edge']:+.4f}",
        f"  verdict: {verdict}",
    ]
    return "\n".join(lines)
