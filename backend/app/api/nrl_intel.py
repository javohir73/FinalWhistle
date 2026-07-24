"""NRL Match Intelligence (Wave 1): per-match detail (prediction, form, h2h,
factors), finals projections (the nightly snapshot, plus a Slice 3
conditional/what-if variant), and NRL probability history. A separate router
from app.api.sports (same /api/nrl prefix, different paths -- mirrors how
football splits /api/matches across matches.py and prob_history.py).
"""
from __future__ import annotations

import random
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlProjection, ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam
from pipeline.sports.nrl_form import _kickoff_key, form_averages, last_n_results
from pipeline.sports.nrl_projections import load_season_state, simulate

router = APIRouter(prefix="/api/nrl", tags=["nrl-intel"])

SPORT = "nrl"
_DISCLAIMER = "For analytics and entertainment only. Not betting advice."


_FORM_OVERFETCH = 1000  # effectively "all" -- no NRL team accumulates this many
                        # finished matches in the dataset; used so filtering out
                        # the h2h opponent below still leaves a true last-5.


def _team_form_block(db: Session, team_id: int, before: SportMatch,
                      exclude_opponent_id: int | None = None) -> dict:
    """Last-5 finished results and averages for `team_id`, ahead of `before`.

    `exclude_opponent_id` drops meetings against the upcoming match's other
    side: those are already surfaced in the `h2h` block, so counting them here
    too would double up the same data point across both panels and (for a
    team that meets its next opponent often) crowd out genuinely different
    recent form. Overfetch first, then filter, then truncate -- filtering
    after `last_n_results` already limited to 5 could otherwise leave fewer
    than 5 even when 5 non-h2h results exist.
    """
    raw = last_n_results(db, team_id, n=_FORM_OVERFETCH, before=before)
    if exclude_opponent_id is not None:
        raw = [r for r in raw if r["opponent_id"] != exclude_opponent_id]
    results = raw[:5]
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    last5 = [
        {"round": r["round"], "opponent": names.get(r["opponent_id"], "Unknown"),
         "result": r["result"], "for": r["for"], "against": r["against"]}
        for r in results
    ]
    return {"last5": last5, **form_averages(results)}


def _head_to_head(db: Session, home_id: int, away_id: int, exclude_match_id: int,
                   limit: int = 5) -> list[dict]:
    rows = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT, SportMatch.status == "finished",
            SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None),
            SportMatch.id != exclude_match_id,
            or_(
                (SportMatch.home_team_id == home_id) & (SportMatch.away_team_id == away_id),
                (SportMatch.home_team_id == away_id) & (SportMatch.away_team_id == home_id),
            ),
        )
        .all()
    )
    rows.sort(key=_kickoff_key, reverse=True)
    rows = rows[:limit]
    names = dict(db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == SPORT).all())
    out = []
    for m in rows:
        winner = ("home" if m.score_home > m.score_away
                  else "away" if m.score_away > m.score_home else "draw")
        out.append({
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "home": names.get(m.home_team_id, "Unknown"),
            "away": names.get(m.away_team_id, "Unknown"),
            "score_home": m.score_home, "score_away": m.score_away, "winner": winner,
        })
    return out


def _composite(form: dict) -> float:
    results = form["last5"]
    win_rate = (sum(1 for r in results if r["result"] == "W") / len(results)) if results else 0.5
    return win_rate * 0.6 + (form["avg_margin"] / 40.0) * 0.4


def _build_factors(home: SportTeam, away: SportTeam, home_form: dict, away_form: dict) -> list[dict]:
    elo_home = home.elo_rating if home.elo_rating is not None else 1500.0
    elo_away = away.elo_rating if away.elo_rating is not None else 1500.0
    elo_favors = "home" if elo_home >= elo_away else "away"
    form_favors = "home" if _composite(home_form) >= _composite(away_form) else "away"

    return [
        {"key": "elo_gap", "label": "Elo rating gap", "weight": 0.5, "favors": elo_favors},
        {"key": "form_composite", "label": "Recent form", "weight": 0.3, "favors": form_favors},
        {"key": "home_advantage", "label": "Home advantage", "weight": 0.2, "favors": "home"},
    ]


@router.get("/matches/{match_id}")
def nrl_match_detail(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    home = db.get(SportTeam, m.home_team_id) if m.home_team_id else None
    away = db.get(SportTeam, m.away_team_id) if m.away_team_id else None

    match_out = {
        "id": m.id, "season": m.season, "round": m.round, "match_no": m.match_no,
        "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
        "venue": m.venue, "home": home.name if home else None, "away": away.name if away else None,
        "home_team_id": m.home_team_id, "away_team_id": m.away_team_id,
        "score_home": m.score_home, "score_away": m.score_away, "status": m.status,
    }

    pred = (
        db.query(SportPrediction).filter_by(match_id=m.id)
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .first()
    )
    prediction_out = None
    if pred is not None:
        prediction_out = {
            "home_prob": pred.p_home, "away_prob": pred.p_away, "draw_prob": pred.p_draw,
            "predicted_margin": pred.predicted_margin, "predicted_total": pred.predicted_total,
            "model_version": pred.model_version, "preview_text": pred.preview_text,
        }

    home_form = (
        _team_form_block(db, m.home_team_id, before=m, exclude_opponent_id=m.away_team_id)
        if m.home_team_id else None
    )
    away_form = (
        _team_form_block(db, m.away_team_id, before=m, exclude_opponent_id=m.home_team_id)
        if m.away_team_id else None
    )

    factors: list[dict] = []
    if home is not None and away is not None and home_form is not None and away_form is not None:
        factors = _build_factors(home, away, home_form, away_form)

    h2h = (
        _head_to_head(db, m.home_team_id, m.away_team_id, exclude_match_id=m.id)
        if (m.home_team_id and m.away_team_id) else []
    )

    return {
        "match": match_out,
        "prediction": prediction_out,
        "form": {"home": home_form, "away": away_form},
        "h2h": h2h,
        "factors": factors,
    }


@router.get("/projections")
def nrl_projections(db: Session = Depends(get_db)):
    rows = db.query(NrlProjection).order_by(NrlProjection.top8.desc()).all()
    computed_at = rows[0].computed_at if rows else None
    return {
        "computed_at": computed_at.isoformat() if computed_at else None,
        "teams": [
            {"team": r.team, "top8": r.top8, "top4": r.top4,
             "minor_premiership": r.minor_premiership}
            for r in rows
        ],
    }


_PICK_RE = re.compile(r"^(\d+)([ha])$")
_N_SIMS = 2000  # module constant: the default AND only value -- no client
                # control over sim count (perf discipline, Render free tier;
                # nrl_projections.N_RUNS's 5000 is fine nightly because it
                # isn't latency-sensitive, but a per-request path is).


def _seed_for(season: int, forced: dict[int, str], n_sims: int) -> str:
    """Stable seed for (season, forced picks, n_sims) -- identical requests
    (same season + same picks, any order) always resolve to the identical
    seed, so `simulate()` returns a byte-identical body and the default
    `public, max-age=60` Cache-Control (app.main.cache_control's generic GET
    /api/* branch, which this path is not excluded from) plus any CDN in
    front of it can serve repeats without re-simulating. `random.Random(str)`
    seeds deterministically from a SHA-512 digest of the string (cpython's
    Lib/random.py), independent of PYTHONHASHSEED."""
    picks_key = ",".join(sorted(f"{mid}{outcome[0]}" for mid, outcome in forced.items()))
    return f"nrl-conditional|{season}|{picks_key}|{n_sims}"


def _parse_picks(db: Session, season: int, remaining: list[SportMatch], picks: str) -> dict[int, str]:
    """Decode the `picks` query param into {match_id: "home"|"away"} --
    comma-separated `<match_id><h|a>` tokens (e.g. "123h,456a"), order-
    insensitive. No draw option: a pick here is "who makes the finals push",
    i.e. who wins, not whether it draws. Raises HTTPException(422) on any
    invalid input -- the frontend must mirror this exact encoding."""
    tokens = [t for t in picks.split(",") if t]
    if not tokens:
        return {}

    remaining_ids = {m.id for m in remaining}
    if len(tokens) > len(remaining_ids):
        raise HTTPException(status_code=422, detail={
            "code": "too_many_picks",
            "message": f"At most {len(remaining_ids)} pick(s) allowed for season {season}'s "
                       f"remaining fixtures ({len(tokens)} given).",
        })

    forced: dict[int, str] = {}
    for tok in tokens:
        match = _PICK_RE.match(tok.strip())
        if not match:
            raise HTTPException(status_code=422, detail={
                "code": "bad_picks_encoding",
                "message": f"Malformed pick {tok!r} -- expected <match_id><h|a>, e.g. '123h'.",
            })
        match_id, outcome = int(match.group(1)), ("home" if match.group(2) == "h" else "away")
        if match_id in forced:
            raise HTTPException(status_code=422, detail={
                "code": "duplicate_pick",
                "message": f"Match {match_id} picked more than once.",
            })
        forced[match_id] = outcome

    unpickable = sorted(mid for mid in forced if mid not in remaining_ids)
    if unpickable:
        # Distinguish "doesn't exist" from "exists but isn't an unfinished
        # fixture this season" only for a clearer message -- either way the
        # whole request is rejected rather than silently dropping the pick.
        existing = {
            mid for (mid,) in db.query(SportMatch.id)
            .filter(SportMatch.sport == SPORT, SportMatch.id.in_(unpickable)).all()
        }
        bad_id = unpickable[0]
        if bad_id not in existing:
            raise HTTPException(status_code=422, detail={
                "code": "unknown_match_id", "message": f"No NRL match {bad_id}.",
            })
        raise HTTPException(status_code=422, detail={
            "code": "match_not_remaining",
            "message": f"Match {bad_id} is not an unfinished fixture in season {season}.",
        })
    return forced


@router.get("/projections/conditional")
def nrl_projections_conditional(
    season: int | None = None, picks: str = "", db: Session = Depends(get_db),
):
    """CONDITIONAL finals projection (Slice 3, "the finals-race machine"):
    the caller's `picks` become forced outcomes inside the SAME Monte Carlo
    `simulate()` the nightly `nrl_projections.run()` uses -- unpicked
    matches keep sampling from the model's win probabilities. Never writes
    NrlProjection (that table is the nightly snapshot GET /projections
    reads) -- this is a read-only, request-scoped variant, so a share-link
    full of picks can never corrupt the real snapshot.

    `picks` encoding (the frontend must mirror it): comma-separated
    `<match_id><h|a>` tokens, e.g. "123h,456a" -- `h`/`a` force that match's
    home/away team to win. Order-insensitive; empty/omitted `picks` runs the
    unconditioned simulation -- same machinery as the nightly job, just not
    persisted (numbers won't match the last nightly run bit for bit, since
    both are independently stochastic, but the distribution is the same).

    `n_sims` is fixed at `_N_SIMS` -- no client control, so there's no
    request-driven way to inflate simulation cost. The RNG is seeded from
    (season, sorted picks, n_sims) (see `_seed_for`) so this GET is safely
    cacheable: identical requests return identical bodies.
    """
    state = load_season_state(db, season)
    if state is None:
        detail = (
            {"code": "season_not_found", "message": f"No NRL matches for season {season}"}
            if season is not None
            else {"code": "no_nrl_data", "message": "No NRL matches are loaded yet"}
        )
        raise HTTPException(status_code=404, detail=detail)
    resolved_season, team_ids, teams, starting, remaining, elos, params = state

    forced = _parse_picks(db, resolved_season, remaining, picks)
    rng = random.Random(_seed_for(resolved_season, forced, _N_SIMS))
    probs = simulate(team_ids, starting, remaining, elos, params,
                     n_runs=_N_SIMS, rng=rng, forced=forced, track_expected=True)

    ordered = sorted(
        team_ids,
        key=lambda t: (-probs[t]["top8"], -probs[t]["expected_points"], teams.get(t, "")),
    )
    return {
        "season": resolved_season,
        "n_sims": _N_SIMS,
        "picks_applied": len(forced),
        "teams": [
            {
                "team": teams.get(t, "Unknown"),
                "top8": probs[t]["top8"],
                "top4": probs[t]["top4"],
                "minor_premiership": probs[t]["minor_premiership"],
                "expected_points": probs[t]["expected_points"],
                "expected_wins": probs[t]["expected_wins"],
            }
            for t in ordered
        ],
    }


@router.get("/matches/{match_id}/prob-history")
def nrl_prob_history(match_id: int, db: Session = Depends(get_db)):
    m = db.get(SportMatch, match_id)
    if m is None or m.sport != SPORT:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found", "message": f"No NRL match {match_id}",
        })

    rows = (
        db.query(ProbabilitySnapshot)
        .filter(ProbabilitySnapshot.sport == SPORT, ProbabilitySnapshot.market == "win_match",
                ProbabilitySnapshot.ref_id == match_id)
        .order_by(ProbabilitySnapshot.snapshot_date.asc())
        .all()
    )
    by_day: dict[date, dict[int, float]] = {}
    for r in rows:
        by_day.setdefault(r.snapshot_date, {})[r.entity_id] = r.prob

    points = []
    for day, by_entity in sorted(by_day.items()):
        p_home = by_entity.get(m.home_team_id)
        p_away = by_entity.get(m.away_team_id)
        if p_home is None and p_away is None:
            continue
        p_draw = round(1.0 - p_home - p_away, 6) if p_home is not None and p_away is not None else None
        points.append({"date": day.isoformat(), "p_home": p_home, "p_draw": p_draw, "p_away": p_away})

    return {"match_id": match_id, "points": points, "disclaimer": _DISCLAIMER}
