"""D1 venue-coordinate resolution: the rule, its refusals, and the snapshot.

Hermetic — the SPARQL bindings are fixtures, and `fetch_bindings` is never
called for real.
"""
from __future__ import annotations

import json

import pytest

from pipeline.ingest.venue_coordinates import (
    ALIASES_PATH,
    DIVISIONS,
    PROVIDER,
    SNAPSHOT_PATH,
    ClubVenue,
    UnresolvedVenue,
    build_query,
    haversine_km,
    load_aliases,
    load_snapshot,
    parse_point,
    required_clubs,
    resolve,
    travel_km,
)


def _binding(name, qid, label, lon, lat, cap):
    return {
        "name": {"value": name},
        "venue": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "venueLabel": {"value": label},
        "coord": {"value": f"Point({lon} {lat})"},
        "cap": {"value": str(cap)},
    }


_ALIASES = {"E0": {"Alpha": "Alpha F.C."}, "SP1": {}, "D1": {}}


# ------------------------------------------------------------ geometry


def test_point_literal_is_longitude_first_and_we_return_latitude_first():
    # Getting this backwards produces distances that are wrong but plausible.
    assert parse_point("Point(-2.200277777 53.483055555)") == (53.483055555, -2.200277777)


@pytest.mark.parametrize("bad", ["", "POINT(1 2)", "Point(1)", "Point(200 100)"])
def test_malformed_or_out_of_range_points_raise(bad):
    with pytest.raises(ValueError):
        parse_point(bad)


def test_haversine_matches_a_known_separation():
    # One degree of latitude is ~111.19 km anywhere on the globe.
    assert haversine_km((51.0, 0.0), (52.0, 0.0)) == pytest.approx(111.19, abs=0.5)
    assert haversine_km((51.0, 0.0), (51.0, 0.0)) == 0.0


def test_haversine_is_symmetric():
    a, b = (53.4308, -2.9608), (51.5550, -0.1083)
    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


# ------------------------------------------------------- the resolution rule


def test_capacity_separates_a_stadium_from_a_training_ground():
    """Wikidata lists both with no end date. Capacity is what tells them apart.

    Athletic Bilbao really does carry Lezama (3,250) alongside San Mamés
    (53,289); RB Leipzig carries Cottaweg alongside the Red Bull Arena.
    """
    bindings = [
        _binding("Alpha F.C.", "Q_TRAIN", "Alpha Training Ground", 0.0, 51.0, 3250),
        _binding("Alpha F.C.", "Q_STAD", "Alpha Stadium", 0.5, 51.5, 53289),
    ]
    resolved, problems = resolve(bindings, _ALIASES)
    assert problems == []
    assert [v.venue_qid for v in resolved] == ["Q_STAD"]
    assert resolved[0].capacity == 53289


def test_several_club_entities_sharing_a_label_still_resolve_if_they_agree():
    # FC Barcelona is modelled as a men's team, a multisport club and a
    # non-profit. All three point at Camp Nou, so the venue is unambiguous
    # even though the club entity is not.
    b = _binding("Alpha F.C.", "Q_STAD", "Alpha Stadium", 0.5, 51.5, 99000)
    resolved, problems = resolve([b, dict(b), dict(b)], _ALIASES)
    assert problems == [] and len(resolved) == 1


def test_a_tied_maximum_is_a_conflict_and_is_never_resolved_by_picking_one():
    bindings = [
        _binding("Alpha F.C.", "Q_A", "Ground A", 0.0, 51.0, 40000),
        _binding("Alpha F.C.", "Q_B", "Ground B", 1.0, 52.0, 40000),
    ]
    resolved, problems = resolve(bindings, _ALIASES)
    assert resolved == []
    assert problems[0]["status"] == "conflict"
    assert {c["venue_qid"] for c in problems[0]["candidates"]} == {"Q_A", "Q_B"}


def test_no_candidate_is_reported_unresolved_with_the_name_it_needed():
    resolved, problems = resolve([], _ALIASES)
    assert resolved == []
    assert problems[0]["status"] == "unresolved"
    # The report has to name the alias, or an operator cannot act on it.
    assert problems[0]["canonical_name"] == "Alpha F.C."


def test_a_venue_without_a_capacity_cannot_win_by_default():
    # Capacity is the discriminator; a venue that has none is not a candidate.
    b = _binding("Alpha F.C.", "Q_X", "No Capacity Ground", 0.0, 51.0, 0)
    del b["cap"]
    resolved, problems = resolve([b], _ALIASES)
    assert resolved == [] and problems[0]["status"] == "unresolved"


def test_query_pins_the_filters_the_rule_depends_on():
    q = build_query(["Alpha F.C."])
    assert "pq:P582" in q  # former venues excluded
    assert "wikibase:DeprecatedRank" in q
    assert "wdt:P625" in q and "wdt:P1083" in q


# ------------------------------------------------ the committed snapshot


def test_every_required_club_is_in_the_committed_snapshot():
    snap = load_snapshot()
    missing = [k for k in required_clubs() if k not in snap]
    assert missing == [], f"clubs with no verified coordinate: {missing}"


def test_snapshot_rows_all_carry_a_wikidata_qid():
    """A coordinate with no QID cannot be checked, so it does not ship."""
    for v in load_snapshot().values():
        assert v.venue_qid.startswith("Q") and v.venue_qid[1:].isdigit(), v


def test_snapshot_records_its_own_provenance():
    raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert raw["provider"]["provider"] == "Wikidata"
    # The licence is the reason these bytes may be committed at all, unlike
    # the football-data captures behind stop gate G1.
    assert "CC0" in raw["provider"]["licence"]
    assert raw["provider"]["redistribution"].startswith("GRANTED")
    assert raw["retrieved_utc"] and raw["query_sha256"]
    assert raw["n_resolved"] == raw["n_required"] == len(required_clubs())


def test_alias_table_contains_no_coordinates():
    """The naming table is naming only; every coordinate comes from Wikidata.

    Structural rather than a substring scan — "Barcelona" contains "lon", and a
    guard that trips on that would be noise. What matters is that no value in
    the file is a number.
    """
    raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    for division in DIVISIONS:
        for short, canonical in raw[division].items():
            assert isinstance(short, str) and isinstance(canonical, str)
    numbers = [
        v
        for division in DIVISIONS
        for v in raw[division].values()
        if isinstance(v, (int, float))
    ]
    assert numbers == []


def test_alias_table_covers_every_division_and_nothing_else():
    al = load_aliases()
    assert set(al) == set(DIVISIONS)
    assert sum(len(v) for v in al.values()) == 94


# --------------------------------------------------------------- travel


def test_travel_km_is_the_away_sides_journey():
    snap = {
        ("E0", "H"): ClubVenue("H", "E0", "H F.C.", "Q1", "H Park", 51.0, 0.0, 1),
        ("E0", "A"): ClubVenue("A", "E0", "A F.C.", "Q2", "A Park", 52.0, 0.0, 1),
    }
    assert travel_km(snap, "E0", "H", "A") == pytest.approx(111.19, abs=0.5)


def test_an_unresolved_club_raises_rather_than_returning_a_fallback():
    with pytest.raises(UnresolvedVenue, match="not given a fallback"):
        travel_km({}, "E0", "H", "A")


def test_real_distances_are_sane():
    """Spot-checks against geography, so a coordinate swap cannot pass quietly."""
    snap = load_snapshot()
    assert travel_km(snap, "E0", "Man City", "Man United") < 15  # Manchester derby
    assert travel_km(snap, "E0", "Arsenal", "Tottenham") < 15  # North London derby
    assert travel_km(snap, "D1", "Dortmund", "Schalke 04") < 40  # Revierderby
    # La Liga reaches the Canary Islands, which is where the range comes from.
    assert travel_km(snap, "SP1", "Real Madrid", "Las Palmas") > 1500


def test_provider_record_states_the_licence_that_permits_committing_bytes():
    assert PROVIDER["licence"].startswith("CC0")
    assert PROVIDER["redistribution"].startswith("GRANTED")
