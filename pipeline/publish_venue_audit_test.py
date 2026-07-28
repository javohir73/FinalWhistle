import json

import pytest

from pipeline.publish_venue_audit import DEFAULT_INPUT, generate


def test_generator_reproduces_headline_values_and_caveats(tmp_path):
    output = tmp_path / "audit.json"
    audit = generate(DEFAULT_INPUT, output)

    assert audit["venues"]["kalshi"]["n_matches"] == 104
    assert audit["venues"]["kalshi"]["venue"]["favorite_hit_rate"] == pytest.approx(
        0.634615
    )
    assert audit["venues"]["kalshi"]["venue"]["log_loss"] == pytest.approx(
        0.8402407
    )
    assert audit["venues"]["kalshi"]["diff_ci95"] == [0.0173, 0.1105]
    assert audit["venues"]["kalshi"]["verdict"] == "beaten"
    assert audit["venues"]["polymarket"]["n_matches"] == 93
    assert audit["venues"]["polymarket"]["verdict"] == "inconclusive"
    assert audit["method"]["bootstrap"] == {
        "unit": "match",
        "seed": 20260727,
        "samples": 10000,
        "note": "Recomputed interval; historical published CI is retained separately because its original seed was not recorded.",
    }
    assert audit["cross_venue"]["favorite_disagreements"] == 0
    assert audit["cross_venue"]["diverging_at_least_3c"] == 0
    assert audit["cross_venue"]["log_loss"]["consensus"] > audit["cross_venue"][
        "log_loss"
    ]["kalshi"]
    assert any(
        "not in-play" in limitation
        for limitation in audit["method"]["limitations"]
    )
    assert json.loads(output.read_text()) == audit


def test_committed_artifact_is_byte_reproducible(tmp_path):
    generated = tmp_path / "audit.json"
    generate(DEFAULT_INPUT, generated)

    committed = DEFAULT_INPUT.parents[3] / "frontend/lib/venue-audit-data.json"
    assert generated.read_bytes() == committed.read_bytes()
