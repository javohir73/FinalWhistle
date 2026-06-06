"""Tests for prediction generation + §17 payload shape (task 3.8/3.9)."""
from datetime import datetime, timezone

from app.models import Match, Prediction, Standing, Team
from pipeline.generate_predictions import build_payload, generate_predictions
from pipeline.ingest.wc26_structure import load_structure


def _set_elos(db):
    """Give every loaded team a plausible Elo so cold-start isn't triggered."""
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40  # spread 1500..1940
    db.commit()


def test_payload_matches_prd_section_17_shape(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )
    payload = build_payload(db_session, match, "poisson-elo-v0.1")

    # Top-level keys from PRD §17
    for key in [
        "match_id", "model_version", "generated_at", "teams", "is_neutral",
        "probabilities", "predicted_score", "confidence", "reasons",
        "top_features", "head_to_head", "odds_comparison", "disclaimer",
    ]:
        assert key in payload, f"missing key {key}"

    probs = payload["probabilities"]
    assert abs(probs["home_win"] + probs["draw"] + probs["away_win"] - 1.0) < 0.01
    assert payload["confidence"] in {"High", "Medium", "Low"}
    assert len(payload["reasons"]) >= 3
    assert payload["odds_comparison"] == {"available": False}


def test_generate_predictions_writes_rows(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    summary = generate_predictions(db_session, n_sims=300)

    assert summary["matches_predicted"] == 72  # all group matches
    assert summary["groups_simulated"] == 12
    assert db_session.query(Prediction).count() == 72

    # Standings: 48 teams, qualification probs sum to ~2 per group.
    standings = db_session.query(Standing).all()
    assert len(standings) == 48


def test_qualification_probs_sum_to_two_per_group(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    generate_predictions(db_session, n_sims=500)
    from app.models import Group

    for group in db_session.query(Group).all():
        rows = db_session.query(Standing).filter_by(group_id=group.id).all()
        total = sum(r.qualification_prob for r in rows)
        assert abs(total - 2.0) < 0.05  # exactly 2 advance per group
