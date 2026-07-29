"""D1 — effective-dated home-venue coordinates for the club leagues, from Wikidata.

There was no coordinate anywhere in this repository before D1. The first cut of
this module resolved **one current venue per club** and applied it backwards
across 2016-17…2024-25. That was wrong, and a review caught it: a club that
moved grounds inside the window had future venue state leaking into its earlier
fixtures. Concretely, in the first snapshot —

- **Brentford** resolved to Griffin Park, which Wikidata still lists as their
  only home venue. Every in-scope Brentford season (2021-22 onward) was
  actually played at Brentford Community Stadium.
- **Tottenham** resolved to Tottenham Hotspur Stadium, applied back through
  2016-17 (White Hart Lane) and 2017-18/2018-19 — two seasons at **Wembley**
  that Wikidata does not record at all.
- **Freiburg** resolved to Europa-Park-Stadion, applied back through five
  seasons at Dreisamstadion.

So this module now models venue as an **interval**, and refuses to answer when
the interval is not established.

What the source can actually support
------------------------------------
Measured across all 94 in-scope clubs, `P115` temporal qualifiers are sparse.
These are the module's OWN status labels, and the authoritative copy is
`status_counts` in `pipeline/data/club_venues.json` — this table is a summary
of that artifact, not a second independent count that could drift from it:

| status | clubs |
|---|---|
| `single_undated` | 73 |
| `dated` | 11 |
| `ambiguous_undated` | 8 |
| `excluded_declared` | 2 |

**Only 11 of 94 clubs can answer a date query at all**, and even those are
patchy — Tottenham's Wembley years are simply missing, Bayern's start value is
an "unknown value" node, and eleven boundaries carry only year precision.
Wikidata alone therefore **cannot** support a temporally-correct travel feature
over this window. That is a finding, not a problem to route around, and it is
why `venue_on` abstains as often as it does.

Abstention is the whole design
------------------------------
An unknown or ambiguous venue yields **missing**. Never the current venue,
never a city centroid, never a nearest neighbour, never a guess. A club-season
that cannot be established is excluded, named and counted.

The declared exclusion list can only ever **remove** fixtures, so being wrong
about an entry costs coverage and cannot manufacture a result.

Licence
-------
Wikidata is **CC0**, so both the raw response snapshot and the derived table
ship in this repository, and the derived table is provably rebuildable from the
raw one offline. That is the deliberate contrast with the football-data.co.uk
captures behind stop gate G1, which grant free download and no redistribution.

Pure and offline apart from :func:`fetch_raw_snapshot`, the one operator-run
network entry point, which no test calls for real.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"
ALIASES_PATH = _DATA / "club_venue_aliases.json"
RAW_SNAPSHOT_PATH = _DATA / "club_venues_raw.json"
SNAPSHOT_PATH = _DATA / "club_venues.json"

DIVISIONS = ("E0", "SP1", "D1")

#: Season codes in D1 scope. The 2025-26 confirmation season is absent and stays
#: absent: it is the consumed #202 holdout.
SEASONS_IN_SCOPE = ("1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425")

PROVIDER = {
    "provider": "Wikidata",
    "endpoint": "https://query.wikidata.org/sparql",
    "properties": {
        "P115": "home venue",
        "P625": "coordinate location",
        "P1083": "maximum capacity",
        "P580": "start time (qualifier — opens the interval)",
        "P582": "end time (qualifier — closes the interval)",
    },
    "cost": "free — no key, no account, no quota tier",
    "licence": "CC0 1.0 Universal (public domain dedication)",
    "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "licence_source": "https://www.wikidata.org/wiki/Wikidata:Licensing — "
    "Wikidata's structured data is released under CC0 1.0",
    "redistribution": "GRANTED — the raw response snapshot and the derived "
    "table are both committed, bytes included",
    "attribution": "Data from Wikidata, CC0 1.0",
    # WDQS is a shared public service. These are the constraints an operator
    # re-running the fetch has to respect, recorded so the receipt is complete.
    "wdqs_usage": {
        "policy": "https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual"
        "#Query_limits",
        "query_timeout_s": 60,
        "user_agent_required": True,
        "user_agent_sent": "finalwhistle-research/0.1 (club venue coordinates; CC0)",
        "client_throttle": "batched 24 labels per query, 1.0s sleep between "
        "batches, single-threaded — well inside the service's concurrency limits",
        "anonymous_rate_limit": "shared per-IP budget; a throttled response "
        "would look like missing data, which is why the raw snapshot records "
        "the binding count",
    },
}

_EARTH_KM = 6371.0088
_POINT = re.compile(r"^Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)$")
_ISO_DATE = re.compile(r"^([+-]?\d{4})-(\d{2})-(\d{2})T")

#: Mid-window probe used only to classify a history as `dated`: a club counts
#: as dated when at least one interval can return a definite in/out for a date
#: inside the D1 window. A boundary whose precision is missing or coarser than a
#: year answers "unknown" everywhere, so it never qualifies.
_PROBE_DATE = date_type(2020, 1, 1)

# ---------------------------------------------------------------- statuses

#: A club whose venue history is established well enough to answer a date.
STATUS_DATED = "dated"
#: Exactly one venue, no usable date. Cannot be verified — Brentford proves the
#: failure mode is real, not theoretical.
STATUS_SINGLE_UNDATED = "single_undated"
#: More than one venue and no usable date. Which applied when is unknowable.
STATUS_AMBIGUOUS_UNDATED = "ambiguous_undated"
#: No venue with coordinates at all.
STATUS_NO_VENUE = "no_venue"
#: On the declared exclusion list below.
STATUS_EXCLUDED = "excluded_declared"

#: Clubs excluded by operator declaration, with the reason. Entries here only
#: ever REMOVE fixtures from the travel feature, so an error costs coverage and
#: cannot manufacture a result.
DECLARED_EXCLUSIONS: dict[tuple[str, str], str] = {
    ("E0", "Brentford"): (
        "Wikidata lists Griffin Park as the only home venue and has no statement "
        "for Brentford Community Stadium. Every in-scope Brentford season "
        "(2021-22 onward) was played at the new ground, so the source's only "
        "venue is wrong for every in-scope fixture."
    ),
    ("E0", "Tottenham"): (
        "Wikidata records White Hart Lane (to 2017-05-14) and Tottenham Hotspur "
        "Stadium (from 2019-04-03) but nothing for the 2017-18 and 2018-19 "
        "seasons at Wembley. The interval set has a two-season hole inside the "
        "window, and Wembley is ~10 km from either Tottenham ground."
    ),
}

#: Seasons in which relocations and ground-shares are known to have occurred
#: across European leagues, and which this source cannot detect per match:
#: football-data.co.uk publishes **no venue column**. Excluded from the
#: verified travel tier rather than assumed normal.
RELOCATION_RISK_SEASONS: frozenset[str] = frozenset({"1920", "2021"})
RELOCATION_RISK_REASON = (
    "COVID-19 era. Fixtures in these seasons were played behind closed doors "
    "and, in some cases, at neutral or substitute grounds. football-data.co.uk "
    "carries no venue column, so a relocated match is undetectable per fixture "
    "and the season is excluded wholesale rather than assumed normal."
)


class UnresolvedVenue(KeyError):
    """No verified coordinate for this club at this date. Never substituted."""


#: Wikidata time precision codes. 11 = day, 10 = month, 9 = year; anything
#: coarser (decade, century) cannot bound a football season at all.
PRECISION_DAY = 11
PRECISION_MONTH = 10
PRECISION_YEAR = 9


def precision_window(d: date_type, precision: int | None) -> tuple[date_type, date_type] | None:
    """The range the true date could occupy, given Wikidata's stated precision.

    A year-precision qualifier serialises as ``YYYY-01-01``, which is
    indistinguishable from a real 1 January date unless the precision is
    fetched alongside it. Reading one as the other is how Atlético Madrid's
    Metropolitano interval came to open on 2017-01-01 — eight months before the
    ground existed — and put the Vicente Calderón farewell match in the wrong
    stadium.

    Returns ``None`` when the precision is absent or too coarse to bound a
    season, which makes the boundary unusable rather than approximate.
    """
    if precision is None or precision < PRECISION_YEAR:
        return None
    if precision >= PRECISION_DAY:
        return (d, d)
    if precision == PRECISION_MONTH:
        if d.month == 12:
            last = date_type(d.year, 12, 31)
        else:
            last = date_type(d.year, d.month + 1, 1) - timedelta(days=1)
        return (date_type(d.year, d.month, 1), last)
    return (date_type(d.year, 1, 1), date_type(d.year, 12, 31))


@dataclass(frozen=True)
class VenueInterval:
    """One venue, valid over a date interval whose bounds carry their precision.

    ``valid_from`` / ``valid_to`` are ``None`` when Wikidata gives no qualifier.
    An interval with no ``valid_from`` cannot answer a date query — see
    :func:`venue_on` — because "we do not know when this started" is not the
    same as "this always applied".
    """

    venue_qid: str
    venue_label: str
    lat: float
    lon: float
    capacity: int
    valid_from: date_type | None
    valid_to: date_type | None
    rank: str
    valid_from_precision: int | None = None
    valid_to_precision: int | None = None

    def status_on(self, on: date_type) -> str:
        """``"in"``, ``"out"`` or ``"unknown"`` for ``on``.

        Three-valued on purpose. A coarse boundary makes an interval genuinely
        indeterminate near it, and collapsing that to a boolean is what
        produced a confident wrong answer instead of an abstention.
        """
        if self.valid_from is None:
            return "unknown"
        start = precision_window(self.valid_from, self.valid_from_precision)
        if start is None:
            return "unknown"
        # The true start lies somewhere in [s0, s1]. It has certainly happened
        # once `on` reaches s1, and certainly not before s0. Between the two it
        # is genuinely unknown — and for a day-precision boundary s0 == s1, so
        # there is no unknown band at all and the exact date still answers.
        if on < start[0]:
            return "out"
        if on < start[1]:
            return "unknown"
        if self.valid_to is None:
            return "in"
        end = precision_window(self.valid_to, self.valid_to_precision)
        if end is None:
            return "unknown"
        # Symmetrically: certainly still open up to e0, certainly closed past
        # e1. `valid_to` is inclusive, which is why the open test uses <=.
        if on <= end[0]:
            return "in"
        if on > end[1]:
            return "out"
        return "unknown"

    def covers(self, on: date_type) -> bool:
        """Certainly in force. Indeterminate reads as **not** covered."""
        return self.status_on(on) == "in"


@dataclass(frozen=True)
class ClubVenueHistory:
    club: str
    division: str
    canonical_name: str
    intervals: tuple[VenueInterval, ...]
    status: str
    note: str = ""


def season_code(on: date_type) -> str:
    """European season code for a date: 1 July starts a new season.

    July is the boundary rather than August because pre-season and early cup
    fixtures can precede the league opener, and a boundary inside the playing
    calendar would split a season in two.
    """
    start = on.year if on.month >= 7 else on.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def parse_point(literal: str) -> tuple[float, float]:
    """Wikidata's ``Point(lon lat)`` WKT -> ``(lat, lon)``.

    Note the order swap: WKT is longitude-first and every consumer here wants
    latitude-first. Getting it backwards produces distances that are wrong but
    plausible, which is the worst kind of wrong.
    """
    m = _POINT.match(literal.strip())
    if not m:
        raise ValueError(f"unparseable Wikidata point literal: {literal!r}")
    lon, lat = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"point out of range: {literal!r}")
    return lat, lon


def parse_wikidata_date(literal: str | None) -> date_type | None:
    """A ``P580``/``P582`` literal, or ``None`` when it is unusable.

    Wikidata serialises "unknown value" as a blank-node URI — Bayern Munich's
    Grünwalder start time is one — and those must read as *absent*, not as a
    date. Returning None rather than raising is deliberate: an unusable
    qualifier degrades that interval to unanswerable, which the caller already
    handles, instead of failing the whole snapshot.
    """
    if not literal or not literal.startswith(("1", "2", "+", "-")):
        return None
    m = _ISO_DATE.match(literal)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 1 or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    try:
        return date_type(year, month, day)
    except ValueError:
        return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two ``(lat, lon)`` pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def load_aliases(path: Path | None = None) -> dict[str, dict[str, str]]:
    raw = json.loads((path or ALIASES_PATH).read_text(encoding="utf-8"))
    return {d: raw[d] for d in DIVISIONS}


def required_clubs(aliases: dict[str, dict[str, str]] | None = None) -> list[tuple[str, str]]:
    al = aliases or load_aliases()
    return [(d, c) for d in DIVISIONS for c in sorted(al[d])]


# ------------------------------------------------------------------ query

#: Projects the qualifier VALUE NODES (``pqv:``) rather than the plain
#: qualifier, because ``wikibase:timePrecision`` only exists on the value node.
#: Without it a year-precision qualifier is indistinguishable from a real
#: 1 January date — the defect that put Atlético Madrid in a stadium four
#: months before it opened. ``?club`` is projected too, so the receipt carries
#: the club QID and not only the venue's.
SPARQL_TEMPLATE = """SELECT ?name ?club ?venue ?venueLabel ?coord ?cap \
?start ?startPrecision ?end ?endPrecision ?rank WHERE {
  VALUES ?name { %s }
  ?club rdfs:label|skos:altLabel ?name .
  ?club p:P115 ?statement .
  ?statement ps:P115 ?venue .
  ?statement wikibase:rank ?rank .
  OPTIONAL {
    ?statement pqv:P580 ?startNode .
    ?startNode wikibase:timeValue ?start ;
               wikibase:timePrecision ?startPrecision .
  }
  OPTIONAL {
    ?statement pqv:P582 ?endNode .
    ?endNode wikibase:timeValue ?end ;
             wikibase:timePrecision ?endPrecision .
  }
  ?venue wdt:P625 ?coord .
  ?venue wdt:P1083 ?cap .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def build_query(names: list[str]) -> str:
    values = " ".join('"%s"@en' % n.replace('"', '\\"') for n in names)
    return SPARQL_TEMPLATE % values


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- resolution


def resolve_histories(
    bindings: list[dict], aliases: dict[str, dict[str, str]] | None = None
) -> list[ClubVenueHistory]:
    """Turn raw bindings into one venue history per required club. Pure.

    Deprecated statements are dropped. Everything else is kept as an interval,
    including undated ones — the *status* records whether those intervals can
    answer a date, rather than the resolver silently discarding them.
    """
    al = aliases or load_aliases()
    by_name: dict[str, set[tuple]] = {}
    for b in bindings:
        if b.get("rank", {}).get("value", "").endswith("DeprecatedRank"):
            continue
        try:
            cap = int(float(b["cap"]["value"]))
            lat, lon = parse_point(b["coord"]["value"])
        except (KeyError, TypeError, ValueError):
            continue
        by_name.setdefault(b["name"]["value"], set()).add(
            (
                _qid(b["venue"]["value"]),
                b.get("venueLabel", {}).get("value", ""),
                lat,
                lon,
                cap,
                (b.get("start") or {}).get("value"),
                (b.get("end") or {}).get("value"),
                _qid(b.get("rank", {}).get("value", "")),
                _int_or_none((b.get("startPrecision") or {}).get("value")),
                _int_or_none((b.get("endPrecision") or {}).get("value")),
            )
        )

    out: list[ClubVenueHistory] = []
    for division, short in required_clubs(al):
        name = al[division][short]
        # Undated statements carry None for start/end, which cannot be ordered
        # against a string — sort on a total key so the output stays canonical.
        rows = sorted(
            by_name.get(name, set()),
            key=lambda r: tuple("" if v is None else str(v) for v in r),
        )
        intervals = tuple(
            VenueInterval(
                venue_qid=r[0], venue_label=r[1], lat=r[2], lon=r[3], capacity=r[4],
                valid_from=parse_wikidata_date(r[5]),
                valid_to=parse_wikidata_date(r[6]),
                rank=r[7],
                valid_from_precision=r[8],
                valid_to_precision=r[9],
            )
            for r in rows
        )
        declared = DECLARED_EXCLUSIONS.get((division, short))
        if declared:
            status, note = STATUS_EXCLUDED, declared
        elif not intervals:
            status, note = STATUS_NO_VENUE, "no P115 venue with coordinates and capacity"
        elif any(i.status_on(_PROBE_DATE) != "unknown" for i in intervals):
            status, note = STATUS_DATED, ""
        elif len({i.venue_qid for i in intervals}) == 1:
            status, note = (
                STATUS_SINGLE_UNDATED,
                "one venue, no P580/P582 qualifier — cannot be verified for any "
                "date. Brentford shows this failure mode is real.",
            )
        else:
            status, note = (
                STATUS_AMBIGUOUS_UNDATED,
                f"{len({i.venue_qid for i in intervals})} venues, none dated — "
                "which applied when is unknowable from this source",
            )
        out.append(ClubVenueHistory(short, division, name, intervals, status, note))
    return out


def venue_on(history: ClubVenueHistory, on: date_type) -> VenueInterval | None:
    """The venue in force on ``on``, or ``None``.

    Abstains — returns ``None`` — whenever the answer is not established:

    - the club's status is anything but ``dated``;
    - no interval covers the date (Tottenham's missing Wembley years);
    - more than one interval covers it (overlapping statements).

    There is deliberately no fallback branch. Adding one would reintroduce the
    exact defect this module was rewritten to remove.
    """
    if history.status != STATUS_DATED:
        return None
    statuses = [i.status_on(on) for i in history.intervals]
    # Any indeterminate interval poisons the whole answer: if one boundary
    # might have moved past this date, "exactly one interval covers it" is not
    # something we know.
    if "unknown" in statuses:
        return None
    covering = [i for i, s in zip(history.intervals, statuses) if s == "in"]
    if len(covering) != 1:
        return None
    return covering[0]


def is_relocation_risk(on: date_type) -> bool:
    return season_code(on) in RELOCATION_RISK_SEASONS


def travel_km_on(
    histories: dict[tuple[str, str], ClubVenueHistory],
    division: str,
    home_club: str,
    away_club: str,
    on: date_type,
) -> float | None:
    """Km the away side travels for a fixture on ``on``, or ``None`` to abstain.

    Abstains when either club's venue is unestablished for that date, or when
    the fixture falls in a relocation-risk season this source cannot audit.
    """
    if is_relocation_risk(on):
        return None
    h = histories.get((division, home_club))
    a = histories.get((division, away_club))
    if h is None or a is None:
        return None
    hv, av = venue_on(h, on), venue_on(a, on)
    if hv is None or av is None:
        return None
    return haversine_km((av.lat, av.lon), (hv.lat, hv.lon))


def travel_exclusion_reason(
    histories: dict[tuple[str, str], ClubVenueHistory],
    division: str,
    home_club: str,
    away_club: str,
    on: date_type,
) -> str | None:
    """Why a fixture has no travel value, or ``None`` when it has one.

    Every excluded fixture has to be attributable to a named reason, or the
    coverage report is just a smaller number with no explanation.
    """
    # Venue status is tested BEFORE the season rule. Both can apply to the same
    # fixture, and reporting the season first over-attributed thousands of
    # fixtures to COVID when the binding constraint was actually an unusable
    # venue history — which is the one an operator could fix.
    for club in (home_club, away_club):
        h = histories.get((division, club))
        if h is None:
            return "club_absent_from_snapshot"
        if h.status != STATUS_DATED:
            return h.status
        if venue_on(h, on) is None:
            statuses = [i.status_on(on) for i in h.intervals]
            if "unknown" in statuses:
                return "boundary_precision_unknown"
            return "interval_gap" if "in" not in statuses else "overlapping_intervals"
    if is_relocation_risk(on):
        return "relocation_risk_season"
    return None


# ------------------------------------------------------------- snapshots


def raw_snapshot_payload(
    bindings: list[dict], names: list[str], retrieved_utc: str
) -> dict:
    """The immutable source receipt: the response, not a summary of it.

    The first cut committed derived rows plus a query hash and called that a
    reproducibility receipt. It was not one — nothing in it could show what the
    provider actually returned, so a resolver change and a provider change were
    indistinguishable after the fact. This holds the bindings themselves.
    """
    query = build_query(sorted(names))
    payload = {
        "provider": PROVIDER,
        "retrieved_utc": retrieved_utc,
        "query": query,
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "requested_labels": sorted(names),
        "n_bindings": len(bindings),
        "bindings_sha256": _bindings_digest(bindings),
        "bindings": bindings,
    }
    # A digest over everything EXCEPT itself, so tampering with the licence
    # text, the retrieval time or the requested labels is caught too. The
    # bindings digest alone left the whole provenance envelope unprotected —
    # the query could be swapped for unrelated SPARQL and nothing noticed.
    payload["envelope_sha256"] = _envelope_digest(payload)
    return payload


def _bindings_digest(bindings: list[dict]) -> str:
    """Order-independent digest over the bindings.

    The SPARQL has no ORDER BY, so the service may return rows in any order;
    an order-sensitive digest would flag a re-fetch as tampering. Each binding
    is canonicalised, then the canonical forms are sorted.
    """
    rows = sorted(
        json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for b in bindings
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _envelope_digest(payload: dict) -> str:
    envelope = {k: v for k, v in payload.items() if k not in ("bindings", "envelope_sha256")}
    return hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def load_raw_snapshot(path: Path | None = None) -> dict:
    """Load the receipt, verifying every claim it makes about itself.

    Three independent checks, because the first cut verified only the bindings:
    the query really is the one whose digest is recorded, the provenance
    envelope has not been edited, and the bindings match.
    """
    raw = json.loads((path or RAW_SNAPSHOT_PATH).read_text(encoding="utf-8"))

    actual_query = hashlib.sha256(raw["query"].encode()).hexdigest()
    if actual_query != raw["query_sha256"]:
        raise ValueError(
            f"raw snapshot query digest mismatch: recorded {raw['query_sha256']}, "
            f"computed {actual_query}. The recorded query is not the one that ran."
        )
    if "envelope_sha256" in raw:
        actual_env = _envelope_digest(raw)
        if actual_env != raw["envelope_sha256"]:
            raise ValueError(
                f"raw snapshot envelope digest mismatch: recorded "
                f"{raw['envelope_sha256']}, computed {actual_env}. Provenance "
                "metadata has been edited."
            )
    actual = _bindings_digest(raw["bindings"])
    if actual != raw["bindings_sha256"]:
        raise ValueError(
            f"raw snapshot digest mismatch: recorded {raw['bindings_sha256']}, "
            f"computed {actual}. The receipt has been edited."
        )
    return raw


def derive_snapshot(raw: dict, aliases: dict[str, dict[str, str]] | None = None) -> dict:
    """Derive the venue table from a raw snapshot. Deterministic and offline.

    Carries no timestamp of its own — the only time in the derived table is the
    raw snapshot's ``retrieved_utc``, so re-deriving is byte-for-byte stable.
    """
    histories = resolve_histories(raw["bindings"], aliases)
    counts: dict[str, int] = {}
    for h in histories:
        counts[h.status] = counts.get(h.status, 0) + 1
    return {
        "derived_from": {
            "raw_snapshot": RAW_SNAPSHOT_PATH.name,
            "retrieved_utc": raw["retrieved_utc"],
            "bindings_sha256": raw["bindings_sha256"],
            "query_sha256": raw["query_sha256"],
        },
        # The RECEIPT's provider block, not this module's constant: the derived
        # table has to describe the fetch it came from, not the code that reads it.
        "provider": raw.get("provider", PROVIDER),
        "seasons_in_scope": list(SEASONS_IN_SCOPE),
        "relocation_risk_seasons": sorted(RELOCATION_RISK_SEASONS),
        "relocation_risk_reason": RELOCATION_RISK_REASON,
        "status_counts": dict(sorted(counts.items())),
        "n_required": len(required_clubs(aliases)),
        "clubs": [
            {
                "club": h.club,
                "division": h.division,
                "canonical_name": h.canonical_name,
                "status": h.status,
                "note": h.note,
                "intervals": [
                    {
                        "venue_qid": i.venue_qid,
                        "venue_label": i.venue_label,
                        "lat": i.lat,
                        "lon": i.lon,
                        "capacity": i.capacity,
                        "valid_from": i.valid_from.isoformat() if i.valid_from else None,
                        "valid_from_precision": i.valid_from_precision,
                        "valid_to": i.valid_to.isoformat() if i.valid_to else None,
                        "valid_to_precision": i.valid_to_precision,
                        "rank": i.rank,
                    }
                    for i in h.intervals
                ],
            }
            for h in sorted(histories, key=lambda x: (x.division, x.club))
        ],
    }


def serialize_snapshot(payload: dict) -> str:
    """One canonical serialization, so "byte-for-byte" means something."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def load_histories(path: Path | None = None) -> dict[tuple[str, str], ClubVenueHistory]:
    raw = json.loads((path or SNAPSHOT_PATH).read_text(encoding="utf-8"))
    out: dict[tuple[str, str], ClubVenueHistory] = {}
    for c in raw["clubs"]:
        intervals = tuple(
            VenueInterval(
                venue_qid=i["venue_qid"], venue_label=i["venue_label"],
                lat=i["lat"], lon=i["lon"], capacity=i["capacity"],
                valid_from=date_type.fromisoformat(i["valid_from"]) if i["valid_from"] else None,
                valid_to=date_type.fromisoformat(i["valid_to"]) if i["valid_to"] else None,
                rank=i["rank"],
                valid_from_precision=i.get("valid_from_precision"),
                valid_to_precision=i.get("valid_to_precision"),
            )
            for i in c["intervals"]
        )
        out[(c["division"], c["club"])] = ClubVenueHistory(
            c["club"], c["division"], c["canonical_name"], intervals, c["status"], c["note"]
        )
    return out


def fetch_raw_snapshot(names: list[str], batch: int = 24, delay_s: float = 1.0) -> list[dict]:
    """Query Wikidata. Operator-run; no test calls this for real.

    Batched and single-threaded per the WDQS usage notes in :data:`PROVIDER`.
    """
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
                "User-Agent": PROVIDER["wdqs_usage"]["user_agent_sent"],
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 (fixed https host)
            out.extend(json.loads(resp.read())["results"]["bindings"])
        if i + batch < len(names):
            time.sleep(delay_s)
    return out


def format_coverage(payload: dict) -> str:
    lines = [
        "=== D1 club home-venue temporal coverage ===",
        f"provider : {PROVIDER['provider']}  ({PROVIDER['cost']})",
        f"licence  : {PROVIDER['licence']} — redistribution GRANTED",
        f"derived  : {payload['derived_from']['raw_snapshot']} "
        f"@ {payload['derived_from']['retrieved_utc']}",
        "",
        "club venue-history status (only 'dated' can answer a date query):",
    ]
    for status, n in payload["status_counts"].items():
        lines.append(f"  {status:22s} {n:>3d}")
    lines.append(f"  {'TOTAL':22s} {payload['n_required']:>3d}")
    excluded = [c for c in payload["clubs"] if c["status"] != STATUS_DATED]
    if excluded:
        lines.append("\nclubs that cannot answer a date query — named, never guessed:")
        for c in excluded:
            lines.append(f"  {c['division']:4s} {c['club']:20s} {c['status']}")
    lines.append(
        f"\nrelocation-risk seasons excluded wholesale: "
        f"{sorted(RELOCATION_RISK_SEASONS)}"
    )
    return "\n".join(lines)


def refresh_snapshots(retrieved_utc: str) -> dict:
    """Operator entry point: fetch, write the receipt, re-derive the table.

    Exists because the evidence card's reproduction receipt used to name three
    functions that a later refactor had renamed away, so the phase's only
    documented rebuild command could not run at all. A receipt that is executed
    by `python -m` cannot drift from the code the way a prose snippet can.
    """
    aliases = load_aliases()
    names = [aliases[d][c] for d, c in required_clubs(aliases)]
    bindings = fetch_raw_snapshot(names)
    raw = raw_snapshot_payload(bindings, names, retrieved_utc)
    RAW_SNAPSHOT_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    derived = derive_snapshot(load_raw_snapshot(), aliases)
    SNAPSHOT_PATH.write_text(serialize_snapshot(derived), encoding="utf-8")
    return derived


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="re-fetch from Wikidata and rewrite both snapshots (network; free, CC0)",
    )
    ap.add_argument(
        "--verify",
        action="store_true",
        help="offline: re-derive from the committed receipt and assert it is "
        "byte-for-byte identical to the committed table",
    )
    args = ap.parse_args(argv)

    if args.refresh:
        derived = refresh_snapshots(
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        print(format_coverage(derived))
        return 0

    raw = load_raw_snapshot()
    rebuilt = serialize_snapshot(derive_snapshot(raw, load_aliases()))
    on_disk = SNAPSHOT_PATH.read_text(encoding="utf-8")
    print(format_coverage(json.loads(on_disk)))
    if args.verify:
        if rebuilt != on_disk:
            print("\nREBUILD MISMATCH: the derived table is not what the "
                  "receipt produces.", file=__import__("sys").stderr)
            return 1
        print("\nrebuild from receipt: byte-for-byte identical")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
