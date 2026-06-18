"""Tests for the HistGradientBoosting W/D/L challenger + blend helper."""
import pytest

from ml.features.wdl_features import assemble_features
from ml.models.wdl_boost import WdlBoost, blend_triples


def _feat(elo_home, elo_away):
    return assemble_features(
        elo_home=elo_home, elo_away=elo_away, is_neutral=True,
        form_home=15.0, form_away=15.0,
        gf_avg_home=1.4, gf_avg_away=1.4, ga_avg_home=1.2, ga_avg_away=1.2,
        h2h_home_wins=0, h2h_matches=0,
        data_points_home=10, data_points_away=10,
    )


def _training_rows():
    """Strong home edge → home win; strong away edge → away win; level → draw."""
    rows = []
    for _ in range(80):
        rows.append({**_feat(1900, 1500), "label": "H"})
        rows.append({**_feat(1500, 1900), "label": "A"})
        rows.append({**_feat(1700, 1700), "label": "D"})
    return rows


def test_predict_proba_is_a_simplex():
    model = WdlBoost().fit(_training_rows())
    probs = model.predict_proba(_feat(1850, 1500))
    assert set(probs.keys()) == {"H", "D", "A"}
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in probs.values())


def test_learns_home_edge():
    model = WdlBoost().fit(_training_rows())
    assert model.predict_proba(_feat(1900, 1500))["H"] > model.predict_proba(_feat(1500, 1900))["H"]


def test_strong_home_favorite_is_labelled_home_not_away():
    # Absolute direction (not just relative): a big home edge must put more mass on
    # "H" than "A". Catches a label/class-order inversion that the relative test misses.
    model = WdlBoost().fit(_training_rows())
    probs = model.predict_proba(_feat(1900, 1500))
    assert probs["H"] > probs["A"]


def test_deterministic_under_fixed_seed():
    a = WdlBoost().fit(_training_rows()).predict_proba(_feat(1800, 1550))
    b = WdlBoost().fit(_training_rows()).predict_proba(_feat(1800, 1550))
    assert a == b


def test_unfitted_raises():
    with pytest.raises(RuntimeError):
        WdlBoost().predict_proba(_feat(1700, 1700))


def test_blend_triples_weights_and_normalizes():
    poisson = (0.5, 0.3, 0.2)
    boost = (0.1, 0.1, 0.8)
    assert blend_triples(poisson, boost, 0.0) == pytest.approx(poisson)
    assert blend_triples(poisson, boost, 1.0) == pytest.approx(boost)
    mid = blend_triples(poisson, boost, 0.5)
    assert sum(mid) == pytest.approx(1.0)
    assert mid[2] == pytest.approx(0.5)   # (0.2 + 0.8) / 2
