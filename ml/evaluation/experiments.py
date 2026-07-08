"""Variant/ablation runner (model v2 design doc §5 validation protocol).

A variant is plain data — {name, params, form_channels, calibrator} — so new
ablations (C1-C3 and combinations) are config, not code:

    {
        "name": "v0.2+form",
        "params": {...ModelParams fields...},   # goals engine
        "form_channels": {"c_atk", "c_def", "cap", "half_life"} | None,
        "calibrator": "fit_on_validation" | None,
    }

``score_variant`` scores one variant on a set of (already leak-free, ledger-
enriched) rows. ``run_experiments`` does the same walk-forward train/val/target
split as ml.evaluation.backtest.walk_forward and scores every named variant on
the held-out tournament, returning one metrics table — log loss, Brier,
accuracy, ECE (from the same pooling as ml.evaluation.calibration's
reliability_curve).

Form channels depend on ml/ratings/form.py, owned by a parallel change (C1)
and not guaranteed to be merged yet. The import is guarded: variants that need
it are simply left out of the default table (never silently stubbed with fake
numbers) if the module is absent, and building one explicitly raises
ImportError so a caller who asked for it by name finds out why.
"""
from __future__ import annotations

from datetime import timedelta

from ml.evaluation.backtest import compute_metrics, is_world_cup_final_match, model_probs
from ml.evaluation.calibration import calibrate, effective_gap, fit_segmented_vector_scaling
from ml.evaluation.tune import tune_params, validation_window
from ml.models.baseline_logistic import result_label
from ml.models.params import DEFAULT_PARAMS
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}


def _form_offsets(ledger_home, ledger_away, form_channels):
    """(atk_home, def_home, atk_away, def_away) log-lambda offsets for one row.

    Delegates to ml.ratings.form.form_offsets (owned elsewhere). Raises
    ImportError if that module isn't present — callers decide whether that's
    fatal (build_variant) or means "skip this row's form contribution".
    """
    from ml.ratings.form import FormConfig, form_offsets  # deferred: optional dep

    cfg = FormConfig(
        c_atk=form_channels["c_atk"], c_def=form_channels["c_def"],
        cap=form_channels["cap"], half_life=form_channels["half_life"],
    )
    atk_home, def_home = form_offsets(ledger_home, cfg)
    atk_away, def_away = form_offsets(ledger_away, cfg)
    return atk_home, def_home, atk_away, def_away


def _row_probs(row: dict, variant: dict, calibrator_blob: dict | None):
    p = variant["params"]
    is_neutral = row["is_neutral"]
    adv = 0.0 if is_neutral else p["home_adv"]

    atk_home = def_home = atk_away = def_away = 0.0
    if variant.get("form_channels"):
        atk_home, def_home, atk_away, def_away = _form_offsets(
            row.get("ledger_home") or [], row.get("ledger_away") or [], variant["form_channels"]
        )

    lam_home, lam_away = expected_goals_from_elo(
        row["pre_home"], row["pre_away"], adv, p["base"], p["beta"],
        atk_home=atk_home, def_home=def_home, atk_away=atk_away, def_away=def_away,
    )
    matrix = score_matrix(lam_home, lam_away, rho=p["rho"])
    probs = outcome_probabilities(matrix)
    gap = effective_gap(row["pre_home"], row["pre_away"], adv)
    return calibrate(probs, calibrator_blob, p["temperature"], eff_gap=gap)


def _ece_from_reliability(probs_list, labels, bins: int = 10) -> float:
    """Expected calibration error, pooled the same way as
    ml.evaluation.calibration.reliability_curve (every class probability of
    every match is one sample; weighted by bin occupancy)."""
    from ml.evaluation.calibration import reliability_curve

    n = len(labels) * 3 if labels else 0
    if n == 0:
        return float("nan")
    curve = reliability_curve(probs_list, labels, bins=bins)
    return sum(b["count"] / n * abs(b["mean_predicted"] - b["empirical_freq"]) for b in curve)


def score_variant(rows: list[dict], variant: dict, val_rows: list[dict] | None = None) -> dict:
    """Score one variant on `rows` (the held-out target). Returns
    compute_metrics's dict (log_loss, brier, accuracy, n) plus "ece".

    variant["calibrator"] == "fit_on_validation" fits a segmented vector-
    scaling blob on `val_rows` (required in that case — raises ValueError
    otherwise) using THIS variant's own goals params, then applies it here.
    """
    calibrator_blob = None
    if variant.get("calibrator") == "fit_on_validation":
        if not val_rows:
            raise ValueError(
                f"variant {variant['name']!r} needs calibrator='fit_on_validation' "
                "but no val_rows were supplied"
            )
        calibrator_blob = _fit_calibrator(val_rows, variant)

    probs_list = [_row_probs(r, variant, calibrator_blob) for r in rows]
    labels_str = [result_label(r["score_home"], r["score_away"]) for r in rows]
    labels = [_LABEL_INDEX[x] for x in labels_str]

    metrics = compute_metrics(probs_list, labels_str)
    metrics["ece"] = _ece_from_reliability(probs_list, labels)
    return metrics


def _fit_calibrator(val_rows: list[dict], variant: dict) -> dict:
    """Fit segmented vector scaling on val_rows using variant's goals params
    (uncalibrated), mirroring how tune_params fits temperature."""
    uncalibrated = {**variant, "calibrator": None}
    probs_list = [_row_probs(r, uncalibrated, None) for r in val_rows]
    labels = [_LABEL_INDEX[result_label(r["score_home"], r["score_away"])] for r in val_rows]
    p = variant["params"]
    eff_gaps = [
        effective_gap(r["pre_home"], r["pre_away"], 0.0 if r["is_neutral"] else p["home_adv"])
        for r in val_rows
    ]
    return fit_segmented_vector_scaling(probs_list, labels, eff_gaps)


# ---------------------------------------------------------------------------
# Named built-in variants
# ---------------------------------------------------------------------------

#: Default form-channel knobs used by the "+form" built-ins when the design
#: doc's tuner (ml/evaluation/tune.py's future tune_form) hasn't fitted real
#: ones yet. Deliberately conservative — small coefficients, short cap.
_DEFAULT_FORM_CHANNELS = {"c_atk": 0.03, "c_def": 0.03, "cap": 0.15, "half_life": 6.0}


def build_variant(name: str, val_rows: list[dict]) -> dict:
    """Construct one of the named built-in variants.

    "v0.1-raw"      — served v0.1 constants, no calibration, no form.
    "v0.2-tuned"    — tune_params(val_rows): goals params + temperature.
    "v0.2+form"     — v0.2-tuned params + default form channels (requires
                       ml/ratings/form.py; raises ImportError if absent).
    "v0.2+cal"      — v0.2-tuned params + a segmented vector-scaling
                       calibrator fit on val_rows.
    "v0.2+form+cal" — both of the above combined.

    Unknown names raise ValueError. This is the "config, not code" seam: a
    caller who wants a bespoke combination builds the dict directly and
    passes it to score_variant instead of going through this factory.
    """
    if name == "v0.1-raw":
        return {"name": name, "params": DEFAULT_PARAMS.to_dict(),
                "form_channels": None, "calibrator": None}

    if name == "v0.2-tuned":
        tuned = tune_params(val_rows)
        return {"name": name, "params": tuned.to_dict(),
                "form_channels": None, "calibrator": None}

    if name == "v0.2+form":
        _assert_form_module_available(name)
        tuned = tune_params(val_rows)
        return {"name": name, "params": tuned.to_dict(),
                "form_channels": dict(_DEFAULT_FORM_CHANNELS), "calibrator": None}

    if name == "v0.2+cal":
        tuned = tune_params(val_rows)
        return {"name": name, "params": tuned.to_dict(),
                "form_channels": None, "calibrator": "fit_on_validation"}

    if name == "v0.2+form+cal":
        _assert_form_module_available(name)
        tuned = tune_params(val_rows)
        return {"name": name, "params": tuned.to_dict(),
                "form_channels": dict(_DEFAULT_FORM_CHANNELS), "calibrator": "fit_on_validation"}

    raise ValueError(f"unknown variant {name!r}")


def _assert_form_module_available(name: str) -> None:
    try:
        import ml.ratings.form  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            f"variant {name!r} needs ml/ratings/form.py, which is not present "
            "in this worktree (owned by a parallel change)"
        ) from exc


def form_module_available() -> bool:
    try:
        import ml.ratings.form  # noqa: F401
    except ImportError:
        return False
    return True


#: Variants attempted by run_experiments when the caller doesn't name any.
#: Form-dependent ones are included opportunistically (see run_experiments).
_CORE_VARIANTS = ["v0.1-raw", "v0.2-tuned"]
_OPTIONAL_VARIANTS = ["v0.2+form", "v0.2+cal", "v0.2+form+cal"]


def run_experiments(
    rows: list[dict], year: int, variant_names: list[str] | None = None, val_days: int = 730
) -> dict:
    """Walk-forward score every named variant on World Cup `year`.

    Same leak discipline as ml.evaluation.backtest.walk_forward: the
    validation window (val_days before the tournament) is used for tuning and
    calibration; the tournament itself is scored once, held out throughout.

    When `variant_names` is None, runs the core variants plus any of the
    optional form/calibration variants whose dependencies are present —
    absent ones are left out of the table rather than stubbed.
    """
    target = [
        r for r in rows if is_world_cup_final_match(r["competition"]) and r["date"].year == year
    ]
    if not target:
        raise ValueError(f"no World Cup matches found for {year}")
    first_date = min(r["date"] for r in target)
    val = validation_window(rows, first_date, days=val_days)

    if variant_names is None:
        variant_names = list(_CORE_VARIANTS)
        for opt in _OPTIONAL_VARIANTS:
            if "form" not in opt or form_module_available():
                variant_names.append(opt)

    variants_out: dict[str, dict] = {}
    for name in variant_names:
        try:
            variant = build_variant(name, val)
        except ImportError:
            continue  # dependency not merged yet — note via absence, not a stub
        variants_out[name] = score_variant(target, variant, val_rows=val)

    return {
        "year": year,
        "n_matches": len(target),
        "val_matches": len(val),
        "variants": variants_out,
    }


def format_table(result: dict) -> str:
    """Human-readable metrics table, mirroring pipeline/tune_model.py's log
    lines. Used by pipeline/run_experiments.py and pipeline/replay_wc26.py."""
    lines = [f"World Cup {result['year']} ({result['n_matches']} matches)"]
    for name, m in result["variants"].items():
        lines.append(
            f"  {name:<16} log_loss={m['log_loss']:.4f} brier={m['brier']:.4f} "
            f"acc={m['accuracy']:.3f} ece={m['ece']:.4f} n={m['n']}"
        )
    return "\n".join(lines)
