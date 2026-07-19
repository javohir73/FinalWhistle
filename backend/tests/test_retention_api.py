"""GET /api/retention — public device-level D7/D14 retention cohorts.

Mirrors test_model_record_api.py's client fixture (in-memory SQLite, module
cache cleared each test) plus a `_today()` monkeypatch seam: cohort math is
anchored to a fixed "since" (the WC26 final) but evaluated against "today",
so tests pin "today" rather than depend on wall-clock date.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.retention as retention_api
from app.cache import cache
from app.db import Base, get_db
from app.main import app
from app.models import DailyActivity

SINCE = date(2026, 7, 19)  # the WC26 final


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client(monkeypatch):
    TestingSession = _make_session()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(retention_api, "_today", lambda: date(2026, 8, 2))
    cache.clear()  # the module-level cache survives across tests otherwise
    yield TestClient(app), TestingSession
    cache.clear()
    app.dependency_overrides.clear()


def _ping(db, device_id, day):
    db.add(DailyActivity(device_id=device_id, day=day))


def test_empty_retention_is_honest(client):
    c, _ = client
    r = c.get("/api/retention")
    assert r.status_code == 200
    body = r.json()
    assert body["since"] == "2026-07-19"
    assert body["total_devices"] == 0
    assert body["cohorts"][0] == {"day": "2026-07-19", "cohort_size": 0, "d1": None, "d7": None, "d14": None}


def test_cohort_math_with_returning_and_non_returning_devices(client, monkeypatch):
    c, TestingSession = client
    db = TestingSession()

    # Cohort A: first-ping 2026-07-19 (day zero). d1 returns every checkpoint,
    # d2 returns once (day+1 only), d3 never returns.
    for day in (date(2026, 7, 19), date(2026, 7, 20), date(2026, 7, 26), date(2026, 8, 2)):
        _ping(db, "device-1", day)
    for day in (date(2026, 7, 19), date(2026, 7, 20)):
        _ping(db, "device-2", day)
    _ping(db, "device-3", date(2026, 7, 19))

    # Cohort B: first-ping 2026-07-20 — device-1/2 also ping this day, but
    # their FIRST ping was 07-19, so they must not inflate this cohort's size.
    _ping(db, "device-4", date(2026, 7, 20))
    _ping(db, "device-4", date(2026, 7, 21))
    _ping(db, "device-5", date(2026, 7, 20))

    db.commit()
    db.close()

    r = c.get("/api/retention")
    assert r.status_code == 200
    body = r.json()

    assert body["total_devices"] == 5
    by_day = {row["day"]: row for row in body["cohorts"]}

    cohort_a = by_day["2026-07-19"]
    assert cohort_a["cohort_size"] == 3  # NOT 5 — first-ping assignment excludes device-4/5
    assert cohort_a["d1"] == pytest.approx(66.7, abs=0.1)   # 2 of 3 (device-1, device-2)
    assert cohort_a["d7"] == pytest.approx(33.3, abs=0.1)   # 1 of 3 (device-1 only)
    # day+14 == "today" (2026-08-02): that UTC day hasn't fully elapsed yet,
    # so this is still null even though device-1 already pinged on it — a
    # same-day count would climb through the day and read as final when it
    # isn't (this is a public honesty surface).
    assert cohort_a["d14"] is None

    cohort_b = by_day["2026-07-20"]
    assert cohort_b["cohort_size"] == 2  # device-4, device-5 only
    assert cohort_b["d1"] == pytest.approx(50.0, abs=0.1)   # 1 of 2 (device-4)
    assert cohort_b["d7"] == pytest.approx(0.0, abs=0.1)    # neither returned on 07-27
    assert cohort_b["d14"] is None  # day+14 == 2026-08-03, entirely in the future

    # A day with no first-time devices at all: cohort_size 0, every dN null.
    empty_day = by_day["2026-07-22"]
    assert empty_day == {"day": "2026-07-22", "cohort_size": 0, "d1": None, "d7": None, "d14": None}

    # Once "today" advances past the checkpoint day, the SAME cohort's d14
    # becomes visible (device-1 pinged on 2026-08-02, which has now fully
    # elapsed).
    monkeypatch.setattr(retention_api, "_today", lambda: date(2026, 8, 3))
    cache.clear()
    r2 = c.get("/api/retention")
    by_day2 = {row["day"]: row for row in r2.json()["cohorts"]}
    assert by_day2["2026-07-19"]["d14"] == pytest.approx(33.3, abs=0.1)


def test_dau_covers_last_30_days_including_zero_days(client):
    c, TestingSession = client
    db = TestingSession()
    _ping(db, "device-1", date(2026, 7, 19))
    _ping(db, "device-2", date(2026, 7, 20))
    db.commit()
    db.close()

    r = c.get("/api/retention")
    body = r.json()
    by_day = {row["day"]: row["devices"] for row in body["dau"]}
    assert by_day["2026-07-19"] == 1
    assert by_day["2026-07-20"] == 1
    assert by_day["2026-07-21"] == 0  # no pings that day, but the day still appears
    # "today" is pinned to 2026-08-02 by the fixture's _today() monkeypatch.
    assert by_day["2026-08-02"] == 0


def test_response_is_cached(client, monkeypatch):
    c, TestingSession = client
    db = TestingSession()
    _ping(db, "device-1", date(2026, 7, 19))
    db.commit()
    db.close()

    first = c.get("/api/retention").json()
    assert first["total_devices"] == 1

    # A second device pings after the first read, but the cached response
    # must still be served (mirrors test_model_record_api.py's cache reuse).
    db = TestingSession()
    _ping(db, "device-2", date(2026, 7, 19))
    db.commit()
    db.close()

    second = c.get("/api/retention").json()
    assert second["total_devices"] == 1  # still cached

    cache.clear()
    third = c.get("/api/retention").json()
    assert third["total_devices"] == 2
