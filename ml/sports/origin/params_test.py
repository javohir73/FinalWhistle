"""Origin params loader — mirrors ml/sports/nrl/params_test.py's pattern."""
from ml.sports.origin import params as origin_params
from ml.sports.origin.params import ORIGIN_DEFAULTS, load_origin_params, save_origin_params


def test_defaults_are_origin_branded():
    assert ORIGIN_DEFAULTS.version == "origin-elo-v0.1"


def test_load_falls_back_to_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(origin_params, "_PARAMS_FILE", tmp_path / "params.json")
    assert load_origin_params() == ORIGIN_DEFAULTS


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(origin_params, "_PARAMS_FILE", tmp_path / "params.json")
    tuned = replace(ORIGIN_DEFAULTS, k=64.0, home_adv=15.0)
    save_origin_params(tuned)
    assert load_origin_params() == tuned
