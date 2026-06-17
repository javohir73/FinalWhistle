"""Large-sample walk-forward model evaluation (read-only experiment).

The shipped tuner (pipeline/tune_model.py) judges candidate models on only the
2014/2018/2022 World Cups — ~190 matches, far too few to detect a real effect, so
every lever has historically been rejected for "no reliable gain". This script
widens the out-of-sample holdout to EVERY major international tournament final
(World Cup, Euro, Copa América, AFCON, Asian Cup, Gold Cup, Confederations Cup)
since a cutoff year, ~20x the matches, and scores candidates with proper metrics
(log-loss, Brier, RPS, exact-score NLL, top-k scoreline hit, ECE) plus a paired
bootstrap CI of each candidate's per-match delta vs the served v0.1 model.

Leak-free by construction: Elo pre-match ratings reflect only earlier matches,
and any per-candidate tuning happens on the 2-year window BEFORE each tournament,
never on the tournament being scored.

Read-only: no DB writes, no model files written. It only prints a report.

Usage:
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_model_eval [--since YEAR] [--boot N]
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict

import numpy as np

from ml.evaluation.calibration import calibrate, fit_temperature, fit_vector_scaling
from ml.evaluation.scoreline_metrics import (
    exact_score_nll,
    expected_calibration_error,
    expected_calibration_error_equal_count,
    per_class_calibration_error,
    ranked_probability_score,
    top_k_scoreline_hit,
)
from ml.evaluation.tune import tune_params, validation_window, MIN_VAL_MATCHES
from ml.models.baseline_logistic import result_label
from ml.models.params import DEFAULT_PARAMS, ModelParams
from ml.models.poisson import (
    expected_goals_from_elo,
    outcome_probabilities,
    score_matrix,
)

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15

# Tournament FINALS most like the World Cup (neutral/host-venue, strong fields).
# Qualifiers are excluded (home/away, a different regime).
_MAJOR_FINALS = (
    "fifa world cup",
    "uefa euro",
    "copa américa",
    "copa america",
    "african cup of nations",
    "afc asian cup",
    "gold cup",
    "confederations cup",
)


def is_major_final(competition: str | None) -> bool:
    c = (competition or "").lower()
    if "qualif" in c:
        return False
    return any(k in c for k in _MAJOR_FINALS)


def block_bootstrap_ci(values, edition_keys, n_boot, rng, pct=(2.5, 97.5)):
    """Percentile CI of the mean of `values`, resampling whole tournament
    EDITIONS with replacement (cluster/block bootstrap). values[i] belongs to
    edition_keys[i]. Matches within an edition share context, so this gives an
    honest (wider) CI than IID match resampling. Returns (lo, hi)."""
    vals = np.asarray(values, dtype=float)
    groups: dict = defaultdict(list)
    for i, k in enumerate(edition_keys):
        groups[k].append(i)
    blocks = [np.asarray(ix) for ix in groups.values()]
    n_ed = len(blocks)
    if n_ed == 0:
        return (0.0, 0.0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        chosen = rng.integers(0, n_ed, size=n_ed)
        idx = np.concatenate([blocks[c] for c in chosen])
        means[b] = vals[idx].mean()
    lo, hi = pct
    return float(np.percentile(means, lo)), float(np.percentile(means, hi))


def tournament_editions(rows: list[dict], since_year: int) -> list[tuple[str, int, list[dict]]]:
    """Group major-tournament-final rows into (competition, year) editions."""
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        if is_major_final(r["competition"]) and r["date"].year >= since_year:
            groups[(r["competition"], r["date"].year)].append(r)
    out = [(comp, year, ms) for (comp, year), ms in groups.items() if len(ms) >= 4]
    out.sort(key=lambda e: (e[1], e[0]))
    return out


# --- per-match scoring -------------------------------------------------------

def wdl_and_grid(pre_home, pre_away, is_neutral, params: ModelParams, gamma: float = 0.0):
    """Return (wdl_triple, normalized_grid) for one match under given params.

    gamma > 0 applies a close-match draw-inflation: diagonal (draw) cells are
    multiplied by exp(gamma * closeness), where closeness decays with the Elo gap,
    then the grid is renormalized (Codex's sharper alternative to global Dixon-Coles).
    """
    adv = 0.0 if is_neutral else params.home_adv
    lam_h, lam_a = expected_goals_from_elo(pre_home, pre_away, adv, params.base, params.beta)
    grid = score_matrix(lam_h, lam_a, rho=params.rho)
    if gamma > 0.0:
        diff = (pre_home + adv) - pre_away
        closeness = math.exp(-abs(diff) / 100.0)  # 1 at parity, ~0.37 at a 100-Elo gap
        factor = math.exp(gamma * closeness)
        grid = [
            [c * factor if h == a else c for a, c in enumerate(row)]
            for h, row in enumerate(grid)
        ]
    wdl = outcome_probabilities(grid)
    wdl = calibrate(wdl, params.calibrator, params.temperature)
    return wdl, grid


def _val_logloss(val_rows, params, gamma=0.0):
    total = 0.0
    n = len(val_rows) or 1
    for r in val_rows:
        idx = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
        wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], params, gamma)
        total -= math.log(max(_EPS, min(1 - _EPS, wdl[idx])))
    return total / n


# --- candidates: each maps (val_rows) -> a per-match scorer ------------------

_TEMP_GRID = [round(0.8 + 0.05 * i, 2) for i in range(0, 25)]  # 0.80 .. 2.00
_GAMMA_GRID = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.45]


def candidate_v1(_val):
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS)


def candidate_v2_full_tune(val):
    params = tune_params(val) if val else DEFAULT_PARAMS
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], params)


def candidate_temperature_only(val):
    # Keep v0.1 goals params; fit only the calibration temperature on the window.
    if val:
        probs = [wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS)[0] for r in val]
        labels = [_LABEL_INDEX[result_label(r["score_home"], r["score_away"])] for r in val]
        t = fit_temperature(probs, labels)
    else:
        t = 1.0
    params = ModelParams(version="v1+temp", base=DEFAULT_PARAMS.base, beta=DEFAULT_PARAMS.beta,
                         home_adv=DEFAULT_PARAMS.home_adv, rho=DEFAULT_PARAMS.rho, temperature=t)
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], params)


def candidate_vector_scaling(val):
    # Keep v0.1 goals params; fit a vector-scaling calibrator (T + per-class bias)
    # on the window — the lever that can lift the under-predicted draw class.
    if val:
        probs = [wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS)[0] for r in val]
        labels = [_LABEL_INDEX[result_label(r["score_home"], r["score_away"])] for r in val]
        t, b = fit_vector_scaling(probs, labels)
        calibrator = {"method": "vector_scaling", "t": t, "b": list(b)}
    else:
        calibrator = None
    params = ModelParams(version="v1+vecscale", base=DEFAULT_PARAMS.base, beta=DEFAULT_PARAMS.beta,
                         home_adv=DEFAULT_PARAMS.home_adv, rho=DEFAULT_PARAMS.rho,
                         temperature=1.0, calibrator=calibrator)
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], params)


def candidate_draw_inflation(val):
    # Tune a single close-match draw-inflation gamma on the window (min val log-loss).
    best_g, best_ll = 0.0, float("inf")
    for g in _GAMMA_GRID:
        ll = _val_logloss(val, DEFAULT_PARAMS, gamma=g) if val else float("inf")
        if ll < best_ll:
            best_ll, best_g = ll, g
    return lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS, gamma=best_g)


CANDIDATES = {
    "v0.1 (served)": candidate_v1,
    "v0.2 (full tune)": candidate_v2_full_tune,
    "v0.1+temperature": candidate_temperature_only,
    "v0.1+draw-inflation": candidate_draw_inflation,
    "v0.1+vector-scaling": candidate_vector_scaling,
}


# --- run ---------------------------------------------------------------------

def run(rows: list[dict], since_year: int, n_boot: int, val_days: int = 730) -> dict:
    editions = tournament_editions(rows, since_year)
    # Per-candidate pooled per-match records.
    pooled: dict[str, dict] = {
        name: {"ll": [], "rps": [], "brier": [], "esnll": [], "top1": [], "top3": [],
               "top5": [], "wdl": [], "labels": []}
        for name in CANDIDATES
    }
    edition_count = 0
    match_count = 0
    edition_keys: list[tuple] = []  # (comp, year) per pooled match, index-aligned
    elo_gaps: list[float] = []  # |pre_home - pre_away| per pooled match

    for comp, year, target in editions:
        first_date = min(r["date"] for r in target)
        val = validation_window(rows, first_date, days=val_days)
        if len(val) < MIN_VAL_MATCHES:  # underpowered window; skip (matches tune guard)
            continue
        edition_count += 1
        match_count += len(target)
        scorers = {name: fn(val) for name, fn in CANDIDATES.items()}
        for r in target:
            label = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
            sh, sa = r["score_home"], r["score_away"]
            edition_keys.append((comp, year))
            elo_gaps.append(abs(r["pre_home"] - r["pre_away"]))
            for name, scorer in scorers.items():
                wdl, grid = scorer(r)
                p = pooled[name]
                p["ll"].append(-math.log(max(_EPS, min(1 - _EPS, wdl[label]))))
                p["rps"].append(ranked_probability_score(wdl, label))
                p["brier"].append(sum((wdl[k] - (1.0 if k == label else 0.0)) ** 2 for k in range(3)))
                p["esnll"].append(exact_score_nll(grid, sh, sa))
                p["top1"].append(1.0 if top_k_scoreline_hit(grid, sh, sa, 1) else 0.0)
                p["top3"].append(1.0 if top_k_scoreline_hit(grid, sh, sa, 3) else 0.0)
                p["top5"].append(1.0 if top_k_scoreline_hit(grid, sh, sa, 5) else 0.0)
                p["wdl"].append(wdl)
                p["labels"].append(label)

    rng = np.random.default_rng(2026)

    def summarize(name: str) -> dict:
        p = pooled[name]
        ll = np.array(p["ll"]); rps = np.array(p["rps"])
        out = {
            "n": len(p["ll"]),
            "log_loss": float(ll.mean()),
            "rps": float(rps.mean()),
            "brier": float(np.mean(p["brier"])),
            "exact_nll": float(np.mean(p["esnll"])),
            "top1": float(np.mean(p["top1"])),
            "top3": float(np.mean(p["top3"])),
            "top5": float(np.mean(p["top5"])),
            "ece": expected_calibration_error(p["wdl"], p["labels"], bins=10),
            "per_class": per_class_calibration_error(p["wdl"], p["labels"], bins=10),
        }
        return out

    base_ll = np.array(pooled["v0.1 (served)"]["ll"])
    base_rps = np.array(pooled["v0.1 (served)"]["rps"])

    base_esnll = np.array(pooled["v0.1 (served)"]["esnll"])
    base_top5 = np.array(pooled["v0.1 (served)"]["top5"])

    def bootstrap_delta(name: str) -> dict:
        # Paired per-match delta (candidate - v0.1); negative = candidate better
        # for losses (ll/rps/esnll), positive = better for hit-rates (top5).
        cand_ll = np.array(pooled[name]["ll"]); cand_rps = np.array(pooled[name]["rps"])
        cand_es = np.array(pooled[name]["esnll"]); cand_t5 = np.array(pooled[name]["top5"])
        d_ll = cand_ll - base_ll; d_rps = cand_rps - base_rps
        d_es = cand_es - base_esnll; d_t5 = cand_t5 - base_top5
        n = len(d_ll)
        if n == 0:
            return {}
        return {
            "d_log_loss": float(d_ll.mean()),
            "ll_ci": block_bootstrap_ci(d_ll, edition_keys, n_boot, rng),
            "d_rps": float(d_rps.mean()),
            "rps_ci": block_bootstrap_ci(d_rps, edition_keys, n_boot, rng),
            "d_exact_nll": float(d_es.mean()),
            "es_ci": block_bootstrap_ci(d_es, edition_keys, n_boot, rng),
            "d_top5": float(d_t5.mean()),
            "t5_ci": block_bootstrap_ci(d_t5, edition_keys, n_boot, rng),
        }

    def segment_report() -> dict:
        served = pooled["v0.1 (served)"]
        ll = served["ll"]; wdl = served["wdl"]; labels = served["labels"]

        def cell(idxs: list[int]) -> dict:
            if not idxs:
                return {"n": 0, "log_loss": 0.0, "ece": 0.0}
            return {
                "n": len(idxs),
                "log_loss": float(np.mean([ll[i] for i in idxs])),
                "ece": expected_calibration_error_equal_count(
                    [wdl[i] for i in idxs], [labels[i] for i in idxs], bins=5),
            }

        by_edition: dict = defaultdict(list)
        for i, k in enumerate(edition_keys):
            by_edition[k].append(i)

        gap_buckets = {"0-50": [], "50-150": [], "150-300": [], "300+": []}
        for i, g in enumerate(elo_gaps):
            key = "0-50" if g < 50 else "50-150" if g < 150 else "150-300" if g < 300 else "300+"
            gap_buckets[key].append(i)

        dvd = {"draw": [], "decisive": []}
        for i, lab in enumerate(labels):
            dvd["draw" if lab == 1 else "decisive"].append(i)

        return {
            "by_edition": {f"{c} {y}": cell(ix) for (c, y), ix in by_edition.items()},
            "by_favorite_gap": {k: cell(ix) for k, ix in gap_buckets.items()},
            "draw_vs_decisive": {k: cell(ix) for k, ix in dvd.items()},
        }

    return {
        "editions": edition_count,
        "matches": match_count,
        "summary": {name: summarize(name) for name in CANDIDATES},
        "bootstrap": {name: bootstrap_delta(name) for name in CANDIDATES if name != "v0.1 (served)"},
        "segments": segment_report(),
    }


def run_global_split(rows: list[dict], train_lo: int, train_hi: int, test_since: int,
                     n_boot: int) -> dict:
    """Fit ONE shippable global param set on [train_lo, train_hi] major-tournament
    finals, then test v0.1 vs that global v0.2 on test_since+ editions.

    This is the honest "can we ship a fixed model that beats v0.1 out-of-sample?"
    test — the per-edition walk-forward shows the tuning ceiling, but production
    needs a single param set.
    """
    train = [r for r in rows if is_major_final(r["competition"]) and train_lo <= r["date"].year <= train_hi]
    test = [r for r in rows if is_major_final(r["competition"]) and r["date"].year >= test_since]
    global_params = tune_params(train, version="poisson-elo-v0.2")

    def metrics_for(scorer) -> tuple[dict, dict]:
        rec = {"ll": [], "rps": [], "esnll": [], "top5": [], "wdl": [], "labels": [], "ed": []}
        for r in test:
            label = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
            wdl, grid = scorer(r)
            rec["ll"].append(-math.log(max(_EPS, min(1 - _EPS, wdl[label]))))
            rec["rps"].append(ranked_probability_score(wdl, label))
            rec["esnll"].append(exact_score_nll(grid, r["score_home"], r["score_away"]))
            rec["top5"].append(1.0 if top_k_scoreline_hit(grid, r["score_home"], r["score_away"], 5) else 0.0)
            rec["wdl"].append(wdl); rec["labels"].append(label)
            rec["ed"].append((r["competition"], r["date"].year))
        summ = {
            "log_loss": float(np.mean(rec["ll"])), "rps": float(np.mean(rec["rps"])),
            "exact_nll": float(np.mean(rec["esnll"])), "top5": float(np.mean(rec["top5"])),
            "ece": expected_calibration_error(rec["wdl"], rec["labels"], bins=10),
        }
        return summ, rec

    v1_s, v1_r = metrics_for(lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], DEFAULT_PARAMS))
    v2_s, v2_r = metrics_for(lambda r: wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], global_params))

    rng = np.random.default_rng(7)
    _REC_KEY = {"log_loss": "ll", "rps": "rps", "exact_nll": "esnll", "top5": "top5"}

    def ci(metric):
        rk = _REC_KEY[metric]
        d = np.array(v2_r[rk]) - np.array(v1_r[rk])
        return float(d.mean()), block_bootstrap_ci(d, v1_r["ed"], n_boot, rng)

    return {
        "global_params": global_params.to_dict(),
        "train_n": len(train), "test_n": len(test),
        "v1": v1_s, "v2": v2_s,
        "delta": {k: ci(k) for k in ("log_loss", "rps", "exact_nll", "top5")},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2004)
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()

    from app.db import SessionLocal
    from pipeline.backtest_data import build_enriched_rows

    db = SessionLocal()
    rows = build_enriched_rows(db)
    db.close()
    print(f"Replayed {len(rows)} historical matches (leak-free pre-match Elo).")

    res = run(rows, since_year=args.since, n_boot=args.boot)
    print(f"\nHold-out: {res['matches']} matches across {res['editions']} major-tournament "
          f"editions since {args.since}.\n")

    hdr = f"{'candidate':22s} {'logloss':>8s} {'RPS':>7s} {'brier':>7s} {'exactNLL':>9s} {'top1':>6s} {'top3':>6s} {'top5':>6s} {'ECE':>6s}"
    print(hdr); print("-" * len(hdr))
    for name, m in res["summary"].items():
        print(f"{name:22s} {m['log_loss']:8.4f} {m['rps']:7.4f} {m['brier']:7.4f} "
              f"{m['exact_nll']:9.4f} {m['top1']:6.3f} {m['top3']:6.3f} {m['top5']:6.3f} {m['ece']:6.3f}")

    def verdict(ci, better_is_lower=True):
        lo, hi = ci
        if better_is_lower:
            return "BETTER" if hi < 0 else ("worse" if lo > 0 else "ns")
        return "BETTER" if lo > 0 else ("worse" if hi < 0 else "ns")

    print("\nPer-class ECE (home / draw / away) — draw is the known pathology:")
    for name, m in res["summary"].items():
        pc = m["per_class"]
        print(f"  {name:22s} home={pc['home']:.4f} draw={pc['draw']:.4f} away={pc['away']:.4f}")

    print("\nPaired bootstrap vs v0.1 (CI excluding 0 = significant):")
    for name, b in res["bootstrap"].items():
        if not b:
            continue
        print(f"  {name}")
        print(f"     W/D/L  logloss d={b['d_log_loss']:+.4f} CI[{b['ll_ci'][0]:+.4f},{b['ll_ci'][1]:+.4f}] {verdict(b['ll_ci'])}"
              f"   RPS d={b['d_rps']:+.4f} CI[{b['rps_ci'][0]:+.4f},{b['rps_ci'][1]:+.4f}] {verdict(b['rps_ci'])}")
        print(f"     SCORE  exactNLL d={b['d_exact_nll']:+.4f} CI[{b['es_ci'][0]:+.4f},{b['es_ci'][1]:+.4f}] {verdict(b['es_ci'])}"
              f"   top5 d={b['d_top5']:+.4f} CI[{b['t5_ci'][0]:+.4f},{b['t5_ci'][1]:+.4f}] {verdict(b['t5_ci'], better_is_lower=False)}")

    print("\nCalibration by segment (served v0.1 — n / log_loss / ece):")
    for group, table in res["segments"].items():
        print(f"  {group}:")
        for seg, cell in table.items():
            print(f"    {seg:<14} n={cell['n']:<5} ll={cell['log_loss']:.4f} ece={cell['ece']:.4f}")

    # Shippable global split: one fixed param set, honest out-of-sample test.
    print("\n==== Shippable global v0.2 (fit on 2004-2017, tested on 2018+ finals) ====")
    g = run_global_split(rows, 2004, 2017, 2018, n_boot=args.boot)
    print(f"  global params: {g['global_params']}")
    print(f"  train matches: {g['train_n']}   test matches: {g['test_n']}")
    print(f"  {'metric':10s} {'v0.1':>9s} {'v0.2-global':>12s} {'delta':>9s}  CI / verdict")
    for k, lower in (("log_loss", True), ("rps", True), ("exact_nll", True), ("top5", False)):
        d, c = g["delta"][k]
        print(f"  {k:10s} {g['v1'][k]:9.4f} {g['v2'][k]:12.4f} {d:+9.4f}  "
              f"CI[{c[0]:+.4f},{c[1]:+.4f}] {verdict(c, better_is_lower=lower)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
