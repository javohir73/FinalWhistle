"""Run the pre-registered club-engine gates (docs/MODEL-EXPERIMENTS.md).

The club analogue of pipeline/experiment_model_eval.py. That runner clusters by
tournament edition; club football has no editions, so this one clusters by
SEASON — see ml/evaluation/club_walkforward.py for the protocol.

Every candidate here is pre-registered. Adding one after the first gate run has
been recorded requires a new, explicitly post-hoc row in the ledger.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_club_eval \\
        --league epl --candidate T1.1_base

    # every candidate, every league
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_club_eval --all

CSVs are downloaded from football-data.co.uk unless --csv-dir points at a
directory of cached ``{DIV}_{SEASON}.csv`` files.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    loss_1x2,
    loss_totals,
    replay,
    rest_deltas,
    season_clustered_ci,
    walk_forward,
)
from ml.models.params import load_params
from pipeline.ingest.club_results import (
    BASE_URL,
    SEASON_CODES,
    clean_club_results_df,
)

# division code, historical_matches.competition, currently-served home advantage
LEAGUES = {
    "epl": ("E0", "Premier League", 60.0),
    "laliga": ("SP1", "La Liga", 80.0),
    "bundesliga": ("D1", "Bundesliga", 60.0),
}


def _frange(lo: float, hi: float, step: float, nd: int = 4) -> list[float]:
    out, x = [], lo
    while x <= hi + step / 2:
        out.append(round(x, nd))
        x += step
    return out


def load_matches(division: str, csv_dir: Path | None) -> list[ClubMatch]:
    frames = []
    for code in SEASON_CODES:
        cached = csv_dir / f"{division}_{code}.csv" if csv_dir else None
        src = cached if cached and cached.exists() else BASE_URL.format(
            season=code, division=division
        )
        df = pd.read_csv(src, usecols=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        frames.append(df.assign(season_code=code))
    df = clean_club_results_df(pd.concat(frames, ignore_index=True))
    df = df.sort_values("match_date")
    return [
        ClubMatch(
            season=r.season_code, home=r.HomeTeam, away=r.AwayTeam,
            goals_home=int(r.FTHG), goals_away=int(r.FTAG),
            date=r.match_date.date().isoformat(),
        )
        for r in df.itertuples(index=False)
    ]


# --- pre-registered candidates -------------------------------------------
# Each entry: (grid, build, loss, metric-name). `build` takes a grid point plus
# the league's control pair and returns the candidate's (EloConfig, GridConfig).

CANDIDATES = {
    # Track 1 — per-league core refit (defect-fix bar)
    "T1.1_base": (
        [(b,) for b in _frange(1.10, 1.80, 0.02)],
        lambda p, e, g: (e, replace(g, base=p[0])),
        loss_totals, "O/U 2.5 log loss",
    ),
    "T1.2_beta": (
        [(b,) for b in _frange(0.0010, 0.0035, 0.0001, nd=5)],
        lambda p, e, g: (e, replace(g, beta=p[0])),
        loss_1x2, "1X2 log loss",
    ),
    "T1.3_rho": (
        [(r,) for r in _frange(-0.20, 0.00, 0.01)],
        lambda p, e, g: (e, replace(g, rho=p[0])),
        loss_1x2, "1X2 log loss",
    ),
    "T1.4_temperature": (
        [(t,) for t in _frange(0.80, 1.40, 0.05)],
        lambda p, e, g: (e, replace(g, temperature=p[0])),
        loss_1x2, "1X2 log loss",
    ),
    "T1.5_home_adv": (
        [(h,) for h in _frange(20.0, 120.0, 10.0)],
        lambda p, e, g: (replace(e, home_adv=p[0]), g),
        loss_1x2, "1X2 log loss",
    ),
    "T1.7_k_factor": (
        [(k,) for k in _frange(10.0, 50.0, 5.0)],
        lambda p, e, g: (replace(e, k=p[0]), g),
        loss_1x2, "1X2 log loss",
    ),
    # Track 3 — free signals (standard gate)
    "T3.1_season_shrinkage": (
        [(s,) for s in _frange(0.00, 0.50, 0.05)],
        lambda p, e, g: (replace(e, shrinkage=p[0]), g),
        loss_1x2, "1X2 log loss",
    ),
    "T3.2_rest_days": (
        [(c, cap) for c in _frange(0.000, 0.020, 0.002) for cap in (0.05, 0.075, 0.10)],
        lambda p, e, g: (e, replace(g, rest_coef=p[0], rest_cap=p[1])),
        loss_1x2, "1X2 log loss",
    ),
    "T3.3_promoted_prior": (
        [(v,) for v in _frange(1250.0, 1550.0, 25.0)],
        lambda p, e, g: (replace(e, promoted_prior=p[0]), g),
        loss_1x2, "1X2 log loss",
    ),
}


# The SELECTION-phase ship list, frozen here so the confirmation run scored
# exactly the config recorded in docs/MODEL-EXPERIMENTS.md and not a re-fit.
# Only deltas vs each league's control appear; anything absent is unchanged.
# Track 3 (season shrinkage / rest days / promoted priors) was refuted in every
# league, so it contributed nothing and had no confirmation run.
#
# HISTORICAL as of the 2026-07-28 confirmation run — kept verbatim because it
# is what that run scored. The `rho` and La Liga `home_adv` entries did NOT
# replicate on the held-out season and are NOT shipping; see that document's
# "FINAL ship list (post-confirmation)". Do not re-run --confirm against 2025-26:
# the season is consumed, and a second pass is multiple testing against a burnt
# holdout. The next clean holdout is the live 2026-27 season.
FINAL_CONFIG: dict[str, dict[str, float]] = {
    "epl": {"base": 1.30, "rho": 0.00},
    "laliga": {"home_adv": 60.0},          # base stays 1.20 — refit was credibly worse
    "bundesliga": {"base": 1.44, "rho": 0.00},
}


def final_for(league: str) -> tuple[EloConfig, GridConfig]:
    """The declared ship-list config for ``league``."""
    elo, grid = control_for(league)
    deltas = FINAL_CONFIG[league]
    if "home_adv" in deltas:
        elo = replace(elo, home_adv=deltas["home_adv"])
    grid_deltas = {k: v for k, v in deltas.items() if k != "home_adv"}
    if grid_deltas:
        grid = replace(grid, **grid_deltas)
    return elo, grid


def run_confirmation(league: str, csv_dir: Path | None, *, n_bootstrap: int) -> list[dict]:
    """Score the declared config on the QUARANTINED season. One shot per track.

    No selection happens here — the config was already chosen, and is frozen in
    FINAL_CONFIG. Both metrics are reported because Track 1 spans them (`base`
    was gated on totals, everything else on 1X2).

    Resampling unit: the **matchweek**, not the season. A single held-out
    season gives exactly one season-cluster, so a season bootstrap would
    resample the same cluster every draw and collapse the CI to zero width —
    an interval that looks certain precisely because it measured nothing.
    Calendar week is the honest within-season unit: it respects the short-range
    correlation between matches sharing a rating snapshot, and yields ~38
    clusters per league season.
    """
    from datetime import date

    division, competition, _ = LEAGUES[league]
    matches = load_matches(division, csv_dir)
    control = control_for(league)
    final = final_for(league)
    rest = rest_deltas(matches)

    c_elo, c_grid = control
    f_elo, f_grid = final
    pre_control = replay(matches, c_elo, competition)
    pre_final = replay(matches, f_elo, competition)

    out = []
    for loss, metric in ((loss_1x2, "1X2 log loss"), (loss_totals, "O/U 2.5 log loss")):
        l_control = loss(matches, pre_control, c_elo, c_grid, rest_deltas=rest)
        l_final = loss(matches, pre_final, f_elo, f_grid, rest_deltas=rest)

        by_week: dict[str, list[float]] = {}
        for i, m in enumerate(matches):
            if m.season != CONFIRM_SEASON:
                continue
            iso = date.fromisoformat(m.date).isocalendar()
            by_week.setdefault(f"{iso[0]}-W{iso[1]:02d}", []).append(l_final[i] - l_control[i])

        ci = season_clustered_ci(by_week, n_bootstrap=n_bootstrap)
        out.append({
            "league": league, "candidate": "TRACK-1 final config",
            "metric": metric, "mode": "CONFIRMATION",
            "config": FINAL_CONFIG[league], "cluster": "matchweek",
            "n_matches": ci["n"], "n_seasons": ci.get("n_seasons"),
            "mean_delta": ci["mean"], "ci95": ci["ci95"], "verdict": ci["verdict"],
            "chosen_per_season": {},
        })
    return out


def control_for(league: str) -> tuple[EloConfig, GridConfig]:
    """Exactly what production serves for this league today."""
    _, _, home_adv = LEAGUES[league]
    p = load_params()
    return (
        EloConfig(home_adv=home_adv),
        GridConfig(base=p.base, beta=p.beta, rho=p.rho,
                   temperature=p.temperature, calibrator=p.calibrator),
    )


def run(league: str, candidate: str, csv_dir: Path | None, *, n_bootstrap: int,
        confirm: bool) -> dict:
    division, competition, _ = LEAGUES[league]
    grid, build, loss, metric = CANDIDATES[candidate]
    matches = load_matches(division, csv_dir)
    c_elo, c_grid = control_for(league)

    scored = [CONFIRM_SEASON] if confirm else None
    out = walk_forward(
        matches,
        grid_points=grid,
        build=lambda p: build(p, c_elo, c_grid),
        control=(c_elo, c_grid),
        loss=loss,
        competition=competition,
        scored_seasons=scored,
        allow_confirm_season=confirm,
        rest=rest_deltas(matches),
    )
    ci = season_clustered_ci(out["deltas"], n_bootstrap=n_bootstrap)
    return {
        "league": league, "candidate": candidate, "metric": metric,
        "mode": "CONFIRMATION" if confirm else "selection",
        "n_matches": ci["n"], "n_seasons": ci.get("n_seasons"),
        "mean_delta": ci["mean"], "ci95": ci["ci95"], "verdict": ci["verdict"],
        "chosen_per_season": {s: list(p) for s, p in out["chosen"].items()},
    }


def format_result(r: dict) -> str:
    ci = r["ci95"]
    ci_s = f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "n/a"
    unit = r.get("cluster", "season")
    lines = [
        f"{r['candidate']}  ·  {r['league']}  ·  {r['mode']}",
        f"  metric      : {r['metric']} (negative delta = candidate better)",
        f"  sample      : {r['n_matches']} matches / {r['n_seasons']} {unit} clusters",
        f"  mean delta  : {r['mean_delta']:+.4f}   CI95 {ci_s}",
        f"  verdict     : {r['verdict']}",
    ]
    if r.get("config"):
        lines.append(f"  config      : {r['config']}")
    if r["chosen_per_season"]:
        lines.append("  picks       : " + ", ".join(
            f"{s}->{p}" for s, p in sorted(r["chosen_per_season"].items())))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", choices=sorted(LEAGUES))
    ap.add_argument("--candidate", choices=sorted(CANDIDATES))
    ap.add_argument("--all", action="store_true", help="every candidate x every league")
    ap.add_argument("--csv-dir", type=Path, help="directory of cached {DIV}_{SEASON}.csv")
    ap.add_argument("--n-bootstrap", type=int, default=2000)
    ap.add_argument(
        "--confirm", action="store_true",
        help=f"score the QUARANTINED {CONFIRM_SEASON} season. One run per track, "
             "at the end, on the final chosen config only.",
    )
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args()

    results = []

    if args.confirm:
        print(f"!! CONFIRMATION MODE — consuming the quarantined {CONFIRM_SEASON} "
              "season. One shot per track; the config comes from FINAL_CONFIG, "
              "not from a re-fit.\n", file=sys.stderr)
        leagues = [args.league] if args.league else sorted(LEAGUES)
        for league in leagues:
            for r in run_confirmation(league, args.csv_dir, n_bootstrap=args.n_bootstrap):
                results.append(r)
                print(format_result(r))
                print()
    else:
        if args.all:
            jobs = [(lg, c) for lg in sorted(LEAGUES) for c in sorted(CANDIDATES)]
        elif args.league and args.candidate:
            jobs = [(args.league, args.candidate)]
        else:
            ap.error("pass --all, or both --league and --candidate")

        for league, candidate in jobs:
            r = run(league, candidate, args.csv_dir,
                    n_bootstrap=args.n_bootstrap, confirm=False)
            results.append(r)
            print(format_result(r))
            print()

    if args.emit_json:
        args.emit_json.write_text(json.dumps(results, indent=2))
        print(f"wrote {args.emit_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
