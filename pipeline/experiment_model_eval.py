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
    # pick-policy gate only (FR-3.1, fast — skips the model-candidate sections):
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_model_eval --pick-only
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import replace
from datetime import date

import numpy as np

from ml.evaluation.calibration import (
    calibrate, effective_gap, fit_segmented_vector_scaling, fit_temperature,
    fit_vector_scaling, gap_bucket,
)
from ml.features.training_rows import _as_date, build_training_rows, training_weight
from ml.models.wdl_boost import WdlBoost, blend_triples
from ml.evaluation.scoreline_metrics import (
    exact_score_nll,
    expected_calibration_error,
    expected_calibration_error_equal_count,
    per_class_calibration_error,
    ranked_probability_score,
    top_k_scoreline_hit,
    production_scoreline_pick,
)
from ml.evaluation.empirical_prior import EmpiricalScorePrior
from ml.evaluation.tune import tune_params, validation_window, MIN_VAL_MATCHES
from ml.models.baseline_logistic import result_label
from ml.models.params import DEFAULT_PARAMS, ModelParams, load_params
from ml.models.poisson import (
    expected_goals_from_elo,
    most_likely_score,
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

def _eval_adv(is_neutral: bool, params: ModelParams) -> float:
    """The home advantage the eval engine applies — 0 at a neutral site, else the
    params' home_adv. Single source so bucketing matches the engine exactly."""
    return 0.0 if is_neutral else params.home_adv


def wdl_and_grid(pre_home, pre_away, is_neutral, params: ModelParams, gamma: float = 0.0):
    """Return (wdl_triple, normalized_grid) for one match under given params.

    gamma > 0 applies a close-match draw-inflation: diagonal (draw) cells are
    multiplied by exp(gamma * closeness), where closeness decays with the Elo gap,
    then the grid is renormalized (Codex's sharper alternative to global Dixon-Coles).
    """
    adv = _eval_adv(is_neutral, params)
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
    eff_gap = effective_gap(pre_home, pre_away, adv)
    wdl = calibrate(wdl, params.calibrator, params.temperature, eff_gap=eff_gap)
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


# --- pick-policy candidates (FR-3.1): same engine, different picks -----------
#
# Same factory pattern as CANDIDATES, one level down: the model (grid + W/D/L
# triple) is the served engine for EVERY candidate; only the scoreline pick
# moves, so top1 is the sole metric that can differ. Each factory maps
# (history, first_date, history_flags) -> picker(r, grid, wdl, is_knockout) ->
# (h, a), where `history` is every enriched row strictly before the edition
# being scored, `first_date` is the edition's first match date — empirical fits
# re-filter at that cutoff inside EmpiricalScorePrior.fit, so a careless caller
# cannot leak — and `history_flags` are index-aligned group/knockout labels
# computed on COMPLETE editions (see history_with_flags), because re-inferring
# stages from a date-truncated history mislabels concurrent editions.

_PICK_CONTROL = "control (production rule)"


def pick_control(history, first_date, history_flags=None):
    # The rule production publishes (FR-2.5 parity) — the gate's baseline.
    return lambda r, grid, wdl, is_ko: production_scoreline_pick(grid, wdl[0], wdl[1], wdl[2])


def pick_unrestricted_argmax(history, first_date, history_flags=None):
    def pick(r, grid, wdl, is_ko):
        sh, sa, _ = most_likely_score(grid)
        return sh, sa
    return pick


def make_band_pick(band: float):
    """Production rule with a wider coin-flip band than DRAW_HEADLINE_BAND."""
    def factory(history, first_date, history_flags=None):
        def pick(r, grid, wdl, is_ko):
            p_home, _, p_away = wdl
            if abs(p_home - p_away) <= band:
                sh, sa, _ = most_likely_score(grid)
            else:
                sh, sa, _ = most_likely_score(grid, "home" if p_home > p_away else "away")
            return sh, sa
        return pick
    return factory


def blend_pick(grid, prior: EmpiricalScorePrior, gap: float, home_is_favorite: bool,
               w: float) -> tuple[int, int]:
    """argmax_s [(1-w)·P_grid(s) + w·F_empirical(s | gap bucket)] over the grid.

    The grid is normalized first (truncated Poisson mass sums slightly under 1).
    Empirical cells are favorite-oriented, so they are transposed for an
    away-favorite match. An unpopulated bucket contributes 0 everywhere, which
    degrades gracefully to the unrestricted grid argmax."""
    total = sum(sum(row) for row in grid)
    best_h = best_a = 0
    best_v = -1.0
    for h, row in enumerate(grid):
        for a, cell in enumerate(row):
            p_grid = cell / total if total > 0 else 0.0
            fav, dog = (h, a) if home_is_favorite else (a, h)
            v = (1.0 - w) * p_grid + w * prior.prob(gap, fav, dog)
            if v > best_v:
                best_v, best_h, best_a = v, h, a
    return best_h, best_a


def make_empirical_pick(w: float):
    """Empirical prior blend (FR-3.1d): one frequency table per Elo-gap bucket."""
    def factory(history, first_date, history_flags=None):
        prior = EmpiricalScorePrior().fit(history, before=first_date)

        def pick(r, grid, wdl, is_ko):
            gap = abs(r["pre_home"] - r["pre_away"])
            return blend_pick(grid, prior, gap, r["pre_home"] >= r["pre_away"], w)
        return pick
    return factory


def make_stage_pick(w: float):
    """Stage-conditional blend (FR-3.1e): separate group/knockout tables.

    Stage labels come from `history_flags` (complete-edition labels, see
    history_with_flags) when supplied. The knockout_flags(history) fallback is
    only safe when every edition in `history` is fully played — on a
    date-truncated history it would mislabel the trailing group matches of
    still-running concurrent editions as knockout."""
    def factory(history, first_date, history_flags=None):
        flags = history_flags if history_flags is not None else knockout_flags(history)
        priors = {
            ko: EmpiricalScorePrior().fit(
                [r for r, f in zip(history, flags) if f == ko], before=first_date)
            for ko in (False, True)
        }

        def pick(r, grid, wdl, is_ko):
            gap = abs(r["pre_home"] - r["pre_away"])
            return blend_pick(grid, priors[is_ko], gap, r["pre_home"] >= r["pre_away"], w)
        return pick
    return factory


PICK_CANDIDATES = {
    _PICK_CONTROL: pick_control,
    "unrestricted argmax": pick_unrestricted_argmax,
    "band 0.15": make_band_pick(0.15),
    "band 0.20": make_band_pick(0.20),
    "band 0.25": make_band_pick(0.25),
    "empirical w=0.1": make_empirical_pick(0.1),
    "empirical w=0.2": make_empirical_pick(0.2),
    "empirical w=0.3": make_empirical_pick(0.3),
    "stage empirical w=0.1": make_stage_pick(0.1),
    "stage empirical w=0.2": make_stage_pick(0.2),
    "stage empirical w=0.3": make_stage_pick(0.3),
}


def _ko_team_count(n_teams: int) -> int:
    """Knockout-round field size: the largest power of two no bigger than 2/3 of
    the entrants — 32→16, 24→16, 16→8, 8→4 (the modern seeded formats)."""
    k = 1
    while k * 2 <= (2 * n_teams) // 3:
        k *= 2
    return k


def knockout_flags(rows: list[dict]) -> list[bool]:
    """Heuristic group-vs-knockout labels for enriched rows, index-aligned.

    historical_matches carries no stage column, so we infer: within each
    major-final edition, the LAST k matches by date are the knockout stage,
    where k = _ko_team_count(distinct teams) — the bracket's k-1 games plus
    roughly one third-place match. Editions with odd legacy formats get a few
    mislabels; acceptable noise for a frequency prior. Non-major rows
    (friendlies, qualifiers) are never knockout.

    The rule assumes every edition in `rows` is COMPLETE. Never apply it to a
    date-truncated history: an edition still underway at the cutoff (summer
    tournaments overlap — Euro/Copa 2016, 2021, 2024, the 2019 Copa/Gold
    Cup/AFCON triple) looks like a tiny finished edition and its trailing GROUP
    matches get flagged as knockout. Truncating callers must label the full row
    set first and slice after — that is history_with_flags below."""
    flags = [False] * len(rows)
    editions: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        if is_major_final(r["competition"]):
            editions[(r["competition"], _as_date(r["date"]).year)].append(i)
    for idxs in editions.values():
        teams = {rows[i]["home_id"] for i in idxs} | {rows[i]["away_id"] for i in idxs}
        n_ko = min(len(idxs), _ko_team_count(len(teams)))
        ordered = sorted(idxs, key=lambda i: (_as_date(rows[i]["date"]), i))
        for i in ordered[len(ordered) - n_ko:]:
            flags[i] = True
    return flags


def history_with_flags(rows: list[dict], first_date) -> tuple[list[dict], list[bool]]:
    """Rows strictly before `first_date`, with index-aligned stage flags computed
    on the FULL row set — never on the truncated slice.

    Labeling before truncating matters: a concurrent edition still underway at
    the cutoff (Euro 2024 when Copa América 2024 kicks off, the 2019 and 2021
    summer overlaps) would look to knockout_flags like a tiny complete edition,
    and its trailing GROUP matches would be mislabeled as knockout. Computing
    flags on complete editions leaks no results — which matches are group vs
    knockout is fixture knowledge, public before a ball is kicked — and the
    returned history still contains only pre-cutoff rows."""
    cutoff = _as_date(first_date)
    flags = knockout_flags(rows)
    pairs = [(r, f) for r, f in zip(rows, flags) if _as_date(r["date"]) < cutoff]
    return [r for r, _ in pairs], [f for _, f in pairs]


# --- run ---------------------------------------------------------------------

def run(rows: list[dict], since_year: int, n_boot: int, val_days: int = 730) -> dict:
    editions = tournament_editions(rows, since_year)
    # Per-candidate pooled per-match records.
    pooled: dict[str, dict] = {
        name: {"ll": [], "rps": [], "brier": [], "esnll": [], "top1": [], "top1_unrestricted": [], "top3": [],
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
                # top1 = the PRODUCTION pick rule (band + outcome restriction):
                # the direct offline proxy for the public exact_score_hits.
                pick = production_scoreline_pick(grid, wdl[0], wdl[1], wdl[2])
                p["top1"].append(1.0 if pick == (sh, sa) else 0.0)
                p["top1_unrestricted"].append(1.0 if top_k_scoreline_hit(grid, sh, sa, 1) else 0.0)
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
            "top1_unrestricted": float(np.mean(p["top1_unrestricted"])),
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


def run_blend_gate(rows: list[dict], train_lo: int = 2004, tail_years: int = 2,
                   test_since: int = 2018, n_boot: int = 2000,
                   served_params: ModelParams | None = None) -> dict:
    """Honest ship test for the booster blend.

    1. Train ONE booster on leak-free history in [train_lo, test_since) minus a
       held-out tail (recency + competition-tier weighted).
    2. Fit the blend weight on the tail (the `tail_years` before the test cutoff),
       minimizing log-loss; fit a vector-scaling calibrator on the blended tail probs.
    3. Score blend vs Poisson-alone on test_since+ major finals with the
       edition-clustered bootstrap. Promote only if the log-loss CI excludes 0
       (better).

    The Poisson leg uses the params actually served (load_params(), i.e. the tuned
    model_params.json), not the v0.1 DEFAULT_PARAMS constant — otherwise the gate
    would measure the booster's lift against an engine we no longer ship. Pass
    `served_params` to score against a specific engine (used by tests).
    """
    feat_rows = build_training_rows(rows)
    test_start = date(test_since, 1, 1)
    tail_start = date(test_since - tail_years, 1, 1)

    train = [r for r in feat_rows if train_lo <= r["date"].year and r["date"] < tail_start]
    tail = [r for r in feat_rows if tail_start <= r["date"] < test_start]
    test = [r for r in feat_rows
            if r["date"].year >= test_since and is_major_final(r["competition"])]

    ref = max((r["date"] for r in train), default=test_start)
    weights = [training_weight(r, ref) for r in train]
    booster = WdlBoost().fit(train, sample_weight=weights)

    served = served_params if served_params is not None else load_params()

    def poisson_triple(fr: dict) -> tuple:
        # feat["is_neutral"] is 1.0 (neutral → adv 0) or 0.0 (home side → adv applies). Correct.
        return wdl_and_grid(fr["pre_home"], fr["pre_away"], fr["is_neutral"], served)[0]

    def boost_triple(fr: dict) -> tuple:
        b = booster.predict_proba(fr)   # fr has every FEATURE_NAMES key; extras ignored
        return (b["H"], b["D"], b["A"])

    # Precompute (poisson, boost, label_idx) for the tail once, then grid-search w.
    tail_pb = [(poisson_triple(fr), boost_triple(fr), _LABEL_INDEX[fr["label"]]) for fr in tail]

    def ll_for_weight(w: float) -> float:
        if not tail_pb:
            return float("inf")
        s = 0.0
        for pz, bz, idx in tail_pb:
            tri = blend_triples(pz, bz, w)
            s -= math.log(max(_EPS, min(1 - _EPS, tri[idx])))
        return s / len(tail_pb)

    weight = min((i / 20 for i in range(21)), key=ll_for_weight)  # grid 0.0..1.0 step .05

    if tail_pb:
        blended_tail = [blend_triples(pz, bz, weight) for pz, bz, _ in tail_pb]
        labels_tail = [idx for _, _, idx in tail_pb]
        t, b = fit_vector_scaling(blended_tail, labels_tail)
        calibrator = {"method": "vector_scaling", "t": t, "b": list(b)}
    else:
        calibrator = None

    base_ll, blend_ll, ed_keys = [], [], []
    for fr in test:
        idx = _LABEL_INDEX[fr["label"]]
        pz = poisson_triple(fr)
        tri = calibrate(blend_triples(pz, boost_triple(fr), weight), calibrator)
        base_ll.append(-math.log(max(_EPS, min(1 - _EPS, pz[idx]))))
        blend_ll.append(-math.log(max(_EPS, min(1 - _EPS, tri[idx]))))
        ed_keys.append((fr["competition"], fr["date"].year))

    rng = np.random.default_rng(2026)
    d_ll = np.array(blend_ll) - np.array(base_ll)
    ci = block_bootstrap_ci(d_ll, ed_keys, n_boot, rng) if len(d_ll) else (0.0, 0.0)

    return {
        "served_version": served.version,
        "weight": round(weight, 3),
        "calibrator": calibrator,
        "train_n": len(train), "tail_n": len(tail), "test_n": len(test),
        "base_log_loss": float(np.mean(base_ll)) if base_ll else 0.0,
        "blend_log_loss": float(np.mean(blend_ll)) if blend_ll else 0.0,
        "delta_log_loss": float(d_ll.mean()) if len(d_ll) else 0.0,
        "ll_ci": ci,
        "verdict": "SHIP" if (ci[1] < 0) else "do-not-ship",
    }


_RPS_TOL = 1e-4  # RPS may not get worse than this on the point estimate (do-no-harm guardrail)


def run_draw_cal_gate(rows: list[dict], tail_years: int = 2, test_since: int = 2018,
                      n_boot: int = 2000, min_bucket: int = 200,
                      served_params: ModelParams | None = None) -> dict:
    """Honest ship test for the segment-conditional draw calibrator.

    Fit per-effective-gap vector scaling on the held-out tail (all competitions,
    uncalibrated v0.2 triples — no calibrator stacking), then score the
    segmented-calibrated engine vs v0.2-alone on test_since+ major finals with the
    edition-clustered bootstrap. SHIP only if the log-loss CI excludes 0 (better)
    AND RPS does not regress beyond _RPS_TOL.
    """
    served = served_params if served_params is not None else load_params()
    # Also neutralize temperature: the segmented calibrate() path ignores scalar
    # temperature entirely (mutually-exclusive dispatch in calibrate()), so the fit
    # must use untempered (temperature=1.0) triples to match what the candidate
    # serves — otherwise a served engine with temperature != 1.0 would silently
    # skew fit vs serve.
    base_params = replace(served, calibrator=None, temperature=1.0)   # uncalibrated, untempered triples for FITTING

    test_start = date(test_since, 1, 1)
    tail_start = date(test_since - tail_years, 1, 1)
    tail = [r for r in rows if tail_start <= _as_date(r["date"]) < test_start]
    test = [r for r in rows
            if _as_date(r["date"]).year >= test_since and is_major_final(r["competition"])]

    # Fit on uncalibrated tail triples, bucketed by the same effective gap the
    # engine uses (via _eval_adv -> effective_gap), so fit and serve agree.
    tail_probs, tail_labels, tail_gaps = [], [], []
    bucket_counts: dict[str, int] = {b: 0 for b in ("0-50", "50-150", "150-300", "300+")}
    for r in tail:
        wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], base_params)
        g = effective_gap(r["pre_home"], r["pre_away"], _eval_adv(r["is_neutral"], base_params))
        tail_probs.append(wdl)
        tail_labels.append(_LABEL_INDEX[result_label(r["score_home"], r["score_away"])])
        tail_gaps.append(g)
        bucket_counts[gap_bucket(g)] += 1

    blob = (fit_segmented_vector_scaling(tail_probs, tail_labels, tail_gaps, min_bucket=min_bucket)
            if tail_probs else None)
    cand_params = replace(served, calibrator=blob)

    base_ll, cal_ll, base_rps, cal_rps, ed_keys = [], [], [], [], []
    for r in test:
        idx = _LABEL_INDEX[result_label(r["score_home"], r["score_away"])]
        b_wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], served)
        c_wdl, _ = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], cand_params)
        base_ll.append(-math.log(max(_EPS, min(1 - _EPS, b_wdl[idx]))))
        cal_ll.append(-math.log(max(_EPS, min(1 - _EPS, c_wdl[idx]))))
        base_rps.append(ranked_probability_score(b_wdl, idx))
        cal_rps.append(ranked_probability_score(c_wdl, idx))
        ed_keys.append((r["competition"], r["date"].year))

    rng = np.random.default_rng(2026)
    d_ll = np.array(cal_ll) - np.array(base_ll)
    ci = block_bootstrap_ci(d_ll, ed_keys, n_boot, rng) if len(d_ll) else (0.0, 0.0)
    d_rps = float(np.mean(cal_rps) - np.mean(base_rps)) if cal_rps else 0.0

    ship = bool(len(d_ll) and ci[1] < 0 and d_rps <= _RPS_TOL)
    return {
        "served_version": served.version,
        "calibrator": blob,
        "tail_n": len(tail), "test_n": len(test),
        "bucket_counts": bucket_counts,
        "base_log_loss": float(np.mean(base_ll)) if base_ll else 0.0,
        "cal_log_loss": float(np.mean(cal_ll)) if cal_ll else 0.0,
        "delta_log_loss": float(d_ll.mean()) if len(d_ll) else 0.0,
        "ll_ci": ci,
        "delta_rps": d_rps,
        "rps_tol": _RPS_TOL,
        "verdict": "SHIP" if ship else "do-not-ship",
    }


def run_pick_policy(rows: list[dict], since_year: int, n_boot: int, val_days: int = 730,
                    served_params: ModelParams | None = None) -> dict:
    """Walk-forward pick-policy gate (FR-3.1/3.2).

    Every candidate scores the SAME served-engine grid per match; only the pick
    differs, so the paired per-match top1 delta vs the production rule is pure
    pick-policy signal. Editions with an underpowered validation window are
    skipped with the same guard as run(), so the holdout is the identical match
    set and top1 numbers are directly comparable across harness sections.
    A candidate SHIPs only when its edition-clustered bootstrap CI on the top1
    delta excludes zero from below (lo > 0)."""
    served = served_params if served_params is not None else load_params()
    editions = tournament_editions(rows, since_year)
    hits: dict[str, list[float]] = {name: [] for name in PICK_CANDIDATES}
    edition_keys: list[tuple] = []
    edition_count = 0
    ko_count = 0

    for comp, year, target in editions:
        first_date = min(r["date"] for r in target)
        val = validation_window(rows, first_date, days=val_days)
        if len(val) < MIN_VAL_MATCHES:  # underpowered window; skip (matches run())
            continue
        edition_count += 1
        # Stage labels are computed on the FULL row set before truncation, so a
        # concurrent edition still underway at first_date keeps its true group
        # labels instead of masquerading as a tiny complete edition.
        history, history_flags = history_with_flags(rows, first_date)
        pickers = {name: fn(history, first_date, history_flags)
                   for name, fn in PICK_CANDIDATES.items()}
        target_flags = knockout_flags(target)
        for r, is_ko in zip(target, target_flags):
            wdl, grid = wdl_and_grid(r["pre_home"], r["pre_away"], r["is_neutral"], served)
            actual = (r["score_home"], r["score_away"])
            edition_keys.append((comp, year))
            ko_count += 1 if is_ko else 0
            for name, picker in pickers.items():
                hits[name].append(1.0 if picker(r, grid, wdl, is_ko) == actual else 0.0)

    control = np.array(hits[_PICK_CONTROL])
    rng = np.random.default_rng(2026)

    def bootstrap(name: str) -> dict:
        d = np.array(hits[name]) - control
        if len(d) == 0:
            return {"d_top1": 0.0, "t1_ci": (0.0, 0.0), "verdict": "ns"}
        lo, hi = block_bootstrap_ci(d, edition_keys, n_boot, rng)
        # top1 is a hit rate: higher is better, so SHIP needs the CI above zero.
        verdict = "SHIP" if lo > 0 else ("worse" if hi < 0 else "ns")
        return {"d_top1": float(d.mean()), "t1_ci": (lo, hi), "verdict": verdict}

    return {
        "served_version": served.version,
        "editions": edition_count,
        "matches": len(control),
        "ko_share": ko_count / len(control) if len(control) else 0.0,
        "top1": {name: float(np.mean(h)) if h else 0.0 for name, h in hits.items()},
        "bootstrap": {name: bootstrap(name) for name in PICK_CANDIDATES if name != _PICK_CONTROL},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2004)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--pick-only", action="store_true",
                    help="run only the pick-policy gate (skips the slow model-candidate sections)")
    args = ap.parse_args()

    from app.db import SessionLocal
    from pipeline.backtest_data import build_enriched_rows

    db = SessionLocal()
    rows = build_enriched_rows(db)
    db.close()
    print(f"Replayed {len(rows)} historical matches (leak-free pre-match Elo).")

    def pick_section() -> None:
        print("\n==== Pick-policy gate (FR-3.1/3.2) — same engine, different picks ====")
        pp = run_pick_policy(rows, since_year=args.since, n_boot=args.boot)
        print(f"  served={pp['served_version']}  {pp['matches']} matches / "
              f"{pp['editions']} editions  (knockout share {pp['ko_share']:.1%})")
        print(f"  {'policy':24s} {'top1':>7s} {'d_top1':>8s}  CI / verdict")
        print(f"  {_PICK_CONTROL:24s} {pp['top1'][_PICK_CONTROL]:7.4f} {'—':>8s}  (control)")
        for name, b in pp["bootstrap"].items():
            print(f"  {name:24s} {pp['top1'][name]:7.4f} {b['d_top1']:+8.4f}  "
                  f"CI[{b['t1_ci'][0]:+.4f},{b['t1_ci'][1]:+.4f}] {b['verdict']}")

    if args.pick_only:
        pick_section()
        return 0

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

    print("\n==== Booster blend gate (HistGradientBoosting) ====")
    bg = run_blend_gate(rows, n_boot=args.boot)
    print(f"  served={bg['served_version']}  weight={bg['weight']}  "
          f"train_n={bg['train_n']} tail_n={bg['tail_n']} test_n={bg['test_n']}")
    print(f"  base_logloss={bg['base_log_loss']:.4f}  blend_logloss={bg['blend_log_loss']:.4f}")
    print(f"  d_logloss={bg['delta_log_loss']:+.4f}  CI[{bg['ll_ci'][0]:+.4f},{bg['ll_ci'][1]:+.4f}]  -> {bg['verdict']}")
    if bg["verdict"] == "SHIP":
        # Valid JSON so it can be pasted straight into model_params.json's wdl_blend.
        blob = json.dumps({"weight": bg["weight"], "calibrator": bg["calibrator"]})
        print(f"  SHIP blob (paste into model_params.json -> wdl_blend): {blob}")

    pick_section()

    print("\n==== Segmented draw-calibration gate ====")
    dg = run_draw_cal_gate(rows, n_boot=args.boot)
    print(f"  served={dg['served_version']}  tail_n={dg['tail_n']} test_n={dg['test_n']}")
    print(f"  bucket_counts={dg['bucket_counts']}")
    print(f"  base_logloss={dg['base_log_loss']:.4f}  cal_logloss={dg['cal_log_loss']:.4f}")
    print(f"  d_logloss={dg['delta_log_loss']:+.4f}  CI[{dg['ll_ci'][0]:+.4f},{dg['ll_ci'][1]:+.4f}]"
          f"  d_rps={dg['delta_rps']:+.5f} (tol {dg['rps_tol']})  -> {dg['verdict']}")
    if dg["verdict"] == "SHIP":
        blob = json.dumps(dg["calibrator"])
        print(f"  SHIP blob (paste into model_params.json -> calibrator): {blob}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
