"""Tests for the pinned club raw-data manifest."""
from __future__ import annotations

import hashlib
import json

import pytest

from pipeline.club_data_manifest import (
    CONFIRM_SEASON,
    DIVISIONS,
    SEASONS,
    expected_keys,
    format_report,
    load_manifest,
    pre_confirmation_keys,
    verify,
)


def test_manifest_covers_every_division_season_the_program_used():
    man = load_manifest()
    assert set(man["files"]) == set(expected_keys())
    assert len(man["files"]) == len(DIVISIONS) * len(SEASONS) == 30


def test_manifest_row_counts_match_the_recorded_experiment_sample():
    """3,800 / 3,800 / 3,060 are the n's every gate in the ledger reports."""
    man = load_manifest()
    per_div = {
        d: sum(man["files"][f"{d}_{s}"]["rows"] for s in SEASONS) for d in DIVISIONS
    }
    assert per_div == {"E0": 3800, "SP1": 3800, "D1": 3060}


def test_every_entry_carries_a_full_sha256():
    for key, meta in load_manifest()["files"].items():
        assert len(meta["sha256"]) == 64, key
        assert int(meta["sha256"], 16) >= 0
        assert meta["bytes"] > 0


def _write(dirpath, key: str, body: bytes) -> None:
    (dirpath / f"{key}.csv").write_bytes(body)


def test_verify_reports_reproducible_on_an_exact_match(tmp_path):
    man = {"files": {}}
    for key in expected_keys():
        body = f"payload-{key}".encode()
        _write(tmp_path, key, body)
        man["files"][key] = {"sha256": hashlib.sha256(body).hexdigest(),
                             "bytes": len(body), "rows": 1}
    result = verify(tmp_path, man)
    assert result["reproducible"] is True
    assert result["matched"] == 30
    assert result["drifted"] == [] and result["missing"] == []
    assert "REPRODUCIBLE" in format_report(result)


def test_verify_flags_an_upstream_revision_rather_than_passing_silently(tmp_path):
    """football-data.co.uk revises files in place — that must be visible."""
    man = {"files": {}}
    for key in expected_keys():
        body = f"payload-{key}".encode()
        _write(tmp_path, key, body)
        man["files"][key] = {"sha256": hashlib.sha256(body).hexdigest(),
                             "bytes": len(body), "rows": 1}
    _write(tmp_path, "E0_2526", b"REVISED UPSTREAM")

    result = verify(tmp_path, man)
    assert result["reproducible"] is False
    assert [d["file"] for d in result["drifted"]] == ["E0_2526"]
    assert "NOT REPRODUCIBLE" in format_report(result)
    assert "DRIFT E0_2526" in format_report(result)


def test_verify_reports_missing_captures(tmp_path):
    man = {"files": {k: {"sha256": "0" * 64, "bytes": 1, "rows": 1}
                     for k in expected_keys()}}
    result = verify(tmp_path, man)
    assert result["reproducible"] is False
    assert len(result["missing"]) == 30


def test_manifest_is_valid_json_on_disk():
    from pipeline.club_data_manifest import MANIFEST_PATH

    assert MANIFEST_PATH.exists()
    assert json.loads(MANIFEST_PATH.read_text())["algorithm"] == "sha256"


# ---------------------------------------------------------------------------
# Scoped verification (mentor review of the T1.6 branch).
#
# verify() HASHES files, which means opening and reading them. The T1.6 runner
# called it over all 30 keys, so it read the consumed 2025-26 holdout bytes at
# its entry point — before load_league's season filter ever ran. The T1.6 path
# must verify the 27 pre-confirmation captures only.
#
# These tests POISON the 2526 captures (as directories, so any read_bytes()
# raises IsADirectoryError regardless of filesystem permissions or test user)
# and prove the scoped path completes without touching them.
# ---------------------------------------------------------------------------

def _valid_pre_confirmation_dir(tmp_path):
    """27 readable pre-confirmation captures + 3 poisoned 2526 entries."""
    man = {"files": {}}
    for key in expected_keys():  # all 30 stay in the manifest
        body = f"payload-{key}".encode()
        man["files"][key] = {"sha256": hashlib.sha256(body).hexdigest(),
                             "bytes": len(body), "rows": 1}
        if key.endswith(f"_{CONFIRM_SEASON}"):
            (tmp_path / f"{key}.csv").mkdir()  # poison: reading it raises
        else:
            (tmp_path / f"{key}.csv").write_bytes(body)
    return man


def test_pre_confirmation_scope_is_27_of_the_30_manifest_files():
    keys = pre_confirmation_keys()
    assert len(keys) == 27
    assert len(expected_keys()) == 30
    assert not any(k.endswith(f"_{CONFIRM_SEASON}") for k in keys)
    assert set(keys) < set(expected_keys())


def test_scoped_verify_succeeds_without_opening_the_poisoned_holdout(tmp_path):
    man = _valid_pre_confirmation_dir(tmp_path)
    result = verify(tmp_path, man, keys=pre_confirmation_keys())
    assert result["reproducible"] is True
    assert result["expected"] == 27
    assert result["matched"] == 27
    assert result["drifted"] == [] and result["missing"] == []
    assert not any(k.endswith(f"_{CONFIRM_SEASON}") for k in result["scope"])


def test_unscoped_verify_would_have_touched_the_holdout(tmp_path):
    """Proves the poison is real, so the test above is not vacuous."""
    man = _valid_pre_confirmation_dir(tmp_path)
    with pytest.raises(IsADirectoryError):
        verify(tmp_path, man)


def test_the_t16_runner_verifies_only_the_pre_confirmation_scope(tmp_path, capsys):
    """End-to-end on the runner's own entry path, holdout poisoned."""
    from pipeline import experiment_club_calibration as t16

    man = _valid_pre_confirmation_dir(tmp_path)
    result = t16.verify(tmp_path, man, keys=t16.pre_confirmation_keys())
    assert result["expected"] == result["matched"] == 27
    assert result["reproducible"] is True


def test_scoped_report_states_the_verified_scope(tmp_path):
    man = _valid_pre_confirmation_dir(tmp_path)
    report = format_report(verify(tmp_path, man, keys=pre_confirmation_keys()))
    assert "verified scope : 27 files" in report
    assert "manifest files : 30" in report


def test_verify_rejects_keys_absent_from_the_manifest(tmp_path):
    man = {"files": {k: {"sha256": "0" * 64, "bytes": 1, "rows": 1}
                     for k in expected_keys()}}
    with pytest.raises(KeyError, match="E0_9999"):
        verify(tmp_path, man, keys=["E0_9999"])


def test_the_holdout_season_constant_agrees_across_modules():
    """Three modules name this season; drift between them would be silent."""
    from ml.evaluation.club_calibration import CONFIRM_SEASON as calib_season
    from ml.evaluation.club_walkforward import CONFIRM_SEASON as wf_season
    from pipeline.ingest.club_results import HOLDOUT_SEASON_CODE

    assert CONFIRM_SEASON == calib_season == wf_season == HOLDOUT_SEASON_CODE
