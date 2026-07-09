"""Exchange display names must fold onto our FIFA-style team names."""
from pipeline.ingest.market_names import build_team_index, normalize


def test_normalize_case_accents_punctuation():
    assert normalize("  Côte d'Ivoire ") == "cote divoire"
    assert normalize("USA") == "united states"
    assert normalize("South Korea") == "korea republic"
    assert normalize("Morocco") == "morocco"


def test_unknown_name_passes_through_normalized():
    assert normalize("Atlantis FC") == "atlantis fc"


def test_build_team_index():
    idx = build_team_index([(1, "United States"), (2, "Côte d'Ivoire")])
    assert idx[normalize("USA")] == 1
    assert idx[normalize("Ivory Coast")] == 2
    assert normalize("Narnia") not in idx
