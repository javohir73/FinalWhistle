"""Tests for the Wave 1 margin+total params loader (ml/models/nrl_margin_total.py)."""
import json

import ml.models.nrl_margin_total as mod
from ml.models.nrl_margin_total import (
    NrlMarginTotalParams,
    load_margin_total_params,
    predict_margin_total,
    save_margin_total_params,
)


def test_missing_file_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_PARAMS_FILE", tmp_path / "absent.json")
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_invalid_json_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    f.write_text("not json")
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_missing_field_falls_back_to_defaults(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"version": "nrl-elo-v0.2"}))  # no margin_coef_elo_diff etc.
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    assert load_margin_total_params() == NrlMarginTotalParams()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    tuned = NrlMarginTotalParams(
        version="nrl-elo-v0.2", margin_coef_elo_diff=0.0512,
        margin_intercept=4.6, expected_total=39.8,
    )
    save_margin_total_params(tuned)
    assert load_margin_total_params() == tuned


def test_saved_file_is_indented_json_with_trailing_newline(tmp_path, monkeypatch):
    f = tmp_path / "p.json"
    monkeypatch.setattr(mod, "_PARAMS_FILE", f)
    save_margin_total_params(NrlMarginTotalParams())
    text = f.read_text()
    assert text.endswith("\n")
    assert "  " in text


def test_predict_margin_total_applies_intercept_and_slope():
    p = NrlMarginTotalParams(version="nrl-elo-v0.2", margin_coef_elo_diff=0.05,
                              margin_intercept=4.0, expected_total=40.0)
    margin, total = predict_margin_total(1550.0, 1500.0, p)
    assert margin == 0.05 * 50 + 4.0
    assert total == 40.0
