import pytest

from pipeline.search_blend_weight import search_blend_weight


def test_search_includes_both_endpoints_and_blocks_small_sample():
    result = search_blend_weight([[0.8, 0.1, 0.1]] * 5, [[0.2, 0.2, 0.6]] * 5, [2] * 5, steps=11)
    assert result["grid"][0]["weight"] == 0
    assert result["grid"][-1]["weight"] == 1
    assert result["best"]["weight"] == 1
    assert result["eligible_for_owner_review"] is False
    assert result["promotion_blocked_reason"] == "insufficient scored pairs"


def test_search_can_become_review_eligible_but_never_promotes():
    result = search_blend_weight([[0.8, 0.1, 0.1]] * 30, [[0.2, 0.2, 0.6]] * 30, [2] * 30)
    assert result["eligible_for_owner_review"] is True
    assert "promoted" not in result


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_invalid_probability_rows_rejected(bad):
    with pytest.raises(ValueError):
        search_blend_weight([[bad, 0.5, 0.5]], [[0.3, 0.3, 0.4]], [0])
