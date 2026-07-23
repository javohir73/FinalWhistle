"""GET /api/nrl/tips -- the round tipsheet (design doc: NRL Round Tips,
Slice 1). Mirrors test_sports_api.py's fixture style, scoped to the sport_*
tables; nrl_tips.py doesn't cache so this file skips the cache.clear() dance
test_sports_api.py needs (same call test_nrl_intel_api.py makes)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import SportMatch, SportPrediction, SportPredictionResult, SportTeam


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_session()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t)
    db.flush()
    return t


def test_defaults_to_current_round_with_scheduled_matches(client):
    """Round 1 is done; round 2 has the earliest still-scheduled match --
    the endpoint must pick round 2 without a `round` query param."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    r1 = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                     kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                     home_team_id=storm.id, away_team_id=eels.id,
                     status="finished", score_home=20, score_away=10)
    r2 = SportMatch(sport="nrl", season=2026, round=2, match_no=1,
                     kickoff_utc=datetime(2026, 3, 12, tzinfo=timezone.utc),
                     venue="AAMI Park", home_team_id=storm.id, away_team_id=eels.id,
                     status="scheduled")
    db.add_all([r1, r2])
    db.flush()
    pred = SportPrediction(match_id=r2.id, model_version="nrl-elo-v0.1",
                           created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                           p_home=0.6, p_draw=0.01, p_away=0.39, expected_margin=3.0)
    db.add(pred)
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 2026
    assert body["round"] == 2
    assert len(body["matches"]) == 1
    match = body["matches"][0]
    assert match["home"] == "Storm"
    assert match["away"] == "Eels"
    assert match["venue"] == "AAMI Park"
    assert match["status"] == "scheduled"
    assert match["prediction"]["p_home"] == pytest.approx(0.6)
    assert match["prediction"]["pick"] == "home"
    assert match["prediction"]["pick_confidence"] == pytest.approx(0.6)
    assert match["prediction"]["is_shadow"] is True
    assert "disclaimer" in body


def test_excludes_post_kickoff_prediction_write(client):
    """A still-'scheduled' match with a prediction written AFTER kickoff (the
    narrow pre-refresh window the design doc calls out) must serve the
    earlier, kickoff-eligible row instead -- never the post-kickoff write."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    kick = datetime(2026, 3, 5, 9, tzinfo=timezone.utc)
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   kickoff_utc=kick, home_team_id=storm.id, away_team_id=eels.id,
                   status="scheduled")
    db.add(m)
    db.flush()
    before = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                             created_at=kick - timedelta(days=1),
                             p_home=0.55, p_draw=0.01, p_away=0.44, expected_margin=2.0)
    after = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=kick + timedelta(hours=1),
                            p_home=0.90, p_draw=0.01, p_away=0.09, expected_margin=9.0)
    db.add_all([before, after])
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026, "round": 1})
    assert r.status_code == 200
    match = r.json()["matches"][0]
    assert match["prediction"]["p_home"] == pytest.approx(0.55)
    assert match["prediction"]["expected_margin"] == pytest.approx(2.0)


def test_worst_miss_picks_highest_confidence_wrong_pick(client):
    """Two wrong picks in the most recent graded round -- worst_miss must
    surface the high-confidence one, not the low-confidence one."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    broncos = _team(db, "Broncos")
    kick = datetime(2026, 3, 5, tzinfo=timezone.utc)

    def graded(match_no, home, away, p_home, score_home, score_away, kickoff):
        m = SportMatch(sport="nrl", season=2026, round=3, match_no=match_no,
                       kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                       status="finished", score_home=score_home, score_away=score_away)
        db.add(m)
        db.flush()
        p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=kickoff - timedelta(days=1),
                            p_home=p_home, p_draw=0.01, p_away=round(1 - p_home - 0.01, 4),
                            expected_margin=5.0)
        db.add(p)
        db.flush()
        outcome = "home" if score_home > score_away else "away" if score_away > score_home else "draw"
        idx = {"home": 0, "draw": 1, "away": 2}[outcome]
        probs = (p.p_home, p.p_draw, p.p_away)
        prob_assigned = probs[idx]
        db.add(SportPredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="nrl-elo-v0.1",
            outcome=outcome, winner_correct=(probs.index(max(probs)) == idx),
            prob_assigned=prob_assigned, log_loss=0.5, brier=0.3, margin_error=4.0,
        ))
        return m

    # Model picked home at 0.80 -- away won. High-confidence miss.
    graded(1, storm, eels, 0.80, 12, 24, kick)
    # Model picked home at 0.55 -- away won too, but with lower confidence.
    graded(2, eels, broncos, 0.55, 10, 16, kick + timedelta(days=1))
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026, "round": 3})
    assert r.status_code == 200
    worst = r.json()["worst_miss"]
    assert worst is not None
    assert worst["round"] == 3
    assert worst["home"] == "Storm"
    assert worst["away"] == "Eels"
    assert worst["score_home"] == 12 and worst["score_away"] == 24
    assert worst["pick"] == "home"
    assert worst["pick_team"] == "Storm"
    assert worst["pick_probability"] == pytest.approx(0.80)
    assert worst["winner"] == "away"
    assert worst["winner_team"] == "Eels"


def test_worst_miss_is_scoped_to_the_latest_graded_round(client):
    """A higher-confidence wrong pick sits in an EARLIER round; a lower-
    confidence wrong pick sits in the latest graded round. worst_miss must
    return the latest round's (lower-confidence) miss -- proving the round
    filter at nrl_tips.py:108 is load-bearing and not equivalent to a global
    argmax over every miss ever graded."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    broncos = _team(db, "Broncos")
    titans = _team(db, "Titans")

    def graded(rnd, home, away, p_home, score_home, score_away, kickoff):
        m = SportMatch(sport="nrl", season=2026, round=rnd, match_no=1,
                       kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                       status="finished", score_home=score_home, score_away=score_away)
        db.add(m)
        db.flush()
        p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=kickoff - timedelta(days=1),
                            p_home=p_home, p_draw=0.01, p_away=round(1 - p_home - 0.01, 4),
                            expected_margin=5.0)
        db.add(p)
        db.flush()
        outcome = "home" if score_home > score_away else "away" if score_away > score_home else "draw"
        idx = {"home": 0, "draw": 1, "away": 2}[outcome]
        probs = (p.p_home, p.p_draw, p.p_away)
        db.add(SportPredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="nrl-elo-v0.1",
            outcome=outcome, winner_correct=(probs.index(max(probs)) == idx),
            prob_assigned=probs[idx], log_loss=0.5, brier=0.3, margin_error=4.0,
        ))

    # Round 1 (earlier): a wrong pick at 0.90 confidence -- the global max
    # over every graded miss, were the round filter ever dropped.
    graded(1, storm, eels, 0.90, 10, 24, datetime(2026, 3, 5, tzinfo=timezone.utc))
    # Round 2 (latest graded): a wrong pick at only 0.55 confidence.
    graded(2, broncos, titans, 0.55, 12, 18, datetime(2026, 3, 12, tzinfo=timezone.utc))
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026, "round": 2})
    assert r.status_code == 200
    worst = r.json()["worst_miss"]
    assert worst is not None
    assert worst["round"] == 2
    assert worst["home"] == "Broncos"
    assert worst["away"] == "Titans"
    assert worst["pick_probability"] == pytest.approx(0.55)


def test_worst_miss_null_when_nothing_graded(client):
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   kickoff_utc=datetime(2026, 3, 5, tzinfo=timezone.utc),
                   home_team_id=storm.id, away_team_id=eels.id, status="scheduled")
    db.add(m)
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026})
    assert r.status_code == 200
    assert r.json()["worst_miss"] is None


def test_finished_season_falls_back_to_latest_round(client):
    """When every match in the season is graded, the default round is the
    latest round with matches, not a 404."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")

    for rnd, day in ((1, 5), (2, 12)):
        m = SportMatch(sport="nrl", season=2026, round=rnd, match_no=1,
                       kickoff_utc=datetime(2026, 3, day, tzinfo=timezone.utc),
                       home_team_id=storm.id, away_team_id=eels.id,
                       status="finished", score_home=20, score_away=10)
        db.add(m)
        db.flush()
        db.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                               created_at=datetime(2026, 3, day - 1, tzinfo=timezone.utc),
                               p_home=0.6, p_draw=0.01, p_away=0.39, expected_margin=3.0))
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["round"] == 2
    assert body["record"]["evaluated_matches"] == 0  # no SportPredictionResult rows seeded


def test_record_is_all_time_not_scoped_to_the_requested_season(client):
    """`record` reuses _ledger_record, which filters only on sport (see
    sports.py) -- a graded match from a DIFFERENT season must still count
    toward the tipsheet's record. This is deliberate (the strip is labelled
    'Model record', not 'Season record') but was previously unguarded by any
    test, so a future accidental season filter would pass CI silently."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")

    def graded(season, kickoff):
        m = SportMatch(sport="nrl", season=season, round=1, match_no=1,
                       kickoff_utc=kickoff, home_team_id=storm.id, away_team_id=eels.id,
                       status="finished", score_home=20, score_away=10)
        db.add(m)
        db.flush()
        p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            created_at=kickoff - timedelta(days=1),
                            p_home=0.7, p_draw=0.01, p_away=0.29, expected_margin=10.0)
        db.add(p)
        db.flush()
        db.add(SportPredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="nrl-elo-v0.1",
            outcome="home", winner_correct=True, prob_assigned=0.7,
            log_loss=0.2, brier=0.1, margin_error=2.0,
        ))

    graded(2025, datetime(2025, 3, 5, tzinfo=timezone.utc))
    graded(2026, datetime(2026, 3, 5, tzinfo=timezone.utc))
    db.commit()

    r = c.get("/api/nrl/tips", params={"season": 2026, "round": 1})
    assert r.status_code == 200
    assert r.json()["record"]["evaluated_matches"] == 2


def test_unknown_season_404s(client):
    c, _ = client
    r = c.get("/api/nrl/tips", params={"season": 1999})
    assert r.status_code == 404


def test_record_reuses_ledger_record_computation(client):
    """record must match /api/nrl/model/record's own output byte-for-byte --
    it's the same helper, not a re-derivation."""
    c, TestingSession = client
    db = TestingSession()
    storm = _team(db, "Storm")
    eels = _team(db, "Eels")
    kick = datetime(2026, 3, 5, tzinfo=timezone.utc)
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   kickoff_utc=kick, home_team_id=storm.id, away_team_id=eels.id,
                   status="finished", score_home=20, score_away=10)
    db.add(m)
    db.flush()
    p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                        created_at=kick - timedelta(days=1),
                        p_home=0.7, p_draw=0.01, p_away=0.29, expected_margin=10.0)
    db.add(p)
    db.flush()
    db.add(SportPredictionResult(
        match_id=m.id, prediction_id=p.id, model_version="nrl-elo-v0.1",
        outcome="home", winner_correct=True, prob_assigned=0.7,
        log_loss=0.2, brier=0.1, margin_error=2.0,
    ))
    db.commit()

    tips_record = c.get("/api/nrl/tips", params={"season": 2026}).json()["record"]
    model_record = c.get("/api/nrl/model/record").json()
    for key in ("evaluated_matches", "winner_accuracy", "winner_accuracy_ci95",
                "avg_log_loss", "avg_brier", "best_streak", "last_updated"):
        assert tips_record[key] == model_record[key]
