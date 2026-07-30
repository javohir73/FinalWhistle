"""D1 venue history: temporal correctness, abstention, and the source receipt.

Hermetic — bindings are fixtures and `fetch_raw_snapshot` is never called for
real. These tests exist because the first cut of this module resolved ONE
current venue per club and applied it backwards across nine seasons, which let
a ground a club moved into in 2019 determine its 2016 distances.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from pipeline.ingest.venue_coordinates import (
    ALIASES_PATH,
    DECLARED_EXCLUSIONS,
    DIVISIONS,
    PROVIDER,
    RAW_SNAPSHOT_PATH,
    RELOCATION_RISK_SEASONS,
    SEASONS_IN_SCOPE,
    SNAPSHOT_PATH,
    STATUS_AMBIGUOUS_UNDATED,
    STATUS_DATED,
    STATUS_EXCLUDED,
    STATUS_SINGLE_UNDATED,
    ClubVenueHistory,
    VenueInterval,
    build_query,
    derive_snapshot,
    haversine_km,
    load_aliases,
    load_histories,
    load_raw_snapshot,
    parse_point,
    parse_wikidata_date,
    required_clubs,
    resolve_histories,
    season_code,
    serialize_snapshot,
    travel_exclusion_reason,
    travel_km_on,
    venue_on,
)


def _binding(name, qid, label, lon, lat, cap, start=None, end=None, rank="NormalRank",
             start_prec=11, end_prec=11):
    b = {
        "name": {"value": name},
        "venue": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "venueLabel": {"value": label},
        "coord": {"value": f"Point({lon} {lat})"},
        "cap": {"value": str(cap)},
        "rank": {"value": f"http://wikiba.se/ontology#{rank}"},
    }
    if start:
        b["start"] = {"value": start}
        b["startPrecision"] = {"value": str(start_prec)}
    if end:
        b["end"] = {"value": end}
        b["endPrecision"] = {"value": str(end_prec)}
    return b


_AL = {"E0": {"Mover": "Mover F.C."}, "SP1": {}, "D1": {}}


def _history(*intervals, status=STATUS_DATED):
    return ClubVenueHistory("Mover", "E0", "Mover F.C.", tuple(intervals), status)


def _iv(qid, lat, lon, frm, to=None, prec=11, to_prec=11):
    """A day-precision interval unless told otherwise.

    Precision is not optional in the model: a boundary whose precision is
    absent or coarser than a year cannot bound a season, so it answers
    "unknown" everywhere. `prec=9` builds the year-precision case that put
    Atlético Madrid in a stadium four months before it opened.
    """
    return VenueInterval(
        qid, qid, lat, lon, 30000,
        date.fromisoformat(frm) if frm else None,
        date.fromisoformat(to) if to else None,
        "NormalRank",
        valid_from_precision=prec if frm else None,
        valid_to_precision=to_prec if to else None,
    )


# ------------------------------------------------------------- primitives


def test_point_literal_is_longitude_first_and_we_return_latitude_first():
    assert parse_point("Point(-2.200277777 53.483055555)") == (53.483055555, -2.200277777)


@pytest.mark.parametrize("bad", ["", "POINT(1 2)", "Point(1)", "Point(200 100)"])
def test_malformed_or_out_of_range_points_raise(bad):
    with pytest.raises(ValueError):
        parse_point(bad)


def test_haversine_matches_a_known_separation_and_is_symmetric():
    assert haversine_km((51.0, 0.0), (52.0, 0.0)) == pytest.approx(111.19, abs=0.5)
    a, b = (53.4308, -2.9608), (51.5550, -0.1083)
    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


def test_unknown_value_date_literals_read_as_absent_not_as_a_date():
    """Wikidata serialises "unknown value" as a blank-node URI.

    Bayern Munich's Grünwalder start time is exactly that. Reading it as a date
    would silently open an interval at an arbitrary point.
    """
    genid = "http://www.wikidata.org/.well-known/genid/8c843f603c5d8acf1320e64a49fbee62"
    assert parse_wikidata_date(genid) is None
    assert parse_wikidata_date(None) is None
    assert parse_wikidata_date("") is None
    assert parse_wikidata_date("2019-04-03T00:00:00Z") == date(2019, 4, 3)


@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2023, 8, 12), "2324"),  # August is the new season
        (date(2024, 5, 19), "2324"),  # May still belongs to it
        (date(2023, 6, 30), "2223"),  # June is the tail of the old one
        (date(2023, 7, 1), "2324"),  # 1 July is the boundary
    ],
)
def test_season_code_boundary_is_1_july(d, expected):
    assert season_code(d) == expected


# ------------------------------------------ temporal correctness (the point)


def test_a_venue_before_its_start_date_does_not_apply():
    """The defect in one line: a 2019 ground must not answer a 2016 fixture."""
    h = _history(_iv("Q_NEW", 51.6, -0.07, "2019-04-03"))
    assert venue_on(h, date(2016, 9, 10)) is None
    assert venue_on(h, date(2019, 4, 3)) is not None
    assert venue_on(h, date(2019, 4, 2)) is None


def test_a_closed_interval_stops_applying_after_its_end_date():
    h = _history(_iv("Q_OLD", 51.6, -0.07, "1899-09-04", "2017-05-14"))
    assert venue_on(h, date(2017, 5, 14)) is not None
    assert venue_on(h, date(2017, 5, 15)) is None


def test_tottenham_shape_the_wembley_gap_abstains_rather_than_picking_a_side():
    """Wikidata has White Hart Lane to 2017-05-14 and the new stadium from
    2019-04-03, and nothing for the two Wembley seasons in between.

    Either neighbouring ground would be a guess, and Wembley is ~10 km away.
    """
    h = _history(
        _iv("Q_WHL", 51.6033, -0.0658, "1899-09-04", "2017-05-14"),
        _iv("Q_THS", 51.6043, -0.0664, "2019-04-03"),
    )
    assert venue_on(h, date(2016, 12, 3)) is not None  # White Hart Lane era
    assert venue_on(h, date(2020, 1, 11)) is not None  # new stadium era
    for gap_day in (date(2017, 8, 20), date(2018, 12, 15), date(2019, 4, 2)):
        assert venue_on(h, gap_day) is None, gap_day


def test_overlapping_intervals_abstain_rather_than_choosing():
    h = _history(
        _iv("Q_A", 51.0, 0.0, "2015-01-01", "2020-01-01"),
        _iv("Q_B", 52.0, 0.0, "2018-01-01"),
    )
    assert venue_on(h, date(2019, 6, 1)) is None  # both cover it
    assert venue_on(h, date(2016, 6, 1)) is not None  # only A covers it


def test_an_undated_interval_can_never_answer_a_date():
    # "We do not know when this started" is not "this always applied".
    h = _history(_iv("Q_X", 51.0, 0.0, None))
    assert venue_on(h, date(2018, 1, 1)) is None


@pytest.mark.parametrize(
    "status", [STATUS_SINGLE_UNDATED, STATUS_AMBIGUOUS_UNDATED, STATUS_EXCLUDED]
)
def test_only_dated_histories_answer_at_all(status):
    h = _history(_iv("Q_X", 51.0, 0.0, "2000-01-01"), status=status)
    assert venue_on(h, date(2018, 1, 1)) is None


# -------------------------------------------------------- status assignment


def test_freiburg_shape_multiple_undated_venues_is_ambiguous():
    bindings = [
        _binding("Mover F.C.", "Q_OLD", "Dreisamstadion", 7.89, 47.99, 24000),
        _binding("Mover F.C.", "Q_NEW", "Europa-Park-Stadion", 7.83, 48.02, 34700),
    ]
    (h,) = resolve_histories(bindings, _AL)
    assert h.status == STATUS_AMBIGUOUS_UNDATED
    assert venue_on(h, date(2018, 3, 1)) is None


def test_brentford_shape_one_undated_venue_is_unverified_not_assumed():
    """Wikidata lists only Griffin Park; the club moved before its first
    in-scope season. A single undated venue is not evidence of stability."""
    bindings = [_binding("Mover F.C.", "Q_OLD", "Griffin Park", -0.30, 51.48, 14863)]
    (h,) = resolve_histories(bindings, _AL)
    assert h.status == STATUS_SINGLE_UNDATED
    assert venue_on(h, date(2022, 1, 1)) is None


def test_deprecated_statements_are_dropped():
    bindings = [
        _binding("Mover F.C.", "Q_BAD", "Wrong", 0.0, 51.0, 90000, rank="DeprecatedRank"),
        _binding("Mover F.C.", "Q_OK", "Right", 0.0, 52.0, 30000, start="2015-01-01T00:00:00Z"),
    ]
    (h,) = resolve_histories(bindings, _AL)
    assert [i.venue_qid for i in h.intervals] == ["Q_OK"]


def test_declared_exclusions_are_honoured_and_carry_their_reason():
    assert ("E0", "Brentford") in DECLARED_EXCLUSIONS
    assert ("E0", "Tottenham") in DECLARED_EXCLUSIONS
    hist = load_histories()
    for key in DECLARED_EXCLUSIONS:
        assert hist[key].status == STATUS_EXCLUDED
        assert hist[key].note, key
        assert venue_on(hist[key], date(2022, 1, 1)) is None


# ------------------------------------------------------- travel abstention


def _pair(status_a=STATUS_DATED, status_b=STATUS_DATED):
    return {
        ("E0", "H"): ClubVenueHistory(
            "H", "E0", "H F.C.", (_iv("Q1", 51.0, 0.0, "2000-01-01"),), status_a
        ),
        ("E0", "A"): ClubVenueHistory(
            "A", "E0", "A F.C.", (_iv("Q2", 52.0, 0.0, "2000-01-01"),), status_b
        ),
    }


def test_travel_is_measured_when_both_sides_are_established():
    d = date(2023, 8, 12)  # 2324 — not a relocation-risk season
    assert travel_km_on(_pair(), "E0", "H", "A", d) == pytest.approx(111.19, abs=0.5)
    assert travel_exclusion_reason(_pair(), "E0", "H", "A", d) is None


def test_one_unestablished_side_is_enough_to_abstain():
    d = date(2023, 8, 12)
    p = _pair(status_b=STATUS_SINGLE_UNDATED)
    assert travel_km_on(p, "E0", "H", "A", d) is None
    assert travel_exclusion_reason(p, "E0", "H", "A", d) == STATUS_SINGLE_UNDATED


def test_covid_era_seasons_are_excluded_wholesale():
    """football-data.co.uk has no venue column, so a relocated match cannot be
    detected per fixture. The season is excluded rather than assumed normal."""
    assert RELOCATION_RISK_SEASONS == {"1920", "2021"}
    for d in (date(2020, 6, 17), date(2021, 2, 3)):
        assert travel_km_on(_pair(), "E0", "H", "A", d) is None
        assert travel_exclusion_reason(_pair(), "E0", "H", "A", d) == "relocation_risk_season"


def test_a_club_missing_from_the_table_abstains_rather_than_raising():
    d = date(2023, 8, 12)
    assert travel_km_on({}, "E0", "H", "A", d) is None
    assert travel_exclusion_reason({}, "E0", "H", "A", d) == "club_absent_from_snapshot"


def test_an_interval_gap_is_reported_as_a_gap_not_as_a_missing_club():
    hist = {
        ("E0", "H"): ClubVenueHistory(
            "H", "E0", "H F.C.",
            (_iv("Q1", 51.0, 0.0, "2000-01-01", "2017-05-14"),
             _iv("Q1b", 51.0, 0.0, "2019-04-03")), STATUS_DATED),
        ("E0", "A"): ClubVenueHistory(
            "A", "E0", "A F.C.", (_iv("Q2", 52.0, 0.0, "2000-01-01"),), STATUS_DATED),
    }
    assert travel_exclusion_reason(hist, "E0", "H", "A", date(2018, 3, 1)) == "interval_gap"


# --------------------------------------- the source receipt (auditability)


def test_raw_snapshot_holds_the_actual_bindings_not_a_summary():
    """The first cut committed derived rows plus a query hash and called that a
    reproducibility receipt. Nothing in it could show what the provider
    returned, so a resolver change and a provider change looked identical."""
    raw = load_raw_snapshot()
    assert isinstance(raw["bindings"], list) and raw["bindings"]
    assert raw["n_bindings"] == len(raw["bindings"])
    b = raw["bindings"][0]
    for field in ("name", "venue", "coord", "cap", "rank"):
        assert field in b, field


def test_raw_snapshot_records_everything_needed_to_re_run_it():
    raw = load_raw_snapshot()
    assert raw["retrieved_utc"].endswith("Z")
    assert raw["query"].strip().startswith("SELECT")
    assert "pqv:P580" in raw["query"] and "pqv:P582" in raw["query"]
    # Precision is the whole point of the value-node form.
    assert "wikibase:timePrecision" in raw["query"]
    assert raw["envelope_sha256"]
    assert raw["query_sha256"] and raw["bindings_sha256"]
    assert raw["requested_labels"] == sorted(raw["requested_labels"])
    prov = raw["provider"]
    assert "CC0" in prov["licence"] and prov["licence_url"]
    assert prov["redistribution"].startswith("GRANTED")
    wd = prov["wdqs_usage"]
    assert wd["user_agent_required"] is True and wd["user_agent_sent"]
    assert wd["query_timeout_s"] and wd["client_throttle"]


def test_raw_snapshot_digest_detects_an_edited_receipt(tmp_path):
    raw = json.loads(RAW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    raw["bindings"][0]["cap"]["value"] = "999999"
    p = tmp_path / "tampered.json"
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_raw_snapshot(p)


def test_derived_table_rebuilds_byte_for_byte_from_the_raw_snapshot():
    """The reproducibility claim, executed rather than asserted in prose."""
    rebuilt = serialize_snapshot(derive_snapshot(load_raw_snapshot(), load_aliases()))
    on_disk = SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert rebuilt == on_disk
    assert (
        hashlib.sha256(rebuilt.encode()).hexdigest()
        == hashlib.sha256(on_disk.encode()).hexdigest()
    )


def test_rebuild_is_deterministic_across_repeated_derivations():
    raw = load_raw_snapshot()
    al = load_aliases()
    assert serialize_snapshot(derive_snapshot(raw, al)) == serialize_snapshot(
        derive_snapshot(raw, al)
    )


def test_derived_table_carries_no_timestamp_of_its_own():
    # A derivation timestamp would make "byte-for-byte" impossible by design.
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert "retrieved_utc" not in payload
    assert payload["derived_from"]["retrieved_utc"] == load_raw_snapshot()["retrieved_utc"]


def test_query_pins_the_qualifiers_the_temporal_rule_depends_on():
    q = build_query(["Alpha F.C."])
    for token in ("pqv:P580", "pqv:P582", "wikibase:timePrecision",
                  "wikibase:rank", "wdt:P625", "wdt:P1083"):
        assert token in q, token


# ------------------------------------------------------ scope and coverage


def test_the_confirmation_season_is_absent_from_scope():
    """2025-26 is the consumed #202 holdout and must not appear anywhere."""
    assert "2526" not in SEASONS_IN_SCOPE
    assert len(SEASONS_IN_SCOPE) == 9
    blob = SNAPSHOT_PATH.read_text(encoding="utf-8") + RAW_SNAPSHOT_PATH.read_text(
        encoding="utf-8"
    )
    assert "2526" not in blob


def test_every_required_club_appears_with_an_explicit_status():
    hist = load_histories()
    missing = [k for k in required_clubs() if k not in hist]
    assert missing == []
    assert all(h.status for h in hist.values())


def test_undated_clubs_are_the_majority_and_that_is_recorded_not_hidden():
    """The honest headline: this source cannot date most of these clubs.

    If a future refresh flips most clubs to `dated`, this test should be
    updated deliberately — not silently, which is the point of pinning it.
    """
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    counts = payload["status_counts"]
    assert counts.get(STATUS_DATED, 0) < payload["n_required"] / 2
    assert sum(counts.values()) == payload["n_required"] == 94


def test_alias_table_contains_no_coordinates():
    raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    numbers = [
        v for d in DIVISIONS for v in raw[d].values() if isinstance(v, (int, float))
    ]
    assert numbers == []
    assert sum(len(raw[d]) for d in DIVISIONS) == 94


def test_provider_record_states_the_licence_that_permits_committing_bytes():
    assert PROVIDER["licence"].startswith("CC0")
    assert PROVIDER["redistribution"].startswith("GRANTED")
    assert PROVIDER["licence_source"].startswith("https://www.wikidata.org/")


# --------------------------------------------- date precision (the P1 fix)


def test_year_precision_boundary_makes_its_whole_year_indeterminate():
    """Wikidata serialises a year-precision qualifier as ``YYYY-01-01``.

    Read as a day, it put Atlético Madrid's Metropolitano interval eight months
    before the ground opened, and scored the Vicente Calderón farewell match at
    a stadium that did not exist. Inside the uncertainty year the answer is
    unknown; outside it, it is still usable.
    """
    h = _history(_iv("Q_NEW", 51.0, 0.0, "2017-01-01", prec=9))
    assert h.intervals[0].status_on(date(2016, 12, 31)) == "out"
    assert h.intervals[0].status_on(date(2017, 5, 21)) == "unknown"
    assert h.intervals[0].status_on(date(2018, 1, 1)) == "in"
    assert venue_on(h, date(2017, 5, 21)) is None
    assert venue_on(h, date(2018, 1, 1)) is not None


def test_month_precision_is_indeterminate_only_within_its_month():
    h = _history(_iv("Q", 51.0, 0.0, "2019-04-01", prec=10))
    assert h.intervals[0].status_on(date(2019, 3, 31)) == "out"
    assert h.intervals[0].status_on(date(2019, 4, 15)) == "unknown"
    assert h.intervals[0].status_on(date(2019, 5, 1)) == "in"


def test_a_boundary_with_no_precision_is_unusable_everywhere():
    h = _history(_iv("Q", 51.0, 0.0, "2019-04-03", prec=None))
    for d in (date(2015, 1, 1), date(2019, 4, 3), date(2024, 1, 1)):
        assert h.intervals[0].status_on(d) == "unknown"
    assert venue_on(h, date(2024, 1, 1)) is None


def test_one_indeterminate_interval_poisons_the_whole_answer():
    """Even if another interval definitely covers the date.

    "Exactly one interval covers this" is not knowable while a second one might
    have opened already.
    """
    h = _history(
        _iv("Q_OLD", 51.0, 0.0, "2000-01-01", "2017-01-01", to_prec=9),
        _iv("Q_NEW", 52.0, 0.0, "2017-01-01", prec=9),
    )
    assert venue_on(h, date(2017, 6, 1)) is None
    assert venue_on(h, date(2016, 6, 1)) is not None   # before both boundaries
    assert venue_on(h, date(2018, 6, 1)) is not None   # after both


def test_the_real_atletico_history_abstains_across_its_ambiguous_year():
    """The committed artifact, not a fixture: the P1 must be dead in the data."""
    am = load_histories()[("SP1", "Ath Madrid")]
    assert am.status == STATUS_DATED
    assert venue_on(am, date(2016, 10, 1)).venue_label.startswith("Vicente")
    for d in (date(2017, 1, 14), date(2017, 5, 21), date(2017, 9, 20)):
        assert venue_on(am, d) is None, d
    assert "Metropolitano" in venue_on(am, date(2018, 3, 1)).venue_label


def test_precision_survives_the_snapshot_round_trip():
    for h in load_histories().values():
        for i in h.intervals:
            if i.valid_from is not None:
                assert i.valid_from_precision is None or isinstance(
                    i.valid_from_precision, int
                )
    # At least one real year-precision boundary exists, or the guard is vacuous.
    assert any(
        i.valid_from_precision == 9
        for h in load_histories().values()
        for i in h.intervals
    )


# ------------------------------------------- receipt integrity, widened


def test_a_swapped_query_is_caught(tmp_path):
    """The bindings digest alone left the whole envelope unprotected."""
    raw = json.loads(RAW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    raw["query"] = "SELECT ?x WHERE { ?x pq:P580 ?y . pq:P582 }"
    p = tmp_path / "swapped.json"
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    with pytest.raises(ValueError, match="query digest mismatch"):
        load_raw_snapshot(p)


def test_edited_provenance_metadata_is_caught(tmp_path):
    raw = json.loads(RAW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    raw["provider"]["licence"] = "All Rights Reserved"
    p = tmp_path / "relicensed.json"
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    with pytest.raises(ValueError, match="envelope digest mismatch"):
        load_raw_snapshot(p)


def test_bindings_digest_is_order_independent(tmp_path):
    """WDQS has no ORDER BY, so a re-fetch may return rows in a new order.

    An order-sensitive digest would report that as tampering.
    """
    raw = json.loads(RAW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    raw["bindings"] = list(reversed(raw["bindings"]))
    p = tmp_path / "reordered.json"
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    assert load_raw_snapshot(p)["n_bindings"] == len(raw["bindings"])


def test_derived_table_records_the_receipts_provider_not_the_modules():
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert payload["provider"] == load_raw_snapshot()["provider"]


def test_the_receipt_carries_club_qids_not_only_venue_qids():
    raw = load_raw_snapshot()
    assert any("club" in b for b in raw["bindings"])


def test_verify_mode_rebuilds_and_agrees(capsys):
    """The documented receipt command, executed."""
    from pipeline.ingest.venue_coordinates import main

    assert main(["--verify"]) == 0
    assert "byte-for-byte identical" in capsys.readouterr().out
