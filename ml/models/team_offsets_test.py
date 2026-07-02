"""Tests for the per-team attack/defence offset policy + store loader (FR-5.2).

The shrink/cap policy mirrors the in-tournament form layer in
ml/ratings/tournament.py: a √(n/full) confidence ramp plus a hard
anti-overfitting cap — here in log-lambda units instead of Elo points.
"""
import json
import math

import pytest

from ml.models.team_offsets import (
    FULL_WEIGHT_EFF_MATCHES,
    OFFSET_CAP,
    load_team_offsets,
    offsets_for,
    shrink_and_cap,
)


def test_cap_mirrors_form_layer_ceiling():
    """OFFSET_CAP is FORM_CAP_ELO (±35 Elo) translated through the served
    elo→goals slope: beta 0.0021 × 35 ≈ 0.0735 → 0.075 log-lambda units."""
    from ml.ratings.tournament import FORM_CAP_ELO

    assert OFFSET_CAP == pytest.approx(FORM_CAP_ELO * 0.0021, rel=0.05)


def test_zero_matches_shrinks_to_zero():
    assert shrink_and_cap(0.5, -0.5, 0.0) == (0.0, 0.0)
    assert shrink_and_cap(0.5, -0.5, -1.0) == (0.0, 0.0)


def test_shrinkage_below_full_weight_is_partial_and_monotone():
    """Below FULL_WEIGHT_EFF_MATCHES the offset shrinks toward 0 on the √ ramp,
    and more effective matches always mean at least as much retained offset."""
    raw = OFFSET_CAP / 2  # inside the cap so only the ramp acts
    prev_atk = 0.0
    for n_eff in (1.0, 4.0, 10.0, FULL_WEIGHT_EFF_MATCHES / 2):
        atk, dfn = shrink_and_cap(raw, -raw, n_eff)
        expected = raw * math.sqrt(n_eff / FULL_WEIGHT_EFF_MATCHES)
        assert atk == pytest.approx(expected)
        assert dfn == pytest.approx(-expected)
        assert abs(atk) < abs(raw)
        assert atk >= prev_atk
        prev_atk = atk


def test_full_weight_at_or_above_threshold():
    raw = OFFSET_CAP / 3
    assert shrink_and_cap(raw, raw, FULL_WEIGHT_EFF_MATCHES) == (raw, raw)
    assert shrink_and_cap(raw, raw, FULL_WEIGHT_EFF_MATCHES * 10) == (raw, raw)


def test_hard_cap_property_over_extreme_inputs():
    """|offset| never exceeds OFFSET_CAP regardless of raw magnitude or n_eff."""
    for raw in (-100.0, -1.0, -0.2, 0.0, 0.2, 1.0, 100.0):
        for n_eff in (0.0, 0.5, 3.0, 29.0, 30.0, 5000.0):
            atk, dfn = shrink_and_cap(raw, -raw, n_eff)
            assert abs(atk) <= OFFSET_CAP
            assert abs(dfn) <= OFFSET_CAP


def test_load_missing_file_returns_empty_store(tmp_path):
    assert load_team_offsets(tmp_path / "nope.json") == {}


def test_load_invalid_json_returns_empty_store(tmp_path):
    f = tmp_path / "team_offsets.json"
    f.write_text("{not json")
    assert load_team_offsets(f) == {}


def test_offsets_for_reads_store_and_falls_back_to_zero(tmp_path):
    f = tmp_path / "team_offsets.json"
    f.write_text(json.dumps({"Brazil": {"atk": 0.05, "def": -0.03, "n_matches": 120}}))
    store = load_team_offsets(f)
    assert offsets_for(store, "Brazil") == (0.05, -0.03)
    assert offsets_for(store, "Moldova") == (0.0, 0.0)


def test_offsets_for_clamps_hand_edited_values_to_cap(tmp_path):
    """A hand-edited (or corrupted) store can never exceed the policy cap at
    serve time — the clamp is defence in depth on top of the fit-time cap."""
    f = tmp_path / "team_offsets.json"
    f.write_text(json.dumps({"Brazil": {"atk": 9.0, "def": -9.0, "n_matches": 120}}))
    store = load_team_offsets(f)
    atk, dfn = offsets_for(store, "Brazil")
    assert atk == OFFSET_CAP
    assert dfn == -OFFSET_CAP
