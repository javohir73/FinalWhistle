"""Leak-safe historical replay and comparison harness for the vNext core.

This module is deliberately pure: it reads already-enriched chronological rows,
performs no database or network access, and never tunes on the selected target.
Every reported market is marginalized from one ``ScoreDistribution`` per model.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from itertools import groupby
from typing import Any, Callable, Mapping, Sequence

from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, MAX_GOALS
from ml.models.vnext import (
    LegacyPoissonEloAdapter,
    MatchContext,
    ScoreDistribution,
    state_from_elo_strength_and_tempo,
)
from ml.ratings.dynamic_strength import (
    DynamicModelConfig,
    DynamicStrengthTempoModel,
    GroupPrior,
)
from ml.ratings.elo import HOME_ADVANTAGE


TargetSelector = Callable[[Mapping[str, Any]], bool]
MODEL_NAMES = (
    "legacy",
    "coherent_legacy",
    "orthogonal_elo_dynamic_tempo",
    "dynamic_strength_tempo",
)
METRIC_DIRECTIONS = {
    "log_loss": "lower",
    "brier": "lower",
    "accuracy": "higher",
    "exact_score_nll": "lower",
    "over_under_2_5_brier": "lower",
}
_EPS = 1e-15


@dataclass(frozen=True, slots=True)
class VNextReplayConfig:
    """Fixed evaluation settings; this harness performs no parameter search."""

    base: float = BASE_GOALS
    beta: float = ELO_TO_GOALS_BETA
    home_advantage_elo: float = HOME_ADVANTAGE
    rho: float = 0.0
    temperature: float = 1.0
    calibrator: Mapping[str, object] | None = None
    calibrator_artifact_id: str | None = None
    max_goals: int = MAX_GOALS
    dynamic: DynamicModelConfig = field(default_factory=DynamicModelConfig)
    group_priors: Mapping[str, GroupPrior] | None = None
    team_groups: Mapping[str, str] | None = None
    bootstrap_samples: int = 2_000
    bootstrap_seed: int = 26

    def __post_init__(self) -> None:
        for value, name in (
            (self.base, "base"),
            (self.beta, "beta"),
            (self.home_advantage_elo, "home_advantage_elo"),
            (self.rho, "rho"),
            (self.temperature, "temperature"),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.base <= 0.0 or self.beta <= 0.0 or self.temperature <= 0.0:
            raise ValueError("base, beta and temperature must be positive")
        if (self.calibrator is not None or self.temperature != 1.0) and (
            not self.calibrator_artifact_id or not self.calibrator_artifact_id.strip()
        ):
            raise ValueError(
                "calibrated legacy replay requires calibrator_artifact_id provenance"
            )
        if isinstance(self.max_goals, bool) or self.max_goals < 1:
            raise ValueError("max_goals must be a positive integer")
        if not isinstance(self.max_goals, int):
            raise ValueError("max_goals must be a positive integer")
        if isinstance(self.bootstrap_samples, bool) or self.bootstrap_samples < 0:
            raise ValueError("bootstrap_samples must be a non-negative integer")
        if not isinstance(self.bootstrap_samples, int):
            raise ValueError("bootstrap_samples must be a non-negative integer")

    @classmethod
    def from_model_params(
        cls,
        params: object,
        *,
        dynamic: DynamicModelConfig | None = None,
        **overrides: Any,
    ) -> "VNextReplayConfig":
        """Build an explicit frozen config from the production params object."""
        values = {
            "base": getattr(params, "base"),
            "beta": getattr(params, "beta"),
            "home_advantage_elo": getattr(params, "home_adv"),
            "rho": getattr(params, "rho"),
            "temperature": getattr(params, "temperature"),
            "calibrator": getattr(params, "calibrator", None),
            "calibrator_artifact_id": f"model-params:{getattr(params, 'version', 'unknown')}",
            "dynamic": dynamic or DynamicModelConfig(),
        }
        values.update(overrides)
        return cls(**values)


def world_cup_year(year: int) -> TargetSelector:
    """Select one World Cup finals edition without inspecting match results."""
    if isinstance(year, bool) or not isinstance(year, int) or year < 1930:
        raise ValueError("year must be a valid World Cup year")

    def select(row: Mapping[str, Any]) -> bool:
        competition = (row.get("competition") or "").lower()
        when = _as_utc_datetime(row.get("date"), "date")
        return (
            "fifa world cup" in competition
            and "qualif" not in competition
            and when.year == year
        )

    return select


def _as_utc_datetime(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} datetime must be timezone-aware")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date or datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            # A date-only ISO string is unambiguous and maps to UTC midnight;
            # an unzoned datetime is ambiguous and therefore rejected.
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{name} datetime must include a timezone") from exc
            return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError(f"{name} must be a date, ISO string or timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class _ReplayRow:
    source: Mapping[str, Any]
    source_index: int
    match_id: str
    home_id: str
    away_id: str
    when: datetime
    pre_home: float
    pre_away: float
    goals_home: int
    goals_away: int
    is_neutral: bool
    competition: str | None


def _normalize_row(row: Mapping[str, Any], index: int) -> _ReplayRow:
    if not isinstance(row, Mapping):
        raise ValueError(f"row {index} must be a mapping")
    required = (
        "home_id",
        "away_id",
        "pre_home",
        "pre_away",
        "score_home",
        "score_away",
        "is_neutral",
        "date",
    )
    missing = [name for name in required if name not in row]
    if missing:
        raise ValueError(f"row {index} is missing required fields: {', '.join(missing)}")

    home_id = str(row["home_id"]).strip()
    away_id = str(row["away_id"]).strip()
    if not home_id or not away_id or home_id == away_id:
        raise ValueError(f"row {index} must contain two distinct team ids")
    try:
        pre_home = float(row["pre_home"])
        pre_away = float(row["pre_away"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {index} Elo ratings must be numeric") from exc
    if not math.isfinite(pre_home) or not math.isfinite(pre_away):
        raise ValueError(f"row {index} Elo ratings must be finite")

    scores: list[int] = []
    for key in ("score_home", "score_away"):
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"row {index} {key} must be a non-negative integer")
        scores.append(value)
    neutral = row["is_neutral"]
    if not isinstance(neutral, bool):
        raise ValueError(f"row {index} is_neutral must be boolean")
    competition = row.get("competition")
    if competition is not None and not isinstance(competition, str):
        raise ValueError(f"row {index} competition must be a string or null")

    when = _as_utc_datetime(row["date"], f"row {index} date")
    source_match_id = row.get("match_id", row.get("id", f"row-{index}"))
    match_id = str(source_match_id).strip()
    if not match_id:
        raise ValueError(f"row {index} match id must not be empty")
    return _ReplayRow(
        source=row,
        source_index=index,
        match_id=match_id,
        home_id=home_id,
        away_id=away_id,
        when=when,
        pre_home=pre_home,
        pre_away=pre_away,
        goals_home=scores[0],
        goals_away=scores[1],
        is_neutral=neutral,
        competition=competition,
    )


def _legacy_forecast(
    row: _ReplayRow,
    context: MatchContext,
    config: VNextReplayConfig,
) -> tuple[ScoreDistribution, tuple[float, float, float]]:
    advantage = 0.0 if row.is_neutral else config.home_advantage_elo
    adapter = LegacyPoissonEloAdapter(
        base=config.base,
        beta=config.beta,
        home_advantage_elo=advantage,
        rho=config.rho,
        temperature=config.temperature,
        calibrator=config.calibrator,
    )
    raw_distribution = adapter.raw_distribution(
        context,
        row.pre_home,
        row.pre_away,
        max_goals=config.max_goals,
    )
    # The current champion calibrates only its W/D/L triple; its exact-score and
    # goal-market outputs still come from the raw DC grid.  Keep that historical
    # split in the baseline receipt so every metric is compared with what the
    # current engine actually serves, rather than an invented raked champion.
    prediction = adapter.prediction(row.pre_home, row.pre_away)
    return raw_distribution, (
        prediction.prob_home_win,
        prediction.prob_draw,
        prediction.prob_away_win,
    )


def _with_local_calibration_parity(
    candidate: ScoreDistribution,
    champion_raw: ScoreDistribution,
    champion_served_wdl: tuple[float, float, float],
    *,
    artifact_id: str,
) -> ScoreDistribution:
    """Apply the champion's fixture-local class weights to a candidate grid.

    This reconstructs the fixed post-processing transform from the champion's
    raw and published W/D/L triples.  A zero-change candidate therefore exactly
    reproduces the served champion W/D/L, while a tempo/strength change is still
    evaluated through the same frozen local calibration policy.
    """
    raw_champion = champion_raw.wdl.as_tuple()
    raw_candidate = candidate.wdl.as_tuple()
    weights = tuple(
        served / raw if raw > 0.0 else 0.0
        for raw, served in zip(raw_champion, champion_served_wdl)
    )
    weighted = tuple(
        probability * weight
        for probability, weight in zip(raw_candidate, weights)
    )
    total = sum(weighted)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("champion calibration parity produces no candidate mass")
    target = tuple(value / total for value in weighted)
    return candidate.calibrated_to_wdl(
        target,
        calibrator_artifact_id=artifact_id,
    )


def _receipt(
    distribution: ScoreDistribution,
    goals_home: int,
    goals_away: int,
    *,
    wdl_override: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    wdl = wdl_override or distribution.wdl.as_tuple()
    outcome = 0 if goals_home > goals_away else 1 if goals_home == goals_away else 2
    p_outcome = max(_EPS, min(1.0 - _EPS, wdl[outcome]))
    brier = sum(
        (probability - (1.0 if i == outcome else 0.0)) ** 2
        for i, probability in enumerate(wdl)
    )
    exact_score_in_grid = (
        goals_home <= distribution.max_goals
        and goals_away <= distribution.max_goals
    )
    exact_probability = (
        max(_EPS, distribution.exact_score_probability(goals_home, goals_away))
        if exact_score_in_grid
        else _EPS
    )
    over_probability = distribution.total_goals_over(2.5)
    over_actual = float(goals_home + goals_away > 2.5)
    modal = distribution.most_likely_score
    return {
        "wdl": wdl,
        "expected_goals": distribution.expected_goals,
        "modal_score": (modal.home, modal.away),
        "exact_score_probability": exact_probability,
        "exact_score_in_grid": exact_score_in_grid,
        "over_2_5_probability": over_probability,
        "values": {
            "log_loss": -math.log(p_outcome),
            "brier": brier,
            "accuracy": float(max(range(3), key=lambda i: wdl[i]) == outcome),
            "exact_score_nll": -math.log(exact_probability),
            "over_under_2_5_brier": (over_probability - over_actual) ** 2,
        },
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _paired_summary(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    direction: str,
    samples: int,
    seed: int,
    clusters: Sequence[str],
) -> dict[str, Any]:
    deltas = [
        candidate_value - baseline_value
        for candidate_value, baseline_value in zip(candidate, baseline)
    ]
    mean_delta = _mean(deltas)
    ci95: tuple[float, float] | None = None
    if len(clusters) != len(deltas):
        raise ValueError("bootstrap clusters must match paired metric rows")
    unique_clusters = tuple(dict.fromkeys(clusters))
    if deltas and samples:
        rng = random.Random(seed)
        grouped = {
            cluster: [
                value
                for value, candidate_cluster in zip(deltas, clusters)
                if candidate_cluster == cluster
            ]
            for cluster in unique_clusters
        }
        draws: list[float] = []
        for _ in range(samples):
            sampled: list[float] = []
            for _ in unique_clusters:
                sampled.extend(grouped[unique_clusters[rng.randrange(len(unique_clusters))]])
            draws.append(_mean(sampled))
        draws.sort()
        ci95 = (_percentile(draws, 0.025), _percentile(draws, 0.975))
    return {
        "mean_delta": mean_delta,
        "ci95": ci95,
        "better_when": "negative" if direction == "lower" else "positive",
        "n": len(deltas),
        "n_clusters": len(unique_clusters),
        "bootstrap_unit": "match_timestamp",
    }


def replay_vnext(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_selector: TargetSelector,
    config: VNextReplayConfig,
) -> dict[str, Any]:
    """Replay all rows oldest-first and score only the selected target rows.

    Dynamic state learns from every row strictly *after* all three forecasts for
    that row have been frozen.  Target outcomes may update later target forecasts
    online, but they never affect their own prediction.  Configuration is supplied
    once and is never selected or altered using target results.
    """
    if not callable(target_selector):
        raise ValueError("target_selector must be callable")
    normalized = [_normalize_row(row, index) for index, row in enumerate(rows)]
    for row in normalized:
        if (
            row.goals_home > config.dynamic.max_goals
            or row.goals_away > config.dynamic.max_goals
        ):
            raise ValueError(
                "historical score exceeds the dynamic model's configured goal cap"
            )
    for previous, current in zip(normalized, normalized[1:]):
        if current.when < previous.when:
            raise ValueError("rows must be chronological oldest-first")

    dynamic = DynamicStrengthTempoModel(
        config.dynamic,
        group_priors=config.group_priors,
        team_groups=config.team_groups,
    )
    receipts: list[dict[str, Any]] = []

    for _, same_time_rows_iter in groupby(normalized, key=lambda row: row.when):
        same_time_rows = list(same_time_rows_iter)
        frozen: list[
            tuple[
                _ReplayRow,
                str,
                Any,
                ScoreDistribution,
                tuple[float, float, float],
                ScoreDistribution,
                ScoreDistribution,
                ScoreDistribution,
            ]
        ] = []

        # Date-only historical data pins every match that day to UTC midnight.
        # Freeze the whole timestamp batch before revealing any result, so the
        # arbitrary CSV row order cannot create same-day information leakage.
        for row in same_time_rows:
            ticket_id = f"vnext-replay-{row.source_index}"
            context = MatchContext(
                match_id=ticket_id,
                home_team_id=row.home_id,
                away_team_id=row.away_id,
                kickoff_utc=row.when,
                features_as_of=row.when,
                competition_id=row.competition,
                neutral_venue=row.is_neutral,
            )
            latent_advantage = (
                0.0
                if row.is_neutral
                else 2.0 * config.beta * config.home_advantage_elo
            )
            dynamic_prediction = dynamic.predict(
                ticket_id,
                row.home_id,
                row.away_id,
                row.when,
                home_advantage=latent_advantage,
            )
            legacy, legacy_served_wdl = _legacy_forecast(row, context, config)
            orthogonal_state = state_from_elo_strength_and_tempo(
                context,
                row.pre_home,
                row.pre_away,
                total_expected_goals=dynamic_prediction.total_expected_goals,
                beta=config.beta,
                home_advantage_elo=(
                    0.0 if row.is_neutral else config.home_advantage_elo
                ),
                rho=config.rho,
                model_version="fw-vnext-elo-dynamic-tempo-v0",
            )
            orthogonal = ScoreDistribution.from_state(
                orthogonal_state, max_goals=config.max_goals
            )
            full_dynamic = ScoreDistribution.from_state(
                dynamic_prediction.to_vnext(context, rho=config.rho),
                max_goals=config.max_goals,
            )
            calibration_id = (
                f"local-parity:{config.calibrator_artifact_id or 'identity'}"
            )
            coherent_legacy = _with_local_calibration_parity(
                legacy,
                legacy,
                legacy_served_wdl,
                artifact_id=calibration_id,
            )
            orthogonal = _with_local_calibration_parity(
                orthogonal,
                legacy,
                legacy_served_wdl,
                artifact_id=calibration_id,
            )
            full_dynamic = _with_local_calibration_parity(
                full_dynamic,
                legacy,
                legacy_served_wdl,
                artifact_id=calibration_id,
            )
            frozen.append(
                (
                    row,
                    ticket_id,
                    dynamic_prediction,
                    legacy,
                    legacy_served_wdl,
                    coherent_legacy,
                    orthogonal,
                    full_dynamic,
                )
            )

        for (
            row,
            _,
            dynamic_prediction,
            legacy,
            legacy_served_wdl,
            coherent_legacy,
            orthogonal,
            full_dynamic,
        ) in frozen:
            if bool(target_selector(row.source)):
                receipts.append(
                    {
                        "match_id": row.match_id,
                        "date": row.when.isoformat(),
                        "home_id": row.home_id,
                        "away_id": row.away_id,
                        "actual_score": (row.goals_home, row.goals_away),
                        "dynamic_evidence_before": dynamic_prediction.evidence_count,
                        "forecasts": {
                            "legacy": _receipt(
                                legacy,
                                row.goals_home,
                                row.goals_away,
                                wdl_override=legacy_served_wdl,
                            ),
                            "coherent_legacy": _receipt(
                                coherent_legacy,
                                row.goals_home,
                                row.goals_away,
                            ),
                            "orthogonal_elo_dynamic_tempo": _receipt(
                                orthogonal, row.goals_home, row.goals_away
                            ),
                            "dynamic_strength_tempo": _receipt(
                                full_dynamic, row.goals_home, row.goals_away
                            ),
                        },
                    }
                )

        # Deterministic source order affects only future timestamps.  Every
        # forecast in this group is already immutable.
        for row, ticket_id, _, _, _, _, _, _ in frozen:
            dynamic.update(
                ticket_id,
                row.goals_home,
                row.goals_away,
                row.when,
            )

    if not receipts:
        raise ValueError("target_selector matched no rows")

    per_model_values: dict[str, dict[str, list[float]]] = {
        model: {metric: [] for metric in METRIC_DIRECTIONS} for model in MODEL_NAMES
    }
    for receipt in receipts:
        for model in MODEL_NAMES:
            values = receipt["forecasts"][model]["values"]
            for metric in METRIC_DIRECTIONS:
                per_model_values[model][metric].append(values[metric])

    models = {
        model: {
            **{metric: _mean(values) for metric, values in metrics.items()},
            "n": len(receipts),
        }
        for model, metrics in per_model_values.items()
    }
    paired: dict[str, dict[str, Any]] = {}
    baseline = per_model_values["legacy"]
    bootstrap_clusters = [receipt["date"] for receipt in receipts]
    for model_index, model in enumerate(MODEL_NAMES[1:], start=1):
        paired[model] = {
            metric: _paired_summary(
                per_model_values[model][metric],
                baseline[metric],
                direction=direction,
                samples=config.bootstrap_samples,
                seed=config.bootstrap_seed + 100 * model_index + metric_index,
                clusters=bootstrap_clusters,
            )
            for metric_index, (metric, direction) in enumerate(METRIC_DIRECTIONS.items())
        }

    component_paired: dict[str, dict[str, Any]] = {}
    coherent_baseline = per_model_values["coherent_legacy"]
    for model_index, model in enumerate(MODEL_NAMES[2:], start=1):
        component_paired[model] = {
            metric: _paired_summary(
                per_model_values[model][metric],
                coherent_baseline[metric],
                direction=direction,
                samples=config.bootstrap_samples,
                seed=(
                    config.bootstrap_seed
                    + 1_000
                    + 100 * model_index
                    + metric_index
                ),
                clusters=bootstrap_clusters,
            )
            for metric_index, (metric, direction) in enumerate(
                METRIC_DIRECTIONS.items()
            )
        }

    return {
        "n_matches": len(receipts),
        "models": models,
        "paired_vs_legacy": paired,
        "paired_component_vs_coherent_legacy": component_paired,
        "receipts": receipts,
        "notes": {
            "target_tuning": "none",
            "delta_definition": "candidate minus legacy",
            "score_grid_tail": "out-of-grid exact scores receive epsilon probability",
            "dynamic_uncertainty": "approximate marginal information tracker",
            "legacy_metric_basis": (
                "served calibrated W/D/L; raw production DC grid for exact score and totals"
            ),
            "candidate_calibration": (
                "coherent grid raking with frozen fixture-local champion class weights"
            ),
            "coherence_ablation": (
                "coherent_legacy isolates grid-raking policy; component deltas use it as baseline"
            ),
            "bootstrap_unit": "match_timestamp",
        },
    }
