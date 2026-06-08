"""Convert ORM rows into API response schemas.

The read path depends only on app.models — never on the ml/ package — so serving
a prediction can never accidentally run the model (PRD §7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import schemas
from app.models import HistoricalMatch, Match, Prediction, Standing, Team

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
    )


def latest_prediction(db: Session, match_id: int) -> Prediction | None:
    return (
        db.query(Prediction)
        .filter_by(match_id=match_id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .first()
    )


def match_to_summary(db: Session, match: Match) -> schemas.MatchSummaryOut:
    home = db.get(Team, match.team_home_id) if match.team_home_id else None
    away = db.get(Team, match.team_away_id) if match.team_away_id else None
    pred = latest_prediction(db, match.id)

    probabilities = predicted_score = predicted_winner = confidence = None
    if pred:
        probabilities = schemas.ProbabilitiesOut(
            home_win=pred.prob_home_win, draw=pred.prob_draw, away_win=pred.prob_away_win
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
        teams=schemas.TeamsOut(
            home=home.name if home else "TBD", away=away.name if away else "TBD"
        ),
        predicted_winner=predicted_winner,
        probabilities=probabilities,
        predicted_score=predicted_score,
        confidence=confidence,
    )


def group_to_out(db: Session, group) -> schemas.GroupOut:
    rows = db.query(Standing).filter_by(group_id=group.id).all()
    rows.sort(key=lambda r: (r.qualification_prob or 0, r.points, r.goal_diff), reverse=True)
    standings = []
    for r in rows:
        team = db.get(Team, r.team_id)
        standings.append(
            schemas.StandingRowOut(
                team_id=r.team_id,
                team=team.name if team else "TBD",
                projected_points=r.points,
                projected_goals_for=r.goals_for,
                projected_goal_diff=r.goal_diff,
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

    return schemas.TeamProfileOut(
        team=team_to_out(team), recent_form=form, strengths=strengths, weaknesses=weaknesses
    )
