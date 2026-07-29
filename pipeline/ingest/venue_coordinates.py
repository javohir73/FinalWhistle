"""D1 — verified home-venue coordinates for the club leagues, from Wikidata.

There was no coordinate anywhere in this repository before this module: no
latitude, no longitude, no distance, for any venue in any sport. Travel has
therefore never been tested here, and it cannot be until a coordinate exists
that someone can check.

**Every coordinate comes from Wikidata and carries its QID.** This module
never invents one and never falls back to a city centroid, a nearest
neighbour, or a "close enough". A club the rule cannot resolve is **named in
the report** — the convention `pipeline/ingest/validation/identity.py` already
sets for German club names, applied to venues.

The resolution rule, fixed before the run
-----------------------------------------
1. `pipeline/data/club_venue_aliases.json` maps a football-data.co.uk short
   label ("Nott'm Forest") to the club's canonical name. That file holds **no
   coordinates** — it is a naming table, and the naming is public knowledge.
2. Candidate venues are every non-ended `P115` (home venue) statement on any
   entity whose English `rdfs:label` or `skos:altLabel` equals that name, where
   the venue carries both `P625` (coordinates) and `P1083` (capacity).
3. Rank candidates by capacity and require a **strictly unique maximum**.

Step 3 is doing real work, not tidying. Wikidata lists training grounds and
former stadiums as home venues with no end date — Athletic Bilbao's Lezama
facilities (3,250) alongside San Mamés (53,289), RB Leipzig's Cottaweg
alongside the Red Bull Arena. Capacity separates them deterministically, and
because the venue is what matters, several club entities sharing one label
(FC Barcelona is modelled as a men's team, a multisport club and a non-profit)
all agree on Camp Nou and resolve cleanly.

Zero candidates → `unresolved`. A tied maximum → `conflict`. Neither is ever
resolved by picking one.

Licence — and why this snapshot IS committed
--------------------------------------------
Wikidata is **CC0**: public domain, redistribution explicitly granted. So the
resolved table ships in the repository, bytes and all, and stays reproducible
forever. That is the exact contrast with `pipeline/ingest/football_data.py`,
whose publisher grants free download and no redistribution (stop gate G1) —
and whose bytes, not being retained, left D0 unable to diagnose its own drift.

Pure and offline apart from :func:`fetch_bindings`, the one operator-run
network entry point, which no test calls for real.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"
ALIASES_PATH = _DATA / "club_venue_aliases.json"
SNAPSHOT_PATH = _DATA / "club_venues.json"

DIVISIONS = ("E0", "SP1", "D1")

#: Provider provenance, carried into every D1 output.
PROVIDER = {
    "provider": "Wikidata",
    "endpoint": "https://query.wikidata.org/sparql",
    "properties": {
        "P115": "home venue",
        "P625": "coordinate location",
        "P1083": "maximum capacity",
        "P582": "end time (qualifier — excludes former venues)",
    },
    "cost": "free — no key, no account, no quota tier",
    "licence": "CC0 1.0 Universal (public domain dedication)",
    "redistribution": "GRANTED — the resolved snapshot is committed, bytes included",
    "attribution": "Data from Wikidata, CC0 1.0",
}

#: Earth radius (km), mean. Great-circle distance is accurate enough at these
#: scales — the longest domestic trip in scope is Las Palmas to a mainland
#: fixture, and a few hundred metres of ellipsoid correction cannot matter to a
#: signal measured per 1000 km.
_EARTH_KM = 6371.0088

_POINT = re.compile(r"^Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)$")


class UnresolvedVenue(KeyError):
    """A club has no verified coordinate. Never substituted for a guess."""


@dataclass(frozen=True)
class ClubVenue:
    """One club's home venue, with enough provenance to be checked by hand."""

    club: str  # football-data.co.uk short label
    division: str
    canonical_name: str  # the alias table's canonical club name
    venue_qid: str
    venue_label: str
    lat: float
    lon: float
    capacity: int


def parse_point(literal: str) -> tuple[float, float]:
    """Wikidata's ``Point(lon lat)`` WKT -> ``(lat, lon)``.

    Note the order swap: WKT is longitude-first and every consumer here wants
    latitude-first. Getting it backwards silently produces distances that are
    wrong but plausible, which is the worst kind of wrong.
    """
    m = _POINT.match(literal.strip())
    if not m:
        raise ValueError(f"unparseable Wikidata point literal: {literal!r}")
    lon, lat = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"point out of range: {literal!r}")
    return lat, lon


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two ``(lat, lon)`` pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def load_aliases(path: Path | None = None) -> dict[str, dict[str, str]]:
    """The naming table, without its documentation keys."""
    raw = json.loads((path or ALIASES_PATH).read_text(encoding="utf-8"))
    return {d: raw[d] for d in DIVISIONS}


def required_clubs(aliases: dict[str, dict[str, str]] | None = None) -> list[tuple[str, str]]:
    """``(division, short_label)`` for every club the snapshot must cover."""
    al = aliases or load_aliases()
    return [(d, c) for d in DIVISIONS for c in sorted(al[d])]


SPARQL_TEMPLATE = """SELECT ?name ?venue ?venueLabel ?coord ?cap WHERE {
  VALUES ?name { %s }
  ?club rdfs:label|skos:altLabel ?name .
  ?club p:P115 ?statement .
  ?statement ps:P115 ?venue .
  FILTER NOT EXISTS { ?statement pq:P582 ?ended }
  FILTER NOT EXISTS { ?statement wikibase:rank wikibase:DeprecatedRank }
  ?venue wdt:P625 ?coord .
  ?venue wdt:P1083 ?cap .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def build_query(names: list[str]) -> str:
    values = " ".join('"%s"@en' % n.replace('"', '\\"') for n in names)
    return SPARQL_TEMPLATE % values


def resolve(
    bindings: list[dict], aliases: dict[str, dict[str, str]] | None = None
) -> tuple[list[ClubVenue], list[dict]]:
    """Apply the rule to SPARQL bindings. Pure — no network, no files.

    Returns ``(resolved, problems)``. A problem is a dict with ``status`` in
    ``{"unresolved", "conflict"}`` carrying the candidates it saw, so the
    report can name what is missing instead of quietly shipping 88 of 94.
    """
    al = aliases or load_aliases()
    by_name: dict[str, list[tuple[int, str, str, str]]] = {}
    for b in bindings:
        try:
            cap = int(float(b["cap"]["value"]))
        except (KeyError, TypeError, ValueError):
            continue
        by_name.setdefault(b["name"]["value"], []).append(
            (
                cap,
                b["venue"]["value"].rsplit("/", 1)[-1],
                b.get("venueLabel", {}).get("value", ""),
                b["coord"]["value"],
            )
        )

    resolved: list[ClubVenue] = []
    problems: list[dict] = []
    for division, short in required_clubs(al):
        name = al[division][short]
        cands = sorted(set(by_name.get(name, [])), reverse=True)
        if not cands:
            problems.append(
                {"club": short, "division": division, "canonical_name": name,
                 "status": "unresolved", "candidates": []}
            )
            continue
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            problems.append(
                {"club": short, "division": division, "canonical_name": name,
                 "status": "conflict",
                 "candidates": [{"venue_qid": c[1], "venue_label": c[2], "capacity": c[0]}
                                for c in cands if c[0] == cands[0][0]]}
            )
            continue
        cap, qid, label, point = cands[0]
        lat, lon = parse_point(point)
        resolved.append(
            ClubVenue(short, division, name, qid, label, lat, lon, cap)
        )
    return resolved, problems


def fetch_bindings(names: list[str], batch: int = 32, delay_s: float = 1.0) -> list[dict]:
    """Query Wikidata for ``names``. Operator-run; no test calls this for real."""
    import time

    out: list[dict] = []
    for i in range(0, len(names), batch):
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": build_query(names[i : i + batch])}
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/sparql-results+json",
                # Wikidata asks for a descriptive agent; an anonymous one gets
                # throttled, which would look like missing data.
                "User-Agent": "finalwhistle-research/0.1 (club venue coordinates; CC0)",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 (fixed https host)
            out.extend(json.loads(resp.read())["results"]["bindings"])
        if i + batch < len(names):
            time.sleep(delay_s)
    return out


def load_snapshot(path: Path | None = None) -> dict[tuple[str, str], ClubVenue]:
    """The committed table, keyed by ``(division, short_label)``.

    Distances are computed from this, never from a live query, so a re-run
    scores the same coordinates even after Wikidata changes.
    """
    raw = json.loads((path or SNAPSHOT_PATH).read_text(encoding="utf-8"))
    return {
        (v["division"], v["club"]): ClubVenue(
            club=v["club"], division=v["division"],
            canonical_name=v["canonical_name"], venue_qid=v["venue_qid"],
            venue_label=v["venue_label"], lat=v["lat"], lon=v["lon"],
            capacity=v["capacity"],
        )
        for v in raw["venues"]
    }


def venue_for(
    snapshot: dict[tuple[str, str], ClubVenue], division: str, club: str
) -> ClubVenue:
    try:
        return snapshot[(division, club)]
    except KeyError as exc:
        raise UnresolvedVenue(
            f"no verified coordinate for {club!r} in {division}. It is reported "
            "in the coverage table; it is not given a fallback."
        ) from exc


def travel_km(
    snapshot: dict[tuple[str, str], ClubVenue],
    division: str,
    home_club: str,
    away_club: str,
) -> float:
    """Distance the AWAY side travels: its home venue to the home side's.

    Domestic league matches are played at the home club's ground, so the home
    side travels zero by construction and the signal is one-sided. This is
    **wrong for a relocated or neutral-venue fixture**, and football-data.co.uk
    publishes no venue column, so this source cannot detect one — declared in
    the D1 pre-registration rather than discovered later.
    """
    h = venue_for(snapshot, division, home_club)
    a = venue_for(snapshot, division, away_club)
    return haversine_km((a.lat, a.lon), (h.lat, h.lon))


def snapshot_payload(
    resolved: list[ClubVenue], problems: list[dict], retrieved_utc: str, query_sha256: str
) -> dict:
    return {
        "provider": PROVIDER,
        "retrieved_utc": retrieved_utc,
        "query_sha256": query_sha256,
        "n_required": len(required_clubs()),
        "n_resolved": len(resolved),
        "problems": problems,
        "venues": [
            {
                "club": v.club, "division": v.division,
                "canonical_name": v.canonical_name, "venue_qid": v.venue_qid,
                "venue_label": v.venue_label, "lat": v.lat, "lon": v.lon,
                "capacity": v.capacity,
            }
            for v in sorted(resolved, key=lambda x: (x.division, x.club))
        ],
    }


def format_coverage(payload: dict) -> str:
    lines = [
        "=== D1 club home-venue coordinate coverage ===",
        f"provider : {PROVIDER['provider']}  ({PROVIDER['cost']})",
        f"licence  : {PROVIDER['licence']}  — redistribution {PROVIDER['redistribution']}",
        f"retrieved: {payload['retrieved_utc']}",
        "",
    ]
    by_div: dict[str, int] = {}
    for v in payload["venues"]:
        by_div[v["division"]] = by_div.get(v["division"], 0) + 1
    required = {d: 0 for d in DIVISIONS}
    for d, _ in required_clubs():
        required[d] += 1
    for d in DIVISIONS:
        got, need = by_div.get(d, 0), required[d]
        lines.append(f"  {d:4s} resolved {got:>3d}/{need:<3d} ({got / need:.1%})")
    lines.append(
        f"  ALL  resolved {payload['n_resolved']:>3d}/{payload['n_required']:<3d}"
    )
    if payload["problems"]:
        lines.append("\nNOT RESOLVED — named, never guessed:")
        for p in payload["problems"]:
            lines.append(
                f"  {p['division']:4s} {p['club']:20s} {p['status']:11s} "
                f"({p['canonical_name']})"
            )
            for c in p.get("candidates", []):
                lines.append(
                    f"        tied candidate {c['venue_qid']} {c['venue_label']} "
                    f"cap={c['capacity']}"
                )
    return "\n".join(lines)
