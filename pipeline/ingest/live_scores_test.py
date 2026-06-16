"""Tests for live in-game score ingestion (mocked feed, no network)."""
from datetime import datetime, timedelta, timezone

from app.models import Match, Team
from pipeline.ingest.live_scores import estimate_minute, refresh_live, update_live_scores
from pipeline.ingest.wc26_structure import load_structure


def _match_for(db, home: str, away: str) -> Match:
    h = db.query(Team).filter_by(name=home).one()
    a = db.query(Team).filter_by(name=away).one()
    return (
        db.query(Match)
        .filter_by(team_home_id=h.id, team_away_id=a.id)
        .one()
    )


def test_updates_status_score_and_minute(db_session):
    load_structure(db_session)
    api = [{
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": "IN_PLAY", "minute": 67,
        "score": {"fullTime": {"home": 2, "away": 1}},
    }]
    summary = update_live_scores(db_session, api)
    assert summary["updated"] == 1 and summary["live"] == 1

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "in_play"
    assert m.score_home == 2 and m.score_away == 1
    assert m.minute == 67


def test_orientation_is_normalized_to_our_home_away(db_session):
    load_structure(db_session)
    # Feed reversed (our fixture is Mexico home, South Africa away).
    api = [{
        "homeTeam": {"name": "South Africa"}, "awayTeam": {"name": "Mexico"},
        "status": "FINISHED",
        "score": {"fullTime": {"home": 3, "away": 0}},
    }]
    update_live_scores(db_session, api)
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "finished"
    assert m.score_home == 0 and m.score_away == 3  # Mexico 0, South Africa 3
    assert m.minute is None  # cleared when not in play


def test_team_name_aliases_are_mapped(db_session):
    load_structure(db_session)
    api = [{
        "homeTeam": {"name": "Korea Republic"}, "awayTeam": {"name": "Czechia"},
        "status": "IN_PLAY", "minute": 12,
        "score": {"fullTime": {"home": 0, "away": 0}},
    }]
    summary = update_live_scores(db_session, api)
    assert summary["updated"] == 1  # "Korea Republic" -> "South Korea"


def test_minute_estimated_from_kickoff_when_feed_omits_it(db_session):
    # football-data.org's free tier sends no `minute` field — the live clock
    # must still tick, estimated from kickoff time.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()

    api = [{
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": "IN_PLAY",  # no "minute" key at all
        "score": {"fullTime": {"home": 1, "away": 0}},
    }]
    update_live_scores(db_session, api)
    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.minute == 31  # 30 elapsed minutes → playing the 31st


def test_estimate_minute_maps_match_phases():
    k = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    at = lambda mins: k + timedelta(minutes=mins)  # noqa: E731
    assert estimate_minute(None) is None
    assert estimate_minute(k, at(-2)) == 1     # pre-kickoff race → clamp
    assert estimate_minute(k, at(0.5)) == 1    # opening minute
    assert estimate_minute(k, at(30)) == 31    # first half
    assert estimate_minute(k, at(50)) == 45    # stoppage / half-time holds at 45
    assert estimate_minute(k, at(61)) == 47    # second half resumes (15' break)
    assert estimate_minute(k, at(120)) == 90   # capped
    # Naive datetimes (SQLite) are treated as UTC.
    assert estimate_minute(k.replace(tzinfo=None), at(30)) == 31


def test_no_api_key_is_a_safe_noop(db_session):
    load_structure(db_session)
    summary = refresh_live(db_session, api_key="")
    assert summary["skipped"] == "no_api_key"
    assert summary["updated"] == 0


def test_unknown_provider_skips_loudly(db_session, monkeypatch):
    # An unrecognised live_provider must NOT silently fetch football-data's
    # endpoint with the wrong key — refresh_live skips with a clear marker so a
    # misconfiguration surfaces instead of looking "broken". (football_data and
    # api_football both have real ingestion; see their own tests.)
    from app.config import settings as app_settings

    load_structure(db_session)
    monkeypatch.setattr(app_settings, "live_provider", "satellite_telepathy")
    monkeypatch.setattr(app_settings, "football_data_api_key", "dummy-key")

    summary = refresh_live(db_session)  # default key path -> active_live_api_key
    assert summary["skipped"] == "unknown_provider:satellite_telepathy"
    assert summary["updated"] == 0


def _feed(status: str, home=1, away=0, *, duration="REGULAR", minute=None,
          injury_time=None, last_updated=None, penalties=None,
          top_penalties=None) -> list[dict]:
    """Build a one-item football-data.org v4 match list.
    `penalties` is the score.penalties OBJECT tally; `top_penalties` is the
    UNRELATED top-level kick-event ARRAY (the collision trap)."""
    score: dict = {"fullTime": {"home": home, "away": away}, "duration": duration}
    if penalties is not None:
        score["penalties"] = penalties
    item: dict = {
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": status, "score": score,
    }
    if minute is not None:
        item["minute"] = minute
    if injury_time is not None:
        item["injuryTime"] = injury_time
    if last_updated is not None:
        item["lastUpdated"] = last_updated
    if top_penalties is not None:
        item["penalties"] = top_penalties
    return [item]


def test_lagging_feed_does_not_regress_live_match_to_scheduled(db_session):
    # football-data.org serves the match list from load-balanced caches; a stale
    # node can still answer TIMED minutes after kickoff. In production that
    # seesawed matches between in_play and scheduled on alternating refreshes,
    # freezing the live UI. A not-started claim must never knock back a match
    # we already saw in play.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()

    update_live_scores(db_session, _feed("IN_PLAY"))
    update_live_scores(db_session, _feed("TIMED", home=None, away=None))

    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.score_home == 1 and m.score_away == 0  # lagging blanks ignored too
    assert m.minute is not None  # the live clock keeps ticking


def test_lagging_feed_does_not_regress_finished_match(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed("FINISHED", home=2, away=0))
    update_live_scores(db_session, _feed("SCHEDULED", home=None, away=None))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "finished"
    assert m.score_home == 2 and m.score_away == 0


def test_suspended_is_a_deliberate_downgrade_and_still_applies(db_session):
    # SUSPENDED/POSTPONED/CANCELLED are real not-playing states, not feed lag —
    # those must still take a live match off the board.
    load_structure(db_session)
    update_live_scores(db_session, _feed("IN_PLAY"))
    update_live_scores(db_session, _feed("SUSPENDED"))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "scheduled"


def test_paused_is_half_time_and_freezes_the_clock(db_session):
    # The overcount bug: the kickoff estimate kept ticking through the break.
    # PAUSED is the feed's half-time signal — stay live, freeze, show HT.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=55)
    db_session.commit()

    update_live_scores(db_session, _feed("PAUSED", home=1, away=0))

    db_session.refresh(m)
    assert m.status == "in_play"   # a single PAUSED is half-time, NOT terminal
    assert m.period == "half_time"
    assert m.minute is None        # frozen: the UI shows HT, never a ticking number


def test_stale_paused_into_second_half_is_not_half_time(db_session):
    # The free feed lags and can stay PAUSED well into the second half. Once our
    # clock is past the half-time interval (>60' elapsed), the match must read as
    # the second half, NOT "HT". Regression: the HT window ran to estimated
    # minute 60, so a 2nd-half match was mislabelled "HT" for ~14 minutes.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=65)
    db_session.commit()

    update_live_scores(db_session, _feed("PAUSED", home=1, away=0))

    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.period == "second_half"   # past the break — not half_time
    assert m.minute is not None        # the clock ticks again in the 2nd half


def test_extra_time_duration_sets_period(db_session):
    # ET/penalties are signalled by score.duration, NOT the status field.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=100)
    db_session.commit()

    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=1, duration="EXTRA_TIME"))

    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.period == "extra_time"


def test_penalty_shootout_sets_period_and_tally(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=1, duration="PENALTY_SHOOTOUT",
        penalties={"home": 5, "away": 4},
    ))
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "in_play"
    assert m.period == "penalty_shootout"
    assert m.penalty_home == 5 and m.penalty_away == 4


def test_penalty_tally_read_from_score_object_not_top_level_array(db_session):
    # score.penalties is the shootout TALLY (object). The top-level `penalties`
    # is an ARRAY of individual kicks — never read it as the aggregate.
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=1, duration="PENALTY_SHOOTOUT",
        penalties={"home": 3, "away": 2},
        top_penalties=[
            {"player": {"id": 1, "name": "A"}, "team": {"id": 9, "name": "Mexico"}, "scored": True},
            {"player": {"id": 2, "name": "B"}, "team": {"id": 9, "name": "Mexico"}, "scored": True},
            {"player": {"id": 3, "name": "C"}, "team": {"id": 9, "name": "Mexico"}, "scored": True},
            {"player": {"id": 4, "name": "D"}, "team": {"id": 9, "name": "Mexico"}, "scored": False},
        ],
    ))
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.penalty_home == 3 and m.penalty_away == 2  # not len(top_penalties)


def test_penalty_tally_orientation_swapped_when_feed_reversed(db_session):
    load_structure(db_session)
    # Our fixture is Mexico home, South Africa away; the feed sends it reversed.
    update_live_scores(db_session, [{
        "homeTeam": {"name": "South Africa"}, "awayTeam": {"name": "Mexico"},
        "status": "IN_PLAY",
        "score": {"fullTime": {"home": 1, "away": 1}, "duration": "PENALTY_SHOOTOUT",
                  "penalties": {"home": 2, "away": 5}},
    }])
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.penalty_home == 5 and m.penalty_away == 2  # swapped to our orientation


def test_absent_phase_nodes_do_not_crash(db_session):
    # A REGULAR match omits the penalties node entirely.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=20)
    db_session.commit()

    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=0))

    db_session.refresh(m)
    assert m.penalty_home is None and m.penalty_away is None
    assert m.period in ("first_half", "second_half")


def test_injury_time_stored_when_feed_reports_it(db_session):
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=46)
    db_session.commit()

    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=0, minute=45, injury_time=2))

    db_session.refresh(m)
    assert m.minute == 45
    assert m.injury_time == 2


def test_first_then_second_half_period(db_session):
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()
    update_live_scores(db_session, _feed("IN_PLAY", home=0, away=0))
    db_session.refresh(m)
    assert m.period == "first_half"

    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=70)
    db_session.commit()
    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=0))
    db_session.refresh(m)
    assert m.period == "second_half"


def test_stale_lastupdated_does_not_overwrite_fresher_record(db_session):
    # A lagging cache node can serve an OLDER snapshot. Compare lastUpdated and
    # never let it clobber a newer record we already applied.
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=2, away=1, minute=70, last_updated="2026-06-13T02:10:00Z"))
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=0, minute=55, last_updated="2026-06-13T02:05:00Z"))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.score_home == 2 and m.score_away == 1  # newer record kept


def test_lastupdated_recorded_and_strictly_newer_applies(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=0, last_updated="2026-06-13T02:05:00Z"))
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.provider_last_updated is not None

    update_live_scores(db_session, _feed(
        "IN_PLAY", home=2, away=0, last_updated="2026-06-13T02:12:00Z"))
    db_session.refresh(m)
    assert m.score_home == 2  # strictly-newer applies


def test_finished_shootout_tally_survives_a_later_finished_without_duration(db_session):
    # A lagging FINISHED snapshot that omits the duration must not wipe a settled
    # knockout result (else the final renders as a draw with the pens line gone).
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "FINISHED", home=1, away=1, duration="PENALTY_SHOOTOUT",
        penalties={"home": 4, "away": 2}))
    update_live_scores(db_session, _feed("FINISHED", home=1, away=1))  # no duration/pens

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.penalty_home == 4 and m.penalty_away == 2


def test_deliberate_suspension_applies_even_from_an_older_snapshot(db_session):
    # SUSPENDED/POSTPONED/CANCELLED have no later snapshot to self-heal, so the
    # freshness guard must not suppress them — a stranded match would show "in
    # play" with a ticking clock forever otherwise.
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=0, last_updated="2026-06-13T02:10:00Z"))
    update_live_scores(db_session, _feed(
        "POSTPONED", home=1, away=0, last_updated="2026-06-13T02:05:00Z"))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "scheduled"


def test_partial_payload_does_not_blank_a_known_live_score(db_session):
    # A missing/null score on a refresh must keep the last known score, not flip
    # the UI back to the predicted score under a live badge.
    load_structure(db_session)
    update_live_scores(db_session, _feed("IN_PLAY", home=2, away=1, minute=70))
    update_live_scores(db_session, [{
        "homeTeam": {"name": "Mexico"}, "awayTeam": {"name": "South Africa"},
        "status": "IN_PLAY",  # no score node at all
    }])
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.score_home == 2 and m.score_away == 1


def test_paused_after_90_is_not_labelled_half_time(db_session):
    # The break before extra time (PAUSED, duration still REGULAR, ~90') must not
    # show "HT" in a knockout match.
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=95)
    db_session.commit()

    update_live_scores(db_session, _feed("PAUSED", home=1, away=1))

    db_session.refresh(m)
    assert m.period != "half_time"


def test_finished_not_reopened_by_a_newer_stamped_in_play(db_session):
    # Production always carries lastUpdated; the anti-flap guard must hold even
    # when a stale IN_PLAY arrives with a *newer* stamp than the final.
    load_structure(db_session)
    update_live_scores(db_session, _feed(
        "FINISHED", home=2, away=0, last_updated="2026-06-13T03:00:00Z"))
    update_live_scores(db_session, _feed(
        "IN_PLAY", home=2, away=1, last_updated="2026-06-13T03:05:00Z"))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "finished"
    assert m.score_home == 2 and m.score_away == 0


def test_in_play_not_regressed_by_an_older_stamped_timed(db_session):
    # Timestamped variant of the PR #26 flap guard (the path production takes).
    load_structure(db_session)
    m = _match_for(db_session, "Mexico", "South Africa")
    m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()

    update_live_scores(db_session, _feed(
        "IN_PLAY", home=1, away=0, last_updated="2026-06-13T02:10:00Z"))
    update_live_scores(db_session, _feed(
        "TIMED", home=None, away=None, last_updated="2026-06-13T02:05:00Z"))

    db_session.refresh(m)
    assert m.status == "in_play"
    assert m.score_home == 1 and m.score_away == 0


def test_finished_match_is_not_reopened_by_lagging_in_play(db_session):
    # A stale node replaying IN_PLAY after full time must not reopen the match:
    # downstream consumers treat the *transition* to finished as an event, so a
    # reopen would make the replayed FINISHED look like a fresh final whistle.
    load_structure(db_session)
    update_live_scores(db_session, _feed("FINISHED", home=2, away=0))
    update_live_scores(db_session, _feed("IN_PLAY", home=2, away=0))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "finished"
    assert m.minute is None


def test_unknown_feed_status_never_downgrades_known_state(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed("IN_PLAY"))
    update_live_scores(db_session, _feed("SOME_FUTURE_STATUS"))

    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.status == "in_play"


def test_scorers_field_is_stored_as_goal_events(db_session):
    load_structure(db_session)
    feed = _feed("IN_PLAY", home=1, away=0, minute=30)
    feed[0]["scorers"] = [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]
    update_live_scores(db_session, feed)
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.goal_events == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]


def test_absent_scorers_leaves_goal_events_untouched(db_session):
    load_structure(db_session)
    update_live_scores(db_session, _feed("IN_PLAY", home=1, away=0, minute=30))
    m = _match_for(db_session, "Mexico", "South Africa")
    assert m.goal_events is None  # football_data feed carries no scorers
