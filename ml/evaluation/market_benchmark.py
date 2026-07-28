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
from datetime import date as date_type, datetime
from collections import Counter, defaultdict

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


def devig2(odds_a: float, odds_b: float) -> tuple[float, float]:
    """De-vig a 2-way market (e.g. over/under, BTTS) -> probabilities summing to 1.

    Same proportional de-vig as :func:`devig`, restricted to two mutually
    exclusive outcomes. The shorter price carries the larger probability.
    """
    if min(odds_a, odds_b) <= 1.0:
        raise ValueError("decimal odds must be > 1.0")
    raw = (1.0 / odds_a, 1.0 / odds_b)
    total = raw[0] + raw[1]
    return (raw[0] / total, raw[1] / total)


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


def _binary_log_loss(p: float, y: int) -> float:
    p = max(_EPS, min(1.0 - _EPS, p))
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def _binary_metrics(probs: list[float], labels: list[int]) -> dict:
    """log-loss, Brier, and accuracy for P(outcome=1) predictions (0/1 labels)."""
    n = len(labels)
    ll = brier = correct = 0.0
    for p, y in zip(probs, labels):
        ll += _binary_log_loss(p, y)
        brier += (p - y) ** 2
        if round(p) == y:
            correct += 1
    return {"log_loss": ll / n, "brier": brier / n, "accuracy": correct / n}


def benchmark_binary(
    model_p: list[float],
    market_p: list[float],
    labels: list[int],
    n_bootstrap: int = 2000,
    seed: int = 26,
) -> dict:
    """Paired model-vs-market comparison for a binary market (e.g. Over/Under 2.5).

    ``model_p`` / ``market_p`` are each P(outcome=1) (e.g. P(over)); ``labels``
    are the realized 0/1 outcomes. Returns the same shape as :func:`benchmark`:

    - ``diff_log_loss``: mean per-match (model LL - market LL). Negative =
      model beats market.
    - ``diff_ci95``: paired bootstrap CI for that mean; below 0 = credible edge,
      straddling 0 = noise.
    - ``model_win_rate``: share of matches where the model's log-loss was
      strictly lower than the market's.
    - ``mean_edge``: mean probability assigned to the *realized* direction, model
      minus market — ``(pm - pk)`` when y==1, ``((1-pm) - (1-pk))`` when y==0.
    """
    if not labels:
        raise ValueError("no matches to benchmark")

    diffs = [
        _binary_log_loss(mo, y) - _binary_log_loss(mk, y)
        for mo, mk, y in zip(model_p, market_p, labels)
    ]
    edges = [
        (mo - mk) if y == 1 else ((1.0 - mo) - (1.0 - mk))
        for mo, mk, y in zip(model_p, market_p, labels)
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
        "model": _binary_metrics(model_p, labels),
        "market": _binary_metrics(market_p, labels),
        "diff_log_loss": sum(diffs) / n,
        "diff_ci95": (lo, hi),
        "model_win_rate": sum(1 for d in diffs if d < 0) / n,
        "mean_edge": sum(edges) / n,
    }


def ou25_label(score_home: int, score_away: int) -> int:
    """Over/Under 2.5 outcome: 1 if total goals >= 3 (Over), else 0 (Under)."""
    return 1 if score_home + score_away >= 3 else 0


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


@dataclass(frozen=True)
class InPlayObservation:
    """One already-normalized pure-model/venue observation pair."""

    match_id: int
    venue: str
    market_type: str
    minute: float | None
    period: str
    model_probs: tuple[float, ...]
    venue_probs: tuple[float, ...]
    label: int
    tick_ts: datetime
    model_state_ts: datetime
    quote_source_ts: datetime | None
    model_score: tuple[int, int]
    venue_score: tuple[int, int]
    mapping_status: str = "mapped"
    supported: bool = True
    settled_at: datetime | None = None
    competition: str = "unknown"
    model_cards: tuple[int, int] = (0, 0)
    venue_cards: tuple[int, int] = (0, 0)


def inplay_horizon(minute: float | None, period: str) -> str | None:
    """Precommitted left-closed buckets; 90 is included in the final bucket."""
    if period == "half_time":
        return "halftime"
    if minute is None or minute < 0 or minute > 90:
        return None
    bounds = [(15, "0-15"), (30, "15-30"), (45, "30-45"), (60, "45-60"), (75, "60-75")]
    for end, label in bounds:
        if minute < end:
            return label
    return "75-90"


def _generic_metrics(rows: list[tuple[tuple[float, ...], int]]) -> dict:
    losses = []
    briers = []
    correct = 0
    bins = defaultdict(list)
    for probs, label in rows:
        p = max(_EPS, min(1 - _EPS, probs[label]))
        losses.append(-math.log(p))
        briers.append(sum((value - (index == label)) ** 2 for index, value in enumerate(probs)))
        prediction = max(range(len(probs)), key=probs.__getitem__)
        correct += prediction == label
        confidence = max(probs)
        bins[min(9, int(confidence * 10))].append((confidence, prediction == label))
    n = len(rows)
    ece = sum(
        len(values) / n * abs(sum(conf for conf, _ in values) / len(values) - sum(ok for _, ok in values) / len(values))
        for values in bins.values()
    )
    return {"log_loss": sum(losses) / n, "brier": sum(briers) / n, "accuracy": correct / n, "ece10": ece}


def _clustered_ci(diffs_by_match: dict[int, list[float]], *, n_bootstrap: int, seed: int) -> tuple[float, float]:
    match_ids = sorted(diffs_by_match)
    rng = random.Random(seed)
    means = []
    for _ in range(n_bootstrap):
        sampled = [match_ids[rng.randrange(len(match_ids))] for _ in match_ids]
        values = [value for match_id in sampled for value in diffs_by_match[match_id]]
        means.append(sum(values) / len(values))
    means.sort()
    return means[int(.025 * n_bootstrap)], means[min(n_bootstrap - 1, int(.975 * n_bootstrap))]


def benchmark_inplay(
    observations: list[InPlayObservation],
    *,
    held_out_cutoff: datetime,
    max_alignment_seconds: float = 10,
    max_quote_age_seconds: float = 30,
    minimum_matches: int = 5,
    n_bootstrap: int = 2000,
    seed: int = 20260727,
) -> dict:
    """Score comparable observations, separated by venue/type/horizon.

    Bootstrap samples match IDs and carries every selected tick from each sampled
    match. Exclusions are reported and never silently pooled.
    """
    exclusions = Counter()
    selected = []
    for row in observations:
        horizon = inplay_horizon(row.minute, row.period)
        if row.tick_ts < held_out_cutoff:
            exclusions["before_held_out_cutoff"] += 1
        elif row.mapping_status != "mapped":
            exclusions["unresolved_mapping"] += 1
        elif not row.supported:
            exclusions["unsupported_outcome"] += 1
        elif row.model_score != row.venue_score:
            exclusions["score_state_mismatch"] += 1
        elif row.model_cards != row.venue_cards:
            exclusions["card_state_mismatch"] += 1
        elif abs((row.tick_ts - row.model_state_ts).total_seconds()) > max_alignment_seconds:
            exclusions["model_state_misaligned"] += 1
        elif row.quote_source_ts is None or (row.tick_ts - row.quote_source_ts).total_seconds() > max_quote_age_seconds:
            exclusions["stale_or_missing_quote_time"] += 1
        elif row.settled_at is not None and row.tick_ts >= row.settled_at:
            exclusions["post_settlement_tick"] += 1
        elif horizon is None:
            exclusions["outside_regulation_horizon"] += 1
        elif len(row.model_probs) != len(row.venue_probs) or row.label >= len(row.model_probs):
            exclusions["outcome_shape_mismatch"] += 1
        elif any(value < 0 or value > 1 for value in (*row.model_probs, *row.venue_probs)):
            exclusions["invalid_probability"] += 1
        else:
            model_total, venue_total = sum(row.model_probs), sum(row.venue_probs)
            if model_total <= 0 or venue_total <= 0:
                exclusions["invalid_probability"] += 1
            else:
                selected.append((row, horizon, tuple(v / model_total for v in row.model_probs), tuple(v / venue_total for v in row.venue_probs)))

    groups = defaultdict(list)
    for item in selected:
        row, horizon, _model, _venue = item
        groups[(row.venue, row.market_type, horizon)].append(item)
    input_group_counts = Counter(
        (row.venue, row.market_type, horizon)
        for row in observations
        if (horizon := inplay_horizon(row.minute, row.period)) is not None
    )
    results = []
    for (venue, market_type, horizon), rows in sorted(groups.items()):
        model_rows = [(model, row.label) for row, _h, model, _venue in rows]
        venue_rows = [(venue_probs, row.label) for row, _h, _model, venue_probs in rows]
        diffs_by_match = defaultdict(list)
        for row, _h, model, venue_probs in rows:
            diffs_by_match[row.match_id].append(-math.log(max(model[row.label], _EPS)) + math.log(max(venue_probs[row.label], _EPS)))
        n_matches = len(diffs_by_match)
        diff = sum(value for values in diffs_by_match.values() for value in values) / len(rows)
        ci = _clustered_ci(diffs_by_match, n_bootstrap=n_bootstrap, seed=seed) if n_matches >= 2 else None
        status = "ready" if n_matches >= minimum_matches else "insufficient"
        verdict = "insufficient"
        if status == "ready" and ci is not None:
            verdict = "beating" if ci[1] < 0 else ("beaten" if ci[0] > 0 else "inconclusive")
        results.append({
            "venue": venue,
            "market_type": market_type,
            "horizon": horizon,
            "status": status,
            "verdict": verdict,
            "sample_matches": n_matches,
            "paired_ticks": len(rows),
            "coverage": len(rows) / input_group_counts[(venue, market_type, horizon)],
            "competition_counts": dict(sorted(Counter(row.competition for row, *_rest in rows).items())),
            "model": _generic_metrics(model_rows),
            "venue_metrics": _generic_metrics(venue_rows),
            "diff_log_loss": diff,
            "diff_ci95": list(ci) if ci is not None else None,
            "model_match_win_rate": sum(
                sum(values) / len(values) < 0 for values in diffs_by_match.values()
            ) / n_matches,
            "model_tick_win_rate": sum(value < 0 for values in diffs_by_match.values() for value in values) / len(rows),
        })
    return {
        "precommit": {
            "held_out_cutoff": held_out_cutoff.isoformat(),
            "max_alignment_seconds": max_alignment_seconds,
            "max_quote_age_seconds": max_quote_age_seconds,
            "minimum_matches": minimum_matches,
            "bootstrap_unit": "match",
            "bootstrap_seed": seed,
            "bootstrap_samples": n_bootstrap,
            "horizons": ["0-15", "15-30", "30-45", "halftime", "45-60", "60-75", "75-90"],
        },
        "population": {"input_observations": len(observations), "included_observations": len(selected), "excluded_observations": sum(exclusions.values()), "exclusions": dict(sorted(exclusions.items()))},
        "groups": results,
    }
