"""Exchange display names must fold onto our FIFA-style team names."""
from pipeline.ingest.market_names import build_team_index, normalize, normalize_text


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


def test_normalize_text_expands_aliases_found_inside_free_text():
    assert normalize("Korea") in normalize_text("Will Korea win?")
    assert normalize("USA") in normalize_text("USA vs. Iran")
    assert normalize("Iran") in normalize_text("USA vs. Iran")
    # longest phrase wins so "south korea" doesn't leave a stray "korea":
    assert normalize_text("Will South Korea win?") == "will korea republic win"


def test_normalize_text_leaves_unaliased_text_alone():
    assert normalize_text("Will France win?") == "will france win"
    # word boundaries: the "us" alias must not fire inside other words
    assert normalize_text("Will Australia win?") == "will australia win"
    assert normalize_text("Will Russia win?") == "will russia win"
