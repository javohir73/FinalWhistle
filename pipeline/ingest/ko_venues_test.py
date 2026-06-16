from app.models import Match
from pipeline.ingest.ko_venues import KO_VENUES, apply_ko_venues
from pipeline.ingest.wc26_structure import load_structure


def test_map_covers_all_knockout_matches():
    assert set(KO_VENUES) == set(range(73, 105))
    assert all(c in {"United States", "Mexico", "Canada"} for _, c in KO_VENUES.values())
    assert KO_VENUES[79][1] == "Mexico"
    assert KO_VENUES[85][1] == "Canada"
    assert KO_VENUES[104][1] == "United States"  # final at East Rutherford


def test_apply_ko_venues_populates_country(db_session):
    load_structure(db_session)
    n = apply_ko_venues(db_session)
    assert n == 32
    m79 = db_session.get(Match, 79)
    assert m79.venue_country == "Mexico"
    m104 = db_session.get(Match, 104)
    assert m104.venue_country == "United States"
