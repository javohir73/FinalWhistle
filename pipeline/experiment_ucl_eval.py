"""Pre-registered UCL engine fit — the Champions League analogue of
pipeline/experiment_club_eval.py (docs/MODEL-EXPERIMENTS.md, club program).

The UCL activated with ``"model_params": {}`` — the served club defaults,
explicitly recorded as "no competition-specific fit has cleared the model
gate" (pipeline/leagues.py). This runner gives the UCL the same two Track-1
fits the domestic leagues got, on its own history:

- ``U1_base``      — goal-rate refit, gated on O/U 2.5 log loss (T1.1's grid).
- ``U2_home_adv``  — home-advantage refit, gated on 1X2 log loss (T1.5's grid).

Data: the four completed editions API-Football serves (2022-2025 — the same
bounded window the activation backfill used), regulation-time scores, via
pipeline/ingest/api_football_club_results.parse_finished_fixtures. Raw
season payloads are cached to --cache-dir and are NOT committed (public
repo; provider data).

Protocol deltas from the domestic runner, declared up front:

- Four editions only: 2022 opens the replay (never scorable), selection
  scores 2023+2024 walk-forward, and **2025 is the quarantined confirmation
  edition** — guarded here exactly as club_walkforward guards "2526".
- Bootstrap clusters are ISO MATCHWEEKS in both phases, not seasons: two
  season clusters would make the selection CI a two-point range, and the
  confirmation season is a single cluster (the domestic confirmation run
  already clusters by matchweek for that same reason).
- Ratings replay UCL history only, from the documented 1500 cold start.
  Serving injects domestic ratings for shared clubs (owns_served_rating);
  that context cannot be reproduced offline without the domestic corpus, so
  the fit reads on the goal environment more than on club identity. Finals
  (4 rows of 988) are neutral in serving but replayed with home advantage
  here — a declared approximation, not a discovered one.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_ucl_eval \
        --candidate U1_base --cache-dir <dir>

    # after selection results are recorded and UCL_FINAL_CONFIG is frozen:
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_ucl_eval \
        --confirm --cache-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from ml.evaluation.club_walkforward import (
    ClubMatch,
    EloConfig,
    GridConfig,
    loss_1x2,
    loss_totals,
    replay,
    season_clustered_ci,
    walk_forward,
)
from ml.models.params import load_params
from pipeline.ingest.api_football_club_results import parse_finished_fixtures

UCL_LEAGUE_ID = 2
UCL_COMPETITION = "UEFA Champions League"
UCL_SEASONS = (2022, 2023, 2024, 2025)
#: Quarantined confirmation edition. Never scored during selection; consumed
#: exactly once, on the frozen UCL_FINAL_CONFIG.
UCL_CONFIRM_SEASON = "2025"
SELECTION_SEASONS = ("2023", "2024")
#: Served UCL home advantage today (pipeline/leagues.py — the inherited club
#: default, not a fitted value).
SERVED_HOME_ADV = 60.0


def _frange(lo: float, hi: float, step: float, nd: int = 4) -> list[float]:
    out, x = [], lo
    while x <= hi + step / 2:
        out.append(round(x, nd))
        x += step
    return out


# Pre-registered candidates — the SAME grids as the domestic tracks they
# mirror (T1.1 / T1.5). Adding one after the first recorded run requires an
# explicitly post-hoc ledger row.
CANDIDATES = {
    "U1_base": (
        [(b,) for b in _frange(1.10, 1.80, 0.02)],
        lambda p, e, g: (e, replace(g, base=p[0])),
        loss_totals, "O/U 2.5 log loss",
    ),
    "U2_home_adv": (
        [(h,) for h in _frange(20.0, 120.0, 10.0)],
        lambda p, e, g: (replace(e, home_adv=p[0]), g),
        loss_1x2, "1X2 log loss",
    ),
}

# Frozen AFTER the selection phase is recorded in docs/MODEL-EXPERIMENTS.md —
# the confirmation run scores exactly this dict, never a re-fit.
#
# Selection (2026-08-06, this runner, --all): U1_base credibly better
# (Δ −0.0332, CI95 [−0.0462, −0.0191], 493 matches / 49 matchweek clusters;
# walk-forward picks 2023→1.32, 2024→1.38). U2_home_adv not credible
# (Δ +0.0010, CI straddles 0) → home_adv stays 60, not shipped. The frozen
# base is the argmin of mean O/U loss on ALL pre-confirmation editions
# (2022-2024, 707 matches): 1.44 (LL 0.6832 vs 0.7116 at the served 1.20;
# observed 2.97 goals/match vs the 2.40 the served base implies).
UCL_FINAL_CONFIG: dict[str, float] | None = {"base": 1.44}


def load_ucl_matches(api_key: str | None, cache_dir: Path) -> list[ClubMatch]:
    """The four editions as ClubMatch rows, cached per season.

    A season's raw fixture payload is fetched at most once; afterwards the
    cache is authoritative (finished editions do not change). With no api_key
    every season must already be cached.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    matches: list[ClubMatch] = []
    for season in UCL_SEASONS:
        cached = cache_dir / f"ucl_{season}.json"
        if cached.exists():
            fixtures = json.loads(cached.read_text())
        else:
            if not api_key:
                raise SystemExit(
                    f"{cached} missing and no API key available to fetch it"
                )
            from pipeline.ingest.api_football import fetch_fixtures

            fixtures = fetch_fixtures(api_key, league=UCL_LEAGUE_ID, season=season)
            cached.write_text(json.dumps(fixtures))
        for r in parse_finished_fixtures(fixtures):
            matches.append(ClubMatch(
                season=str(season), home=r["home_name"], away=r["away_name"],
                goals_home=r["score_home"], goals_away=r["score_away"],
                date=r["date"].date().isoformat(),
            ))
    matches.sort(key=lambda m: m.date)
    return matches


def control() -> tuple[EloConfig, GridConfig]:
    """Exactly what production serves for the UCL today: the global club
    defaults (club_params_for('ucl') applies an empty override dict)."""
    p = load_params()
    return (
        EloConfig(home_adv=SERVED_HOME_ADV),
        GridConfig(base=p.base, beta=p.beta, rho=p.rho,
                   temperature=p.temperature, calibrator=p.calibrator),
    )


def _weekly(deltas_by_season: dict[str, list[float]],
            matches: list[ClubMatch]) -> dict[str, list[float]]:
    """Re-key per-season delta lists by ISO matchweek. Delta lists follow the
    input order of that season's matches (walk_forward contract)."""
    by_season = {s: [m for m in matches if m.season == s] for s in deltas_by_season}
    weekly: dict[str, list[float]] = {}
    for season, ds in deltas_by_season.items():
        for m, d in zip(by_season[season], ds):
            iso = date.fromisoformat(m.date).isocalendar()
            weekly.setdefault(f"{iso[0]}-W{iso[1]:02d}", []).append(d)
    return weekly


def run_selection(candidate: str, matches: list[ClubMatch], *,
                  n_bootstrap: int) -> dict:
    grid, build, loss, metric = CANDIDATES[candidate]
    c_elo, c_grid = control()
    scored = [s for s in SELECTION_SEASONS]
    if UCL_CONFIRM_SEASON in scored:
        raise ValueError(
            f"edition {UCL_CONFIRM_SEASON} is the quarantined confirmation "
            "edition; selection must never score it"
        )
    out = walk_forward(
        matches, grid_points=grid, build=lambda p: build(p, c_elo, c_grid),
        control=(c_elo, c_grid), loss=loss, competition=UCL_COMPETITION,
        scored_seasons=scored,
    )
    ci = season_clustered_ci(_weekly(out["deltas"], matches),
                             n_bootstrap=n_bootstrap)
    return {
        "league": "ucl", "candidate": candidate, "metric": metric,
        "mode": "selection", "cluster": "matchweek",
        "n_matches": ci["n"], "n_clusters": ci.get("n_seasons"),
        "mean_delta": ci["mean"], "ci95": ci["ci95"], "verdict": ci["verdict"],
        "chosen_per_season": {s: list(p) for s, p in out["chosen"].items()},
    }


def run_confirmation(matches: list[ClubMatch], *, n_bootstrap: int) -> list[dict]:
    """Score the frozen UCL_FINAL_CONFIG on the QUARANTINED 2025 edition —
    one shot, both metrics, matchweek clusters (a single edition is one
    season cluster; see the domestic confirmation's identical reasoning)."""
    if not UCL_FINAL_CONFIG:
        raise SystemExit(
            "UCL_FINAL_CONFIG is not frozen yet — record the selection phase "
            "in docs/MODEL-EXPERIMENTS.md first"
        )
    c_elo, c_grid = control()
    f_elo, f_grid = c_elo, c_grid
    if "home_adv" in UCL_FINAL_CONFIG:
        f_elo = replace(f_elo, home_adv=UCL_FINAL_CONFIG["home_adv"])
    grid_deltas = {k: v for k, v in UCL_FINAL_CONFIG.items() if k != "home_adv"}
    if grid_deltas:
        f_grid = replace(f_grid, **grid_deltas)

    pre_control = replay(matches, c_elo, UCL_COMPETITION)
    pre_final = replay(matches, f_elo, UCL_COMPETITION)

    out = []
    for loss, metric in ((loss_1x2, "1X2 log loss"), (loss_totals, "O/U 2.5 log loss")):
        l_control = loss(matches, pre_control, c_elo, c_grid)
        l_final = loss(matches, pre_final, f_elo, f_grid)
        confirm = {
            UCL_CONFIRM_SEASON: [
                l_final[i] - l_control[i]
                for i, m in enumerate(matches) if m.season == UCL_CONFIRM_SEASON
            ]
        }
        ci = season_clustered_ci(_weekly(confirm, matches), n_bootstrap=n_bootstrap)
        out.append({
            "league": "ucl", "candidate": "UCL final config", "metric": metric,
            "mode": "CONFIRMATION", "cluster": "matchweek",
            "config": UCL_FINAL_CONFIG,
            "n_matches": ci["n"], "n_clusters": ci.get("n_seasons"),
            "mean_delta": ci["mean"], "ci95": ci["ci95"], "verdict": ci["verdict"],
        })
    return out


def format_result(r: dict) -> str:
    ci = r["ci95"]
    ci_s = f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "n/a"
    lines = [
        f"{r['candidate']}  ·  ucl  ·  {r['mode']}",
        f"  metric      : {r['metric']} (negative delta = candidate better)",
        f"  sample      : {r['n_matches']} matches / {r['n_clusters']} {r['cluster']} clusters",
        f"  mean delta  : {r['mean_delta']:+.4f}   CI95 {ci_s}",
        f"  verdict     : {r['verdict']}",
    ]
    if r.get("config"):
        lines.append(f"  config      : {r['config']}")
    if r.get("chosen_per_season"):
        lines.append("  picks       : " + ", ".join(
            f"{s}->{p}" for s, p in sorted(r["chosen_per_season"].items())))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", choices=sorted(CANDIDATES))
    ap.add_argument("--all", action="store_true", help="every candidate")
    ap.add_argument("--cache-dir", type=Path, required=True,
                    help="directory for cached ucl_{season}.json payloads")
    ap.add_argument("--n-bootstrap", type=int, default=2000)
    ap.add_argument("--confirm", action="store_true",
                    help=f"score the QUARANTINED {UCL_CONFIRM_SEASON} edition "
                         "on the frozen UCL_FINAL_CONFIG — once, at the end")
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args()

    from app.config import settings

    matches = load_ucl_matches(settings.api_football_api_key or None, args.cache_dir)
    results = []
    if args.confirm:
        print(f"!! CONFIRMATION MODE — consuming the quarantined "
              f"{UCL_CONFIRM_SEASON} edition.\n", file=sys.stderr)
        for r in run_confirmation(matches, n_bootstrap=args.n_bootstrap):
            results.append(r)
            print(format_result(r))
            print()
    else:
        names = sorted(CANDIDATES) if args.all else ([args.candidate] if args.candidate else None)
        if not names:
            ap.error("pass --all or --candidate (or --confirm)")
        for name in names:
            r = run_selection(name, matches, n_bootstrap=args.n_bootstrap)
            results.append(r)
            print(format_result(r))
            print()

    if args.emit_json:
        args.emit_json.write_text(json.dumps(results, indent=2))
        print(f"wrote {args.emit_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
