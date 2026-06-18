"""Tests for ModelParams (calibrator round-trip)."""
import json

from ml.models.params import DEFAULT_PARAMS, ModelParams, load_params, save_params
import ml.models.params as params_mod


def test_default_params_have_no_calibrator():
    assert DEFAULT_PARAMS.calibrator is None


def test_calibrator_round_trips_through_save_load(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    blob = {"method": "vector_scaling", "t": 1.2, "b": [0.0, 0.4, -0.1]}
    p = ModelParams(version="v0.2+cal", base=1.2, beta=0.0021, home_adv=60.0,
                    rho=-0.06, temperature=1.0, pk_beta=0.0, calibrator=blob)
    save_params(p)
    loaded = load_params()
    assert loaded.calibrator == blob


def test_json_without_calibrator_loads_as_none(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    f.write_text(json.dumps({
        "version": "v0.2", "base": 1.2, "beta": 0.0021, "home_adv": 60.0,
        "rho": -0.06, "temperature": 1.0, "pk_beta": 0.0,
    }))
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_params().calibrator is None


def test_json_explicit_null_calibrator_loads_as_none(tmp_path, monkeypatch):
    # The shipped model_params.json carries an explicit "calibrator": null.
    f = tmp_path / "model_params.json"
    f.write_text(json.dumps({
        "version": "v0.2", "base": 1.2, "beta": 0.0021, "home_adv": 60.0,
        "rho": -0.06, "temperature": 1.0, "pk_beta": 0.0, "calibrator": None,
    }))
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_params().calibrator is None


def test_to_dict_includes_calibrator():
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 0.5, 0.0]}
    p = ModelParams(version="v", base=1.2, beta=0.002, home_adv=60.0, rho=0.0,
                    temperature=1.0, calibrator=blob)
    assert p.to_dict()["calibrator"] == blob


def test_default_params_have_no_wdl_blend():
    assert DEFAULT_PARAMS.wdl_blend is None


def test_wdl_blend_round_trips_through_save_load(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    blend = {"weight": 0.35, "calibrator": {"method": "vector_scaling", "t": 1.1, "b": [0.0, 0.2, 0.0]}}
    p = ModelParams(version="v0.2+blend", base=1.2, beta=0.0021, home_adv=60.0,
                    rho=-0.06, temperature=1.0, pk_beta=0.0, wdl_blend=blend)
    save_params(p)
    assert load_params().wdl_blend == blend


def test_json_without_wdl_blend_loads_as_none(tmp_path, monkeypatch):
    f = tmp_path / "model_params.json"
    f.write_text(json.dumps({
        "version": "v0.2", "base": 1.2, "beta": 0.0021, "home_adv": 60.0,
        "rho": -0.06, "temperature": 1.0, "pk_beta": 0.0,
    }))
    monkeypatch.setattr(params_mod, "_PARAMS_FILE", f)
    assert load_params().wdl_blend is None
