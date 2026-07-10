"""Tests for pipeline/sports/nrl_live_poll.py -- live-match poller (Wave 3
Task 4). No live HTTP anywhere in this file.

Covers the brief's 5 core behaviors (time-windowed polling, frozen
pre-game-probability reuse, event-on-score-change, provider-empty ->
None, never-raises) plus two deltas required by the real StatsProvider
contract (pipeline/sports/nrl_stats.py) that the brief's LivePayload
assumption didn't anticipate:
  - status can be "pre" (not just "live"/"final") -- treated as nothing to
    poll yet, and NrlLiveState is never written for it.
  - minute can be None while status == "live" -- the poller falls back to
    a wall-clock estimate for the probability model and the NOT NULL
    NrlLiveEvent.minute column, but stores NrlLiveState.minute exactly as
    received (nullable by design; never fabricated).
"""
from datetime import datetime, timedelta, timezone

from app.models import NrlLiveEvent, NrlLiveState, SportMatch, SportPrediction
from pipeline.sports.nrl_fixture_provider import RecordedFixtureStatsProvider
from pipeline.sports.nrl_live_poll import matches_in_live_window, poll_live_matches, poll_match
from pipeline.sports.nrl_stats import LivePayload


def _make_match(db, kickoff, match_no=1):
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=match_no,
                    status="scheduled", kickoff_utc=kickoff)
    db.add(m)
    db.flush()
    return m


def test_matches_in_live_window_includes_in_progress_excludes_far_future(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    live = _make_match(db_session, kickoff=now - timedelta(minutes=30), match_no=1)
    future = _make_match(db_session, kickoff=now + timedelta(days=2), match_no=2)
    db_session.commit()

    ids = {m.id for m in matches_in_live_window(db_session, now=now)}
    assert live.id in ids
    assert future.id not in ids


def test_poll_match_reuses_frozen_pregame_probability(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.7, p_draw=0.01, p_away=0.29))
    db_session.commit()

    provider = RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=20, score_home=6, score_away=0, status="live"),
    })
    result = poll_match(db_session, m, provider, now=now)
    assert result["status"] == "live"
    assert result["live_home_prob"] > 0.7  # ahead + favourite -> even more likely

    state = db_session.query(NrlLiveState).filter_by(match_id=m.id).one()
    assert state.score_home == 6 and state.minute == 20


def test_poll_match_logs_event_on_score_change(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.5, p_draw=0.01, p_away=0.49))
    db_session.commit()

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=10, score_home=0, score_away=0, status="live"),
    }), now=now)
    assert db_session.query(NrlLiveEvent).filter_by(match_id=m.id).count() == 0

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(minute=15, score_home=4, score_away=0, status="live"),
    }), now=now)
    events = db_session.query(NrlLiveEvent).filter_by(match_id=m.id).all()
    assert len(events) == 1
    assert events[0].team == "home"


def test_poll_match_returns_none_when_provider_has_nothing(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()
    assert poll_match(db_session, m, RecordedFixtureStatsProvider(), now=now) is None


def test_poll_live_matches_never_raises_on_provider_error(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()

    class _Boom:
        def fetch_match_stats(self, *a): return None
        def fetch_team_list(self, *a): return []
        def fetch_live(self, *a): raise RuntimeError("feed down")

    assert poll_live_matches(db_session, _Boom(), now=now) == {"candidates": 1, "polled": 0}


# --- per-side event attribution ---------------------------------------------

def test_poll_match_logs_away_event_on_away_only_increase(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=10, score_home=0, score_away=0),
    }), now=now)
    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=15, score_home=0, score_away=6),
    }), now=now)

    events = db_session.query(NrlLiveEvent).filter_by(match_id=m.id).all()
    assert len(events) == 1
    assert events[0].team == "away"


def test_poll_match_score_correction_updates_state_without_event(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=10, score_home=10, score_away=0),
    }), now=now)
    # Feed correction: home score revised DOWN, away unchanged -- nobody scored.
    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=12, score_home=8, score_away=0),
    }), now=now)

    state = db_session.query(NrlLiveState).filter_by(match_id=m.id).one()
    assert state.score_home == 8  # corrected score persisted
    assert db_session.query(NrlLiveEvent).filter_by(match_id=m.id).count() == 0


def test_poll_match_logs_two_events_when_both_sides_increase(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.commit()

    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=10, score_home=0, score_away=0),
    }), now=now)
    # Slow poll cadence: both sides scored between observations.
    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=18, score_home=6, score_away=4),
    }), now=now)

    events = db_session.query(NrlLiveEvent).filter_by(match_id=m.id).all()
    assert len(events) == 2
    assert {e.team for e in events} == {"home", "away"}
    assert all(e.minute == 18 for e in events)


# --- deltas: real LivePayload has status "pre" and a nullable minute -------

def test_poll_match_ignores_pre_status_payload(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now + timedelta(minutes=3))
    db_session.commit()

    provider = RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="pre", minute=None, score_home=0, score_away=0),
    })
    assert poll_match(db_session, m, provider, now=now) is None
    assert db_session.query(NrlLiveState).filter_by(match_id=m.id).count() == 0


def test_poll_match_handles_none_minute_while_live(db_session):
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=now - timedelta(minutes=20))
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.5, p_draw=0.01, p_away=0.49))
    db_session.commit()

    # First poll: minute known, 0-0 -- establishes the prior stored state.
    poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=10, score_home=0, score_away=0),
    }), now=now)

    # Second poll: provider hasn't resolved a minute yet, but the score moved.
    result = poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=None, score_home=4, score_away=0),
    }), now=now)
    assert result is not None

    state = db_session.query(NrlLiveState).filter_by(match_id=m.id).one()
    assert state.minute is None  # stored exactly as received -- never fabricated
    assert 0.0 < state.live_home_prob < 1.0

    events = db_session.query(NrlLiveEvent).filter_by(match_id=m.id).all()
    assert len(events) == 1
    assert events[0].minute == 20  # wall-clock estimate: kickoff was 20min before `now`


def test_poll_match_handles_none_minute_with_null_kickoff(db_session):
    # SportMatch.kickoff_utc is nullable; a direct poll_match call on such a
    # match with an unresolved minute must not raise (poll_match's contract:
    # never raises). The elapsed estimate falls back to 0 -- conservative,
    # pregame-dominated probability.
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    m = _make_match(db_session, kickoff=None)
    db_session.commit()

    result = poll_match(db_session, m, RecordedFixtureStatsProvider(live={
        (2026, 1, 1): LivePayload(status="live", minute=None, score_home=4, score_away=0),
    }), now=now)
    assert result is not None
    assert 0.0 < result["live_home_prob"] < 1.0

    state = db_session.query(NrlLiveState).filter_by(match_id=m.id).one()
    assert state.minute is None
    assert state.score_home == 4
