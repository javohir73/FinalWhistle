"""The reviewed q3 artifact: provenance, holdout safety, and binding to config."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.evaluation.calibration import assert_servable_calibrator
from ml.evaluation.club_calibration import CONFIRM_SEASON, bucket_names
from pipeline.club_data_manifest import PRE_CONFIRMATION_SEASONS, pre_confirmation_keys
from pipeline.fit_club_calibrator import ELIGIBLE, manifest_digest
from pipeline.leagues import AVAILABLE_SHADOW_VARIANTS, club_shadow_variants_for

ARTIFACT = Path(__file__).resolve().parents[1] / "ml/models/calibrators/bundesliga_q3.json"


def _blob() -> dict:
    return json.loads(ARTIFACT.read_text())


def test_the_artifact_exists_and_is_servable():
    assert_servable_calibrator(_blob())


def test_the_artifact_was_fitted_only_on_pre_confirmation_seasons():
    prov = _blob()["provenance"]
    assert tuple(prov["fitted_on_seasons"]) == PRE_CONFIRMATION_SEASONS
    assert CONFIRM_SEASON not in prov["fitted_on_seasons"]
    assert prov["excluded_holdout_season"] == CONFIRM_SEASON
    assert prov["manifest_files_verified"] == len(pre_confirmation_keys()) == 27


def test_the_artifact_is_pinned_to_the_raw_bytes_it_was_fitted_on():
    """If upstream revises a season file the digest moves and this fails —
    which is the point: the artifact would then be stale, not merely old."""
    assert _blob()["provenance"]["manifest_digest_sha256"] == manifest_digest()


def test_the_artifact_records_the_engine_it_was_fitted_against():
    eng = _blob()["provenance"]["engine"]
    assert eng["base"] == 1.44  # Bundesliga's #202 shipped base
    assert eng["home_adv"] == 60.0
    assert {"beta", "rho", "served_params_version"} <= set(eng)


def test_the_artifact_records_a_reproduction_command_and_candidate():
    prov = _blob()["provenance"]
    assert prov["candidate"] == "refit_q3"
    assert "pipeline.fit_club_calibrator" in prov["command"]


def test_the_artifact_has_three_balanced_buckets_and_none_thin():
    b = _blob()
    assert len(b["edges"]) == 2
    assert set(b["buckets"]) == set(bucket_names(b["edges"]))
    assert b["thin_buckets"] == []
    occ = list(b["bucket_occupancy_train"].values())
    assert max(occ) - min(occ) <= 5, "quantile edges should split near-evenly"
    assert b["n_train"] == sum(occ) == 2754  # 9 seasons x 306


def test_every_bucket_carries_a_real_vector_scaling_cell():
    for name, cell in _blob()["buckets"].items():
        assert cell["t"] > 0, name
        assert len(cell["b"]) == 3 and cell["b"][0] == 0.0, name


def test_only_bundesliga_may_be_fitted():
    assert ELIGIBLE == {"bundesliga"}
    from pipeline.fit_club_calibrator import fit

    for league in ("epl", "laliga"):
        with pytest.raises(ValueError, match="not eligible"):
            fit(league, Path("/nonexistent"))


# --- binding: the loaded candidate IS this artifact -------------------------

def test_the_registry_points_at_this_artifact():
    assert AVAILABLE_SHADOW_VARIANTS["bundesliga"]["cal_q3"] == ARTIFACT.name


def test_the_enabled_variant_loads_exactly_this_artifact():
    v = club_shadow_variants_for("bundesliga", env_value="bundesliga:cal_q3")
    assert v["cal_q3"].calibrator == _blob()


def test_the_variant_differs_from_served_params_in_the_calibrator_alone():
    from pipeline.leagues import club_params_for

    served = club_params_for("bundesliga")
    variant = club_shadow_variants_for("bundesliga", env_value="bundesliga:cal_q3")["cal_q3"]
    assert variant.calibrator != served.calibrator
    for field in ("base", "beta", "rho", "home_adv", "temperature", "version"):
        assert getattr(variant, field) == getattr(served, field), field
