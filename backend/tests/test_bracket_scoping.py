"""The knockout bracket is ONE tournament's bracket.

`stage != "group"` + a non-null match_no was the whole filter — a WC26-shaped
assumption from before this database held four club competitions. It leaks the
moment any other tournament numbers a knockout tie.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Match, Team, Tournament


def _client(seed):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    seed(s)
    s.commit()
    s.close()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    from app.cache import cache
    cache.clear()
    return TestClient(app)


def _seed(s):
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    ucl = Tournament(name="UEFA Champions League 2026-27", year=2026)
    s.add_all([wc, ucl])
    s.flush()
    a, b, c, d = (Team(name=n) for n in ("Brazil", "Spain", "Arsenal", "Real Madrid"))
    s.add_all([a, b, c, d])
    s.flush()
    s.add(Match(tournament_id=wc.id, stage="final", match_no=104, team_home_id=a.id,
                team_away_id=b.id, status="scheduled",
                kickoff_utc=datetime(2026, 7, 19, tzinfo=timezone.utc)))
    # A club knockout tie that HAS been numbered — the leak this guards.
    s.add(Match(tournament_id=ucl.id, stage="final", match_no=125, team_home_id=c.id,
                team_away_id=d.id, status="scheduled",
                kickoff_utc=datetime(2027, 5, 29, tzinfo=timezone.utc)))


def test_bracket_excludes_another_tournaments_numbered_knockout_tie():
    client = _client(_seed)
    try:
        ties = client.get("/api/knockout/bracket").json()["ties"]
        assert [t["match_no"] for t in ties] == [104]
        names = {t["home"]["team"] for t in ties} | {t["away"]["team"] for t in ties}
        assert "Arsenal" not in names and "Real Madrid" not in names
    finally:
        app.dependency_overrides.clear()


def test_league_only_database_keeps_the_legacy_unscoped_behaviour():
    """No WC26 row -> fall back rather than serving an empty bracket."""
    def seed(s):
        ucl = Tournament(name="UEFA Champions League 2026-27", year=2026)
        s.add(ucl)
        s.flush()
        c, d = Team(name="Arsenal"), Team(name="Real Madrid")
        s.add_all([c, d])
        s.flush()
        s.add(Match(tournament_id=ucl.id, stage="final", match_no=125,
                    team_home_id=c.id, team_away_id=d.id, status="scheduled"))

    client = _client(seed)
    try:
        ties = client.get("/api/knockout/bracket").json()["ties"]
        assert [t["match_no"] for t in ties] == [125]
    finally:
        app.dependency_overrides.clear()
