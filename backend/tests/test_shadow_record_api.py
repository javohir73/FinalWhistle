"""GET /api/internal/shadow-record — production vs shadow comparison (FR-4.6).

Token-guarded like every internal endpoint (fail-closed without a configured
token). The payload is the input to the MANUAL promotion decision (FR-4.8):
matches scored, exact hits, winner accuracy and average Brier for the
production record and the shadow record side by side.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Match, Prediction, PredictionResult, Team, Tournament

SHADOW_MV = "poisson-elo-v0.3-shadow"


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _seed_results(db):
    """One PAIRED match (production + shadow twin results) and one pre-Phase-4
    match (production result only, no twin) — the mid-tournament deploy shape."""
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    home = Team(name="Mexico")
    away = Team(name="South Africa")
    db.add_all([wc, home, away])
    db.flush()

    def match(i):
        m = Match(tournament_id=wc.id, stage="group", status="finished",
                  team_home_id=home.id, team_away_id=away.id,
                  score_home=2, score_away=i)
        db.add(m)
        db.flush()
        return m

    def result(m, *, shadow, exact, winner, brier):
        p = Prediction(match_id=m.id,
                       model_version=SHADOW_MV if shadow else "poisson-elo-v0.2",
                       prob_home_win=0.6, prob_draw=0.25, prob_away_win=0.15,
                       predicted_score_home=2, predicted_score_away=0,
                       is_shadow=shadow)
        db.add(p)
        db.flush()
        db.add(PredictionResult(
            match_id=m.id, prediction_id=p.id, model_version=p.model_version,
            actual_score_home=2, actual_score_away=m.score_away, outcome="home",
            winner_correct=winner, exact_score_correct=exact,
            prob_assigned=0.6, brier=brier, log_loss=0.5 if not shadow else 0.4,
            goal_error=abs(m.score_away),
            is_shadow=shadow,
        ))

    paired = match(0)
    result(paired, shadow=False, exact=True, winner=True, brier=0.2)
    result(paired, shadow=True, exact=True, winner=True, brier=0.1)
    pre_phase4 = match(1)  # evaluated before Phase 4 deployed — no shadow twin
    result(pre_phase4, shadow=False, exact=False, winner=True, brier=0.4)
    db.commit()


def test_shadow_record_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "")
    client, _ = _client()
    try:
        assert client.get("/api/internal/shadow-record").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        assert client.get("/api/internal/shadow-record").status_code == 401
        assert client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_compares_production_and_shadow(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        _seed_results(TestingSession())
        r = client.get("/api/internal/shadow-record",
                       headers={"X-Recompute-Token": "secret"})
        assert r.status_code == 200
        body = r.json()
        prod, shad = body["production"], body["shadow"]
        assert prod["n"] == 1 and shad["n"] == 1
        assert prod["exact_hits"] == 1 and shad["exact_hits"] == 1
        assert prod["winner_acc"] == 1.0 and shad["winner_acc"] == 1.0
        assert prod["avg_brier"] == 0.2 and shad["avg_brier"] == 0.1
        assert prod["avg_log_loss"] == 0.5 and shad["avg_log_loss"] == 0.4
        assert shad["model_versions"] == [SHADOW_MV]
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_production_column_is_paired_to_shadow_matches(monkeypatch):
    """Like-for-like comparison (FR-4.6/4.8): the production column must cover
    ONLY matches that also have a shadow result. Pre-Phase-4 matches (evaluated
    before any twin existed) would otherwise skew the side-by-side numbers the
    manual promotion decision reads. The full production record stays available
    as a separate, clearly-labelled aggregate."""
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        _seed_results(TestingSession())
        body = client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "secret"}).json()
        prod, shad, full = (body["production"], body["shadow"],
                            body["production_full_record"])
        # Paired columns cover the same single match — the twin's match.
        assert prod["n"] == shad["n"] == 1
        # The unpaired pre-Phase-4 result (brier=0.4, no exact hit) is excluded
        # from the comparison column...
        assert prod["avg_brier"] == 0.2
        assert prod["exact_hits"] == 1
        # ...but still visible in the full-record aggregate for context.
        assert full["n"] == 2
        assert full["avg_brier"] == 0.3
        assert full["exact_hits"] == 1
    finally:
        app.dependency_overrides.clear()


def test_shadow_record_is_honest_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, _ = _client()
    try:
        body = client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "secret"}).json()
        assert body["production"] == {"n": 0, "exact_hits": 0, "winner_acc": None,
                                      "avg_brier": None, "avg_log_loss": None,
                                      "model_versions": []}
        assert body["shadow"]["n"] == 0
        assert body["production_full_record"]["n"] == 0
        assert body["club"]["shadow"]["n"] == 0
    finally:
        app.dependency_overrides.clear()


def _seed_club_pair(db, *, brier=0.3, log_loss=0.6):
    """One EPL paired match (production + its OWN club shadow twin, tagged
    "poisson-elo-club-v0.1-shadow" — never SHADOW_MODEL_VERSION)."""
    epl = Tournament(name="Premier League 2026-27", year=2026, home_advantage_mode="home")
    home = Team(name="Arsenal")
    away = Team(name="Chelsea")
    db.add_all([epl, home, away])
    db.flush()
    m = Match(tournament_id=epl.id, stage="group", status="finished",
             team_home_id=home.id, team_away_id=away.id, score_home=2, score_away=1)
    db.add(m)
    db.flush()

    def result(*, shadow, brier_val):
        p = Prediction(
            match_id=m.id,
            model_version="poisson-elo-club-v0.1-shadow" if shadow else "poisson-elo-club-v0.1",
            prob_home_win=0.6, prob_draw=0.25, prob_away_win=0.15,
            predicted_score_home=2, predicted_score_away=0, is_shadow=shadow,
        )
        db.add(p)
        db.flush()
        db.add(PredictionResult(
            match_id=m.id, prediction_id=p.id, model_version=p.model_version,
            actual_score_home=2, actual_score_away=1, outcome="home",
            winner_correct=True, exact_score_correct=False,
            prob_assigned=0.6, brier=brier_val, log_loss=log_loss, goal_error=1,
            is_shadow=shadow,
        ))

    result(shadow=False, brier_val=brier)
    result(shadow=True, brier_val=brier - 0.1)
    db.commit()
    return m


def test_shadow_record_separates_club_ledger_from_wc26(monkeypatch):
    """League pivot regression (Opus review of PR #171, item 1): an EPL
    paired match must surface under "club", and must NOT be pooled into the
    top-level WC26 columns — the promotion gate's paired sample must not
    move just because an EPL match finished."""
    monkeypatch.setattr(settings, "recompute_token", "secret")
    client, TestingSession = _client()
    try:
        db = TestingSession()
        _seed_results(db)  # 1 WC26 paired match + 1 unpaired WC26 match
        _seed_club_pair(db)  # 1 EPL paired match, own shadow tag
        body = client.get("/api/internal/shadow-record",
                          headers={"X-Recompute-Token": "secret"}).json()

        # Top-level (WC26) columns are UNCHANGED from the WC26-only scenario —
        # the EPL pair never enters them.
        assert body["production"]["n"] == 1
        assert body["shadow"]["n"] == 1
        assert body["shadow"]["model_versions"] == [SHADOW_MV]
        assert body["production_full_record"]["n"] == 2  # the two WC26 rows only

        # The club ledger holds exactly the EPL pair, tagged its own version.
        club = body["club"]
        assert club["production"]["n"] == 1
        assert club["shadow"]["n"] == 1
        assert club["shadow"]["model_versions"] == ["poisson-elo-club-v0.1-shadow"]
        assert club["production_full_record"]["n"] == 1
    finally:
        app.dependency_overrides.clear()
