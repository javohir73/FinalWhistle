"""Hermetic tests for the independent validation sources. No network, no keys."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Match,
    MarketOddsSnapshot,
    Odds,
    Prediction,
    Team,
    Tournament,
    ValidationFixtureObservation,
    ValidationMarketSnapshot,
)
from pipeline.ingest.validation import loader, sources
from pipeline.ingest.validation.identity import (
    KICKOFF_TOLERANCE,
    MatchCandidate,
    canonical_club,
    resolve,
)
from pipeline.report_validation_sources import (
    LIVE_VALIDATION_SEASON_START,
    reconciliation_report,
    secondary_market_benchmark,
)
from pipeline.run_validation_ingest import run_source

KO = datetime(2026, 9, 12, 13, 30, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, status_code=200, payload=None, raises=None):
        self.status_code, self._p, self._raises = status_code, payload, raises

    def json(self):
        if self._raises:
            raise self._raises
        return self._p


class _Req:
    def __init__(self, resp=None, raises=None):
        self._resp, self._raises = resp, raises

    def get(self, *a, **k):
        if self._raises:
            raise self._raises
        return self._resp


BUNDESLIGA = loader.DEFAULT_TOURNAMENT


def _fixture_db(db, home="Bayern Munich", away="Dortmund", kickoff=KO,
                score=(None, None), status="scheduled", tournament=None):
    name = tournament or BUNDESLIGA
    t = db.query(Tournament).filter_by(name=name).one_or_none()
    if t is None:
        t = Tournament(name=name, year=2026)
        db.add(t)
        db.flush()
    h = db.query(Team).filter_by(name=home).one_or_none() or Team(name=home, is_host=False)
    a = db.query(Team).filter_by(name=away).one_or_none() or Team(name=away, is_host=False)
    db.add_all([h, a])
    db.flush()
    m = Match(tournament_id=t.id, team_home_id=h.id, team_away_id=a.id,
              kickoff_utc=kickoff, status=status, score_home=score[0],
              score_away=score[1], stage="group")
    db.add(m)
    db.commit()
    return m


# --- identity ---------------------------------------------------------------

def test_german_club_aliases_map_provider_spellings():
    assert canonical_club("FC Bayern München") == "Bayern Munich"
    assert canonical_club("Bayern Munchen") == "Bayern Munich"
    assert canonical_club("Bor. Mönchengladbach") == "M'gladbach"
    assert canonical_club("1. FC Köln") == "Koln"
    assert canonical_club("FC St. Pauli") == "St Pauli"
    assert canonical_club("SpVgg Greuther Fürth") == "Greuther Furth"


def test_an_unmapped_label_is_none_not_a_guess():
    assert canonical_club("Some Unknown FC") is None
    assert canonical_club("") is None


def test_resolve_matches_on_both_clubs_and_kickoff_window():
    c = [MatchCandidate(7, "Bayern Munich", "Dortmund", KO)]
    r = resolve("FC Bayern München", "Borussia Dortmund", KO + timedelta(hours=2), c)
    assert (r.status, r.match_id) == ("matched", 7)


def test_resolve_rejects_a_kickoff_outside_the_tolerance():
    c = [MatchCandidate(7, "Bayern Munich", "Dortmund", KO)]
    r = resolve("FC Bayern München", "Borussia Dortmund",
                KO + KICKOFF_TOLERANCE + timedelta(hours=1), c)
    assert r.status == "unmatched"


def test_resolve_respects_orientation_so_the_reverse_fixture_is_not_matched():
    c = [MatchCandidate(7, "Bayern Munich", "Dortmund", KO)]
    r = resolve("Borussia Dortmund", "FC Bayern München", KO, c)
    assert r.status == "unmatched"


def test_an_unmapped_label_is_reported_with_the_alias_it_needs():
    r = resolve("Mystery FC", "Borussia Dortmund", KO, [])
    assert r.status == "unmatched"
    assert "Mystery FC" in r.note and "ALIASES" in r.note


def test_ambiguous_candidates_are_a_conflict_not_a_coin_flip():
    c = [MatchCandidate(1, "Bayern Munich", "Dortmund", KO),
         MatchCandidate(2, "Bayern Munich", "Dortmund", KO + timedelta(hours=1))]
    r = resolve("FC Bayern München", "Borussia Dortmund", KO, c)
    assert r.status == "conflict" and r.match_id is None
    assert "ambiguous" in r.note


# --- parsers ----------------------------------------------------------------

def _fdo_payload(score=(2, 1), mid=101):
    return {"matches": [{
        "id": mid, "utcDate": "2026-09-12T13:30:00Z", "status": "FINISHED",
        "lastUpdated": "2026-09-12T15:30:00Z",
        "season": {"startDate": "2026-08-01"},
        "homeTeam": {"name": "FC Bayern München"},
        "awayTeam": {"name": "Borussia Dortmund"},
        "score": {"fullTime": {"home": score[0], "away": score[1]}}}]}


def _old_payload(score=(2, 1), mid=201):
    return [{
        "matchID": mid, "matchDateTimeUTC": "2026-09-12T13:30:00Z",
        "matchIsFinished": True, "leagueSeason": 2026,
        "lastUpdateDateTime": "2026-09-12T15:31:00",
        "team1": {"teamName": "FC Bayern München"},
        "team2": {"teamName": "Borussia Dortmund"},
        "matchResults": [{"resultTypeID": 1, "pointsTeam1": 1, "pointsTeam2": 0},
                         {"resultTypeID": 2, "pointsTeam1": score[0],
                          "pointsTeam2": score[1]}]}]


def test_football_data_org_parser_extracts_the_full_time_score():
    [o] = sources.parse_football_data_org(_fdo_payload())
    assert (o.source, o.score_home, o.score_away) == ("football_data_org", 2, 1)
    assert o.kickoff_utc == KO
    assert o.source_updated_at is not None
    assert len(o.payload_sha256) == 64


def test_openligadb_parser_prefers_the_final_result_over_half_time():
    [o] = sources.parse_openligadb(_old_payload())
    assert (o.score_home, o.score_away) == (2, 1)  # not the 1-0 half time
    assert o.status == "finished"


def test_parsers_skip_malformed_rows_instead_of_raising():
    assert sources.parse_football_data_org({"matches": [{"id": None}, {}]}) == []
    assert sources.parse_openligadb([{"matchID": 1}, {}]) == []
    assert sources.parse_football_data_org({}) == []
    assert sources.parse_openligadb([]) == []


def test_odds_api_parser_uses_the_bookmakers_own_timestamp():
    payload = [{
        "id": "evt1", "commence_time": "2026-09-12T13:30:00Z",
        "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
        "bookmakers": [{"key": "pinnacle", "last_update": "2026-09-12T13:10:00Z",
                        "markets": [{"key": "h2h", "outcomes": [
                            {"name": "FC Bayern München", "price": 1.5},
                            {"name": "Draw", "price": 4.2},
                            {"name": "Borussia Dortmund", "price": 6.0}]}]}]}]
    rows = sources.parse_odds_api(payload)
    assert {r.outcome for r in rows} == {"home", "draw", "away"}
    assert all(r.captured_at == datetime(2026, 9, 12, 13, 10, tzinfo=timezone.utc)
               for r in rows)
    assert all(r.bookmaker_key == "pinnacle" for r in rows)


def test_odds_api_parser_ignores_non_h2h_markets():
    payload = [{"id": "e", "commence_time": "2026-09-12T13:30:00Z",
                "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
                "bookmakers": [{"key": "b", "last_update": "2026-09-12T13:00:00Z",
                                "markets": [{"key": "totals", "outcomes": [
                                    {"name": "Over", "price": 1.9}]}]}]}]
    assert sources.parse_odds_api(payload) == []


# --- betfair importer: stateful available-to-back reconstruction -----------
#
# rc messages are PARTIAL DELTAS carrying `atb` [price, size] levels; size 0
# removes a level. Sides come from sortPriority, never list order. Anything
# that is not soccer Bundesliga MATCH_ODDS is rejected rather than stamped, and
# in-play is excluded. `ltp` is last-traded, NOT available-to-back, and is
# never substituted.

BF_COMP = "5555"
BF_KO = datetime(2026, 9, 12, 13, 30, tzinfo=timezone.utc)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _bf_md(*, event_type="1", market_type="MATCH_ODDS", competition=BF_COMP,
           in_play=False, draw_name="The Draw"):
    return {"eventTypeId": event_type, "marketType": market_type,
            "competitionId": competition, "inPlay": in_play,
            "marketTime": BF_KO.isoformat().replace("+00:00", "Z"),
            "runners": [
                {"id": 11, "name": "Borussia Dortmund", "sortPriority": 2},
                {"id": 10, "name": "FC Bayern München", "sortPriority": 1},
                {"id": 12, "name": draw_name, "sortPriority": 3}]}


def _line(dt, mc):
    return json.dumps({"pt": _ms(dt), "mc": mc})


def _bf_parse(lines, **kw):
    kw.setdefault("archive_sha256", "d" * 64)
    kw.setdefault("acquisition_note", "downloaded 2026-09-13, Pro tier")
    kw.setdefault("competition_id", BF_COMP)
    return sources.parse_betfair_archive(lines, **kw)


def test_betfair_requires_digest_note_and_competition():
    lines = [_line(BF_KO - timedelta(hours=1), [{"id": "1.1",
                                                 "marketDefinition": _bf_md()}])]
    with pytest.raises(ValueError, match="archive_sha256 AND acquisition_note"):
        _bf_parse(lines, archive_sha256="")
    with pytest.raises(ValueError, match="archive_sha256 AND acquisition_note"):
        _bf_parse(lines, acquisition_note="")
    with pytest.raises(ValueError, match="competition_id"):
        _bf_parse(lines, competition_id="")


def test_a_partial_delta_sequence_forms_a_triple_only_once_all_three_exist():
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        # Two runners priced: still incoherent, emit nothing.
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.50, 100]]}, {"id": 11, "atb": [[6.00, 50]]}]}]),
        # Third runner arrives -> first coherent snapshot.
        _line(t0 + timedelta(minutes=2), [{"id": "1.1", "rc": [
            {"id": 12, "atb": [[4.20, 25]]}]}]),
    ]
    rows = _bf_parse(lines)
    assert len(rows) == 3
    assert {r.outcome for r in rows} == {"home", "draw", "away"}
    assert all(r.captured_at == t0 + timedelta(minutes=2) for r in rows)
    assert {r.outcome: r.price_decimal for r in rows} == {
        "home": 1.50, "away": 6.00, "draw": 4.20}


def test_best_back_is_the_highest_offered_price_and_zero_size_removes_a_level():
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.50, 100], [1.55, 20]]},
            {"id": 11, "atb": [[6.00, 50]]}, {"id": 12, "atb": [[4.20, 25]]}]}]),
        # Remove the 1.55 level; best back must fall back to 1.50.
        _line(t0 + timedelta(minutes=2), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.55, 0]]}]}]),
    ]
    rows = _bf_parse(lines)
    homes = [r for r in rows if r.outcome == "home"]
    assert [h.price_decimal for h in homes] == [1.55, 1.50]


def test_an_unchanged_ladder_does_not_emit_a_duplicate_snapshot():
    t0 = BF_KO - timedelta(hours=2)
    full = [{"id": 10, "atb": [[1.50, 100]]}, {"id": 11, "atb": [[6.00, 50]]},
            {"id": 12, "atb": [[4.20, 25]]}]
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": full}]),
        # Same sizes restated: nothing moved, so nothing new is emitted.
        _line(t0 + timedelta(minutes=2), [{"id": "1.1", "rc": full}]),
    ]
    assert len(_bf_parse(lines)) == 3


def test_sides_come_from_sort_priority_not_runner_list_order():
    """The definition lists away first; home must still be sortPriority 1."""
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.50, 100]]}, {"id": 11, "atb": [[6.00, 50]]},
            {"id": 12, "atb": [[4.20, 25]]}]}]),
    ]
    by_side = {r.outcome: r for r in _bf_parse(lines)}
    assert by_side["home"].price_decimal == 1.50   # runner 10, sortPriority 1
    assert by_side["away"].price_decimal == 6.00   # runner 11, sortPriority 2
    assert by_side["home"].raw_home_label == "FC Bayern München"
    assert by_side["home"].raw_away_label == "Borussia Dortmund"


def test_a_non_bundesliga_competition_is_rejected_not_stamped():
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md(competition="9999")}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.5, 1]]}, {"id": 11, "atb": [[6.0, 1]]},
            {"id": 12, "atb": [[4.2, 1]]}]}]),
    ]
    assert _bf_parse(lines) == []


def test_non_soccer_and_non_match_odds_markets_are_rejected():
    t0 = BF_KO - timedelta(hours=2)
    for md in (_bf_md(event_type="7"), _bf_md(market_type="OVER_UNDER_25")):
        lines = [
            _line(t0, [{"id": "1.1", "marketDefinition": md}]),
            _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
                {"id": 10, "atb": [[1.5, 1]]}, {"id": 11, "atb": [[6.0, 1]]},
                {"id": 12, "atb": [[4.2, 1]]}]}]),
        ]
        assert _bf_parse(lines) == []


def test_in_play_snapshots_are_excluded():
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md(in_play=True)}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.5, 1]]}, {"id": 11, "atb": [[6.0, 1]]},
            {"id": 12, "atb": [[4.2, 1]]}]}]),
    ]
    assert _bf_parse(lines) == []


def test_a_snapshot_exactly_at_kickoff_is_excluded():
    lines = [
        _line(BF_KO - timedelta(hours=1), [{"id": "1.1",
                                            "marketDefinition": _bf_md()}]),
        _line(BF_KO, [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.5, 1]]}, {"id": 11, "atb": [[6.0, 1]]},
            {"id": 12, "atb": [[4.2, 1]]}]}]),
    ]
    assert _bf_parse(lines) == []


def test_a_basic_tier_archive_with_only_ltp_fails_closed():
    """Never relabel last-traded price as available-to-back."""
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "ltp": 1.5}, {"id": 11, "ltp": 6.0}, {"id": 12, "ltp": 4.2}]}]),
    ]
    with pytest.raises(sources.BetfairArchiveUnsupported, match="ADVANCED or PRO"):
        _bf_parse(lines)


def test_unparseable_lines_are_skipped_without_losing_the_rest():
    t0 = BF_KO - timedelta(hours=2)
    lines = [
        "not json", "",
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.5, 1]]}, {"id": 11, "atb": [[6.0, 1]]},
            {"id": 12, "atb": [[4.2, 1]]}]}]),
    ]
    assert len(_bf_parse(lines)) == 3


def test_betfair_run_source_refuses_without_a_note(db_session, tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text("")
    r = run_source(db_session, "betfair_historical", archive=f,
                   acquisition_note=None, competition_id=BF_COMP)
    assert r["ok"] is False and "acquisition-note" in r["reason"]


def test_betfair_run_source_reports_an_unsupported_tier_without_raising(
        db_session, tmp_path):
    t0 = BF_KO - timedelta(hours=2)
    f = tmp_path / "basic.jsonl"
    f.write_text("\n".join([
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "ltp": 1.5}]}]),
    ]))
    r = run_source(db_session, "betfair_historical", archive=f,
                   acquisition_note="note", competition_id=BF_COMP)
    assert r["ok"] is False and "ADVANCED or PRO" in r["reason"]


# --- fetch isolation --------------------------------------------------------

def test_unconfigured_keys_fail_closed_without_raising(monkeypatch):
    monkeypatch.delenv(sources.FOOTBALL_DATA_ENV, raising=False)
    monkeypatch.delenv(sources.ODDS_API_ENV, raising=False)
    a = sources.fetch_football_data_org(2026)
    b = sources.fetch_odds_api()
    assert (a.ok, b.ok) == (False, False)
    assert "not configured" in a.reason and "not configured" in b.reason
    assert a.items == [] and b.items == []


def test_rate_limit_is_reported_not_raised():
    r = sources.fetch_openligadb(2026, requests_mod=_Req(_Resp(429)))
    assert r.ok is False and "rate limited" in r.reason


def test_timeout_is_reported_not_raised():
    r = sources.fetch_openligadb(2026, requests_mod=_Req(raises=TimeoutError("slow")))
    assert r.ok is False and "TimeoutError" in r.reason


def test_malformed_json_is_reported_not_raised():
    r = sources.fetch_openligadb(
        2026, requests_mod=_Req(_Resp(200, raises=ValueError("bad json"))))
    assert r.ok is False and "ValueError" in r.reason


def test_non_200_is_reported_not_raised():
    r = sources.fetch_openligadb(2026, requests_mod=_Req(_Resp(500)))
    assert r.ok is False and "http 500" in r.reason


# --- loader: append-only, idempotent, isolated ------------------------------

def test_fixture_load_matches_and_is_idempotent(db_session):
    _fixture_db(db_session)
    obs = sources.parse_openligadb(_old_payload())
    first = loader.load_fixture_observations(db_session, obs)
    assert (first["inserted"], first["matched"]) == (1, 1)

    again = loader.load_fixture_observations(db_session, obs)
    assert (again["inserted"], again["duplicate"]) == (0, 1)
    assert db_session.query(ValidationFixtureObservation).count() == 1


def test_a_corrected_score_appends_rather_than_overwriting(db_session):
    _fixture_db(db_session)
    loader.load_fixture_observations(db_session, sources.parse_openligadb(_old_payload()))
    loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload(score=(3, 1))))
    rows = db_session.query(ValidationFixtureObservation).order_by(
        ValidationFixtureObservation.id).all()
    assert len(rows) == 2
    assert (rows[0].score_home, rows[1].score_home) == (2, 3)  # original readable


def test_an_unmatched_observation_is_stored_with_its_reason(db_session):
    obs = sources.parse_openligadb(_old_payload())
    stats = loader.load_fixture_observations(db_session, obs)
    assert stats["unmatched"] == 1
    row = db_session.query(ValidationFixtureObservation).one()
    assert row.match_id is None
    assert row.reconciliation_status == "unmatched"
    assert row.raw_home_label == "FC Bayern München"      # raw label preserved
    assert row.canonical_home == "Bayern Munich"          # canonical too


def test_market_load_devigs_within_a_group_and_is_idempotent(db_session):
    m = _fixture_db(db_session)
    rows = sources.parse_odds_api([{
        "id": "e1", "commence_time": "2026-09-12T13:30:00Z",
        "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
        "bookmakers": [{"key": "pin", "last_update": "2026-09-12T13:00:00Z",
                        "markets": [{"key": "h2h", "outcomes": [
                            {"name": "FC Bayern München", "price": 1.5},
                            {"name": "Draw", "price": 4.2},
                            {"name": "Borussia Dortmund", "price": 6.0}]}]}]}])
    s = loader.load_market_observations(db_session, rows)
    assert s["inserted"] == 3 and s["devigged_groups"] == 1
    stored = db_session.query(ValidationMarketSnapshot).all()
    assert all(r.match_id == m.id for r in stored)
    assert sum(r.implied_prob_devig for r in stored) == pytest.approx(1.0)

    again = loader.load_market_observations(db_session, rows)
    assert again["inserted"] == 0 and again["duplicate"] == 3


def test_an_incomplete_book_is_stored_but_not_devigged(db_session):
    _fixture_db(db_session)
    rows = sources.parse_odds_api([{
        "id": "e1", "commence_time": "2026-09-12T13:30:00Z",
        "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
        "bookmakers": [{"key": "pin", "last_update": "2026-09-12T13:00:00Z",
                        "markets": [{"key": "h2h", "outcomes": [
                            {"name": "FC Bayern München", "price": 1.5}]}]}]}])
    loader.load_market_observations(db_session, rows)
    assert db_session.query(ValidationMarketSnapshot).one().implied_prob_devig is None


# --- THE BOUNDARY: never touch odds or market_odds_snapshots ----------------

def test_ingest_never_writes_the_pre_registered_odds_baseline(db_session, tmp_path):
    """The regression test the review asked for. The q3 benchmark reads `odds`;
    a new provider landing there would silently change a merged, pre-registered
    comparison."""
    _fixture_db(db_session)
    before_odds = db_session.query(Odds).count()
    before_intel = db_session.query(MarketOddsSnapshot).count()

    loader.load_fixture_observations(db_session, sources.parse_openligadb(_old_payload()))
    loader.load_market_observations(db_session, sources.parse_odds_api([{
        "id": "e", "commence_time": "2026-09-12T13:30:00Z",
        "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
        "bookmakers": [{"key": "b", "last_update": "2026-09-12T13:00:00Z",
                        "markets": [{"key": "h2h", "outcomes": [
                            {"name": "FC Bayern München", "price": 1.5},
                            {"name": "Draw", "price": 4.2},
                            {"name": "Borussia Dortmund", "price": 6.0}]}]}]}]))
    t0 = BF_KO - timedelta(hours=2)
    f = tmp_path / "a.jsonl"
    f.write_text("\n".join([
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.5, 100]]}, {"id": 11, "atb": [[6.0, 50]]},
            {"id": 12, "atb": [[4.2, 25]]}]}]),
    ]))
    r = run_source(db_session, "betfair_historical", archive=f,
                   acquisition_note="test archive", competition_id=BF_COMP)
    assert r["ok"] is True

    assert db_session.query(Odds).count() == before_odds
    assert db_session.query(MarketOddsSnapshot).count() == before_intel
    assert db_session.query(ValidationFixtureObservation).count() > 0
    assert db_session.query(ValidationMarketSnapshot).count() > 0


def test_no_module_in_this_package_imports_the_frozen_baseline_models():
    """Structural guard: the boundary should be impossible, not merely untaken."""
    import pathlib

    pkg = pathlib.Path(loader.__file__).parent
    for f in pkg.glob("*.py"):
        if f.name.endswith("_test.py"):
            continue
        src = f.read_text()
        assert "MarketOddsSnapshot" not in src, f
        # `Odds` only ever appears as part of ValidationMarketSnapshot here.
        assert "import Odds" not in src and ", Odds," not in src, f


# --- reporting --------------------------------------------------------------

def test_score_disagreement_is_reported_and_nothing_is_overwritten(db_session):
    m = _fixture_db(db_session, score=(1, 1), status="finished")
    loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload(score=(2, 1))))
    rep = reconciliation_report(db_session)
    assert rep["clean"] is False
    [d] = rep["score_disagreements"]
    assert d["ours"] == "1-1" and d["theirs"] == "2-1"
    db_session.refresh(m)
    assert (m.score_home, m.score_away) == (1, 1)  # untouched


def test_secondary_benchmark_counts_one_match_as_n_equals_one(db_session):
    """Two sources and two books must NOT inflate n."""
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    db_session.add(Prediction(
        match_id=m.id, model_version="poisson-elo-club-v0.2", is_shadow=False,
        prob_home_win=0.55, prob_draw=0.25, prob_away_win=0.20,
        created_at=m.kickoff_utc - timedelta(hours=3)))
    for source, book in (("the_odds_api", "pin"), ("betfair_historical", "bf")):
        for outcome, p in (("home", 0.6), ("draw", 0.25), ("away", 0.15)):
            db_session.add(ValidationMarketSnapshot(
                source=source, source_market_id=f"{source}-m", outcome=outcome,
                competition_code="BL1", kickoff_utc=m.kickoff_utc,
                raw_home_label="x", raw_away_label="y", match_id=m.id,
                bookmaker_key=book, implied_prob_devig=p,
                captured_at=m.kickoff_utc - timedelta(minutes=30),
                retrieved_at=m.kickoff_utc, payload_sha256="p",
                reconciliation_status="matched"))
    db_session.commit()

    b = secondary_market_benchmark(db_session)
    assert b["distinct_matches"] == 1
    assert set(b["by_source"]) == {"the_odds_api", "betfair_historical"}
    assert all(v["n_matches"] == 1 for v in b["by_source"].values())
    assert "SECONDARY" in b["status"]


def test_post_kickoff_snapshots_are_inadmissible(db_session):
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    db_session.add(Prediction(
        match_id=m.id, model_version="v", is_shadow=False, prob_home_win=0.5,
        prob_draw=0.3, prob_away_win=0.2,
        created_at=m.kickoff_utc - timedelta(hours=3)))
    for offset in (timedelta(0), timedelta(minutes=1)):  # at, and after, kickoff
        for outcome, p in (("home", 0.6), ("draw", 0.25), ("away", 0.15)):
            db_session.add(ValidationMarketSnapshot(
                source="the_odds_api", source_market_id=f"m{offset}", outcome=outcome,
                competition_code="BL1", kickoff_utc=m.kickoff_utc,
                raw_home_label="x", raw_away_label="y", match_id=m.id,
                bookmaker_key="pin", implied_prob_devig=p,
                captured_at=m.kickoff_utc + offset, retrieved_at=m.kickoff_utc,
                payload_sha256="p", reconciliation_status="matched"))
    db_session.commit()
    assert secondary_market_benchmark(db_session)["by_source"] == {}


def test_pre_2026_27_matches_cannot_reach_the_live_confirmation_window(db_session):
    """Training seasons and the consumed holdout are provenance only."""
    old_ko = LIVE_VALIDATION_SEASON_START - timedelta(days=30)
    m = _fixture_db(db_session, score=(2, 0), status="finished", kickoff=old_ko)
    db_session.add(Prediction(
        match_id=m.id, model_version="v", is_shadow=False, prob_home_win=0.5,
        prob_draw=0.3, prob_away_win=0.2, created_at=old_ko - timedelta(hours=3)))
    for outcome, p in (("home", 0.6), ("draw", 0.25), ("away", 0.15)):
        db_session.add(ValidationMarketSnapshot(
            source="the_odds_api", source_market_id="m", outcome=outcome,
            competition_code="BL1", kickoff_utc=old_ko, raw_home_label="x",
            raw_away_label="y", match_id=m.id, bookmaker_key="pin",
            implied_prob_devig=p, captured_at=old_ko - timedelta(minutes=30),
            retrieved_at=old_ko, payload_sha256="p",
            reconciliation_status="matched"))
    db_session.commit()

    live = secondary_market_benchmark(db_session, live_only=True)
    assert live["by_source"] == {} and live["excluded_pre_2026_27_matches"] == 1
    provenance = secondary_market_benchmark(db_session, live_only=False)
    assert provenance["by_source"]["the_odds_api"]["n_matches"] == 1


def test_run_source_rejects_an_unknown_source(db_session):
    r = run_source(db_session, "not_a_source")
    assert r["ok"] is False and "unknown source" in r["reason"]


# ---------------------------------------------------------------------------
# Independent P1 review fixes.
# ---------------------------------------------------------------------------

def test_the_default_tournament_tracks_the_league_registry():
    """A drifting literal would silently unscope every candidate search."""
    from pipeline.leagues import LEAGUES

    assert loader.DEFAULT_TOURNAMENT == LEAGUES["bundesliga"]["tournament_name"]


def test_a_betfair_archive_loads_as_ONE_devigged_triple(db_session):
    """End-to-end: the market id must be shared across runners, or the loader
    sees three one-outcome groups and can never de-vig."""
    _fixture_db(db_session)
    t0 = BF_KO - timedelta(hours=2)
    rows = _bf_parse([
        _line(t0, [{"id": "1.1", "marketDefinition": _bf_md()}]),
        _line(t0 + timedelta(minutes=1), [{"id": "1.1", "rc": [
            {"id": 10, "atb": [[1.50, 100]]}, {"id": 11, "atb": [[6.00, 50]]},
            {"id": 12, "atb": [[4.20, 25]]}]}]),
    ])
    assert len({r.source_market_id for r in rows}) == 1  # one market, three runners

    stats = loader.load_market_observations(db_session, rows)
    assert stats["devigged_groups"] == 1
    assert stats["inserted"] == 3
    stored = db_session.query(ValidationMarketSnapshot).all()
    assert {r.outcome for r in stored} == {"home", "draw", "away"}
    assert all(r.implied_prob_devig is not None for r in stored)
    assert sum(r.implied_prob_devig for r in stored) == pytest.approx(1.0)
    assert all(r.match_id is not None for r in stored)


def test_candidates_are_scoped_so_another_tournament_cannot_steal_a_match(db_session):
    """Same clubs, same kickoff, different competition -> must not resolve."""
    _fixture_db(db_session, tournament="Premier League 2026-27")
    stats = loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload()))
    assert stats["matched"] == 0 and stats["unmatched"] == 1


def test_a_bundesliga_fixture_still_resolves_when_a_decoy_exists(db_session):
    """The decoy in another tournament must not create ambiguity either."""
    _fixture_db(db_session, tournament="Premier League 2026-27")
    _fixture_db(db_session)  # the real Bundesliga fixture
    stats = loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload()))
    assert stats["matched"] == 1 and stats["conflict"] == 0


def test_observations_are_unresolved_when_no_bundesliga_fixture_exists(db_session):
    stats = loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload()))
    assert stats["unmatched"] == 1
    assert db_session.query(ValidationFixtureObservation).one().match_id is None


@pytest.mark.parametrize("bad", [1.0, 0.5, 0.0, -2.0, float("nan"),
                                 float("inf"), None])
def test_unusable_prices_are_rejected_before_storage(db_session, bad):
    _fixture_db(db_session)
    good = sources.MarketObservation(
        source="the_odds_api", source_market_id="m", source_event_id="e",
        competition_code="BL1", kickoff_utc=KO, raw_home_label="FC Bayern München",
        raw_away_label="Borussia Dortmund", bookmaker_key="pin", outcome="home",
        price_decimal=bad, captured_at=KO - timedelta(hours=1), payload_sha256="p")
    stats = loader.load_market_observations(db_session, [good])
    assert stats["rejected_price"] == 1
    assert stats["inserted"] == 0
    assert db_session.query(ValidationMarketSnapshot).count() == 0


def test_a_partially_unusable_group_stores_the_rest_without_devigging(db_session):
    _fixture_db(db_session)
    base = dict(source="the_odds_api", source_market_id="m", source_event_id="e",
                competition_code="BL1", kickoff_utc=KO,
                raw_home_label="FC Bayern München", raw_away_label="Borussia Dortmund",
                bookmaker_key="pin", captured_at=KO - timedelta(hours=1),
                payload_sha256="p")
    obs = [sources.MarketObservation(outcome="home", price_decimal=1.5, **base),
           sources.MarketObservation(outcome="draw", price_decimal=4.2, **base),
           sources.MarketObservation(outcome="away", price_decimal=1.0, **base)]
    stats = loader.load_market_observations(db_session, obs)
    assert stats["rejected_price"] == 1 and stats["inserted"] == 2
    assert stats["devigged_groups"] == 0
    assert all(r.implied_prob_devig is None
               for r in db_session.query(ValidationMarketSnapshot).all())


def test_domain_violations_raise_rather_than_storing_junk(db_session):
    _fixture_db(db_session)
    bad_source = sources.MarketObservation(
        source="not_a_real_source", source_market_id="m", source_event_id="e",
        competition_code="BL1", kickoff_utc=KO, raw_home_label="FC Bayern München",
        raw_away_label="Borussia Dortmund", bookmaker_key="pin", outcome="home",
        price_decimal=1.5, captured_at=KO - timedelta(hours=1), payload_sha256="p")
    with pytest.raises(ValueError, match="unknown source"):
        loader.load_market_observations(db_session, [bad_source])

    bad_outcome = sources.MarketObservation(
        source="the_odds_api", source_market_id="m", source_event_id="e",
        competition_code="BL1", kickoff_utc=KO, raw_home_label="FC Bayern München",
        raw_away_label="Borussia Dortmund", bookmaker_key="pin", outcome="tie",
        price_decimal=1.5, captured_at=KO - timedelta(hours=1), payload_sha256="p")
    with pytest.raises(ValueError, match="bad outcome"):
        loader.load_market_observations(db_session, [bad_outcome])


def test_domain_constants_cover_exactly_the_expected_values():
    assert loader.VALID_OUTCOMES == {"home", "draw", "away"}
    assert loader.VALID_RECONCILIATION == {"matched", "unmatched", "conflict"}
    assert loader.VALID_SOURCES == {"football_data_org", "openligadb",
                                    "the_odds_api", "betfair_historical"}


def test_stored_probabilities_are_always_a_valid_distribution(db_session):
    _fixture_db(db_session)
    rows = sources.parse_odds_api([{
        "id": "e1", "commence_time": "2026-09-12T13:30:00Z",
        "home_team": "FC Bayern München", "away_team": "Borussia Dortmund",
        "bookmakers": [{"key": "pin", "last_update": "2026-09-12T13:00:00Z",
                        "markets": [{"key": "h2h", "outcomes": [
                            {"name": "FC Bayern München", "price": 1.5},
                            {"name": "Draw", "price": 4.2},
                            {"name": "Borussia Dortmund", "price": 6.0}]}]}]}])
    loader.load_market_observations(db_session, rows)
    for r in db_session.query(ValidationMarketSnapshot).all():
        assert 0.0 < r.implied_prob_devig < 1.0
        assert 0.0 < r.implied_prob_raw < 1.0
        assert r.price_decimal > 1.0


# ---------------------------------------------------------------------------
# Final independent review: coherent snapshots, superseded revisions, q3 pairing.
# ---------------------------------------------------------------------------

def _snap(db, match, *, source, book, market, captured, probs, outcomes=None):
    """Write one market snapshot per outcome for a single coherent snapshot."""
    for outcome, p in (outcomes or probs).items():
        db.add(ValidationMarketSnapshot(
            source=source, source_market_id=market, outcome=outcome,
            competition_code="BL1", kickoff_utc=match.kickoff_utc,
            raw_home_label="x", raw_away_label="y", match_id=match.id,
            bookmaker_key=book, implied_prob_devig=p, captured_at=captured,
            retrieved_at=match.kickoff_utc, payload_sha256="p",
            reconciliation_status="matched"))


def _prod_pred(db, match, probs=(0.50, 0.25, 0.25),
               version="poisson-elo-club-v0.2"):
    db.add(Prediction(
        match_id=match.id, model_version=version, is_shadow=False,
        prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
        created_at=match.kickoff_utc - timedelta(hours=3)))


def test_a_closing_triple_is_never_stitched_from_different_timestamps(db_session):
    """Selecting the latest row PER OUTCOME would fabricate a line that never
    existed at any instant."""
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m)
    t = m.kickoff_utc
    # Three incomplete snapshots, each missing two outcomes, at three times.
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=t - timedelta(hours=3), probs={"home": 0.90})
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=t - timedelta(hours=2), probs={"draw": 0.05})
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=t - timedelta(hours=1), probs={"away": 0.05})
    db_session.commit()

    assert secondary_market_benchmark(db_session)["by_source"] == {}


def test_a_coherent_snapshot_is_used_even_when_a_later_partial_exists(db_session):
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m)
    t = m.kickoff_utc
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=t - timedelta(hours=3),
          probs={"home": 0.60, "draw": 0.25, "away": 0.15})
    # A later, INCOMPLETE update must not displace the complete earlier one.
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=t - timedelta(hours=1), probs={"home": 0.99})
    db_session.commit()

    b = secondary_market_benchmark(db_session)["by_source"]["the_odds_api"]
    assert b["n_matches"] == 1
    # Home happened at p=0.60 -> LL ~0.51. The 0.99 partial would give ~0.01.
    assert b["source_log_loss"] == pytest.approx(-math.log(0.60), abs=1e-6)


def test_the_newest_complete_snapshot_wins_not_the_alphabetically_first_book(db_session):
    """'aaa_book' sorts first but is older; 'zzz_book' is closer to kickoff."""
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m)
    t = m.kickoff_utc
    _snap(db_session, m, source="the_odds_api", book="aaa_book", market="mk1",
          captured=t - timedelta(hours=5),
          probs={"home": 0.90, "draw": 0.05, "away": 0.05})
    _snap(db_session, m, source="the_odds_api", book="zzz_book", market="mk2",
          captured=t - timedelta(minutes=20),
          probs={"home": 0.40, "draw": 0.30, "away": 0.30})
    db_session.commit()

    b = secondary_market_benchmark(db_session)["by_source"]["the_odds_api"]
    assert b["source_log_loss"] == pytest.approx(-math.log(0.40), abs=1e-6)


def test_snapshot_selection_is_deterministic_across_reruns(db_session):
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m)
    t = m.kickoff_utc - timedelta(hours=1)
    for book, market in (("b_book", "m2"), ("a_book", "m1")):
        _snap(db_session, m, source="the_odds_api", book=book, market=market,
              captured=t, probs={"home": 0.5, "draw": 0.3, "away": 0.2})
    db_session.commit()
    runs = {secondary_market_benchmark(db_session)["by_source"][
        "the_odds_api"]["source_log_loss"] for _ in range(3)}
    assert len(runs) == 1


def test_a_corrected_observation_supersedes_the_old_conflict(db_session):
    """Append-only history is preserved, but only the CURRENT row is judged."""
    _fixture_db(db_session, score=(1, 1), status="finished")
    loader.load_fixture_observations(
        db_session, sources.parse_openligadb(_old_payload(score=(2, 1))))
    assert reconciliation_report(db_session)["score_disagreements"]

    corrected = sources.parse_openligadb(_old_payload(score=(1, 1)))
    corrected[0].source_updated_at = KO + timedelta(hours=4)  # later revision
    loader.load_fixture_observations(db_session, corrected)

    rep = reconciliation_report(db_session)
    assert rep["score_disagreements"] == []
    assert rep["per_source"]["openligadb"]["score_agreements"] == 1
    assert rep["effective_observations"] == 1
    assert rep["superseded_revisions"] == 1
    # History retained, not rewritten.
    assert db_session.query(ValidationFixtureObservation).count() == 2


def test_q3_coverage_is_reported_separately_and_never_shrinks_the_counts(db_session):
    """Two matches, only one with a twin: source counts must stay at 2."""
    from pipeline.generate_predictions import variant_model_version_for

    matches = []
    for i, ko in enumerate((KO, KO + timedelta(days=7))):
        m = _fixture_db(db_session, home="Bayern Munich", away="Dortmund",
                        kickoff=ko, score=(2, 0), status="finished")
        _prod_pred(db_session, m)
        _snap(db_session, m, source="the_odds_api", book="pin", market=f"mk{i}",
              captured=ko - timedelta(hours=1),
              probs={"home": 0.55, "draw": 0.25, "away": 0.20})
        matches.append(m)
    # Twin on the FIRST match only.
    db_session.add(Prediction(
        match_id=matches[0].id,
        model_version=variant_model_version_for("poisson-elo-club-v0.2", "cal_q3"),
        is_shadow=True, prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
        created_at=matches[0].kickoff_utc - timedelta(hours=3)))
    db_session.commit()

    bench = secondary_market_benchmark(db_session)
    b = bench["by_source"]["the_odds_api"]
    assert b["n_matches"] == 2                    # NOT reduced by the missing twin
    assert bench["distinct_matches"] == 2
    assert bench["distinct_matches_with_variant"] == 1

    v = b["variant"]
    assert v["name"] == "cal_q3" and v["n_paired"] == 1
    assert v["coverage"] == pytest.approx(0.5)
    # Paired deltas are stated on the paired subset, not the full sample.
    assert v["variant_log_loss"] == pytest.approx(-math.log(0.70), abs=1e-6)
    assert v["model_log_loss_on_paired"] == pytest.approx(-math.log(0.50), abs=1e-6)
    assert v["delta_variant_minus_model"] < 0


def test_a_post_kickoff_twin_is_not_paired(db_session):
    from pipeline.generate_predictions import variant_model_version_for

    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m)
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=m.kickoff_utc - timedelta(hours=1),
          probs={"home": 0.55, "draw": 0.25, "away": 0.20})
    db_session.add(Prediction(
        match_id=m.id,
        model_version=variant_model_version_for("poisson-elo-club-v0.2", "cal_q3"),
        is_shadow=True, prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
        created_at=m.kickoff_utc + timedelta(minutes=5)))
    db_session.commit()

    bench = secondary_market_benchmark(db_session)
    assert bench["by_source"]["the_odds_api"]["n_matches"] == 1
    assert bench["by_source"]["the_odds_api"]["variant"] is None
    assert bench["distinct_matches_with_variant"] == 0


def test_a_twin_for_another_production_version_is_not_paired(db_session):
    m = _fixture_db(db_session, score=(2, 0), status="finished")
    _prod_pred(db_session, m, version="poisson-elo-club-v0.2")
    _snap(db_session, m, source="the_odds_api", book="pin", market="mk",
          captured=m.kickoff_utc - timedelta(hours=1),
          probs={"home": 0.55, "draw": 0.25, "away": 0.20})
    db_session.add(Prediction(
        match_id=m.id, model_version="poisson-elo-v0.5+cal_q3", is_shadow=True,
        prob_home_win=0.70, prob_draw=0.18, prob_away_win=0.12,
        created_at=m.kickoff_utc - timedelta(hours=3)))
    db_session.commit()
    assert secondary_market_benchmark(db_session)[
        "by_source"]["the_odds_api"]["variant"] is None
