from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, Team, Tournament
from pipeline.generate_predictions import AVAILABILITY_MODEL_VERSION

_EMPTY_LEDGER = {"n_matches": 0, "verdict": "insufficient", "production": None,
                 "availability": None, "diff_log_loss": None, "diff_ci95": None,
                 "availability_win_rate": None}
_EMPTY = {**_EMPTY_LEDGER, "club": _EMPTY_LEDGER}


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSession


def _seed_pair(db):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home, away = Team(name="Mexico"), Team(name="South Africa")
    db.add_all([wc, home, away]); db.flush()
    m = Match(tournament_id=wc.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=2, score_away=0)
    db.add(m); db.flush()
    for mv, probs, sh in (("poisson-elo-v0.2", (0.55, 0.25, 0.20), False),
                          (AVAILABILITY_MODEL_VERSION, (0.70, 0.18, 0.12), True)):
        db.add(Prediction(match_id=m.id, model_version=mv,
                          prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                          predicted_score_home=2, predicted_score_away=0, is_shadow=sh))
    db.commit()


def test_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client, _ = _client()
    try:
        assert client.get("/api/internal/availability-record").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        assert client.get("/api/internal/availability-record").status_code == 401
        assert client.get("/api/internal/availability-record",
                          headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_returns_paired_comparison(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        _seed_pair(TestingSession())
        r = client.get("/api/internal/availability-record",
                       headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        assert body["n_matches"] == 1
        assert body["verdict"] == "availability_beats_published"
        assert body["availability"]["log_loss"] < body["production"]["log_loss"]
    finally:
        app.dependency_overrides.clear()


def test_is_honest_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        body = client.get("/api/internal/availability-record",
                          headers={"X-Recompute-Token": "secret"}).json()
        assert body == _EMPTY
    finally:
        app.dependency_overrides.clear()


def _seed_club_pair(db):
    """One EPL paired match: production tagged "poisson-elo-club-v0.1", its
    twin tagged the derived "poisson-elo-club-v0.1+avail" — never the frozen
    WC26 constant."""
    epl = Tournament(name="Premier League 2026-27", year=2026)
    home, away = Team(name="Arsenal"), Team(name="Chelsea")
    db.add_all([epl, home, away]); db.flush()
    m = Match(tournament_id=epl.id, stage="group", status="finished",
              team_home_id=home.id, team_away_id=away.id, score_home=3, score_away=1)
    db.add(m); db.flush()
    for mv, probs, sh in (("poisson-elo-club-v0.1", (0.50, 0.30, 0.20), False),
                          ("poisson-elo-club-v0.1+avail", (0.62, 0.24, 0.14), True)):
        db.add(Prediction(match_id=m.id, model_version=mv,
                          prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                          predicted_score_home=2, predicted_score_away=0, is_shadow=sh))
    db.commit()


def test_separates_club_ledger_from_wc26(monkeypatch):
    """League pivot regression (same leak as the shadow-ledger fix, PR #171):
    an EPL paired match must surface under "club" and must NOT be pooled into
    the top-level WC26 columns."""
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        db = TestingSession()
        _seed_pair(db)
        _seed_club_pair(db)
        body = client.get("/api/internal/availability-record",
                          headers={"X-Recompute-Token": "secret"}).json()

        # Top-level (WC26) columns are UNCHANGED from the WC26-only scenario.
        assert body["n_matches"] == 1
        assert body["verdict"] == "availability_beats_published"

        # The club ledger holds exactly the EPL pair.
        assert body["club"]["n_matches"] == 1
        assert body["club"]["verdict"] == "availability_beats_published"
    finally:
        app.dependency_overrides.clear()
