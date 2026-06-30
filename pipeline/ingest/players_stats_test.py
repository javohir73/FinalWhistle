from app.models import Player
from pipeline.ingest import players as players_mod
from pipeline.ingest.players import _aggregate_stats, ingest_player_stats


def test_aggregate_sums_entries_and_treats_null_as_zero():
    statistics = [
        {"league": {"id": 15, "season": 2025}, "games": {"minutes": 540}, "goals": {"total": None}, "penalty": {"scored": 0}},
        {"league": {"id": 140, "season": 2025}, "games": {"minutes": 2880}, "goals": {"total": 4}, "penalty": {"scored": 2}},
        {"league": {"id": 2, "season": 2025}, "games": {"minutes": None}, "goals": {"total": 1}, "penalty": {"scored": None}},
    ]
    goals, minutes, pens = _aggregate_stats(statistics)
    assert goals == 5          # None + 4 + 1
    assert minutes == 3420     # 540 + 2880 + 0
    assert pens == 2           # 0 + 2 + 0


def test_aggregate_filters_by_league_id():
    statistics = [
        {"league": {"id": 1}, "games": {"minutes": 270}, "goals": {"total": 2}, "penalty": {"scored": 1}},
        {"league": {"id": 140}, "games": {"minutes": 900}, "goals": {"total": 9}, "penalty": {"scored": 3}},
    ]
    goals, minutes, pens = _aggregate_stats(statistics, league_id=1)
    assert (goals, minutes, pens) == (2, 270, 1)   # only the WC (league 1) entry


def test_ingest_player_stats_sets_club_and_wc(db_session, monkeypatch):
    player = Player(provider_player_id=909, name="K. De Bruyne", position="M")
    db_session.add(player)
    db_session.commit()

    def fake_fetch(api_key, player_id, season, **k):
        if season == 2025:   # club season -> sum all
            return [{"player": {"id": 909}, "statistics": [
                {"league": {"id": 140}, "games": {"minutes": 2400}, "goals": {"total": 8}, "penalty": {"scored": 1}},
                {"league": {"id": 2}, "games": {"minutes": 600}, "goals": {"total": 2}, "penalty": {"scored": 0}},
            ]}]
        return [{"player": {"id": 909}, "statistics": [   # WC season -> filter league 1
            {"league": {"id": 1}, "games": {"minutes": 270}, "goals": {"total": 1}, "penalty": {"scored": 0}},
        ]}]

    monkeypatch.setattr(players_mod, "fetch_player_stats", fake_fetch)
    ingest_player_stats(db_session, "k", player, club_season=2025, wc_season=2026, wc_league=1)

    got = db_session.query(Player).filter_by(provider_player_id=909).one()
    assert got.club_goals == 10 and got.club_minutes == 3000 and got.club_penalties == 1
    assert got.wc_goals == 1 and got.wc_minutes == 270
    assert got.season == 2025 and got.updated_at is not None


def test_ingest_player_stats_zeros_stale_data_on_empty_response(db_session, monkeypatch):
    """Re-ingestion with an empty response must zero all five stat fields."""
    player = Player(
        provider_player_id=42,
        name="Stale Player",
        position="F",
        club_goals=7,
        club_minutes=1800,
        club_penalties=2,
        wc_goals=3,
        wc_minutes=270,
    )
    db_session.add(player)
    db_session.commit()

    monkeypatch.setattr(players_mod, "fetch_player_stats", lambda *a, **k: [])
    ingest_player_stats(db_session, "k", player, club_season=2025, wc_season=2026, wc_league=1)

    got = db_session.query(Player).filter_by(provider_player_id=42).one()
    assert got.club_goals == 0
    assert got.club_minutes == 0
    assert got.club_penalties == 0
    assert got.wc_goals == 0
    assert got.wc_minutes == 0
    assert got.updated_at is not None
