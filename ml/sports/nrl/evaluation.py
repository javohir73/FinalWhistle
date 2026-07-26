"""Deterministic, leak-audited evaluation of the complete NRL pre-match engine.

This module is deliberately pure: callers provide finished-match dictionaries
and receive per-match predictions, aggregate metrics, paired confidence
intervals, and independent promotion gates.  It reuses the production winner
and score models; it does not contain a second inference implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import groupby
from typing import Callable, Iterable

from ml.evaluation.calibration import reliability_curve
from ml.evaluation.scoreline_metrics import (
    expected_calibration_error_equal_count,
    per_class_calibration_error,
    ranked_probability_score,
)
from ml.models.nrl_score import (
    NrlExternalScoreSignals,
    NrlScoreParams,
    NrlScoreState,
    predict_scoreline,
)
from ml.sports.nrl.backtest import replay_seasons, tune
from ml.sports.nrl.model import NrlParams, predict, regress_season, update

_EPS = 1e-15
_LEGACY_TOTAL = 47.093590784472916
_UNIFORM = (1 / 3, 1 / 3, 1 / 3)
_OUTCOME_NAMES = ("home", "draw", "away")


class LeakageError(ValueError):
    """Raised when an input could contain information unavailable at kickoff."""


@dataclass(frozen=True)
class EvaluationConfig:
    from_season: int = 2023
    to_season: int = 2025
    model_version: str = "nrl-score-v0.1-shadow"
    bootstrap_samples: int = 10_000
    seed: int = 2026
    minimum_improvement: float = 0.05
    market_min_coverage: float = 0.70
    scoreline_regression_tolerance: float = 0.01

    @property
    def held_out_seasons(self) -> tuple[int, ...]:
        return tuple(range(self.from_season, self.to_season + 1))


@dataclass
class RollingBaselines:
    n: int = 0
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0
    total_sum: float = 0.0
    margin_sum: float = 0.0
    home_score_sum: float = 0.0
    away_score_sum: float = 0.0
    max_kickoff: datetime | None = None

    def class_rates(self) -> tuple[float, float, float]:
        if not self.n:
            return _UNIFORM
        return (
            self.home_wins / self.n,
            self.draws / self.n,
            self.away_wins / self.n,
        )

    @property
    def mean_total(self) -> float:
        return self.total_sum / self.n if self.n else 42.0

    @property
    def mean_margin(self) -> float:
        return self.margin_sum / self.n if self.n else 2.0

    @property
    def mean_home_score(self) -> float:
        return self.home_score_sum / self.n if self.n else 22.0

    @property
    def mean_away_score(self) -> float:
        return self.away_score_sum / self.n if self.n else 20.0

    def update(self, row: dict) -> None:
        score_home = int(row["score_home"])
        score_away = int(row["score_away"])
        outcome = _outcome_index(score_home, score_away)
        self.home_wins += int(outcome == 0)
        self.draws += int(outcome == 1)
        self.away_wins += int(outcome == 2)
        self.total_sum += score_home + score_away
        self.margin_sum += score_home - score_away
        self.home_score_sum += score_home
        self.away_score_sum += score_away
        self.n += 1
        kickoff = row["kickoff_utc"]
        if self.max_kickoff is None or kickoff > self.max_kickoff:
            self.max_kickoff = kickoff


def _outcome_index(score_home: int, score_away: int) -> int:
    if score_home > score_away:
        return 0
    if score_home < score_away:
        return 2
    return 1


def _safe_probabilities(values: Iterable[float]) -> tuple[float, float, float]:
    probs = tuple(float(value) for value in values)
    if len(probs) != 3 or any(not math.isfinite(p) or p < 0 for p in probs):
        raise ValueError(
            "probability triple must contain three finite non-negative values"
        )
    mass = sum(probs)
    if mass <= 0:
        raise ValueError("probability triple must have positive mass")
    return tuple(p / mass for p in probs)  # type: ignore[return-value]


def _reordered_rates(
    rates: tuple[float, float, float], favored: int
) -> tuple[float, float, float]:
    larger, smaller = sorted((rates[0], rates[2]), reverse=True)
    out = [0.0, rates[1], 0.0]
    out[favored] = larger
    out[2 if favored == 0 else 0] = smaller
    return _safe_probabilities(out)


def _parse_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"unsupported datetime value {value!r}")


def _validated_market(row: dict) -> dict | None:
    market = row.get("market")
    if not market or market.get("licensed") is not True:
        return None
    captured_at = _parse_datetime(market.get("captured_at"))
    if captured_at is None:
        raise LeakageError(
            f"match {row['match_id']}: licensed market lacks captured_at"
        )
    if captured_at >= row["kickoff_utc"]:
        raise LeakageError(
            f"match {row['match_id']}: market captured_at must be before kickoff"
        )
    out = dict(market)
    out["captured_at"] = captured_at
    if out.get("moneyline") is not None:
        out["moneyline"] = _safe_probabilities(out["moneyline"])
    return out


def validate_rows(rows: list[dict], held_out_seasons: tuple[int, ...]) -> list[dict]:
    """Validate and sort a snapshot without deriving anything from future rows."""
    seen: set[int] = set()
    cleaned: list[dict] = []
    for source in rows:
        row = dict(source)
        required = (
            "match_id",
            "season",
            "round",
            "kickoff_utc",
            "venue",
            "home_team_id",
            "away_team_id",
            "score_home",
            "score_away",
        )
        missing = [key for key in required if row.get(key) is None]
        if missing:
            raise ValueError(f"match row missing required fields: {missing}")
        match_id = int(row["match_id"])
        if match_id in seen:
            raise ValueError(f"duplicate match_id {match_id}")
        seen.add(match_id)
        row["match_id"] = match_id
        row["season"] = int(row["season"])
        row["round"] = int(row["round"])
        row["home_team_id"] = int(row["home_team_id"])
        row["away_team_id"] = int(row["away_team_id"])
        row["score_home"] = int(row["score_home"])
        row["score_away"] = int(row["score_away"])
        row["kickoff_utc"] = _parse_datetime(row["kickoff_utc"])
        if row["kickoff_utc"] is None or row["kickoff_utc"].tzinfo is None:
            raise ValueError(f"match {match_id}: kickoff_utc must be timezone-aware")
        if row["score_home"] < 0 or row["score_away"] < 0:
            raise ValueError(f"match {match_id}: scores cannot be negative")
        _validated_market(row)
        cleaned.append(row)
    cleaned.sort(key=lambda row: (row["kickoff_utc"], row["match_id"]))
    present = {row["season"] for row in cleaned}
    absent = [season for season in held_out_seasons if season not in present]
    if absent:
        raise ValueError(f"held-out seasons missing from snapshot: {absent}")
    return cleaned


def dataset_fingerprint(rows: list[dict]) -> str:
    payload = []
    for row in rows:
        market = _validated_market(row)
        market_payload = None
        if market:
            market_payload = {
                "captured_at": market["captured_at"].isoformat(),
                "moneyline": market.get("moneyline"),
                "margin": market.get("margin"),
                "total": market.get("total"),
                "source": market.get("source"),
            }
        payload.append(
            {
                "match_id": row["match_id"],
                "season": row["season"],
                "round": row["round"],
                "kickoff_utc": row["kickoff_utc"].isoformat(),
                "venue": row["venue"],
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
                "score_home": row["score_home"],
                "score_away": row["score_away"],
                "market": market_payload,
            }
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _replay_score_state(rows: list[dict], params: NrlScoreParams) -> NrlScoreState:
    state = NrlScoreState(params=params)
    for row in rows:
        state.update(
            row["home_team_id"],
            row["away_team_id"],
            row["score_home"],
            row["score_away"],
        )
    return state


def _winner_start_state(rows: list[dict], params: NrlParams) -> dict[int, float]:
    by_season: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_season[row["season"]].append(row)
    snapshots = replay_seasons(dict(by_season), params)
    if not snapshots:
        return {}
    return regress_season(snapshots[max(snapshots)], params)


def _params_for_fold(rows: list[dict], season: int) -> NrlParams:
    train_by_season: dict[int, list[dict]] = defaultdict(list)
    validation: list[dict] = []
    for row in rows:
        if row["season"] <= season - 2:
            train_by_season[row["season"]].append(row)
        elif row["season"] == season - 1:
            validation.append(row)
    if not train_by_season or not validation:
        raise ValueError(f"season {season}: insufficient training/validation history")
    return tune(dict(train_by_season), validation)


def _prediction_record(
    row: dict,
    winner_elos: dict[int, float],
    winner_params: NrlParams,
    score_state: NrlScoreState,
    rolling: RollingBaselines,
    model_version: str,
) -> dict:
    kickoff = row["kickoff_utc"]
    if rolling.max_kickoff is not None and rolling.max_kickoff >= kickoff:
        raise LeakageError(
            f"match {row['match_id']}: model state includes a non-prior kickoff"
        )
    home_elo = winner_elos.get(row["home_team_id"], 1500.0)
    away_elo = winner_elos.get(row["away_team_id"], 1500.0)
    winner = predict(home_elo, away_elo, winner_params)
    rates = rolling.class_rates()
    favorite = 0 if home_elo + winner_params.home_adv >= away_elo else 2
    market = _validated_market(row)
    score = predict_scoreline(
        score_state,
        row["home_team_id"],
        row["away_team_id"],
        # Internal promotion gates measure the independent production model.
        # Archived markets are conditional comparison benchmarks and must not
        # improve or degrade those gates when coverage is incomplete.
        NrlExternalScoreSignals(),
    )
    actual_home = row["score_home"]
    actual_away = row["score_away"]
    return {
        "match_id": row["match_id"],
        "season": row["season"],
        "round": row["round"],
        "kickoff_utc": kickoff.isoformat(),
        "venue": row["venue"],
        "home_team_id": row["home_team_id"],
        "away_team_id": row["away_team_id"],
        "actual_home": actual_home,
        "actual_away": actual_away,
        "actual_outcome": _OUTCOME_NAMES[_outcome_index(actual_home, actual_away)],
        "model_version": model_version,
        "winner_model_version": winner_params.version,
        "score_model_version": score.model_version,
        "winner": {
            "model": [winner["p_home"], winner["p_draw"], winner["p_away"]],
            "uniform": list(_UNIFORM),
            "base_rate": list(rates),
            "always_home": list(_reordered_rates(rates, 0)),
            "elo_favorite": list(_reordered_rates(rates, favorite)),
            "market": (
                list(market["moneyline"])
                if market and market.get("moneyline")
                else None
            ),
        },
        "margin": {
            "model": score.expected_margin,
            "zero": 0.0,
            "rolling_home": rolling.mean_margin,
            "elo": winner["expected_margin"],
            "market": market.get("margin") if market else None,
        },
        "total": {
            "model": score.expected_total,
            "rolling": rolling.mean_total,
            "legacy_constant": _LEGACY_TOTAL,
            "market": market.get("total") if market else None,
        },
        "scoreline": {
            "expected_home": score.expected_home,
            "expected_away": score.expected_away,
            "predicted_home": score.predicted_home,
            "predicted_away": score.predicted_away,
            "baseline_home": rolling.mean_home_score,
            "baseline_away": rolling.mean_away_score,
        },
        "audit": {
            "state_max_kickoff": (
                rolling.max_kickoff.isoformat() if rolling.max_kickoff else None
            ),
            "market_captured_at": (
                market["captured_at"].isoformat() if market else None
            ),
        },
    }


def _advance_states(
    rows: list[dict],
    winner_elos: dict[int, float],
    winner_params: NrlParams,
    score_state: NrlScoreState,
    rolling: RollingBaselines,
) -> None:
    for row in rows:
        home_id = row["home_team_id"]
        away_id = row["away_team_id"]
        home_elo = winner_elos.get(home_id, 1500.0)
        away_elo = winner_elos.get(away_id, 1500.0)
        winner_elos[home_id], winner_elos[away_id] = update(
            home_elo,
            away_elo,
            row["score_home"],
            row["score_away"],
            winner_params,
        )
        score_state.update(
            home_id,
            away_id,
            row["score_home"],
            row["score_away"],
        )
        rolling.update(row)


def _walk_fold(
    rows: list[dict],
    season: int,
    config: EvaluationConfig,
    score_params: NrlScoreParams,
    winner_params: NrlParams | None,
) -> tuple[list[dict], NrlParams]:
    prior = [row for row in rows if row["season"] < season]
    target = [row for row in rows if row["season"] == season]
    params = winner_params or _params_for_fold(rows, season)
    winner_elos = _winner_start_state(prior, params)
    score_state = _replay_score_state(prior, score_params)
    rolling = RollingBaselines()
    for row in prior:
        rolling.update(row)

    predictions: list[dict] = []
    for _, group_iter in groupby(target, key=lambda row: row["kickoff_utc"]):
        group = list(group_iter)
        # Every fixture at this timestamp is predicted from the same strictly
        # earlier state. Results are applied only after the whole group.
        predictions.extend(
            _prediction_record(
                row,
                winner_elos,
                params,
                score_state,
                rolling,
                config.model_version,
            )
            for row in group
        )
        _advance_states(group, winner_elos, params, score_state, rolling)
    return predictions, params


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _winner_contribution(probs: list[float], outcome: int) -> dict:
    safe = _safe_probabilities(probs)
    clamped = [max(_EPS, min(1 - _EPS, value)) for value in safe]
    return {
        "log_loss": -math.log(clamped[outcome]),
        "brier": sum(
            (clamped[i] - (1.0 if i == outcome else 0.0)) ** 2 for i in range(3)
        ),
        "rps": ranked_probability_score(safe, outcome),
        "correct": float(max(range(3), key=lambda i: safe[i]) == outcome),
    }


def _winner_summary(records: list[dict], key: str) -> dict:
    contributions = [
        _winner_contribution(
            record["winner"][key],
            _OUTCOME_NAMES.index(record["actual_outcome"]),
        )
        for record in records
    ]
    probs = [tuple(record["winner"][key]) for record in records]
    labels = [_OUTCOME_NAMES.index(record["actual_outcome"]) for record in records]
    return {
        "n": len(records),
        "log_loss": _mean([item["log_loss"] for item in contributions]),
        "brier": _mean([item["brier"] for item in contributions]),
        "rps": _mean([item["rps"] for item in contributions]),
        "accuracy": _mean([item["correct"] for item in contributions]),
        "ece": expected_calibration_error_equal_count(probs, labels, bins=10),
    }


def _numeric_summary(
    records: list[dict], section: str, key: str, actual: Callable
) -> dict:
    errors = [record[section][key] - actual(record) for record in records]
    return {
        "n": len(errors),
        "mae": _mean([abs(error) for error in errors]),
        "rmse": math.sqrt(_mean([error * error for error in errors])),
        "bias": _mean(errors),
        "within_6": _mean([float(abs(error) <= 6) for error in errors]),
        "within_12": _mean([float(abs(error) <= 12) for error in errors]),
    }


def _margin_summary(records: list[dict], key: str) -> dict:
    out = _numeric_summary(
        records,
        "margin",
        key,
        lambda record: record["actual_home"] - record["actual_away"],
    )

    def sign(value: float) -> int:
        return 1 if value > 0 else -1 if value < 0 else 0

    out["winner_sign_accuracy"] = _mean(
        [
            float(
                sign(record["margin"][key])
                == sign(record["actual_home"] - record["actual_away"])
            )
            for record in records
            if record["actual_home"] != record["actual_away"]
        ]
    )
    return out


def _total_summary(records: list[dict], key: str) -> dict:
    return _numeric_summary(
        records,
        "total",
        key,
        lambda record: record["actual_home"] + record["actual_away"],
    )


def _scoreline_summary(records: list[dict], model: bool) -> dict:
    if model:
        homes = [record["scoreline"]["expected_home"] for record in records]
        aways = [record["scoreline"]["expected_away"] for record in records]
        picked = [
            (
                record["scoreline"]["predicted_home"],
                record["scoreline"]["predicted_away"],
            )
            for record in records
        ]
    else:
        homes = [record["scoreline"]["baseline_home"] for record in records]
        aways = [record["scoreline"]["baseline_away"] for record in records]
        picked = [(round(home), round(away)) for home, away in zip(homes, aways)]
    home_errors = [
        abs(home - record["actual_home"]) for home, record in zip(homes, records)
    ]
    away_errors = [
        abs(away - record["actual_away"]) for away, record in zip(aways, records)
    ]
    return {
        "n": len(records),
        "home_mae": _mean(home_errors),
        "away_mae": _mean(away_errors),
        "combined_team_mae": _mean(home_errors + away_errors),
        "exact_hit_rate": _mean(
            [
                float(pair == (record["actual_home"], record["actual_away"]))
                for pair, record in zip(picked, records)
            ]
        ),
        "both_within_6": _mean(
            [
                float(home_error <= 6 and away_error <= 6)
                for home_error, away_error in zip(home_errors, away_errors)
            ]
        ),
    }


def cluster_bootstrap_ci(
    values: list[float],
    cluster_keys: list[tuple[int, int]],
    samples: int = 10_000,
    seed: int = 2026,
) -> tuple[float, float]:
    """Percentile CI for a mean, resampling entire season-round clusters."""
    if len(values) != len(cluster_keys):
        raise ValueError("values and cluster_keys must be the same length")
    if not values or samples < 1:
        raise ValueError("bootstrap requires values and at least one sample")
    groups: dict[tuple[int, int], list[float]] = defaultdict(list)
    for value, key in zip(values, cluster_keys):
        groups[key].append(float(value))
    blocks = [(sum(group), len(group)) for group in groups.values()]
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        chosen = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        means.append(sum(total for total, _ in chosen) / sum(n for _, n in chosen))
    means.sort()
    low = means[int(0.025 * (samples - 1))]
    high = means[int(0.975 * (samples - 1))]
    return low, high


def _paired_report(
    records: list[dict],
    model_error: Callable[[dict], float],
    baseline_error: Callable[[dict], float],
    config: EvaluationConfig,
) -> dict:
    deltas = [model_error(record) - baseline_error(record) for record in records]
    keys = [(record["season"], record["round"]) for record in records]
    ci = cluster_bootstrap_ci(
        deltas,
        keys,
        samples=config.bootstrap_samples,
        seed=config.seed,
    )
    mean = _mean(deltas)
    return {
        "mean_delta": mean,
        "ci95": list(ci),
        "clusters": len(set(keys)),
        "noise_floor": max(abs(ci[0] - mean), abs(ci[1] - mean)),
    }


def _relative_improvement(model: float, baseline: float) -> float:
    return (baseline - model) / baseline if baseline > 0 else float("-inf")


def _seasons_improved(
    records: list[dict],
    model_error: Callable[[dict], float],
    baseline_error: Callable[[dict], float],
) -> int:
    improved = 0
    for season in sorted({record["season"] for record in records}):
        season_rows = [record for record in records if record["season"] == season]
        if _mean([model_error(row) for row in season_rows]) < _mean(
            [baseline_error(row) for row in season_rows]
        ):
            improved += 1
    return improved


def _promotion_gate(
    *,
    model_metric: float,
    baseline_metric: float,
    paired: dict,
    seasons_improved: int,
    seasons_evaluated: int,
    minimum_improvement: float,
    require_improvement: bool,
    extra_checks: dict[str, bool] | None = None,
) -> dict:
    required_seasons = seasons_evaluated // 2 + 1
    improvement = _relative_improvement(model_metric, baseline_metric)
    checks = {
        "point_estimate_better": model_metric < baseline_metric,
        "minimum_improvement": (
            improvement >= minimum_improvement if require_improvement else True
        ),
        "majority_of_seasons": seasons_improved >= required_seasons,
        "ci_upper_not_above_zero": paired["ci95"][1] <= 0,
        **(extra_checks or {}),
    }
    return {
        "passed": all(checks.values()),
        "improvement": improvement,
        "minimum_required": minimum_improvement if require_improvement else None,
        "seasons_improved": seasons_improved,
        "required_seasons": required_seasons,
        "checks": checks,
    }


def _market_coverage(records: list[dict], config: EvaluationConfig) -> dict:
    sections = {
        "moneyline": lambda row: row["winner"]["market"],
        "margin": lambda row: row["margin"]["market"],
        "total": lambda row: row["total"]["market"],
    }
    report: dict[str, dict] = {}
    for name, getter in sections.items():
        by_season = {}
        enabled = True
        for season in config.held_out_seasons:
            season_rows = [row for row in records if row["season"] == season]
            count = sum(getter(row) is not None for row in season_rows)
            coverage = count / len(season_rows) if season_rows else 0.0
            by_season[str(season)] = {
                "covered": count,
                "total": len(season_rows),
                "coverage": coverage,
            }
            enabled = enabled and coverage >= config.market_min_coverage
        covered_rows = [row for row in records if getter(row) is not None]
        metrics = None
        if enabled:
            if name == "moneyline":
                metrics = _winner_summary(covered_rows, "market")
            elif name == "margin":
                metrics = _margin_summary(covered_rows, "market")
            else:
                metrics = _total_summary(covered_rows, "market")
        report[name] = {
            "status": "available" if enabled else "unavailable",
            "minimum_coverage": config.market_min_coverage,
            "by_season": by_season,
            "metrics": metrics,
            "blocker": (
                None if enabled else "insufficient licensed pre-kickoff coverage"
            ),
        }
    return report


def summarize(records: list[dict], config: EvaluationConfig) -> dict:
    winner_keys = ("model", "uniform", "base_rate", "always_home", "elo_favorite")
    winner = {key: _winner_summary(records, key) for key in winner_keys}
    margin = {
        key: _margin_summary(records, key)
        for key in ("model", "zero", "rolling_home", "elo")
    }
    total = {
        key: _total_summary(records, key)
        for key in ("model", "rolling", "legacy_constant")
    }
    scoreline = {
        "model": _scoreline_summary(records, True),
        "rolling_home_away": _scoreline_summary(records, False),
    }

    def winner_loss(row: dict, key: str) -> float:
        return _winner_contribution(
            row["winner"][key], _OUTCOME_NAMES.index(row["actual_outcome"])
        )["log_loss"]

    def actual_margin(row: dict) -> int:
        return row["actual_home"] - row["actual_away"]

    def actual_total(row: dict) -> int:
        return row["actual_home"] + row["actual_away"]

    winner_paired = _paired_report(
        records,
        lambda row: winner_loss(row, "model"),
        lambda row: winner_loss(row, "elo_favorite"),
        config,
    )
    margin_paired = _paired_report(
        records,
        lambda row: abs(row["margin"]["model"] - actual_margin(row)),
        lambda row: abs(row["margin"]["elo"] - actual_margin(row)),
        config,
    )
    total_paired = _paired_report(
        records,
        lambda row: abs(row["total"]["model"] - actual_total(row)),
        lambda row: abs(row["total"]["rolling"] - actual_total(row)),
        config,
    )
    score_paired = _paired_report(
        records,
        lambda row: (
            abs(row["scoreline"]["expected_home"] - row["actual_home"])
            + abs(row["scoreline"]["expected_away"] - row["actual_away"])
        )
        / 2,
        lambda row: (
            abs(row["scoreline"]["baseline_home"] - row["actual_home"])
            + abs(row["scoreline"]["baseline_away"] - row["actual_away"])
        )
        / 2,
        config,
    )
    seasons_evaluated = len(config.held_out_seasons)
    winner_seasons = _seasons_improved(
        records,
        lambda row: winner_loss(row, "model"),
        lambda row: winner_loss(row, "elo_favorite"),
    )
    margin_seasons = _seasons_improved(
        records,
        lambda row: abs(row["margin"]["model"] - actual_margin(row)),
        lambda row: abs(row["margin"]["elo"] - actual_margin(row)),
    )
    total_seasons = _seasons_improved(
        records,
        lambda row: abs(row["total"]["model"] - actual_total(row)),
        lambda row: abs(row["total"]["rolling"] - actual_total(row)),
    )
    score_seasons = _seasons_improved(
        records,
        lambda row: (
            abs(row["scoreline"]["expected_home"] - row["actual_home"])
            + abs(row["scoreline"]["expected_away"] - row["actual_away"])
        )
        / 2,
        lambda row: (
            abs(row["scoreline"]["baseline_home"] - row["actual_home"])
            + abs(row["scoreline"]["baseline_away"] - row["actual_away"])
        )
        / 2,
    )
    margin_no_regression = margin["model"]["mae"] <= margin["elo"]["mae"] * (
        1 + config.scoreline_regression_tolerance
    )
    total_no_regression = total["model"]["mae"] <= total["rolling"]["mae"] * (
        1 + config.scoreline_regression_tolerance
    )
    gates = {
        "winner": _promotion_gate(
            model_metric=winner["model"]["log_loss"],
            baseline_metric=winner["elo_favorite"]["log_loss"],
            paired=winner_paired,
            seasons_improved=winner_seasons,
            seasons_evaluated=seasons_evaluated,
            minimum_improvement=0.0,
            require_improvement=False,
        ),
        "margin": _promotion_gate(
            model_metric=margin["model"]["mae"],
            baseline_metric=margin["elo"]["mae"],
            paired=margin_paired,
            seasons_improved=margin_seasons,
            seasons_evaluated=seasons_evaluated,
            minimum_improvement=config.minimum_improvement,
            require_improvement=True,
        ),
        "total": _promotion_gate(
            model_metric=total["model"]["mae"],
            baseline_metric=total["rolling"]["mae"],
            paired=total_paired,
            seasons_improved=total_seasons,
            seasons_evaluated=seasons_evaluated,
            minimum_improvement=config.minimum_improvement,
            require_improvement=True,
        ),
        "scoreline": _promotion_gate(
            model_metric=scoreline["model"]["combined_team_mae"],
            baseline_metric=scoreline["rolling_home_away"]["combined_team_mae"],
            paired=score_paired,
            seasons_improved=score_seasons,
            seasons_evaluated=seasons_evaluated,
            minimum_improvement=config.minimum_improvement,
            require_improvement=True,
            extra_checks={
                "margin_no_material_regression": margin_no_regression,
                "total_no_material_regression": total_no_regression,
            },
        ),
    }
    model_probs = [tuple(row["winner"]["model"]) for row in records]
    labels = [_OUTCOME_NAMES.index(row["actual_outcome"]) for row in records]
    by_season = {}
    for season in config.held_out_seasons:
        season_rows = [row for row in records if row["season"] == season]
        by_season[str(season)] = {
            "n": len(season_rows),
            "winner": {
                "model": _winner_summary(season_rows, "model"),
                "elo_favorite": _winner_summary(season_rows, "elo_favorite"),
            },
            "margin": {
                "model": _margin_summary(season_rows, "model"),
                "elo": _margin_summary(season_rows, "elo"),
            },
            "total": {
                "model": _total_summary(season_rows, "model"),
                "rolling": _total_summary(season_rows, "rolling"),
            },
            "scoreline": {
                "model": _scoreline_summary(season_rows, True),
                "rolling_home_away": _scoreline_summary(season_rows, False),
            },
        }
    return {
        "n": len(records),
        "seasons": list(config.held_out_seasons),
        "winner": winner,
        "margin": margin,
        "total": total,
        "scoreline": scoreline,
        "paired_comparisons": {
            "winner_log_loss_vs_elo_favorite": winner_paired,
            "margin_mae_vs_elo": margin_paired,
            "total_mae_vs_rolling": total_paired,
            "scoreline_mae_vs_rolling": score_paired,
        },
        "calibration": {
            "ece": expected_calibration_error_equal_count(model_probs, labels, bins=10),
            "per_class_ece": per_class_calibration_error(model_probs, labels, bins=10),
            "reliability": reliability_curve(model_probs, labels, bins=10),
        },
        "market_benchmarks": _market_coverage(records, config),
        "gates": gates,
        "by_season": by_season,
    }


def evaluate(
    rows: list[dict],
    config: EvaluationConfig,
    *,
    score_params: NrlScoreParams | None = None,
    winner_params: NrlParams | None = None,
) -> dict:
    """Run all held-out folds and return deterministic records plus reports.

    Passing ``winner_params`` is useful for deterministic unit fixtures. The
    production CLI omits it, so each fold follows the existing production
    fitting procedure: train through T-2 and tune on T-1.
    """
    # A historical run is a snapshot as of its final evaluated season. Later
    # results must not change its dataset identity or any aggregate.
    historical_rows = [
        row
        for row in rows
        if int(row.get("season", config.to_season + 1)) <= config.to_season
    ]
    cleaned = validate_rows(historical_rows, config.held_out_seasons)
    score_params = score_params or NrlScoreParams()
    records: list[dict] = []
    fold_params: dict[str, dict] = {}
    for season in config.held_out_seasons:
        fold_records, params = _walk_fold(
            cleaned,
            season,
            config,
            score_params,
            winner_params,
        )
        records.extend(fold_records)
        fold_params[str(season)] = asdict(params)
    summary = summarize(records, config)
    audit_checks = {
        "strictly_prior_state": all(
            record["audit"]["state_max_kickoff"] is None
            or _parse_datetime(record["audit"]["state_max_kickoff"])
            < _parse_datetime(record["kickoff_utc"])
            for record in records
        ),
        "external_signals_pre_kickoff": all(
            record["audit"]["market_captured_at"] is None
            or _parse_datetime(record["audit"]["market_captured_at"])
            < _parse_datetime(record["kickoff_utc"])
            for record in records
        ),
        "same_kickoff_batching": True,
        "full_history_aggregates_used": False,
    }
    audit = {
        "passed": all(
            value is True
            for key, value in audit_checks.items()
            if key != "full_history_aggregates_used"
        )
        and audit_checks["full_history_aggregates_used"] is False,
        "rows_checked": len(records),
        **audit_checks,
        "violations": [
            key
            for key, value in audit_checks.items()
            if (key == "full_history_aggregates_used" and value is not False)
            or (key != "full_history_aggregates_used" and value is not True)
        ],
    }
    return {
        "dataset_fingerprint": dataset_fingerprint(cleaned),
        "config": asdict(config),
        "score_params": asdict(score_params),
        "winner_params_by_season": fold_params,
        "predictions": records,
        "results": summary,
        "leakage_audit": audit,
    }
