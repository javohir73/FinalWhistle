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


def test_build_payload_applies_calibrator_blob_end_to_end(db_session):
    """A vector-scaling blob with a positive draw bias must lift the served draw
    probability through the whole card path: blob -> ModelParams.calibrator ->
    calibrate() inside predict_match -> §17 payload. Guards the build_payload
    forwarding line (calibrator=params.calibrator) that wires production serving
    to the calibrator — if it were dropped, this is the only test that fails.

    Both payloads use ModelParams built from the same base/beta/rho/home_adv/
    temperature so ONLY the calibrator differs. The baseline is constructed with
    calibrator=None rather than via load_params(), keeping the test hermetic from
    whatever model_params.json happens to hold on disk."""
    from dataclasses import replace

    from ml.models.params import DEFAULT_PARAMS, ModelParams

    load_structure(db_session)
    _set_elos(db_session)
    match = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .first()
    )

    # Identical engine params for both; only the calibrator field differs.
    baseline = replace(DEFAULT_PARAMS, version="poisson-elo-v0.1", calibrator=None)
    assert isinstance(baseline, ModelParams) and baseline.calibrator is None
    blob = {"method": "vector_scaling", "t": 1.0, "b": [0.0, 1.0, 0.0]}
    lifted = replace(baseline, calibrator=blob)

    base = build_payload(db_session, match, "poisson-elo-v0.1", params=baseline)
    cal = build_payload(db_session, match, "poisson-elo-v0.1", params=lifted)

    assert cal["probabilities"]["draw"] > base["probabilities"]["draw"]
    p = cal["probabilities"]
    assert abs(p["home_win"] + p["draw"] + p["away_win"] - 1.0) < 0.01


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


def test_finished_matches_feed_standings_as_facts(db_session):
    """Real results must flow into projected standings: a team that has already
    won all three of its games sits on exactly 9 points with qualification
    locked at 1.0 — regardless of what the model would have predicted."""
    load_structure(db_session)
    _set_elos(db_session)

    from app.models import Group

    group = db_session.query(Group).first()
    matches = db_session.query(Match).filter_by(group_id=group.id).all()
    members = sorted({m.team_home_id for m in matches} | {m.team_away_id for m in matches})
    elo = {t: db_session.get(Team, t).elo_rating for t in members}
    target = min(members, key=lambda t: elo[t])   # weakest wins everything
    loser = max(members, key=lambda t: elo[t])    # strongest loses everything

    for m in matches:
        m.status = "finished"
        if target in (m.team_home_id, m.team_away_id):
            m.score_home, m.score_away = (1, 0) if m.team_home_id == target else (0, 1)
        elif loser in (m.team_home_id, m.team_away_id):
            m.score_home, m.score_away = (0, 1) if m.team_home_id == loser else (1, 0)
        else:
            m.score_home, m.score_away = 0, 0
    db_session.commit()

    generate_predictions(db_session, n_sims=300)

    rows = {r.team_id: r for r in db_session.query(Standing).filter_by(group_id=group.id)}
    assert rows[target].points == 9
    assert rows[target].qualification_prob == 1.0
    assert rows[loser].points == 0
    assert rows[loser].qualification_prob == 0.0


def test_qualification_probs_sum_to_two_per_group(db_session):
    load_structure(db_session)
    _set_elos(db_session)
    generate_predictions(db_session, n_sims=500)
    from app.models import Group

    for group in db_session.query(Group).all():
        rows = db_session.query(Standing).filter_by(group_id=group.id).all()
        total = sum(r.qualification_prob for r in rows)
        assert abs(total - 2.0) < 0.05  # exactly 2 advance per group
