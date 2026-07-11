"""Wave 1 finals projections: 5,000-run Monte Carlo of remaining nrl
fixtures, seeded from the CURRENT ladder + Elo state, producing
top8/top4/minor-premiership probabilities per team. Delete-then-insert into
nrl_projections each run (mirrors pipeline.prob_snapshots' _replace_day
idiom, at table granularity) so a re-run stays idempotent. A `nrl-refresh`
pipeline step (see .github/workflows/nrl-refresh.yml).

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
) -> dict[int, dict]:
    """Return {team_id: {"top8": p, "top4": p, "minor_premiership": p}} across
    `n_runs` simulated completions of `remaining`. Pure -- no DB access, so the
    Monte Carlo core is unit-testable without a database."""
    # Unseeded by design: each production refresh should genuinely resample; tests inject a seeded Random.
    rng = rng or random.Random()
    counts = {t: {"top8": 0, "top4": 0, "minor_premiership": 0} for t in team_ids}
    if n_runs == 0 or not team_ids:
        return counts

    for _ in range(n_runs):
        points = {t: starting.get(t, {}).get("points", 0) for t in team_ids}
        diff = {t: starting.get(t, {}).get("diff", 0) for t in team_ids}

        for m in remaining:
            if m.home_team_id not in points or m.away_team_id not in points:
                continue
            elo_home = elos.get(m.home_team_id, 1500.0)
            elo_away = elos.get(m.away_team_id, 1500.0)
            out = predict(elo_home, elo_away, params)
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
            # written back as a real score.
            margin = max(1.0, abs(rng.gauss(out["expected_margin"], params.margin_sigma)))
            if outcome == "home":
                points[m.home_team_id] += 2
                diff[m.home_team_id] += margin
                diff[m.away_team_id] -= margin
            else:
                points[m.away_team_id] += 2
                diff[m.away_team_id] += margin
                diff[m.home_team_id] -= margin

        ranked = sorted(team_ids, key=lambda t: (-points[t], -diff[t], t))
        for rank, t in enumerate(ranked, start=1):
            if rank <= 8:
                counts[t]["top8"] += 1
            if rank <= 4:
                counts[t]["top4"] += 1
            if rank == 1:
                counts[t]["minor_premiership"] += 1

    return {t: {k: v / n_runs for k, v in c.items()} for t, c in counts.items()}


def _replace_projections(db: Session, rows: list[NrlProjection]) -> int:
    db.query(NrlProjection).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def run(
    db: Session, season: int | None = None, n_runs: int = N_RUNS,
    rng: random.Random | None = None,
) -> int:
    """Compute + store finals projections for `season` (latest if omitted).
    Returns the number of team rows written (0 if no nrl data)."""
    if season is None:
        latest = (
            db.query(SportMatch.season)
            .filter(SportMatch.sport == SPORT)
            .order_by(SportMatch.season.desc())
            .first()
        )
        if latest is None:
            return 0
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
        return 0

    teams = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.sport == SPORT, SportTeam.id.in_(team_ids)).all()
    )
    starting = _ladder_from(m for m in season_matches if m.status == "finished")
    remaining = [m for m in season_matches if m.status == "scheduled"]
    elos = _current_elos(db)
    params = load_nrl_params()

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
