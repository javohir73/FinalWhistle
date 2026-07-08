"""Tests for the NRL params loader (task 5)."""
import json

import ml.sports.nrl.params as params_mod
from ml.sports.nrl.model import NrlParams
from ml.sports.nrl.params import load_nrl_params, save_nrl_params


def test_missing_file_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", tmp_path / "absent.json")
    assert load_nrl_params() == NrlParams()


def test_invalid_json_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "params.json"
    f.write_text("not json")
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_nrl_params() == NrlParams()


def test_missing_field_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "params.json"
    f.write_text(json.dumps({"version": "nrl-elo-v0.1", "k": 36.0}))  # no home_adv etc.
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_nrl_params() == NrlParams()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    f = tmp_path / "params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    tuned = NrlParams(
        version="nrl-elo-v0.1", k=32.0, home_adv=65.0, margin_mult_cap=2.6,
        season_regress=0.35, margin_slope=0.045, margin_sigma=15.0, p_draw=0.02,
    )
    save_nrl_params(tuned)
    assert load_nrl_params() == tuned


def test_saved_file_is_indented_json_with_trailing_newline(tmp_path, monkeypatch):
    f = tmp_path / "params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    save_nrl_params(NrlParams())
    text = f.read_text()
    assert text.endswith("\n")
    assert "  " in text  # indent=2
