"""Tests for pipeline/sports/nrl_form.py -- shared 'last N finished results
for one team' helper used by both the offline preview generator
(nrl_predict.py) and the online detail endpoint (nrl_intel.py)."""
from datetime import datetime, timezone

from app.models import SportMatch, SportTeam
from pipeline.sports.nrl_form import form_averages, last_n_results


def _team(db, name):
    t = SportTeam(sport="nrl", name=name)
    db.add(t); db.flush()
    return t


def _match(db, home, away, no, kickoff, sh, sa, round_=1, status="finished"):
    m = SportMatch(sport="nrl", season=2026, round=round_, match_no=no,
                   kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
                   score_home=sh, score_away=sa, status=status)
    db.add(m); db.flush()
    return m


def test_last_n_results_orders_most_recent_first_and_limits(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    for i in range(1, 8):
        _match(db_session, home, away, i, datetime(2026, 1, i, tzinfo=timezone.utc), 20, 10)
    db_session.commit()

    results = last_n_results(db_session, home.id, n=5)

    assert len(results) == 5
    assert [r["kickoff_utc"].day for r in results] == [7, 6, 5, 4, 3]
    assert all(r["result"] == "W" for r in results)


def test_last_n_results_computes_correct_side_perspective(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), 10, 24)
    db_session.commit()

    away_results = last_n_results(db_session, away.id, n=5)
    assert away_results[0]["for"] == 24
    assert away_results[0]["against"] == 10
    assert away_results[0]["result"] == "W"
    assert away_results[0]["opponent_id"] == home.id


def test_last_n_results_before_excludes_later_matches(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    m1 = _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), 20, 10)
    m2 = _match(db_session, home, away, 2, datetime(2026, 1, 8, tzinfo=timezone.utc), 12, 30)
    db_session.commit()

    results = last_n_results(db_session, home.id, n=5, before=m2)
    assert len(results) == 1
    assert results[0]["for"] == 20


def test_last_n_results_skips_unfinished_matches(db_session):
    home = _team(db_session, "Broncos")
    away = _team(db_session, "Storm")
    _match(db_session, home, away, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), None, None,
           status="scheduled")
    db_session.commit()
    assert last_n_results(db_session, home.id) == []


def test_form_averages_computes_rounded_means():
    results = [
        {"for": 20, "against": 10}, {"for": 10, "against": 20}, {"for": 30, "against": 12},
    ]
    avgs = form_averages(results)
    assert avgs["avg_for"] == round((20 + 10 + 30) / 3, 1)
    assert avgs["avg_against"] == round((10 + 20 + 12) / 3, 1)
    assert avgs["avg_margin"] == round(((20 - 10) + (10 - 20) + (30 - 12)) / 3, 1)


def test_form_averages_empty_is_zeroed():
    assert form_averages([]) == {"avg_for": 0.0, "avg_against": 0.0, "avg_margin": 0.0}
