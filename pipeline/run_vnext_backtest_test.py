"""Tests for the local-file vNext backtest command."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from pipeline.run_vnext_backtest import (
    WORLD_CUP_GROUP_STAGE_COUNTS,
    build_replay_rows,
    build_replay_rows_with_boundary,
    dynamic_config_for_history,
    main,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "home_team": "Zulu",
                "away_team": "Alpha",
                "home_score": 2,
                "away_score": 0,
                "tournament": "Friendly",
                "city": "X",
                "country": "X",
                "neutral": True,
            },
            {
                "date": "2026-06-12",
                "home_team": "Alpha",
                "away_team": "Zulu",
                "home_score": 1,
                "away_score": 1,
                "tournament": "FIFA World Cup",
                "city": "Y",
                "country": "Y",
                "neutral": True,
            },
            {
                "date": "2026-06-15",
                "home_team": "Zulu",
                "away_team": "Alpha",
                "home_score": 1,
                "away_score": 0,
                "tournament": "FIFA World Cup",
                "city": "Z",
                "country": "Z",
                "neutral": True,
            },
        ]
    )


def test_build_replay_rows_is_chronological_with_stable_team_ids():
    rows = build_replay_rows(_frame().iloc[::-1])

    assert [row["date"].year for row in rows] == [2025, 2026, 2026]
    # Alphabetical IDs are stable, independent of CSV encounter order.
    alpha_ids = {
        row["home_id"] if source_home == "Alpha" else row["away_id"]
        for row, source_home in zip(
            rows,
            ["Zulu", "Alpha", "Zulu"],
        )
    }
    assert alpha_ids == {1}
    assert rows[0]["pre_home"] == 1500.0
    assert rows[0]["pre_away"] == 1500.0
    assert all(row["date"].tzinfo is not None for row in rows)


def test_same_day_elo_is_frozen_before_any_same_day_result():
    first = _frame().iloc[:1].copy()
    first["date"] = "2025-01-02"
    first["home_team"] = "Alpha"
    first["away_team"] = "Bravo"
    second = first.copy()
    second["home_team"] = "Alpha"
    second["away_team"] = "Charlie"
    second["home_score"] = 0
    second["away_score"] = 4

    rows = build_replay_rows(pd.concat([first, second], ignore_index=True))

    assert len(rows) == 2
    assert rows[0]["pre_home"] == 1500.0
    assert rows[1]["pre_home"] == 1500.0


def test_main_prints_concise_json_without_receipts(tmp_path, capsys):
    csv_path = tmp_path / "results.csv"
    _frame().to_csv(csv_path, index=False)

    assert main(
        [
            "--csv",
            str(csv_path),
            "--year",
            "2026",
            "--bootstrap-samples",
            "20",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["n_matches"] == 2
    assert "receipts" not in output
    assert set(output["models"]) == {
        "legacy",
        "coherent_legacy",
        "orthogonal_elo_dynamic_tempo",
        "dynamic_strength_tempo",
    }
    assert output["notes"]["target_tuning"] == "none"
    assert output["notes"]["target_scope"] == (
        "FIFA World Cup group-stage regulation-time labels only"
    )
    boundary = output["regulation_time_boundary"]
    assert boundary["editions"]["2026"] == {
        "excluded_post_group_rows": 0,
        "expected_group_matches": 72,
        "observed_finals_rows": 2,
        "retained_group_rows": 2,
        "status": "incomplete_or_synthetic_all_retained",
    }


def test_build_replay_rows_uses_cleaner_validation():
    with pytest.raises(ValueError, match="missing columns"):
        build_replay_rows(pd.DataFrame({"date": ["2026-01-01"]}))


def test_empty_cleaned_csv_is_rejected():
    frame = _frame().iloc[:1].copy()
    frame["home_score"] = None
    with pytest.raises(ValueError, match="no usable"):
        build_replay_rows(frame)


def test_historical_blowout_expands_validation_cap_and_cli_keeps_row(
    tmp_path, capsys
):
    blowout = _frame().iloc[:1].copy()
    blowout["date"] = "2024-01-01"
    blowout["home_score"] = 31
    frame = pd.concat([blowout, _frame()], ignore_index=True)
    rows = build_replay_rows(frame)

    dynamic = dynamic_config_for_history(rows, production_base=1.2)
    assert dynamic.max_goals == 31

    csv_path = tmp_path / "blowout-results.csv"
    frame.to_csv(csv_path, index=False)
    assert main(
        [
            "--csv",
            str(csv_path),
            "--year",
            "2026",
            "--bootstrap-samples",
            "0",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["n_matches"] == 2
    assert output["configuration"]["dynamic_result_goal_cap"] == 31


def _completed_world_cup(year: int, matches: int = 64) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": f"{year}-06-{1 + index // 4:02d}",
                "home_team": "Alpha",
                "away_team": "Bravo",
                "home_score": 1,
                "away_score": 0,
                "tournament": "FIFA World Cup",
                "city": "X",
                "country": "X",
                "neutral": True,
            }
            for index in range(matches)
        ]
    )


def test_completed_2022_keeps_48_group_matches_and_excludes_knockouts():
    rows, boundary = build_replay_rows_with_boundary(_completed_world_cup(2022))

    assert WORLD_CUP_GROUP_STAGE_COUNTS == {2018: 48, 2022: 48, 2026: 72}
    assert len(rows) == 48
    assert boundary["world_cup_rows_seen"] == 64
    assert boundary["world_cup_group_rows_retained"] == 48
    assert boundary["world_cup_post_group_rows_excluded"] == 16
    assert boundary["editions"]["2022"]["status"] == "group_boundary_applied"


def test_excluded_knockout_scores_never_train_later_elo():
    original = _completed_world_cup(2022)
    changed = original.copy()
    changed.loc[48:, "home_score"] = 20
    changed.loc[48:, "away_score"] = 19
    later = _frame().iloc[:1].copy()
    later["date"] = "2023-01-01"
    original = pd.concat([original, later], ignore_index=True)
    changed = pd.concat([changed, later], ignore_index=True)

    original_rows, _ = build_replay_rows_with_boundary(original)
    changed_rows, _ = build_replay_rows_with_boundary(changed)

    assert len(original_rows) == len(changed_rows) == 49
    assert original_rows[-1]["pre_home"] == changed_rows[-1]["pre_home"]
    assert original_rows[-1]["pre_away"] == changed_rows[-1]["pre_away"]


def test_unsupported_world_cup_editions_are_excluded_from_training():
    unsupported = _completed_world_cup(2014, matches=3)
    friendly = _frame().iloc[:1].copy()
    rows, boundary = build_replay_rows_with_boundary(
        pd.concat([unsupported, friendly], ignore_index=True)
    )

    assert len(rows) == 1
    assert rows[0]["competition"] == "Friendly"
    assert boundary["unsupported_editions_excluded"] == {"2014": 3}
