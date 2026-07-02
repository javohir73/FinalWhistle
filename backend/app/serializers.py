"""Convert ORM rows into API response schemas.

The read path depends only on app.models — never on the ml/ package — so serving
a prediction can never accidentally run the model (PRD §7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import schemas
from app.live_winprob import live_probabilities_for_match
from app.models import Group, GroupTeam, HistoricalMatch, Match, Prediction, Standing, Team
from ml.models.poisson import goal_markets as _goal_markets

DISCLAIMER = "For analytics and entertainment only. Not betting advice."


def _kickoff_iso(dt: datetime | None) -> str | None:
    """Always emit kickoff as an explicit-UTC ISO string. SQLite drops tzinfo,
    so a naive value is assumed UTC and tagged accordingly; the frontend then
    converts the instant to the user's local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def team_to_out(team: Team) -> schemas.TeamOut:
    return schemas.TeamOut(
        id=team.id,
        name=team.name,
        country_code=team.country_code,
        confederation=team.confederation,
        fifa_rank=team.fifa_rank,
        elo_rating=team.elo_rating,
        is_host=team.is_host,
    )


def _goal_markets_out(lam_home, lam_away, rho) -> schemas.GoalMarketsOut | None:
    gm = _goal_markets(lam_home, lam_away, rho)
    if gm is None:
        return None
    return schemas.GoalMarketsOut(
        home=schemas.TeamGoalBandsOut(**gm["home"]),
        away=schemas.TeamGoalBandsOut(**gm["away"]),
        total=schemas.GoalTotalsOut(**gm["total"]),
        btts=gm["btts"],
    )


def _head_to_head(db: Session, home_id: int, away_id: int, last_n: int = 5) -> schemas.HeadToHeadOut:
    rows = (
        db.query(HistoricalMatch)
        .filter(
            ((HistoricalMatch.team_a_id == home_id) & (HistoricalMatch.team_b_id == away_id))
            | ((HistoricalMatch.team_a_id == away_id) & (HistoricalMatch.team_b_id == home_id))
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(last_n)
        .all()
    )
    hw = aw = d = 0
    for m in rows:
        if m.score_a == m.score_b:
            d += 1
            continue
        winner = m.team_a_id if m.score_a > m.score_b else m.team_b_id
        if winner == home_id:
            hw += 1
        else:
            aw += 1
    return schemas.HeadToHeadOut(matches=len(rows), home_wins=hw, draws=d, away_wins=aw)


def prediction_to_out(db: Session, match: Match, pred: Prediction) -> schemas.PredictionOut:
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    return schemas.PredictionOut(
        match_id=match.id,
        model_version=pred.model_version,
        generated_at=pred.created_at.isoformat() if pred.created_at else None,
        teams=schemas.TeamsOut(home=home.name if home else "TBD", away=away.name if away else "TBD"),
        home_team_id=match.team_home_id,
        away_team_id=match.team_away_id,
        group=match.group.name if match.group else None,
        group_id=match.group_id,
        stage=match.stage,
        is_neutral=match.is_neutral,
        kickoff_utc=_kickoff_iso(match.kickoff_utc),
        venue=match.venue,
        venue_city=match.venue_city,
        venue_country=match.venue_country,
        probabilities=schemas.ProbabilitiesOut(
            home_win=pred.prob_home_win, draw=pred.prob_draw, away_win=pred.prob_away_win
        ),
        predicted_score=schemas.PredictedScoreOut(
            home=pred.predicted_score_home,
            away=pred.predicted_score_away,
            probability=pred.predicted_score_prob,
        ),
        confidence=pred.confidence,
        reasons=pred.reasons or [],
        top_features=[schemas.FeatureWeightOut(**f) for f in (pred.top_features or [])],
        head_to_head=_head_to_head(db, match.team_home_id, match.team_away_id)
        if match.team_home_id and match.team_away_id
        else schemas.HeadToHeadOut(matches=0, home_wins=0, draws=0, away_wins=0),
        odds_comparison=schemas.OddsComparisonOut(available=False),
        disclaimer=DISCLAIMER,
        goal_markets=_goal_markets_out(pred.lambda_home, pred.lambda_away, pred.rho),
    )


def latest_prediction(db: Session, match_id: int) -> Prediction | None:
    return (
        db.query(Prediction)
        .filter_by(match_id=match_id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .first()
    )


def _card_counts(card_events: list | None) -> dict[str, int]:
    """Per-side red and ACTIVE-yellow counts for the live model. A yellow is
    active only while its player has not been sent off — once the red arrives
    (a second yellow comes through as one red event for the same player) the
    booking no longer carries second-yellow risk. None/malformed -> all zero."""
    counts = {"red_home": 0, "red_away": 0, "yellow_home": 0, "yellow_away": 0}
    events = [e for e in (card_events or [])
              if isinstance(e, dict) and e.get("side") in ("home", "away")]
    sent_off = {"home": set(), "away": set()}
    for e in events:
        if e.get("type") == "red":
            counts[f"red_{e['side']}"] += 1
            sent_off[e["side"]].add(e.get("player"))
    for e in events:
        if e.get("type") == "yellow" and e.get("player") not in sent_off[e["side"]]:
            counts[f"yellow_{e['side']}"] += 1
    return counts


def match_to_summary(db: Session, match: Match) -> schemas.MatchSummaryOut:
    home = db.get(Team, match.team_home_id) if match.team_home_id else None
    away = db.get(Team, match.team_away_id) if match.team_away_id else None
    pred = latest_prediction(db, match.id)

    probabilities = predicted_score = predicted_winner = confidence = None
    live_probabilities = None
    if pred:
        probabilities = schemas.ProbabilitiesOut(
            home_win=pred.prob_home_win, draw=pred.prob_draw, away_win=pred.prob_away_win
        )
        live = live_probabilities_for_match(
            status=match.status,
            score_home=match.score_home,
            score_away=match.score_away,
            minute=match.minute,
            period=match.period,
            lam_home=pred.lambda_home,
            lam_away=pred.lambda_away,
            rho=pred.rho,
            **_card_counts(match.card_events),
        )
        if live is not None:
            live_probabilities = schemas.ProbabilitiesOut(
                home_win=round(live[0], 4), draw=round(live[1], 4), away_win=round(live[2], 4)
            )
        predicted_score = schemas.PredictedScoreOut(
            home=pred.predicted_score_home,
            away=pred.predicted_score_away,
            probability=pred.predicted_score_prob,
        )
        confidence = pred.confidence
        best = max(
            [("home", pred.prob_home_win), ("draw", pred.prob_draw), ("away", pred.prob_away_win)],
            key=lambda kv: kv[1],
        )[0]
        predicted_winner = {
            "home": home.name if home else None,
            "away": away.name if away else None,
            "draw": "Draw",
        }[best]

    return schemas.MatchSummaryOut(
        match_id=match.id,
        stage=match.stage,
        group=match.group.name if match.group else None,
        kickoff_utc=_kickoff_iso(match.kickoff_utc),
        venue=match.venue,
        venue_city=match.venue_city,
        venue_country=match.venue_country,
        is_neutral=match.is_neutral,
        status=match.status,
        score_home=match.score_home,
        score_away=match.score_away,
        minute=match.minute,
        period=match.period,
        injury_time=match.injury_time,
        penalty_home=match.penalty_home,
        penalty_away=match.penalty_away,
        goal_events=[schemas.GoalEventOut(**g) for g in (match.goal_events or [])],
        card_events=[schemas.CardEventOut(**c) for c in (match.card_events or [])],
        teams=schemas.TeamsOut(
            home=home.name if home else "TBD", away=away.name if away else "TBD"
        ),
        predicted_winner=predicted_winner,
        probabilities=probabilities,
        predicted_score=predicted_score,
        confidence=confidence,
        live_probabilities=live_probabilities,
    )


def live_group_table(db: Session, group_id: int, include_in_play: bool = True) -> dict[int, dict]:
    """Real standings tallies from results: {team_id: {played, won, drawn, lost,
    points, gf, ga}}. Finished matches count as fact; an in-play match's current
    score counts provisionally when include_in_play (a live league table)."""
    statuses = ("finished", "in_play") if include_in_play else ("finished",)
    tally: dict[int, dict] = {}

    def row(tid: int) -> dict:
        return tally.setdefault(
            tid, {"played": 0, "won": 0, "drawn": 0, "lost": 0, "points": 0, "gf": 0, "ga": 0}
        )

    matches = (
        db.query(Match)
        .filter(
            Match.group_id == group_id,
            Match.status.in_(statuses),
            Match.score_home.isnot(None),
            Match.score_away.isnot(None),
            Match.team_home_id.isnot(None),
            Match.team_away_id.isnot(None),
        )
        .all()
    )
    for m in matches:
        h, a = row(m.team_home_id), row(m.team_away_id)
        h["played"] += 1
        a["played"] += 1
        h["gf"] += m.score_home
        h["ga"] += m.score_away
        a["gf"] += m.score_away
        a["ga"] += m.score_home
        if m.score_home > m.score_away:
            h["points"] += 3
            h["won"] += 1
            a["lost"] += 1
        elif m.score_home < m.score_away:
            a["points"] += 3
            a["won"] += 1
            h["lost"] += 1
        else:
            h["points"] += 1
            a["points"] += 1
            h["drawn"] += 1
            a["drawn"] += 1
    return tally


_EMPTY_TALLY = {"played": 0, "won": 0, "drawn": 0, "lost": 0, "points": 0, "gf": 0, "ga": 0}


def group_to_out(db: Session, group) -> schemas.GroupOut:
    """The LIVE group table: points/goals come from real results (in-play scores
    count provisionally), never from simulations. Qualification probability is
    the model's forecast for the games still to play — a separate column.
    Ranked points → GD → GF, with qual prob as the pre-tournament tiebreak so an
    all-zero table still orders sensibly."""
    rows = db.query(Standing).filter_by(group_id=group.id).all()
    live = live_group_table(db, group.id)

    def tally(r: Standing) -> dict:
        return live.get(r.team_id, _EMPTY_TALLY)

    rows.sort(
        key=lambda r: (
            tally(r)["points"],
            tally(r)["gf"] - tally(r)["ga"],
            tally(r)["gf"],
            r.qualification_prob or 0.0,
        ),
        reverse=True,
    )
    standings = []
    for r in rows:
        team = db.get(Team, r.team_id)
        t = tally(r)
        standings.append(
            schemas.StandingRowOut(
                team_id=r.team_id,
                team=team.name if team else "TBD",
                projected_points=t["points"],
                projected_goals_for=t["gf"],
                projected_goal_diff=t["gf"] - t["ga"],
                qualification_prob=r.qualification_prob,
            )
        )
    return schemas.GroupOut(id=group.id, name=group.name, standings=standings)


def team_profile(db: Session, team: Team, form_n: int = 8) -> schemas.TeamProfileOut:
    rows = (
        db.query(HistoricalMatch)
        .filter(
            (HistoricalMatch.team_a_id == team.id) | (HistoricalMatch.team_b_id == team.id)
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(form_n)
        .all()
    )
    form: list[schemas.FormResultOut] = []
    wins = goals_for = goals_against = 0
    for m in rows:
        if m.team_a_id == team.id:
            sf, sa, opp_id = m.score_a, m.score_b, m.team_b_id
        else:
            sf, sa, opp_id = m.score_b, m.score_a, m.team_a_id
        opp = db.get(Team, opp_id)
        result = "W" if sf > sa else "D" if sf == sa else "L"
        wins += result == "W"
        goals_for += sf
        goals_against += sa
        form.append(
            schemas.FormResultOut(
                opponent=opp.name if opp else "Unknown",
                score_for=sf, score_against=sa, result=result,
                date=m.date.date().isoformat() if m.date else None,
            )
        )

    strengths, weaknesses = [], []
    n = len(rows) or 1
    if team.elo_rating and team.elo_rating >= 1900:
        strengths.append("Top-tier Elo rating")
    if wins / n >= 0.6:
        strengths.append("Strong recent form")
    if goals_for / n >= 1.8:
        strengths.append("Potent attack")
    if goals_against / n <= 0.8:
        strengths.append("Solid defense")
    if wins / n <= 0.3:
        weaknesses.append("Poor recent form")
    if goals_against / n >= 1.6:
        weaknesses.append("Leaky defense")
    if goals_for / n <= 0.9:
        weaknesses.append("Struggles to score")
    if not strengths:
        strengths.append("Balanced side")
    if not weaknesses:
        weaknesses.append("No glaring weakness")

    gt = (
        db.query(GroupTeam, Group)
        .join(Group, Group.id == GroupTeam.group_id)
        .filter(GroupTeam.team_id == team.id)
        .first()
    )
    group_id = gt[1].id if gt else None
    group_name = gt[1].name if gt else None

    return schemas.TeamProfileOut(
        team=team_to_out(team),
        group_id=group_id,
        group_name=group_name,
        recent_form=form,
        strengths=strengths,
        weaknesses=weaknesses,
    )
