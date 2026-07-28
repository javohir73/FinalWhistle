"""Tests for the pinned club raw-data manifest."""
from __future__ import annotations

import hashlib
import json

from pipeline.club_data_manifest import (
    DIVISIONS,
    SEASONS,
    expected_keys,
    format_report,
    load_manifest,
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
