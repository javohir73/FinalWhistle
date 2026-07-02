"""Tests for the API-Football (api-sports.io v3) -> normalized feed adapter.

to_feed() translates api-sports fixtures into the football-data v4 shape that
update_live_scores() already consumes, so all the battle-tested update logic
(orientation, freshness, periods, penalties) is reused unchanged. The win over
football-data's free tier: the REAL live minute (status.elapsed)."""
from app.models import Match, Team
from pipeline.ingest.api_football import to_feed, cards_from_events
from pipeline.ingest.live_scores import refresh_live, update_live_scores
from pipeline.ingest.wc26_structure import load_structure


def _fixture(short, elapsed=None, *, home="Mexico", away="South Africa",
             gh=None, ga=None, extra=None, pen_h=None, pen_a=None):
    """Build a one-item api-sports.io v3 /fixtures `response` list."""
    return {
        "fixture": {"id": 42, "date": "2026-06-14T18:00:00+00:00",
                    "status": {"short": short, "elapsed": elapsed, "extra": extra}},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": gh, "away": ga},
        "score": {"halftime": {"home": None, "away": None},
                  "fulltime": {"home": None, "away": None},
                  "extratime": {"home": None, "away": None},
                  "penalty": {"home": pen_h, "away": pen_a}},
    }


def test_live_second_half_carries_the_real_minute():
    item = to_feed([_fixture("2H", elapsed=67, gh=2, ga=1)])[0]
    assert item["status"] == "IN_PLAY"
    assert item["minute"] == 67  # the OFFICIAL minute, not a kickoff estimate
    assert item["score"]["fullTime"] == {"home": 2, "away": 1}


def test_finished_maps_to_finished():
    item = to_feed([_fixture("FT", gh=3, ga=0)])[0]
    assert item["status"] == "FINISHED"
    assert item["score"]["fullTime"] == {"home": 3, "away": 0}


def test_halftime_maps_to_paused():
    assert to_feed([_fixture("HT", elapsed=45, gh=1, ga=0)])[0]["status"] == "PAUSED"


def test_break_before_extra_time_stays_live():
    assert to_feed([_fixture("BT", elapsed=90, gh=1, ga=1)])[0]["status"] == "PAUSED"


def test_extra_time_sets_duration():
    item = to_feed([_fixture("ET", elapsed=105, gh=1, ga=1)])[0]
    assert item["status"] == "IN_PLAY"
    assert item["score"]["duration"] == "EXTRA_TIME"


def test_penalty_shootout_sets_duration_and_tally():
    item = to_feed([_fixture("PEN", gh=1, ga=1, pen_h=5, pen_a=4)])[0]
    assert item["status"] == "FINISHED"
    assert item["score"]["duration"] == "PENALTY_SHOOTOUT"
    assert item["score"]["penalties"] == {"home": 5, "away": 4}


def test_injury_time_read_from_status_extra():
    item = to_feed([_fixture("2H", elapsed=90, extra=4, gh=0, ga=0)])[0]
    assert item["minute"] == 90
    assert item["injuryTime"] == 4


def test_not_started_maps_to_timed():
    assert to_feed([_fixture("NS")])[0]["status"] == "TIMED"


def test_deliberate_stops_map_through():
    assert to_feed([_fixture("PST")])[0]["status"] == "POSTPONED"
    assert to_feed([_fixture("CANC")])[0]["status"] == "CANCELLED"
    assert to_feed([_fixture("SUSP")])[0]["status"] == "SUSPENDED"


def test_malformed_fixture_is_skipped_not_crashed():
    assert to_feed([{"fixture": {}, "teams": {}}, _fixture("FT", gh=1, ga=0)]) \
        == to_feed([{"fixture": {}, "teams": {}}, _fixture("FT", gh=1, ga=0)])
    # one good item survives a broken sibling
    assert len(to_feed([{"junk": True}, _fixture("FT", gh=1, ga=0)])) == 1


def test_translated_feed_applies_through_update_live_scores(db_session):
    # End-to-end: api-sports fixture -> to_feed -> update_live_scores writes the
    # REAL minute (67) into the DB, proving the adapter reuses the tested pipeline.
    load_structure(db_session)
    summary = update_live_scores(db_session, to_feed([_fixture("2H", elapsed=67, gh=2, ga=1)]))
    assert summary["updated"] == 1 and summary["live"] == 1
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    assert m.status == "in_play"
    assert m.minute == 67  # real minute from the feed, not estimated
    assert m.score_home == 2 and m.score_away == 1


def test_refresh_live_routes_to_api_football_when_selected(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    monkeypatch.setattr(app_settings, "live_provider", "api_football")
    monkeypatch.setattr(app_settings, "api_football_api_key", "dummy-key")
    monkeypatch.setattr(af, "fetch_fixtures",
                        lambda *a, **k: [_fixture("2H", elapsed=55, gh=1, ga=0)])
    monkeypatch.setattr(af, "fetch_events", lambda *a, **k: [])

    summary = refresh_live(db_session)  # default key path -> active_live_api_key
    assert summary["updated"] == 1
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    assert m.status == "in_play" and m.minute == 55


from pipeline.ingest.api_football import goals_from_events


def _event(detail, team, player, minute, etype="Goal"):
    return {"type": etype, "detail": detail, "team": {"name": team},
            "player": {"name": player}, "time": {"elapsed": minute}}


def test_goals_from_events_normal_penalty_and_side():
    events = [
        _event("Normal Goal", "Iran", "R. Rezaeian", 32),
        _event("Penalty", "New Zealand", "C. Wood", 70),
    ]
    out = goals_from_events(events, "Iran", "New Zealand")
    assert out == [
        {"minute": 32, "side": "home", "player": "R. Rezaeian", "type": "goal"},
        {"minute": 70, "side": "away", "player": "C. Wood", "type": "penalty"},
    ]


def test_own_goal_is_credited_to_the_opponent():
    # Player from the home team scores an own goal -> counts for the AWAY side.
    out = goals_from_events([_event("Own Goal", "Iran", "Defender X", 18)],
                            "Iran", "New Zealand")
    assert out == [{"minute": 18, "side": "away", "player": "Defender X", "type": "own_goal"}]


def test_non_goal_and_missed_penalty_events_ignored():
    events = [
        _event("Yellow Card", "Iran", "Y", 10, etype="Card"),
        _event("Missed Penalty", "Iran", "Z", 22),
    ]
    assert goals_from_events(events, "Iran", "New Zealand") == []


def test_unknown_team_event_is_skipped_and_missing_player_defaulted():
    events = [
        _event("Normal Goal", "Some Other Team", "P", 5),
        {"type": "Goal", "detail": "Normal Goal", "team": {"name": "Iran"},
         "player": {}, "time": {"elapsed": 60}},
    ]
    out = goals_from_events(events, "Iran", "New Zealand")
    assert out == [{"minute": 60, "side": "home", "player": "Unknown", "type": "goal"}]


def test_attach_scorers_fetches_only_when_goal_total_changed(db_session, monkeypatch):
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    # A live fixture, Mexico 1-0 South Africa, fixture id 777.
    feed = to_feed([_fixture("2H", elapsed=55, gh=1, ga=0)])
    feed[0]["_fixture_id"] = 777

    calls = {"n": 0}
    def fake_events(key, fid, timeout=15.0):
        calls["n"] += 1
        return [_event("Normal Goal", "Mexico", "R. Jimenez", 30)]
    monkeypatch.setattr(af, "fetch_events", fake_events)

    af._last_events_fetch.clear()
    af.attach_events(db_session, feed, "dummy-key")
    assert calls["n"] == 1
    assert feed[0]["scorers"] == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]


def test_refresh_live_api_football_stores_scorers(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    monkeypatch.setattr(app_settings, "live_provider", "api_football")
    monkeypatch.setattr(app_settings, "api_football_api_key", "dummy-key")
    monkeypatch.setattr(af, "fetch_fixtures",
                        lambda *a, **k: [_fixture("2H", elapsed=55, gh=1, ga=0)])
    monkeypatch.setattr(af, "fetch_events",
                        lambda *a, **k: [_event("Normal Goal", "Mexico", "R. Jimenez", 30)])

    refresh_live(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    assert m.goal_events == [
        {"minute": 30, "side": "home", "player": "R. Jimenez", "type": "goal"}]


def test_cards_from_events_yellow_red_and_sides():
    events = [
        _event("Yellow Card", "Iran", "S. Moharrami", 28, etype="Card"),
        _event("Red Card", "New Zealand", "J. Bell", 55, etype="Card"),
    ]
    out = cards_from_events(events, "Iran", "New Zealand")
    assert out == [
        {"minute": 28, "side": "home", "player": "S. Moharrami", "type": "yellow"},
        {"minute": 55, "side": "away", "player": "J. Bell", "type": "red"},
    ]


def test_cards_from_events_skips_goals_unknown_details_and_teams():
    events = [
        _event("Normal Goal", "Iran", "R. Rezaeian", 32),               # not a card
        _event("Card upgrade", "Iran", "X", 40, etype="Card"),          # unknown detail
        _event("Yellow Card", "Brazil", "Y", 50, etype="Card"),         # unknown team
        "garbage",                                                       # malformed
    ]
    assert cards_from_events(events, "Iran", "New Zealand") == []


def test_cards_from_events_defaults_missing_player():
    e = _event("Red Card", "Iran", None, 77, etype="Card")
    e["player"] = {}
    assert cards_from_events([e], "Iran", "New Zealand") == [
        {"minute": 77, "side": "home", "player": "Unknown", "type": "red"}]


def test_attach_events_refetches_when_stale_without_goal_change(db_session, monkeypatch):
    from app.config import settings as app_settings
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    # Neutralize the goal-count trigger: 0 feed goals == 0 stored goal events.
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.goal_events = []
    db_session.commit()

    calls = {"n": 0}
    def fake_events(key, fid, timeout=15.0):
        calls["n"] += 1
        return [_event("Red Card", "Mexico", "J. Vasquez", 50, etype="Card")]
    monkeypatch.setattr(af, "fetch_events", fake_events)
    monkeypatch.setattr(app_settings, "events_refetch_seconds", 180)
    af._last_events_fetch.clear()

    feed = to_feed([_fixture("2H", elapsed=55, gh=0, ga=0)])
    feed[0]["_fixture_id"] = 778
    af.attach_events(db_session, feed, "dummy-key")   # never fetched before -> stale
    assert calls["n"] == 1
    assert feed[0]["cards"] == [
        {"minute": 50, "side": "home", "player": "J. Vasquez", "type": "red"}]
    assert feed[0]["scorers"] == []

    feed2 = to_feed([_fixture("2H", elapsed=56, gh=0, ga=0)])
    feed2[0]["_fixture_id"] = 778
    af.attach_events(db_session, feed2, "dummy-key")  # fresh -> no fetch
    assert calls["n"] == 1
    assert "cards" not in feed2[0]

    af._last_events_fetch[778] -= 9999                # age past the cutoff
    af.attach_events(db_session, feed2, "dummy-key")  # stale again -> fetch
    assert calls["n"] == 2


def test_attach_events_finished_fixture_keeps_goal_count_trigger_only(db_session, monkeypatch):
    import pipeline.ingest.api_football as af

    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    m = db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()
    m.goal_events = []
    db_session.commit()

    calls = {"n": 0}
    monkeypatch.setattr(af, "fetch_events",
                        lambda *args, **kw: calls.__setitem__("n", calls["n"] + 1) or [])
    af._last_events_fetch.clear()

    feed = to_feed([_fixture("FT", gh=0, ga=0)])
    feed[0]["_fixture_id"] = 779
    af.attach_events(db_session, feed, "dummy-key")
    assert calls["n"] == 0  # finished + goal totals agree: no staleness refetch
