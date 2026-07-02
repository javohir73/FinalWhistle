from app.models import Match
from pipeline.ingest.ko_venues import KO_VENUES, STADIUM_BY_CITY, apply_ko_venues
from pipeline.ingest.wc26_structure import load_structure


def test_map_covers_all_knockout_matches():
    assert set(KO_VENUES) == set(range(73, 105))
    assert all(c in {"United States", "Mexico", "Canada"} for _, c in KO_VENUES.values())
    assert KO_VENUES[79][1] == "Mexico"
    assert KO_VENUES[85][1] == "Canada"
    assert KO_VENUES[104][1] == "United States"  # final at East Rutherford


def test_every_knockout_city_has_a_stadium():
    """Every host city referenced by a KO match must have a stadium name, so
    apply_ko_venues can populate the `venue` field for all 32 matches."""
    ko_cities = {city for city, _ in KO_VENUES.values()}
    assert ko_cities <= set(STADIUM_BY_CITY)


def test_apply_ko_venues_populates_country(db_session):
    load_structure(db_session)
    n = apply_ko_venues(db_session)
    assert n == 32
    m79 = db_session.get(Match, 79)
    assert m79.venue_country == "Mexico"
    m104 = db_session.get(Match, 104)
    assert m104.venue_country == "United States"


def test_apply_ko_venues_populates_stadium_and_city(db_session):
    """KO rows must show a stadium name (the `venue` field) like group matches,
    not just city/country — otherwise the match page shows a blank venue."""
    load_structure(db_session)
    apply_ko_venues(db_session)
    m82 = db_session.get(Match, 82)  # Seattle
    assert m82.venue == "Lumen Field"
    assert m82.venue_city == "Seattle"
    m81 = db_session.get(Match, 81)  # Santa Clara
    assert m81.venue == "Levi's Stadium"
    m104 = db_session.get(Match, 104)  # East Rutherford (final)
    assert m104.venue == "MetLife Stadium"
