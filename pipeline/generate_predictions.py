"""Generate predictions for all upcoming WC2026 matches (PRD §4.2, §17).

For each scheduled group match it builds features, runs the Poisson engine,
derives confidence + reasons, and writes a Prediction row plus a §17-shaped
payload. It then simulates each group to fill predicted standings + qualification
probabilities. Designed to be called by the daily pipeline (task 7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Group, GroupTeam, Match, Prediction, Standing, Team
from ml.explain.reasons import confidence_level, generate_reasons, top_features
from ml.features.build_features import build_match_features, estimate_strength
from ml.models.poisson import predict_match
from ml.ratings.elo import HOME_ADVANTAGE
from ml.simulate.group_sim import GroupFixture, simulate_group


def _host_adv(match: Match, home: Team) -> float:
    """Signed host bonus: + if home is host, - if away is host (boosts away)."""
    if match.host_team_id is None:
        return 0.0
    return HOME_ADVANTAGE if match.host_team_id == home.id else -HOME_ADVANTAGE


def build_payload(
    db: Session, match: Match, model_version: str
) -> dict | None:
    """Build the PRD §17 prediction payload for a match (None if teams unknown)."""
    if match.team_home_id is None or match.team_away_id is None:
        return None
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)

    feats = build_match_features(db, home, away, host_team_id=match.host_team_id)
    host_adv = _host_adv(match, home)
    elo_home, _ = estimate_strength(home)
    elo_away, _ = estimate_strength(away)
    pred = predict_match(elo_home, elo_away, home_adv=host_adv)

    cold_start = feats.strength_source_home != "elo" or feats.strength_source_away != "elo"
    confidence = confidence_level(
        pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
        feats.data_points_home, feats.data_points_away, cold_start,
    )
    reasons = generate_reasons(
        feats, home.name, away.name,
        pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
    )
    factors = top_features(feats)

    return {
        "match_id": match.id,
        "model_version": model_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": {"home": home.name, "away": away.name},
        "is_neutral": match.is_neutral,
        "probabilities": {
            "home_win": round(pred.prob_home_win, 4),
            "draw": round(pred.prob_draw, 4),
            "away_win": round(pred.prob_away_win, 4),
        },
        "predicted_score": {
            "home": pred.score_home,
            "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "confidence": confidence,
        "reasons": reasons,
        "top_features": factors,
        "head_to_head": {
            "matches": feats.h2h["matches"],
            "home_wins": feats.h2h["a_wins"],
            "draws": feats.h2h["draws"],
            "away_wins": feats.h2h["b_wins"],
        },
        "odds_comparison": {"available": False},
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


def _write_prediction(db: Session, payload: dict, model_version: str) -> None:
    p = payload["probabilities"]
    s = payload["predicted_score"]
    db.add(
        Prediction(
            match_id=payload["match_id"],
            model_version=model_version,
            prob_home_win=p["home_win"],
            prob_draw=p["draw"],
            prob_away_win=p["away_win"],
            predicted_score_home=s["home"],
            predicted_score_away=s["away"],
            predicted_score_prob=s["probability"],
            confidence=payload["confidence"],
            reasons=payload["reasons"],
            top_features=payload["top_features"],
        )
    )


def _simulate_standings(db: Session, group: Group, model_version: str, n_sims: int) -> None:
    members = [gt.team for gt in group.group_teams]
    team_elos = {t.id: estimate_strength(t)[0] for t in members}
    fixtures = []
    for m in db.query(Match).filter_by(group_id=group.id).all():
        if m.team_home_id and m.team_away_id:
            home = db.get(Team, m.team_home_id)
            fixtures.append(
                GroupFixture(m.team_home_id, m.team_away_id, home_adv=_host_adv(m, home))
            )

    results = simulate_group(team_elos, fixtures, n_sims=n_sims, seed=2026)
    now = datetime.now(timezone.utc)
    for team_id, r in results.items():
        row = db.query(Standing).filter_by(group_id=group.id, team_id=team_id).one_or_none()
        if row is None:
            row = Standing(group_id=group.id, team_id=team_id)
            db.add(row)
        row.qualification_prob = r["qualification_prob"]
        row.points = round(r["avg_points"])
        row.goal_diff = round(r["avg_gd"])
        row.goals_for = round(r["avg_gf"])
        row.as_of = now


def generate_predictions(
    db: Session, model_version: str = "poisson-elo-v0.1", n_sims: int = 5000
) -> dict:
    """Predict all upcoming group matches and simulate every group's standings."""
    matches = (
        db.query(Match)
        .filter(Match.stage == "group", Match.status == "scheduled")
        .all()
    )
    predicted = 0
    for match in matches:
        payload = build_payload(db, match, model_version)
        if payload is None:
            continue
        _write_prediction(db, payload, model_version)
        predicted += 1

    groups = db.query(Group).all()
    for group in groups:
        _simulate_standings(db, group, model_version, n_sims)

    db.commit()
    return {"matches_predicted": predicted, "groups_simulated": len(groups)}
