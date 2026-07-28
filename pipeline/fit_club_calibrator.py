"""Fit the reviewed q3 calibrator artifact for one league. One-shot, offline.

T1.6 (`docs/MODEL-EXPERIMENTS.md`) selected `refit_q3` for Bundesliga as the
only candidate surviving multiplicity correction. That experiment refitted the
blob per outer season; what a live shadow twin needs is ONE frozen artifact,
fitted on the whole pre-confirmation block, serialized with its provenance.

Holdout safety: this fits on exactly the 27 manifest-verified captures for
2016-17..2024-25. The consumed 2025-26 season is excluded at load AND the
manifest verification is scoped to `pre_confirmation_keys()`, so the holdout is
never opened — hashing a file is a read. `assert_holdout_absent` is a backstop.

Determinism: `fit_vector_scaling` is coordinate descent over fixed grids with
no RNG, so re-running on the same inputs reproduces the artifact byte for byte.
A test asserts that.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.fit_club_calibrator \\
        --league bundesliga --csv-dir <captures> \\
        --out ml/models/calibrators/bundesliga_q3.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ml.evaluation.calibration import assert_servable_calibrator, effective_gap
from ml.evaluation.club_calibration import (
    CANDIDATES,
    assert_holdout_absent,
    fit_segmented,
    occupancy,
    quantile_edges,
)
from ml.evaluation.club_walkforward import ClubMatch, EloConfig, replay
from ml.models.params import load_params
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix
from pipeline.club_data_manifest import (
    PRE_CONFIRMATION_SEASONS,
    load_manifest,
    pre_confirmation_keys,
    verify,
)
from pipeline.experiment_club_calibration import LEAGUES, load_league

#: Only leagues whose recut survived Bonferroni in T1.6 may be fitted here.
#: EPL was nominal-only; La Liga showed no effect. Fitting an artifact for
#: either would invite promoting a candidate that never qualified.
ELIGIBLE = {"bundesliga"}


def manifest_digest() -> str:
    """Stable digest over the 27 pre-confirmation manifest entries.

    Pins the artifact to the exact raw bytes it was fitted on: if upstream
    revises a season file, this digest moves and the artifact is stale.
    """
    man = load_manifest()["files"]
    payload = "".join(f"{k}:{man[k]['sha256']};" for k in sorted(pre_confirmation_keys()))
    return hashlib.sha256(payload.encode()).hexdigest()


def fit(league: str, csv_dir: Path, n_buckets: int = 3, min_bucket: int = 200) -> dict:
    if league not in ELIGIBLE:
        raise ValueError(
            f"{league!r} is not eligible: only {sorted(ELIGIBLE)} cleared T1.6's "
            "multiplicity-corrected gate. See docs/MODEL-EXPERIMENTS.md."
        )
    div, comp, home_adv, ship_base = next(x for x in LEAGUES if x[0] ==
                                          {"bundesliga": "D1"}[league])
    v = verify(csv_dir, keys=pre_confirmation_keys())
    if not v["reproducible"]:
        raise RuntimeError(
            f"raw captures do not match the manifest (drifted="
            f"{len(v['drifted'])}, missing={len(v['missing'])}); refusing to fit "
            "an artifact whose provenance cannot be stated"
        )

    df, _trip = load_league(div, csv_dir)
    seasons = sorted(set(df.season_code))
    assert_holdout_absent(seasons, "fit_club_calibrator")
    if tuple(seasons) != PRE_CONFIRMATION_SEASONS:
        raise RuntimeError(f"expected exactly {PRE_CONFIRMATION_SEASONS}, got {tuple(seasons)}")

    p = load_params()
    ms = [ClubMatch(r.season_code, r.HomeTeam, r.AwayTeam, int(r.FTHG), int(r.FTAG),
                    r.match_date.date().isoformat()) for r in df.itertuples(index=False)]
    pre = replay(ms, EloConfig(home_adv=home_adv), comp)

    probs, labels, gaps = [], [], []
    for m, pp in zip(ms, pre):
        lh, la = expected_goals_from_elo(pp[0], pp[1], home_adv=home_adv,
                                         base=ship_base, beta=p.beta)
        probs.append(outcome_probabilities(score_matrix(lh, la, rho=p.rho)))
        gaps.append(effective_gap(pp[0], pp[1], home_adv))
        labels.append(0 if m.goals_home > m.goals_away
                      else (1 if m.goals_home == m.goals_away else 2))

    edges = quantile_edges(gaps, n_buckets)
    blob = fit_segmented(probs, labels, gaps, edges, min_bucket=min_bucket)
    assert_servable_calibrator(blob)

    blob["provenance"] = {
        "candidate": "refit_q3",
        "league": league,
        "fitted_on_seasons": list(PRE_CONFIRMATION_SEASONS),
        "excluded_holdout_season": "2526",
        "manifest_files_verified": v["expected"],
        "manifest_digest_sha256": manifest_digest(),
        "engine": {"base": ship_base, "beta": p.beta, "rho": p.rho,
                   "home_adv": home_adv, "served_params_version": p.version},
        "fit": {"n_buckets": n_buckets, "min_bucket": min_bucket,
                "grid": CANDIDATES["refit_q3"]},
        "command": (f"python -m pipeline.fit_club_calibrator --league {league} "
                    f"--csv-dir <captures> --out <artifact>"),
        "note": ("Fitted ONCE on the whole pre-confirmation block. T1.6's archived "
                 "nested results refit per outer season and are NOT this artifact; "
                 "they are not restated."),
    }
    blob["bucket_occupancy_train"] = occupancy(gaps, edges)
    return blob


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", default="bundesliga", choices=sorted(ELIGIBLE))
    ap.add_argument("--csv-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-buckets", type=int, default=3)
    ap.add_argument("--min-bucket", type=int, default=200)
    args = ap.parse_args()

    blob = fit(args.league, args.csv_dir, args.n_buckets, args.min_bucket)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(blob, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    print(f"  edges     : {blob['edges']}")
    print(f"  n_train   : {blob['n_train']}")
    print(f"  occupancy : {blob['bucket_occupancy_train']}")
    print(f"  thin      : {blob['thin_buckets'] or 'none'}")
    print(f"  manifest  : {blob['provenance']['manifest_digest_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
