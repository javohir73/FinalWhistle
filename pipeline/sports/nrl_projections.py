"""Wave 1 finals projections: 5,000-run Monte Carlo of remaining nrl
fixtures, seeded from the CURRENT ladder + Elo state, producing
top8/top4/minor-premiership probabilities per team. Delete-then-insert into
nrl_projections each run (mirrors pipeline.prob_snapshots' _replace_day
idiom, at table granularity) so a re-run stays idempotent. A `nrl-refresh`
pipeline step (see .github/workflows/nrl-refresh.yml).

`load_season_state` (Slice 3) splits `run()`'s DB-loading half out so a
second caller -- the conditional/what-if projections API
(backend/app/api/nrl_intel.py) -- can load the identical season state and
call `simulate()` with a `forced` outcomes dict, without ever writing to
NrlProjection (that table stays the nightly snapshot only).

CLI: PYTHONPATH=backend:. python -m pipeline.sports.nrl_projections
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import NrlProjection, SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams, predict
from ml.sports.nrl.params import load_nrl_params
from pipeline.sports.nrl_predict import _current_elos

log = logging.getLogger(__name__)

SPORT = "nrl"
N_RUNS = 5000


def _ladder_from(matches) -> dict[int, dict]:
    """Points + points-diff for every team across `matches` (FINISHED only;
    2 pts/win, 1/draw -- same rule as backend.app.api.sports.nrl_ladder).
    Pure -- takes an iterable of SportMatch, not a DB session."""
    table: dict[int, dict] = {}

    def row(team_id: int) -> dict:
        return table.setdefault(team_id, {"points": 0, "diff": 0})

    for m in matches:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        if m.score_home is None or m.score_away is None:
            continue
        h, a = row(m.home_team_id), row(m.away_team_id)
        h["diff"] += m.score_home - m.score_away
        a["diff"] += m.score_away - m.score_home
        if m.score_home > m.score_away:
            h["points"] += 2
        elif m.score_home < m.score_away:
            a["points"] += 2
        else:
            h["points"] += 1
            a["points"] += 1
    return table


def simulate(
    team_ids: list[int],
    starting: dict[int, dict],
    remaining: list[SportMatch],
    elos: dict[int, float],
    params: NrlParams,
    n_runs: int = N_RUNS,
    rng: random.Random | None = None,
    forced: dict[int, str] | None = None,
    track_expected: bool = False,
) -> dict[int, dict]:
    """Return {team_id: {"top8": p, "top4": p, "minor_premiership": p}} across
    `n_runs` simulated completions of `remaining`. Pure -- no DB access, so the
    Monte Carlo core is unit-testable without a database.

    `forced` (Slice 3, conditional projections): {match_id: "home"|"away"} --
    a forced fixture skips its win/draw/away roll and uses that outcome in
    EVERY run instead; everything else (points/diff bookkeeping, the margin
    sample for the diff tie-break, the tiebreak/aggregation below) is
    unchanged. Default None (equivalent to {}) preserves the original
    behavior byte-for-byte -- the nightly `run()` path never passes it.

    `track_expected` (Slice 3): also returns each team's "expected_points"/
    "expected_wins" (means across all n_runs) alongside the base three keys.
    Default False keeps the return shape identical to before this parameter
    existed, so nrl_projections_test.py's exact-dict-equality assertions
    keep passing unmodified.
    """
    # Unseeded by design: each production refresh should genuinely resample; tests inject a seeded Random.
    rng = rng or random.Random()
    forced = forced or {}
    counts = {t: {"top8": 0, "top4": 0, "minor_premiership": 0} for t in team_ids}
    points_total = {t: 0.0 for t in team_ids}
    wins_total = {t: 0 for t in team_ids}
    if n_runs == 0 or not team_ids:
        if track_expected:
            return {t: {**c, "expected_points": 0, "expected_wins": 0} for t, c in counts.items()}
        return counts

    for _ in range(n_runs):
        points = {t: starting.get(t, {}).get("points", 0) for t in team_ids}
        diff = {t: starting.get(t, {}).get("diff", 0) for t in team_ids}
        wins = {t: 0 for t in team_ids}

        for m in remaining:
            if m.home_team_id not in points or m.away_team_id not in points:
                continue
            elo_home = elos.get(m.home_team_id, 1500.0)
            elo_away = elos.get(m.away_team_id, 1500.0)
            out = predict(elo_home, elo_away, params)

            forced_outcome = forced.get(m.id)
            if forced_outcome is not None:
                outcome = forced_outcome
            else:
                roll = rng.random()
                if roll < out["p_home"]:
                    outcome = "home"
                elif roll < out["p_home"] + out["p_draw"]:
                    outcome = "draw"
                else:
                    outcome = "away"

            if outcome == "draw":
                points[m.home_team_id] += 1
                points[m.away_team_id] += 1
                continue

            # Margin sampling for points-differential tie-breaks only -- never
            # written back as a real score. Sampled even for a forced outcome
            # so a forced win still produces a plausible (non-zero) diff.
            margin = max(1.0, abs(rng.gauss(out["expected_margin"], params.margin_sigma)))
            if outcome == "home":
                points[m.home_team_id] += 2
                diff[m.home_team_id] += margin
                diff[m.away_team_id] -= margin
                wins[m.home_team_id] += 1
            else:
                points[m.away_team_id] += 2
                diff[m.away_team_id] += margin
                diff[m.home_team_id] -= margin
                wins[m.away_team_id] += 1

        ranked = sorted(team_ids, key=lambda t: (-points[t], -diff[t], t))
        for rank, t in enumerate(ranked, start=1):
            if rank <= 8:
                counts[t]["top8"] += 1
            if rank <= 4:
                counts[t]["top4"] += 1
            if rank == 1:
                counts[t]["minor_premiership"] += 1
        for t in team_ids:
            points_total[t] += points[t]
            wins_total[t] += wins[t]

    result = {t: {k: v / n_runs for k, v in c.items()} for t, c in counts.items()}
    if track_expected:
        for t in team_ids:
            result[t]["expected_points"] = points_total[t] / n_runs
            result[t]["expected_wins"] = wins_total[t] / n_runs
    return result


def _replace_projections(db: Session, rows: list[NrlProjection]) -> int:
    db.query(NrlProjection).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def load_season_state(
    db: Session, season: int | None = None,
) -> tuple[int, list[int], dict[int, str], dict[int, dict], list[SportMatch], dict[int, float], NrlParams] | None:
    """Resolve `season` (latest if omitted) and load everything `simulate()`
    needs to run it: team ids, a team-name lookup, starting ladder state
    (points/diff from FINISHED matches only), remaining (scheduled) fixtures,
    current Elo ratings, and model params.

    This is `run()`'s DB-loading half, split out (Slice 3) so a second
    caller can load the identical state -- e.g. the conditional-projections
    API, which builds a `forced` dict and calls `simulate()` directly
    without ever touching NrlProjection. Returns None when the season
    resolves to no nrl data at all (mirrors the original `run()`'s early
    `if not team_ids: return 0`).
    """
    if season is None:
        latest = (
            db.query(SportMatch.season)
            .filter(SportMatch.sport == SPORT)
            .order_by(SportMatch.season.desc())
            .first()
        )
        if latest is None:
            return None
        season = latest[0]

    season_matches = (
        db.query(SportMatch)
        .filter(SportMatch.sport == SPORT, SportMatch.season == season)
        .all()
    )
    team_ids = sorted({
        tid for m in season_matches for tid in (m.home_team_id, m.away_team_id) if tid is not None
    })
    if not team_ids:
        return None

    teams = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.sport == SPORT, SportTeam.id.in_(team_ids)).all()
    )
    starting = _ladder_from(m for m in season_matches if m.status == "finished")
    remaining = [m for m in season_matches if m.status == "scheduled"]
    elos = _current_elos(db)
    params = load_nrl_params()
    return season, team_ids, teams, starting, remaining, elos, params


def run(
    db: Session, season: int | None = None, n_runs: int = N_RUNS,
    rng: random.Random | None = None,
) -> int:
    """Compute + store finals projections for `season` (latest if omitted).
    Returns the number of team rows written (0 if no nrl data)."""
    state = load_season_state(db, season)
    if state is None:
        return 0
    season, team_ids, teams, starting, remaining, elos, params = state

    probs = simulate(team_ids, starting, remaining, elos, params, n_runs=n_runs, rng=rng)
    now = datetime.now(timezone.utc)
    out_rows = [
        NrlProjection(
            team=teams.get(t, "Unknown"),
            top8=probs[t]["top8"], top4=probs[t]["top4"],
            minor_premiership=probs[t]["minor_premiership"],
            computed_at=now,
        )
        for t in team_ids
    ]
    return _replace_projections(db, out_rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        n = run(db)
        log.info("nrl projections: %d team row(s) written", n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
