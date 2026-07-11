"""Origin walk-forward backtest + coordinate-descent tuner (design 2026-07-11).

DB-free: replays the committed seed file. One chronological walk (43 seasons,
3 games each — trivially small): for scored seasons, predict-before-update
(leak-free, same rule as ml/sports/nrl/backtest.py), applying regress_season
at season boundaries and the neutral flag on interstate venues.

The first seasons are burn-in (ratings still settling from the 1500 seed), so
scoring starts at `score_from` (default 1985). The tuner scores seasons >=
val_from only, giving a chronological train/validate split.

Retrodictions produced here NEVER enter the DB — the summary is written to
backtest_record.json (committed) and served as the labeled "backtest" segment
of /api/nrl/origin/record.

CLI: PYTHONPATH=backend:. python -m ml.sports.origin.backtest --tune --write
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from ml.sports.nrl.model import NrlParams, predict, regress_season, update
from ml.sports.origin.params import ORIGIN_DEFAULTS, save_origin_params
from ml.sports.origin.venues import model_is_neutral
from pipeline.sports.origin_names import TEAM_INDEX

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parents[3] / "data" / "raw" / "state_of_origin_history.json"
_RECORD_FILE = Path(__file__).with_name("backtest_record.json")
_EPS = 1e-15

_K_GRID = [2.0, 4.0, 8.0, 12.0, 24.0, 36.0, 48.0, 64.0]
_HOME_ADV_GRID = [10.0, 20.0, 30.0, 45.0, 65.0, 90.0, 100.0, 110.0, 116.0, 120.0, 130.0, 150.0]
_MARGIN_CAP_GRID = [1.8, 2.2, 2.6]
_SEASON_REGRESS_GRID = [0.0, 0.10, 0.25, 0.50]
_P_DRAW_GRID = [0.01, 0.0125, 0.0167, 0.02, 0.035]


def load_history(path: Path = SEED_FILE) -> dict[int, list[dict]]:
    """Seed file -> replay rows keyed by season (TEAM_INDEX ids, parsed
    kickoffs, neutral flags).

    Uses `model_is_neutral`, not `is_neutral` — the zero-home-advantage-at-
    neutral-venues hypothesis was tested and REFUTED (see venues.py); the
    model applies home_adv everywhere while the API still badges neutral
    venues via `is_neutral` as a display fact.
    """
    data = json.loads(path.read_text())
    history: dict[int, list[dict]] = {}
    for m in data["matches"]:
        history.setdefault(m["season"], []).append({
            "home_id": TEAM_INDEX[m["home_team"]],
            "away_id": TEAM_INDEX[m["away_team"]],
            "score_home": m["score_home"],
            "score_away": m["score_away"],
            "neutral": model_is_neutral(m["venue"]),
            "kickoff_utc": datetime.strptime(
                m["kickoff_utc"], "%Y-%m-%d %H:%M:%SZ"
            ).replace(tzinfo=timezone.utc),
        })
    return history


def _result_index(sh: int, sa: int) -> int:
    return 0 if sh > sa else 2 if sh < sa else 1


def _clamp(p: float) -> float:
    return max(_EPS, min(1 - _EPS, p))


def walk_forward(
    history: dict[int, list[dict]], params: NrlParams, score_from: int = 1985
) -> dict:
    """Chronological replay; seasons >= score_from are scored (model + an
    always-pick-the-designated-home-side baseline), earlier ones are burn-in.

    Also reports `home_prior_log_loss`: the log loss of a FIXED probability
    triple equal to the scored span's own outcome class frequencies
    (home/draw/away), applied to every scored game. This is a hindsight
    baseline — it peeks at the very outcomes it's scored against, so it is
    not a leak-free walk-forward number like the model's own avg_log_loss —
    but it's the standard reference point for "does the model add anything
    beyond just knowing the outcome distribution in hindsight."
    """
    running: dict[int, float] = {}
    ll_sum = brier_sum = 0.0
    correct = home_correct = n = 0
    idxs: list[int] = []
    first = True

    for season in sorted(history):
        if not first:
            running = regress_season(running, params)
        first = False
        for m in sorted(history[season], key=lambda x: x["kickoff_utc"]):
            elo_h = running.get(m["home_id"], 1500.0)
            elo_a = running.get(m["away_id"], 1500.0)
            if season >= score_from:
                out = predict(elo_h, elo_a, params, neutral=m["neutral"])
                probs = (out["p_home"], out["p_draw"], out["p_away"])
                idx = _result_index(m["score_home"], m["score_away"])
                ll_sum += -math.log(_clamp(probs[idx]))
                brier_sum += sum(
                    (p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs)
                )
                predicted = max(range(3), key=lambda i: (probs[i], -i))
                correct += int(predicted == idx)
                home_correct += int(idx == 0)
                idxs.append(idx)
                n += 1
            new_h, new_a = update(
                elo_h, elo_a, m["score_home"], m["score_away"], params,
                neutral=m["neutral"],
            )
            running[m["home_id"]] = new_h
            running[m["away_id"]] = new_a

    if n:
        counts = [0, 0, 0]
        for idx in idxs:
            counts[idx] += 1
        freqs = [c / n for c in counts]
        home_prior_ll = sum(-math.log(_clamp(freqs[idx])) for idx in idxs) / n
    else:
        home_prior_ll = float("nan")

    return {
        "n": n,
        "winner_accuracy": correct / n if n else float("nan"),
        "avg_log_loss": ll_sum / n if n else float("nan"),
        "avg_brier": brier_sum / n if n else float("nan"),
        "home_baseline_accuracy": home_correct / n if n else float("nan"),
        "home_prior_log_loss": home_prior_ll,
        "span": [score_from, max(history)] if history else [score_from, score_from],
    }


def tune(
    history: dict[int, list[dict]], val_from: int = 2015, grid: dict | None = None
) -> NrlParams:
    """Coordinate-descent the W/D/L-relevant knobs against validation log loss
    (all matches in seasons >= val_from), starting from ORIGIN_DEFAULTS. Two
    sweeps, same style as ml/sports/nrl/backtest.tune. margin_slope/sigma
    stay at defaults (they don't feed the 3-way objective)."""
    g = grid or {}
    grids = {
        "k": g.get("k", _K_GRID),
        "home_adv": g.get("home_adv", _HOME_ADV_GRID),
        "margin_mult_cap": g.get("margin_mult_cap", _MARGIN_CAP_GRID),
        "season_regress": g.get("season_regress", _SEASON_REGRESS_GRID),
        "p_draw": g.get("p_draw", _P_DRAW_GRID),
    }

    def val_logloss(p: NrlParams) -> float:
        return walk_forward(history, p, score_from=val_from)["avg_log_loss"]

    params = ORIGIN_DEFAULTS

    def best_on(field: str) -> float:
        best_v, best_ll = getattr(params, field), float("inf")
        for v in grids[field]:
            ll = val_logloss(replace(params, **{field: v}))
            if ll < best_ll:
                best_ll, best_v = ll, v
        return best_v

    for _ in range(2):
        for field in ("k", "home_adv", "margin_mult_cap", "season_regress", "p_draw"):
            params = replace(params, **{field: best_on(field)})

    return params


def load_backtest_record() -> dict | None:
    """The committed backtest artifact, or None if absent/corrupt."""
    try:
        return json.loads(_RECORD_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tune", action="store_true", help="fit params before reporting")
    ap.add_argument("--write", action="store_true",
                    help="write params.json + backtest_record.json")
    args = ap.parse_args()

    history = load_history()
    params = tune(history) if args.tune else ORIGIN_DEFAULTS
    report = walk_forward(history, params, score_from=1985)

    log.info("params: %s", params)
    log.info("backtest 1985-%s: n=%d acc=%.3f ll=%.4f brier=%.4f home-baseline=%.3f prior-ll=%.4f",
             report["span"][1], report["n"], report["winner_accuracy"],
             report["avg_log_loss"], report["avg_brier"], report["home_baseline_accuracy"],
             report["home_prior_log_loss"])

    if args.write:
        save_origin_params(params)
        _RECORD_FILE.write_text(json.dumps({
            "model_version": params.version,
            "span": report["span"],
            "n": report["n"],
            "winner_accuracy": round(report["winner_accuracy"], 4),
            "avg_log_loss": round(report["avg_log_loss"], 4),
            "avg_brier": round(report["avg_brier"], 4),
            "home_baseline_accuracy": round(report["home_baseline_accuracy"], 4),
            "home_prior_log_loss": round(report["home_prior_log_loss"], 4),
            "generated": date.today().isoformat(),
            "source": "walk-forward backtest over data/raw/state_of_origin_history.json",
        }, indent=2) + "\n")
        log.info("wrote %s and params.json", _RECORD_FILE.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
