"""Read-only NRL API (multi-sport vertical, task 6).

All endpoints are read-only: `/matches` (fixtures grouped by round, each with
its LATEST prediction attached — shadow included, since this endpoint IS the
shadow surface pre-launch, unlike football's public /api/matches which filters
shadow rows out via serializers.latest_prediction), `/model/record` (the same
record shape family as football's /api/model/record, computed from the graded
SportPredictionResult ledger), `/ladder` (computed standings) and
`/teams/{id}` (club profile: ladder slot, season splits, results graded
against the ledger, upcoming fixtures with the club's win chance).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import aliased, Session

from app.api.model_record import wilson_ci95
from app.db import get_db
from app.models import (
    NrlMatchStat,
    NrlTryEvent,
    SportMatch,
    SportPrediction,
    SportPredictionResult,
    SportTeam,
)

router = APIRouter(prefix="/api/nrl", tags=["nrl"])


def _latest_season(db: Session) -> int | None:
    row = (
        db.query(SportMatch.season)
        .filter(SportMatch.sport == "nrl")
        .order_by(SportMatch.season.desc())
        .first()
    )
    return row[0] if row else None


@router.get("/matches")
def nrl_matches(round: int | None = None, season: int | None = None,
                db: Session = Depends(get_db)):
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    home = aliased(SportTeam)
    away = aliased(SportTeam)
    q = (
        db.query(SportMatch, home.name, away.name)
        .outerjoin(home, SportMatch.home_team_id == home.id)
        .outerjoin(away, SportMatch.away_team_id == away.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season)
    )
    if round is not None:
        q = q.filter(SportMatch.round == round)
    rows = q.order_by(
        SportMatch.round.asc(), SportMatch.kickoff_utc.is_(None),
        SportMatch.kickoff_utc.asc(), SportMatch.match_no.asc(),
    ).all()

    if not rows:
        detail = (
            {"code": "round_not_found", "message": f"No matches for round {round} in season {season}"}
            if round is not None
            else {"code": "season_not_found", "message": f"No NRL matches for season {season}"}
        )
        raise HTTPException(status_code=404, detail=detail)

    match_ids = [m.id for m, _, _ in rows]
    # Latest prediction per match_id, single query (avoid N+1): pull every
    # prediction for the page's matches ordered so the first row seen per
    # match_id is the latest one (created_at desc, id desc — same tiebreak as
    # serializers.latest_prediction).
    preds = (
        db.query(SportPrediction)
        .filter(SportPrediction.match_id.in_(match_ids))
        .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
        .all()
    )
    latest_pred_by_match: dict[int, SportPrediction] = {}
    for p in preds:
        latest_pred_by_match.setdefault(p.match_id, p)

    rounds: dict[int, list[dict]] = {}
    for m, home_name, away_name in rows:
        pred = latest_pred_by_match.get(m.id)
        pred_out = None
        if pred is not None:
            pred_out = {
                "p_home": pred.p_home,
                "p_draw": pred.p_draw,
                "p_away": pred.p_away,
                "expected_margin": pred.expected_margin,
                "model_version": pred.model_version,
                "created_at": pred.created_at.isoformat() if pred.created_at else None,
                "is_shadow": pred.is_shadow,
            }
        rounds.setdefault(m.round, []).append({
            "id": m.id,
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "home": home_name,
            "away": away_name,
            "home_team_id": m.home_team_id,
            "away_team_id": m.away_team_id,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "status": m.status,
            "prediction": pred_out,
        })

    return {
        "season": season,
        "rounds": [
            {"round": r, "matches": matches}
            for r, matches in sorted(rounds.items(), key=lambda kv: (kv[0] is None, kv[0]))
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


@router.get("/model/record")
def nrl_model_record(db: Session = Depends(get_db)):
    from ml.sports.nrl.params import load_nrl_params

    model_version = load_nrl_params().version

    rows = (
        db.query(SportPredictionResult, SportMatch)
        .join(SportMatch, SportPredictionResult.match_id == SportMatch.id)
        .filter(SportMatch.sport == "nrl")
        .order_by(SportPredictionResult.evaluated_at.asc())
        .all()
    )

    n = len(rows)
    if n == 0:
        return {
            "evaluated_matches": 0,
            "winner_accuracy": None,
            "winner_accuracy_ci95": None,
            "avg_log_loss": None,
            "avg_brier": None,
            "best_streak": 0,
            "model_version": model_version,
            "last_updated": None,
            "disclaimer": "For analytics and entertainment only. Not betting advice.",
        }

    winners = sum(1 for r, _ in rows if r.winner_correct)

    # Longest run of correct winner calls in kickoff order (not evaluation
    # order), same rationale as football's model_record.best_streak.
    by_kickoff = sorted(rows, key=lambda t: (t[1].kickoff_utc is None, t[1].kickoff_utc, t[1].id))
    best_streak = streak = 0
    for r, _ in by_kickoff:
        streak = streak + 1 if r.winner_correct else 0
        best_streak = max(best_streak, streak)

    last_updated = max(r.evaluated_at for r, _ in rows)

    return {
        "evaluated_matches": n,
        "winner_accuracy": round(winners / n, 4),
        "winner_accuracy_ci95": wilson_ci95(winners, n),
        "avg_log_loss": round(sum(r.log_loss for r, _ in rows) / n, 4),
        "avg_brier": round(sum(r.brier for r, _ in rows) / n, 4),
        "best_streak": best_streak,
        "model_version": model_version,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


@router.get("/ladder")
def nrl_ladder(season: int | None = None, db: Session = Depends(get_db)):
    """Computed ladder: 2 pts/win, 1/draw, ordered by points then for-against diff."""
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    season_exists = (
        db.query(SportMatch.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season)
        .first()
    )
    if season_exists is None:
        raise HTTPException(status_code=404, detail={
            "code": "season_not_found",
            "message": f"No NRL matches for season {season}",
        })

    finished = (
        db.query(SportMatch)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season,
                SportMatch.status == "finished",
                SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None))
        .all()
    )
    table: dict[int, dict] = {}

    def row(team_id: int) -> dict:
        return table.setdefault(team_id, {
            "team_id": team_id, "played": 0, "wins": 0, "draws": 0,
            "losses": 0, "points": 0, "diff": 0,
        })

    for m in finished:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        h, a = row(m.home_team_id), row(m.away_team_id)
        h["played"] += 1; a["played"] += 1
        h["diff"] += m.score_home - m.score_away
        a["diff"] += m.score_away - m.score_home
        if m.score_home > m.score_away:
            h["wins"] += 1; h["points"] += 2; a["losses"] += 1
        elif m.score_home < m.score_away:
            a["wins"] += 1; a["points"] += 2; h["losses"] += 1
        else:
            h["draws"] += 1; a["draws"] += 1; h["points"] += 1; a["points"] += 1

    names = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.id.in_(table.keys())).all()
    ) if table else {}
    rows = sorted(
        ({**r, "name": names.get(r["team_id"], "Unknown")} for r in table.values()),
        key=lambda r: (-r["points"], -r["diff"], r["name"]),
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    return {"season": season, "rows": rows,
            "disclaimer": "For analytics and entertainment only. Not betting advice."}


@router.get("/teams/{team_id}")
def nrl_team(team_id: int, season: int | None = None, db: Session = Depends(get_db)):
    """Club profile for one season: ladder slot, W/D/L record with home/away
    splits, every finished result (graded against the SportPredictionResult
    ledger — never re-derived from raw predictions, so the profile can't
    disagree with /model/record), and upcoming fixtures with the club's
    latest win probability."""
    team = (
        db.query(SportTeam)
        .filter(SportTeam.id == team_id, SportTeam.sport == "nrl")
        .first()
    )
    if team is None:
        raise HTTPException(status_code=404, detail={
            "code": "team_not_found", "message": f"No NRL team with id {team_id}",
        })
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })
    elif (
        db.query(SportMatch.id)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season)
        .first()
    ) is None:
        raise HTTPException(status_code=404, detail={
            "code": "season_not_found",
            "message": f"No NRL matches for season {season}",
        })

    matches = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == "nrl", SportMatch.season == season,
            or_(SportMatch.home_team_id == team_id,
                SportMatch.away_team_id == team_id),
        )
        .all()
    )

    opp_ids = {
        (m.away_team_id if m.home_team_id == team_id else m.home_team_id)
        for m in matches
    } - {None}
    names = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.id.in_(opp_ids)).all()
    ) if opp_ids else {}

    # Chronological order without a sentinel datetime (SQLite hands back naive
    # kickoffs, Postgres aware — a mixed-key sort would blow up): dated matches
    # by kickoff, then undated ones by (round, match_no).
    def chrono(ms: list[SportMatch]) -> list[SportMatch]:
        dated = sorted((m for m in ms if m.kickoff_utc is not None),
                       key=lambda m: m.kickoff_utc)
        undated = sorted((m for m in ms if m.kickoff_utc is None),
                         key=lambda m: (m.round is None, m.round, m.match_no))
        return dated + undated

    finished = chrono([
        m for m in matches
        if m.status == "finished"
        and m.score_home is not None and m.score_away is not None
    ])
    next_up = chrono([m for m in matches if m.status != "finished"])[:5]

    # Grading comes from the append-only ledger; ungraded matches stay None.
    graded: dict[int, bool] = {}
    if finished:
        result_rows = (
            db.query(SportPredictionResult)
            .filter(SportPredictionResult.match_id.in_([m.id for m in finished]))
            .order_by(SportPredictionResult.evaluated_at.asc(),
                      SportPredictionResult.id.asc())
            .all()
        )
        for r in result_rows:
            graded[r.match_id] = r.winner_correct

    def match_ref(m: SportMatch) -> dict:
        was_home = m.home_team_id == team_id
        opp_id = m.away_team_id if was_home else m.home_team_id
        return {
            "id": m.id,
            "round": m.round,
            "match_no": m.match_no,
            "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            "venue": m.venue,
            "opponent": names.get(opp_id),
            "opponent_id": opp_id,
            "was_home": was_home,
        }

    results_chrono: list[dict] = []
    wins = draws = losses = points_for = points_against = 0
    home_split = {"wins": 0, "draws": 0, "losses": 0}
    away_split = {"wins": 0, "draws": 0, "losses": 0}
    for m in finished:
        was_home = m.home_team_id == team_id
        sf, sa = ((m.score_home, m.score_away) if was_home
                  else (m.score_away, m.score_home))
        result = "W" if sf > sa else "L" if sf < sa else "D"
        points_for += sf; points_against += sa
        split = home_split if was_home else away_split
        if result == "W":
            wins += 1; split["wins"] += 1
        elif result == "L":
            losses += 1; split["losses"] += 1
        else:
            draws += 1; split["draws"] += 1
        results_chrono.append({
            **match_ref(m),
            "score_for": sf,
            "score_against": sa,
            "result": result,
            "model_called": graded.get(m.id),
        })

    summary = None
    if results_chrono:
        last = results_chrono[-1]["result"]
        streak_len = 0
        for r in reversed(results_chrono):
            if r["result"] != last:
                break
            streak_len += 1
        margin = lambda r: r["score_for"] - r["score_against"]  # noqa: E731
        win_rows = [r for r in results_chrono if r["result"] == "W"]
        loss_rows = [r for r in results_chrono if r["result"] == "L"]
        played = len(results_chrono)
        summary = {
            "played": played, "wins": wins, "draws": draws, "losses": losses,
            "points_for": points_for, "points_against": points_against,
            "avg_for": round(points_for / played, 1),
            "avg_against": round(points_against / played, 1),
            "avg_margin": round((points_for - points_against) / played, 1),
            "home": home_split, "away": away_split,
            "streak": {"result": last, "length": streak_len},
            "biggest_win": max(win_rows, key=margin) if win_rows else None,
            "biggest_loss": min(loss_rows, key=margin) if loss_rows else None,
        }

    # Latest prediction per upcoming match — same dedup as /matches.
    latest_pred_by_match: dict[int, SportPrediction] = {}
    if next_up:
        preds = (
            db.query(SportPrediction)
            .filter(SportPrediction.match_id.in_([m.id for m in next_up]))
            .order_by(SportPrediction.created_at.desc(), SportPrediction.id.desc())
            .all()
        )
        for p in preds:
            latest_pred_by_match.setdefault(p.match_id, p)

    upcoming = []
    for m in next_up:
        pred = latest_pred_by_match.get(m.id)
        win_prob = None
        if pred is not None:
            win_prob = pred.p_home if m.home_team_id == team_id else pred.p_away
        upcoming.append({**match_ref(m), "win_prob": win_prob})

    model = None
    if graded:
        n = len(graded)
        called = sum(1 for correct in graded.values() if correct)
        model = {"graded": n, "called": called, "accuracy": round(called / n, 4)}

    ladder_slot = next(
        (r for r in nrl_ladder(season=season, db=db)["rows"] if r["team_id"] == team_id),
        None,
    )

    return {
        "season": season,
        "team": {"id": team.id, "name": team.name, "elo_rating": team.elo_rating},
        "ladder": ladder_slot,
        "summary": summary,
        "results": list(reversed(results_chrono)),
        "upcoming": upcoming,
        "model": model,
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


@router.get("/matches/{match_id}/stats")
def nrl_match_stats(match_id: int, db: Session = Depends(get_db)):
    """Team stat lines + try timeline for one finished NRL match (Wave 2
    contract): { home: TeamMatchStats, away: TeamMatchStats,
    try_timeline: TryEvent[] }. 404 stats_not_available until the
    nrl-refresh stats step has ingested this match."""
    match = (
        db.query(SportMatch)
        .filter(SportMatch.id == match_id, SportMatch.sport == "nrl")
        .first()
    )
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "match_not_found",
            "message": f"No NRL match with id {match_id}",
        })

    rows = db.query(NrlMatchStat).filter(NrlMatchStat.match_id == match_id).all()
    names = dict(
        db.query(SportTeam.id, SportTeam.name)
        .filter(SportTeam.id.in_([tid for tid in (match.home_team_id, match.away_team_id)
                                  if tid is not None]))
        .all()
    )
    by_team = {r.team: r for r in rows}
    home_row = by_team.get(names.get(match.home_team_id))
    away_row = by_team.get(names.get(match.away_team_id))
    if home_row is None or away_row is None:
        raise HTTPException(status_code=404, detail={
            "code": "stats_not_available",
            "message": f"No team stats ingested for match {match_id}",
        })

    def stat_line(r: NrlMatchStat) -> dict:
        return {
            "tries": r.tries, "conversions": r.conversions,
            "penalties_conceded": r.penalties_conceded, "errors": r.errors,
            "set_restarts": r.set_restarts, "run_metres": r.run_metres,
            "line_breaks": r.line_breaks, "tackles": r.tackles,
            "tackle_efficiency": r.tackle_efficiency,
        }

    events = (
        db.query(NrlTryEvent)
        .filter(NrlTryEvent.match_id == match_id)
        .order_by(NrlTryEvent.minute, NrlTryEvent.id)
        .all()
    )
    return {
        "home": stat_line(home_row),
        "away": stat_line(away_row),
        "try_timeline": [
            {"minute": e.minute, "team": e.team, "player": e.player,
             "score_home": e.score_home, "score_away": e.score_away}
            for e in events
        ],
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


def _slugify(name: str) -> str:
    """URL slug from a team name: 'Wests Tigers' -> 'wests-tigers'.
    Must stay in lockstep with slugify() in frontend/lib/nrlSlug.ts."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.get("/teams/{slug}/profile")
def nrl_team_profile(slug: str, season: int | None = None, db: Session = Depends(get_db)):
    """Attack/defence season ranks + venue splits (Wave 2 contract):
    { attack_rank, defence_rank, venue_splits, position_concessions }.
    Slugs derive from SportTeam.name (no slug column exists — 17 teams,
    resolved in-process). position_concessions is [] until Wave 3's
    team-lists ingest supplies player positions."""
    teams = db.query(SportTeam).filter(SportTeam.sport == "nrl").all()
    team = next((t for t in teams if _slugify(t.name) == slug), None)
    if team is None:
        raise HTTPException(status_code=404, detail={
            "code": "team_not_found",
            "message": f"No NRL team with slug {slug!r}",
        })
    if season is None:
        season = _latest_season(db)
        if season is None:
            raise HTTPException(status_code=404, detail={
                "code": "no_nrl_data", "message": "No NRL matches are loaded yet",
            })

    finished = (
        db.query(SportMatch)
        .filter(SportMatch.sport == "nrl", SportMatch.season == season,
                SportMatch.status == "finished",
                SportMatch.score_home.isnot(None), SportMatch.score_away.isnot(None))
        .all()
    )

    # Per-team scoring aggregates over the season's finished matches.
    agg: dict[int, dict] = {}

    def bucket(team_id: int) -> dict:
        return agg.setdefault(team_id, {"played": 0, "for": 0, "against": 0})

    for m in finished:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        h, a = bucket(m.home_team_id), bucket(m.away_team_id)
        h["played"] += 1; a["played"] += 1
        h["for"] += m.score_home; h["against"] += m.score_away
        a["for"] += m.score_away; a["against"] += m.score_home

    def rank_of(key: str, reverse: bool) -> int | None:
        """1-based rank of `team` among teams with played > 0."""
        rows = [(tid, b[key] / b["played"]) for tid, b in agg.items() if b["played"] > 0]
        if not any(tid == team.id for tid, _ in rows):
            return None
        rows.sort(key=lambda r: r[1], reverse=reverse)
        return next(i for i, (tid, _) in enumerate(rows, start=1) if tid == team.id)

    attack_rank = rank_of("for", reverse=True)     # most points scored = rank 1
    defence_rank = rank_of("against", reverse=False)  # fewest conceded = rank 1

    # Venue splits for this team.
    venues: dict[str, dict] = {}
    for m in finished:
        if team.id not in (m.home_team_id, m.away_team_id) or not m.venue:
            continue
        was_home = m.home_team_id == team.id
        score_for = m.score_home if was_home else m.score_away
        score_against = m.score_away if was_home else m.score_home
        v = venues.setdefault(m.venue, {
            "venue": m.venue, "played": 0, "wins": 0, "draws": 0, "losses": 0,
            "for": 0, "against": 0,
        })
        v["played"] += 1
        v["for"] += score_for
        v["against"] += score_against
        if score_for > score_against:
            v["wins"] += 1
        elif score_for < score_against:
            v["losses"] += 1
        else:
            v["draws"] += 1

    venue_splits = [
        {"venue": v["venue"], "played": v["played"], "wins": v["wins"],
         "draws": v["draws"], "losses": v["losses"],
         "avg_for": round(v["for"] / v["played"], 1),
         "avg_against": round(v["against"] / v["played"], 1)}
        for v in sorted(venues.values(), key=lambda v: (-v["played"], v["venue"]))
    ]

    return {
        "team": {"id": team.id, "name": team.name, "slug": slug},
        "season": season,
        "attack_rank": attack_rank,
        "defence_rank": defence_rank,
        "venue_splits": venue_splits,
        "position_concessions": [],  # Wave 3: filled once team lists provide positions
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }
