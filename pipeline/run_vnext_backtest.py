"""Run the vNext shadow comparison against a local international-results CSV.

No database or network access is performed.  Example::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_vnext_backtest \
        --csv data/results.csv --year 2022
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from ml.evaluation.vnext_replay import (
    VNextReplayConfig,
    replay_vnext,
    world_cup_year,
)
from ml.models.params import load_params
from ml.ratings.dynamic_strength import DynamicModelConfig
from ml.ratings.elo import (
    BASE_RATING,
    HOME_ADVANTAGE,
    MatchInput,
    update_ratings,
)
from pipeline.ingest.historical_results import clean_results_df


WORLD_CUP_GROUP_STAGE_COUNTS = {2018: 48, 2022: 48, 2026: 72}
REGULATION_TIME_POLICY = "fifa-world-cup-first-group-stage-only-v1"


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _simultaneous_prematch_elo(
    inputs: Sequence[MatchInput], timestamps: Sequence[object]
) -> list[dict[str, Any]]:
    """Replay Elo while freezing every equal-timestamp batch before updates."""
    if len(inputs) != len(timestamps):
        raise ValueError("inputs and timestamps must have equal length")
    ratings: dict[int, float] = {}
    rows: list[dict[str, Any] | None] = [None] * len(inputs)
    indexed = enumerate(zip(inputs, timestamps))
    for _, batch_iter in groupby(indexed, key=lambda item: item[1][1]):
        batch = list(batch_iter)
        deltas: dict[int, float] = defaultdict(float)
        for index, (match, _) in batch:
            home = ratings.get(match.home_id, BASE_RATING)
            away = ratings.get(match.away_id, BASE_RATING)
            rows[index] = {
                "home_id": match.home_id,
                "away_id": match.away_id,
                "pre_home": home,
                "pre_away": away,
                "is_neutral": match.is_neutral,
                "competition": match.competition,
                "score_home": match.score_home,
                "score_away": match.score_away,
            }
            new_home, new_away = update_ratings(
                home,
                away,
                match.score_home,
                match.score_away,
                competition=match.competition,
                is_neutral=match.is_neutral,
                home_advantage=HOME_ADVANTAGE,
            )
            deltas[match.home_id] += new_home - home
            deltas[match.away_id] += new_away - away
        for team_id, delta in deltas.items():
            ratings[team_id] = ratings.get(team_id, BASE_RATING) + delta
    if any(row is None for row in rows):
        raise RuntimeError("simultaneous Elo replay left an unfilled row")
    return [row for row in rows if row is not None]


def _regulation_time_safe_results(
    cleaned: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Remove World Cup rows whose 90-minute score is not unambiguous.

    The international-results CSV has no stage or score-at-90 field.  For the
    supported editions, chronological order plus the official first-group-stage
    count gives a conservative boundary.  Unsupported editions are excluded
    rather than allowing an extra-time final score to enter Elo or dynamic state.
    An incomplete/synthetic supported edition keeps every available row.
    """
    tournament = cleaned["tournament"].fillna("").astype(str).str.lower()
    world_cup = tournament.str.contains("fifa world cup", regex=False) & ~tournament.str.contains(
        "qualif", regex=False
    )
    keep = pd.Series(True, index=cleaned.index)
    editions: dict[str, dict[str, Any]] = {}
    unsupported: dict[str, int] = {}
    kept_world_cup = 0
    excluded_knockout = 0
    excluded_unsupported = 0

    years = sorted(set(cleaned.loc[world_cup, "parsed_when"].dt.year.tolist()))
    for year in years:
        indices = cleaned.index[world_cup & (cleaned["parsed_when"].dt.year == year)].tolist()
        observed = len(indices)
        expected = WORLD_CUP_GROUP_STAGE_COUNTS.get(year)
        if expected is None:
            keep.loc[indices] = False
            unsupported[str(year)] = observed
            excluded_unsupported += observed
            continue
        retained = min(observed, expected)
        excluded = max(0, observed - expected)
        if excluded:
            keep.loc[indices[expected:]] = False
            excluded_knockout += excluded
        kept_world_cup += retained
        editions[str(year)] = {
            "expected_group_matches": expected,
            "observed_finals_rows": observed,
            "retained_group_rows": retained,
            "excluded_post_group_rows": excluded,
            "status": (
                "incomplete_or_synthetic_all_retained"
                if observed < expected
                else "group_boundary_applied"
            ),
        }

    filtered = cleaned.loc[keep].reset_index(drop=True)
    summary = {
        "policy": REGULATION_TIME_POLICY,
        "scope": "FIFA World Cup group-stage regulation-time labels only",
        "supported_group_stage_counts": {
            str(year): count
            for year, count in sorted(WORLD_CUP_GROUP_STAGE_COUNTS.items())
        },
        "editions": editions,
        "unsupported_editions_excluded": unsupported,
        "world_cup_rows_seen": int(world_cup.sum()),
        "world_cup_group_rows_retained": kept_world_cup,
        "world_cup_post_group_rows_excluded": excluded_knockout,
        "world_cup_unsupported_rows_excluded": excluded_unsupported,
    }
    return filtered, summary


def build_replay_rows_with_boundary(
    raw: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Clean, boundary-filter and attach stable IDs plus prematch Elo."""
    cleaned = clean_results_df(raw).reset_index(drop=True)
    if cleaned.empty:
        raise ValueError("results CSV contains no usable matches")
    parsed_dates = pd.to_datetime(cleaned["date"], errors="raise", utc=True)
    cleaned = cleaned.assign(parsed_when=parsed_dates, source_order=range(len(cleaned)))
    cleaned = cleaned.sort_values(
        ["parsed_when", "source_order"], kind="mergesort"
    ).reset_index(drop=True)
    cleaned, boundary = _regulation_time_safe_results(cleaned)
    if cleaned.empty:
        raise ValueError("no regulation-time-safe matches remain after boundary filtering")

    team_names = sorted(
        set(cleaned["home_team"].tolist()) | set(cleaned["away_team"].tolist())
    )
    team_ids = {name: index + 1 for index, name in enumerate(team_names)}
    inputs = [
        MatchInput(
            home_id=team_ids[row.home_team],
            away_id=team_ids[row.away_team],
            score_home=int(row.home_score),
            score_away=int(row.away_score),
            competition=str(row.tournament),
            is_neutral=bool(row.neutral),
        )
        for row in cleaned.itertuples(index=False)
    ]
    elo_rows = _simultaneous_prematch_elo(inputs, cleaned["parsed_when"].tolist())

    rows: list[dict[str, Any]] = []
    for index, (elo_row, source) in enumerate(
        zip(elo_rows, cleaned.itertuples(index=False))
    ):
        rows.append(
            {
                **elo_row,
                "match_id": f"csv-{index}",
                "date": source.parsed_when.to_pydatetime(),
                "competition": str(source.tournament),
            }
        )
    return rows, boundary


def build_replay_rows(raw: pd.DataFrame) -> list[dict[str, Any]]:
    """Compatibility helper returning rows without the boundary audit summary."""
    rows, _ = build_replay_rows_with_boundary(raw)
    return rows


def concise_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Drop large per-match receipts while retaining metrics and audit notes."""
    return {key: value for key, value in result.items() if key != "receipts"}


def dynamic_config_for_history(
    rows: Sequence[dict[str, Any]], *, production_base: float
) -> DynamicModelConfig:
    """Size result validation to the observed file while retaining update caps.

    The maximum score is not a fitted parameter and does not affect any forecast;
    it only prevents valid historical blowouts from being rejected.  Likelihood
    gradients remain bounded by ``DynamicModelConfig.max_abs_gradient``.
    """
    if not math.isfinite(production_base) or production_base <= 0.0:
        raise ValueError("production_base must be positive and finite")
    if not rows:
        raise ValueError("cannot configure dynamic replay without rows")
    observed_max = max(
        max(int(row["score_home"]), int(row["score_away"])) for row in rows
    )
    defaults = DynamicModelConfig()
    return DynamicModelConfig(
        base_log_total=math.log(2.0 * production_base),
        max_goals=max(defaults.max_goals, observed_max),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare FinalWhistle vNext candidates on a local results CSV."
    )
    parser.add_argument("--csv", required=True, type=Path, help="Local results CSV")
    parser.add_argument("--year", required=True, type=int, help="World Cup finals year")
    parser.add_argument(
        "--bootstrap-samples",
        type=_non_negative_int,
        default=2_000,
        help="Paired bootstrap draws (0 disables confidence intervals)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.year not in WORLD_CUP_GROUP_STAGE_COUNTS:
        raise ValueError(
            f"no regulation-time-safe group boundary is registered for {args.year}"
        )
    raw = pd.read_csv(args.csv)
    rows, regulation_boundary = build_replay_rows_with_boundary(raw)
    params = load_params()
    dynamic = dynamic_config_for_history(rows, production_base=params.base)
    config = VNextReplayConfig.from_model_params(
        params,
        dynamic=dynamic,
        bootstrap_samples=args.bootstrap_samples,
    )
    result = replay_vnext(
        rows,
        target_selector=world_cup_year(args.year),
        config=config,
    )
    summary = concise_summary(result)
    summary["configuration"] = {
        "dynamic_result_goal_cap": dynamic.max_goals,
        "bootstrap_samples": args.bootstrap_samples,
    }
    summary["regulation_time_boundary"] = regulation_boundary
    summary["notes"]["target_scope"] = regulation_boundary["scope"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
