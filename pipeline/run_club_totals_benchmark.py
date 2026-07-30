"""Run the D0-B totals benchmark: served O/U 2.5 book vs the closing line.

Pre-registration: `docs/experiments/2026-07-30-d0b-totals-market/
PRE-REGISTRATION.md` (`aa7a445`, corrections `1e207a6`). This runner selects
nothing and writes nothing to production — see §12 of that document.

Usage::

    PYTHONPATH=backend:. python -m pipeline.run_club_totals_benchmark \
        --csv-dir data/raw/club \
        --emit-json /tmp/d0b-totals.json

Offline and hermetic by construction
------------------------------------
`pipeline/experiment_club_eval.py::load_matches` falls back to a live download
when a cached CSV is absent (`experiment_club_eval.py:69-72`). Pointed at
`data/raw/club` — where the three `*_2526` captures do not exist — that would
**fetch the consumed 2025-26 holdout**. This module therefore does not reuse
it: it reads only files that exist, scoped to
`club_data_manifest.pre_confirmation_keys()`, and raises on a missing one
rather than reaching for the network.

Names are joined on ``str.strip`` alone, on BOTH sides, from the same raw CSV
strings. `clean_club_results_df` maps names through `team_mapping`, which is
correct for a DB ingest and wrong here: the totals loader does not, so mixing
the two would silently fail to join every renamed club. Any row that does not
join is a defect, and `--strict-join` (the default) raises on it.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ml.evaluation.club_totals_benchmark import (
    build_matched_totals,
    clustered_deltas,
    information_share,
    information_share_ci,
    score_totals,
)
from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    replay,
    season_clustered_ci,
)
from pipeline.club_data_manifest import PRE_CONFIRMATION_SEASONS, sha256_of
from pipeline.ingest.football_data import (
    PROVIDER,
    ClosingTotalsUnavailable,
    load_football_data_totals_csv,
    select_totals_family,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

#: league -> (division code, historical competition label, served home adv).
#: Mirrors `pipeline.experiment_club_eval.LEAGUES`; kept local so this runner
#: does not import that module and inherit its network fallback.
LEAGUES: dict[str, tuple[str, str, float]] = {
    "epl": ("E0", "Premier League", 60.0),
    "laliga": ("SP1", "La Liga", 80.0),
    "bundesliga": ("D1", "Bundesliga", 60.0),
}

#: §4 of the pre-registration. The constant baseline's rate is fitted on
#: FIT_SEASONS and every predictor is scored on SCORED_SEASONS; the two are
#: disjoint and `score_totals` enforces that rather than trusting it.
FIT_SEASONS: tuple[str, ...] = ("1920", "2021", "2122", "2223")
SCORED_SEASONS: tuple[str, ...] = ("2324", "2425")

#: Section 11 of the pre-registration fixes the bootstrap seed at 26.
#: `season_clustered_ci` defaults to 12345, so every call here passes this
#: explicitly — the first cut relied on that default and therefore reported
#: intervals drawn with an unregistered seed.
BOOTSTRAP_SEED = 26

#: Section 7's closed set of drop reasons. First failing check wins, matching
#: the loader's own order, so `usable + sum(drops) == rows` holds exactly.
DROP_REASONS = (
    "no_closing_totals_columns",
    "unparseable_date",
    "missing_or_invalid_score",
    "blank_price",
    "non_positive_price",
)


def _read_division_csv(csv_dir: Path, division: str, season: str) -> pd.DataFrame:
    """Read one capture. Raises rather than falling back to the network."""
    path = csv_dir / f"{division}_{season}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is absent. This runner never downloads — a missing capture "
            "is a fact to report, not a fetch to make."
        )
    return pd.read_csv(path)


def load_division_matches(csv_dir: Path, division: str) -> list[ClubMatch]:
    """Every pre-confirmation match for ``division``, oldest-first.

    ALL nine seasons, including the three with no closing totals family: those
    are burn-in for the Elo replay and are never scored. Restricting the replay
    to the six priced seasons would hand 2019-20 a cold-start rating for every
    club and change every probability downstream.
    """
    rows: list[tuple] = []
    for season in PRE_CONFIRMATION_SEASONS:
        df = _read_division_csv(csv_dir, division, season)
        dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        for i, r in df.iterrows():
            d = dates.iloc[i]
            if pd.isna(d):
                continue
            try:
                gh, ga = int(r["FTHG"]), int(r["FTAG"])
            except (KeyError, TypeError, ValueError):
                continue
            home, away = str(r["HomeTeam"]).strip(), str(r["AwayTeam"]).strip()
            if not home or not away or home == away:
                continue
            rows.append((d.date().isoformat(), season, home, away, gh, ga))

    # Stable sort by date: Elo is path-dependent and `replay` requires
    # oldest-first. Same-day rows keep file order, as run_club_benchmark does.
    rows.sort(key=lambda t: t[0])
    return [
        ClubMatch(season=s, home=h, away=a, goals_home=gh, goals_away=ga, date=d)
        for d, s, h, a, gh, ga in rows
    ]


def load_division_totals(csv_dir: Path, division: str) -> tuple[list[dict], list[dict]]:
    """Priced over/under rows for ``division``, plus a per-file coverage census.

    Returns (records, census). A file with no closing totals family abstains
    whole and is recorded with ``family=None`` and its row count, so the
    denominator is always visible and the nine structural exclusions are named
    rather than absent.
    """
    records: list[dict] = []
    census: list[dict] = []
    for season in PRE_CONFIRMATION_SEASONS:
        path = csv_dir / f"{division}_{season}.csv"
        df = _read_division_csv(csv_dir, division, season)
        n_rows = int(df["HomeTeam"].notna().sum())
        try:
            family = select_totals_family(df.columns)
        except ClosingTotalsUnavailable as exc:
            census.append({
                "file": path.name, "rows": n_rows, "family": None, "usable": 0,
                "dropped": n_rows,
                "drops_by_reason": {"no_closing_totals_columns": n_rows},
                "detail": str(exc), "sha256": sha256_of(path),
            })
            continue
        recs = load_football_data_totals_csv(str(path))
        for r in recs:
            r["season"] = season
        records.extend(recs)
        drops = _attribute_drops(df, family.columns)
        booksums = [1.0 / r["odds_over"] + 1.0 / r["odds_under"] for r in recs]
        census.append({
            "file": path.name, "rows": n_rows, "family": family.key,
            "basis": family.basis, "bookmaker": family.bookmaker,
            "usable": len(recs), "dropped": n_rows - len(recs),
            "drops_by_reason": drops,
            # Section 10 requires the measured booksum per family. An underround
            # book (< 1.0) has no Shin solution and falls back to proportional,
            # so the reader needs to see whether that branch was ever taken.
            "booksum_min": min(booksums) if booksums else None,
            "booksum_mean": sum(booksums) / len(booksums) if booksums else None,
            "booksum_max": max(booksums) if booksums else None,
            "n_underround": sum(1 for b in booksums if b < 1.0),
            "sha256": sha256_of(path),
        })
    return records, census


def _attribute_drops(df: pd.DataFrame, columns: tuple[str, str]) -> dict[str, int]:
    """Per-row drop reasons, in the loader's own check order.

    Section 7 promises a closed set that sums exactly to the shortfall. The
    first cut reported a single bucket named ``unusable_price_or_score``, which
    is a reason-shaped string rather than an attribution.
    """
    over_col, under_col = columns
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    counts = {r: 0 for r in DROP_REASONS}
    for i, row in df.iterrows():
        if not str(row.get("HomeTeam") or "").strip():
            continue
        if pd.isna(dates.iloc[i]):
            counts["unparseable_date"] += 1
            continue
        try:
            int(row["FTHG"]), int(row["FTAG"])
        except (KeyError, TypeError, ValueError):
            counts["missing_or_invalid_score"] += 1
            continue
        try:
            o, u = float(row[over_col]), float(row[under_col])
        except (KeyError, TypeError, ValueError):
            counts["blank_price"] += 1
            continue
        if o != o or u != u:
            counts["blank_price"] += 1
        elif min(o, u) <= 1.0:
            counts["non_positive_price"] += 1
    return {k: v for k, v in counts.items() if v}


def _grids(league: str) -> tuple[EloConfig, GridConfig, GridConfig]:
    """(elo, served_grid, control_grid) for ``league``.

    ``served`` is `pipeline.leagues.club_params_for` — the exact per-league
    configuration in production, `base` override included. ``control`` is
    `club_baseline_params_for` — the pre-override global. The control is the
    only column that is out-of-sample with respect to T1.1, which selected
    `base` on this metric over a superset of the scored seasons.

    NOT `ml.evaluation.backtest.model_probs`, whose defaults
    (`base=1.35, beta=0.0019, rho=0.0`, no calibrator) are what
    `pipeline/run_club_benchmark.py:98` scores and are served by nothing.
    """
    from pipeline.leagues import club_baseline_params_for, club_params_for

    _div, _comp, home_adv = LEAGUES[league]
    served, control = club_params_for(league), club_baseline_params_for(league)

    # `ml/models/odds_blend.py::lambda_total_from_over` inverts THIS market
    # straight into the served lambda sum. With `use_odds` on, the model column
    # would become a function of the market column and this benchmark would
    # converge toward zero while looking like progress. The committed config is
    # pinned by test; this guards a run made against a modified one.
    for name, p in (("served", served), ("control", control)):
        if p.use_odds:
            raise AssertionError(
                f"{league}/{name} has use_odds=True — the odds-blend shadow path "
                "feeds the closing over/under line into the model's lambdas, so "
                "this benchmark would be scoring the market against itself"
            )
    to_grid = lambda p: GridConfig(  # noqa: E731 - a 1-line adapter, not logic
        base=p.base, beta=p.beta, rho=p.rho,
        temperature=p.temperature, calibrator=p.calibrator,
    )
    return EloConfig(home_adv=home_adv), to_grid(served), to_grid(control)


def run_league(league: str, csv_dir: Path, *, n_bootstrap: int = 2000,
               strict_join: bool = True) -> dict:
    """Score one league. Pure orchestration over pure modules."""
    division, competition, _ = LEAGUES[league]
    matches = load_division_matches(csv_dir, division)
    if any(m.season == CONFIRM_SEASON for m in matches):
        raise AssertionError(
            f"{CONFIRM_SEASON} reached the replay — the holdout is consumed and "
            "must never be read by this phase"
        )

    elo, served_grid, control_grid = _grids(league)
    pre = replay(matches, elo, competition)
    priced, census = load_division_totals(csv_dir, division)

    matched, unpriced = build_matched_totals(
        matches, pre, elo, served_grid, control_grid, priced,
    )
    if unpriced and strict_join:
        sample = [(r["date"].isoformat(), r["home_team"], r["away_team"])
                  for r in unpriced[:5]]
        raise AssertionError(
            f"{len(unpriced)} priced rows did not join to a replayed match "
            f"(first {len(sample)}: {sample}). Both sides come from the same "
            "CSVs under str.strip, so a miss is a defect, not missingness."
        )

    result = score_totals(matched, FIT_SEASONS, SCORED_SEASONS)
    rows = result.pop("rows")
    deltas = {
        "model_minus_market": result.pop("deltas_model_minus_market"),
        "model_minus_control": result.pop("deltas_model_minus_control"),
        "model_minus_constant": result.pop("deltas_model_minus_constant"),
        "market_minus_constant": result.pop("deltas_market_minus_constant"),
    }

    result["league"] = league
    result["division"] = division
    result["information_share"] = information_share(result)
    result["information_share_ci"] = information_share_ci(
        rows, deltas["model_minus_market"], deltas["market_minus_constant"],
        n_bootstrap=n_bootstrap, seed=BOOTSTRAP_SEED,
    )

    # EVERY paired comparison gets an interval, at the pre-registered seed.
    # The first cut gave one only to model-vs-market and then reported
    # model-vs-constant as a difference of two levels — which is how two
    # sub-0.003-nat claims got stated as findings in a document that dismissed
    # #202's sub-0.003-nat candidates as unresolvable.
    result["comparisons"] = {}
    for name, d in deltas.items():
        entry: dict = {"mean": sum(d) / len(d)}
        for by in ("iso_week", "season"):
            ci = season_clustered_ci(clustered_deltas(rows, d, by),
                                     n_bootstrap=n_bootstrap, seed=BOOTSTRAP_SEED)
            n_cl = len({r.iso_week if by == "iso_week" else r.season for r in rows})
            half = (ci["ci95"][1] - ci["ci95"][0]) / 2 if ci["ci95"] else None
            entry[by] = {
                "n_clusters": n_cl, "ci95": ci["ci95"], "half_width": half,
                # A percentile bootstrap over 2 clusters can only produce 3
                # distinct resamples, so its "interval" is the range of a
                # handful of values, not a 95% interval. Labelled, not quoted.
                "is_an_interval": n_cl >= 20,
                "excludes_zero": bool(
                    ci["ci95"] and (ci["ci95"][1] < 0 or ci["ci95"][0] > 0)
                ),
            }
        n = len(d)
        mean = entry["mean"]
        sd = (sum((x - mean) ** 2 for x in d) / (n - 1)) ** 0.5 if n > 1 else float("nan")
        entry["paired_sd"] = sd
        # 2.80 = 1.96 + 0.84, i.e. 80% power at two-sided alpha 0.05. This is a
        # POWER threshold and is deliberately larger than the 1.96-sigma
        # half-width beside it; the two answer different questions and neither
        # is "the conservative one".
        entry["naive_mde_80pct"] = 2.80 * sd / (n ** 0.5)
        hw = entry["iso_week"]["half_width"]
        entry["resolved"] = bool(hw is not None and abs(mean) > hw)
        # La Liga ships no `base` override, so its model and control columns are
        # the same numbers and every paired difference is an exact 0.0 with zero
        # variance. That is a wiring check that PASSED, not a comparison too
        # noisy to call, and it must not print as "unresolved".
        entry["degenerate_zero"] = bool(mean == 0.0 and sd == 0.0)
        result["comparisons"][name] = entry

    # Kept for report/JSON compatibility; same numbers, primary clustering.
    result["intervals"] = {
        by: {
            "n_clusters": result["comparisons"]["model_minus_market"][by]["n_clusters"],
            "mean": result["comparisons"]["model_minus_market"]["mean"],
            "ci95": result["comparisons"]["model_minus_market"][by]["ci95"],
            "role": "PRIMARY (pre-registered)" if by == "iso_week"
                    else "sensitivity — too few clusters to be an interval",
        }
        for by in ("iso_week", "season")
    }
    result["resolution"] = {
        k: result["comparisons"]["model_minus_market"][k]
        for k in ("paired_sd", "naive_mde_80pct", "resolved")
    } | {"clustered_ci_half_width":
         result["comparisons"]["model_minus_market"]["iso_week"]["half_width"]}
    result["census"] = census
    result["n_replayed"] = len(matches)
    result["n_priced_rows"] = len(priced)
    result["n_unjoined"] = len(unpriced)
    result["params"] = {
        "served": {"base": served_grid.base, "beta": served_grid.beta,
                   "rho": served_grid.rho, "temperature": served_grid.temperature,
                   "calibrator": served_grid.calibrator is not None},
        "control": {"base": control_grid.base, "beta": control_grid.beta,
                    "rho": control_grid.rho, "temperature": control_grid.temperature,
                    "calibrator": control_grid.calibrator is not None},
        "home_adv": elo.home_adv,
    }
    return result


def pooled_result(results: list[dict]) -> dict:
    """§2's "and pooled" objectives, which the first cut never produced.

    This is a sample-size-weighted mean of the PER-LEAGUE paired comparisons,
    each against its own league's constant. That choice matters: pooling every
    match against a SINGLE constant instead would hand the market a free win,
    because one rate cannot fit three leagues whose over-rates are ~0.61 / 0.61
    / 0.47, and the inflated budget would flatter the model's share (+27% rather
    than the +13% this weighting gives). The per-league numbers remain the
    honest read; this exists because section 2 asks for it.
    """
    n = sum(r["n_matches"] for r in results)
    if not n:
        return {}
    def wavg(path: str) -> float:
        return sum(r[path] * r["n_matches"] for r in results) / n
    out = {
        "n_matches": n,
        "n_fit": sum(r["n_fit"] for r in results),
        "model_minus_market": wavg("model_minus_market"),
        "model_minus_control": wavg("model_minus_control"),
        "model_minus_constant": wavg("model_minus_constant"),
        "market_minus_constant": wavg("market_minus_constant"),
        "caveat": "sample-size-weighted mean of per-league comparisons, each "
                  "against its own league's constant. Pooling against ONE "
                  "constant would inflate the budget and flatter the share "
                  "(+27% vs +13%). Per-league is the honest read.",
    }
    for k in ("model", "control", "market", "constant"):
        out[k] = {
            m: sum(r[k][m] * r["n_matches"] for r in results) / n
            for m in ("log_loss", "brier", "accuracy")
        }
    out["information_share"] = information_share(out)
    return out


def _ci(entry: dict, by: str = "iso_week") -> str:
    ci = entry[by]["ci95"]
    if not ci:
        return "n/a"
    tag = "" if entry[by]["is_an_interval"] else " (NOT an interval)"
    return f"[{ci[0]:+.4f}, {ci[1]:+.4f}]{tag}"


def format_report(results: list[dict]) -> str:
    """Plain-text report. Every rate carries its denominator, every paired
    comparison carries its interval, and an unresolved comparison says so."""
    out: list[str] = []
    w = out.append
    w("=" * 78)
    w("D0-B \u2014 CLUB TOTALS (O/U 2.5) vs THE CLOSING LINE")
    w("=" * 78)
    w(f"provider   : {PROVIDER['provider']} \u2014 {PROVIDER['attribution']}")
    w(f"redistrib. : {PROVIDER['redistribution']}")
    w(f"fit seasons: {', '.join(FIT_SEASONS)}   scored: {', '.join(SCORED_SEASONS)}")
    w(f"bootstrap  : seed {BOOTSTRAP_SEED}, iso-week clusters (pre-registered primary)")
    w("SELECTS NOTHING. The served `base` is IN-SAMPLE on this metric (T1.1")
    w("chose it on O/U 2.5 log loss over 1718-2425, a superset of the scored")
    w("window), so a favourable model-vs-market number is NOT an edge.")
    w("")

    for r in results:
        c = r["comparisons"]
        w("-" * 78)
        w(f"{r['league'].upper()}  ({r['division']})   market: {r['market_basis']}")
        w("-" * 78)
        w(f"  replayed {r['n_replayed']} matches over 9 seasons")
        w(f"  priced {r['n_priced_rows']} rows; {r['n_unjoined']} unjoined; "
          f"of those {r['n_fit']} fit the constant and {r['n_matches']} are SCORED")
        w(f"  over-rate scored {r['over_rate_scored']:.4f}; "
          f"constant rate {r['constant_rate']:.4f} (fitted out-of-sample)")
        w("")
        w(f"  {'predictor':<12} {'log loss':>10} {'brier':>9} {'accuracy':>9}")
        for name in ("model", "control", "market", "constant"):
            m = r[name]
            w(f"  {name:<12} {m['log_loss']:>10.4f} {m['brier']:>9.4f} "
              f"{m['accuracy']:>9.4f}")
        w("")
        w(f"  paired comparisons (n={r['n_matches']}, "
          f"{c['model_minus_market']['iso_week']['n_clusters']} iso-week clusters)")
        w(f"  {'comparison':<24} {'mean':>9} {'CI95':>26} {'MDE80':>8}  verdict")
        for key, label in (
            ("model_minus_market", "model - market"),
            ("model_minus_constant", "model - constant"),
            ("model_minus_control", "model - control"),
            ("market_minus_constant", "market - constant"),
        ):
            e = c[key]
            if e["degenerate_zero"]:
                verdict = "EXACTLY ZERO (identical columns)"
            elif e["iso_week"]["excludes_zero"]:
                verdict = "RESOLVED"
            else:
                verdict = "UNRESOLVED at this n"
            w(f"  {label:<24} {e['mean']:>+9.4f} {_ci(e):>26} "
              f"{e['naive_mde_80pct']:>8.4f}  {verdict}")
        w("")
        share, sci = r["information_share"], r["information_share_ci"]
        if share is None:
            w("  information share: n/a (market does not beat the constant)")
        else:
            band = (f"[{sci['ci95'][0]:+.1%}, {sci['ci95'][1]:+.1%}]"
                    if sci["ci95"] else "n/a")
            w(f"  information share captured by the model: {share:+.1%}  {band}")
            if sci["n_undefined"]:
                w(f"    {sci['n_undefined']}/{sci['n_clusters'] and 2000} resamples "
                  "had a non-positive budget: no share is defined there")
            w("    a RATIO of two noisy paired means -- never quote the point "
              "estimate alone")
        w("")
        sn = c["model_minus_market"]["season"]
        w(f"  season-clustered sensitivity: {_ci(c['model_minus_market'], 'season')} "
          f"({sn['n_clusters']} clusters)")
        w("")
        abstained = [x for x in r["census"] if x["family"] is None]
        w(f"  coverage: {len(r['census']) - len(abstained)}/{len(r['census'])} "
          f"captures priced; {len(abstained)} abstained "
          f"({', '.join(x['file'] for x in abstained) or 'none'})")
        drops: dict[str, int] = {}
        for x in r["census"]:
            for k, v in (x.get("drops_by_reason") or {}).items():
                drops[k] = drops.get(k, 0) + v
        w(f"  drops by reason: {drops or 'none'}")
        bs = [x for x in r["census"] if x.get("booksum_mean") is not None]
        if bs:
            w(f"  booksum: min {min(x['booksum_min'] for x in bs):.4f} "
              f"max {max(x['booksum_max'] for x in bs):.4f}; "
              f"{sum(x['n_underround'] for x in bs)} underround rows")
        w("")

    pooled = pooled_result(results)
    if pooled and len(results) > 1:
        w("=" * 78)
        w(f"POOLED (n={pooled['n_matches']}) \u2014 reported because \u00a72 asks for it")
        w("=" * 78)
        w(f"  model {pooled['model']['log_loss']:.4f}  "
          f"control {pooled['control']['log_loss']:.4f}  "
          f"market {pooled['market']['log_loss']:.4f}  "
          f"constant {pooled['constant']['log_loss']:.4f}")
        w(f"  model - market {pooled['model_minus_market']:+.4f}   "
          f"budget {pooled['market_minus_constant']:+.4f}   "
          f"share {pooled['information_share']:+.1%}")
        w(f"  CAVEAT: {pooled['caveat']}")
        w("")
    return "\n".join(out)


def _positive_int(raw: str) -> int:
    """A bootstrap of zero resamples indexes an empty list deep inside
    `season_clustered_ci`. Rejected at the boundary with a readable message."""
    n = int(raw)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", default="data/raw/club", type=Path)
    ap.add_argument("--league", action="append", choices=sorted(LEAGUES),
                    help="repeatable; default all three")
    ap.add_argument("--n-bootstrap", type=_positive_int, default=2000,
                    help="resamples; must be >= 1")
    ap.add_argument("--emit-json", type=Path)
    ap.add_argument("--allow-unjoined", action="store_true",
                    help="report unjoined rows instead of raising (diagnosis only)")
    args = ap.parse_args(argv)

    leagues = args.league or sorted(LEAGUES)
    results = [
        run_league(lg, args.csv_dir, n_bootstrap=args.n_bootstrap,
                   strict_join=not args.allow_unjoined)
        for lg in leagues
    ]
    print(format_report(results))

    if args.emit_json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "phase": "D0-B",
            "pre_registration": "docs/experiments/2026-07-30-d0b-totals-market/"
                                "PRE-REGISTRATION.md",
            "selects_nothing": True,
            "model_column_is_in_sample": True,
            "provider": PROVIDER,
            "fit_seasons": list(FIT_SEASONS),
            "scored_seasons": list(SCORED_SEASONS),
            "bootstrap_seed": BOOTSTRAP_SEED,
            "results": results,
            "pooled": pooled_result(results),
        }
        args.emit_json.write_text(json.dumps(payload, indent=2, default=str))
        log.info("wrote %s", args.emit_json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
