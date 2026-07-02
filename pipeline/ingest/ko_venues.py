"""Official 2026 World Cup knockout venue schedule (matches 73-104).

KO Match rows ship with venue fields NULL; this populates stadium + city +
country so the bracket simulator can apply host advantage by actual venue/team
pairing and match pages show a venue like group-stage games do. Source: FIFA /
Wikipedia 2026 FIFA World Cup knockout stage. Country is the field that drives
host advantage (USA/Canada/Mexico are the three co-hosts)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Match

# match_no -> (city, country). Host-country KO matches: Mexico {75,79,92},
# Canada {83,85,96}; every other knockout match is in the United States.
KO_VENUES: dict[int, tuple[str, str]] = {
    73: ("Inglewood", "United States"), 74: ("Foxborough", "United States"),
    75: ("Monterrey", "Mexico"), 76: ("Houston", "United States"),
    77: ("East Rutherford", "United States"), 78: ("Arlington", "United States"),
    79: ("Mexico City", "Mexico"), 80: ("Atlanta", "United States"),
    81: ("Santa Clara", "United States"), 82: ("Seattle", "United States"),
    83: ("Toronto", "Canada"), 84: ("Inglewood", "United States"),
    85: ("Vancouver", "Canada"), 86: ("Miami Gardens", "United States"),
    87: ("Kansas City", "United States"), 88: ("Arlington", "United States"),
    89: ("Philadelphia", "United States"), 90: ("Houston", "United States"),
    91: ("East Rutherford", "United States"), 92: ("Mexico City", "Mexico"),
    93: ("Arlington", "United States"), 94: ("Seattle", "United States"),
    95: ("Atlanta", "United States"), 96: ("Vancouver", "Canada"),
    97: ("Foxborough", "United States"), 98: ("Inglewood", "United States"),
    99: ("Miami Gardens", "United States"), 100: ("Kansas City", "United States"),
    101: ("Arlington", "United States"), 102: ("Atlanta", "United States"),
    103: ("Miami Gardens", "United States"), 104: ("East Rutherford", "United States"),
}

# city -> stadium. Commercial names, matching the group-stage convention already
# stored by wc26_structure (e.g. "Estadio Azteca", "SoFi Stadium"). Every city
# appearing in KO_VENUES must be present here (enforced by ko_venues_test).
STADIUM_BY_CITY: dict[str, str] = {
    "Inglewood": "SoFi Stadium",
    "Foxborough": "Gillette Stadium",
    "Monterrey": "Estadio BBVA",
    "Houston": "NRG Stadium",
    "East Rutherford": "MetLife Stadium",
    "Arlington": "AT&T Stadium",
    "Mexico City": "Estadio Azteca",
    "Atlanta": "Mercedes-Benz Stadium",
    "Santa Clara": "Levi's Stadium",
    "Seattle": "Lumen Field",
    "Toronto": "BMO Field",
    "Vancouver": "BC Place",
    "Miami Gardens": "Hard Rock Stadium",
    "Kansas City": "Arrowhead Stadium",
    "Philadelphia": "Lincoln Financial Field",
}


def apply_ko_venues(db: Session) -> int:
    """Populate venue (stadium) / venue_city / venue_country on KO Match rows
    (keyed by match_no). Returns the number of rows updated."""
    updated = 0
    for match_no, (city, country) in KO_VENUES.items():
        m = db.query(Match).filter(Match.match_no == match_no).one_or_none()
        if m is None:
            continue
        m.venue = STADIUM_BY_CITY[city]
        m.venue_city = city
        m.venue_country = country
        updated += 1
    db.commit()
    return updated
