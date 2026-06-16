"""Official 2026 World Cup knockout venue schedule (matches 73-104).

KO Match rows ship with venue_country = NULL; this populates city + country so
the bracket simulator can apply host advantage by actual venue/team pairing.
Source: FIFA / Wikipedia 2026 FIFA World Cup knockout stage. Country is the field
that drives host advantage (USA/Canada/Mexico are the three co-hosts)."""
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


def apply_ko_venues(db: Session) -> int:
    """Populate venue_city/venue_country on KO Match rows (id == match_no).
    Returns the number of rows updated."""
    updated = 0
    for match_no, (city, country) in KO_VENUES.items():
        m = db.get(Match, match_no)
        if m is None:
            continue
        m.venue_city = city
        m.venue_country = country
        updated += 1
    db.commit()
    return updated
