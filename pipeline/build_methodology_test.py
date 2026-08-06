"""The public methodology page must describe the engine that is actually
serving. It drifted once — the page badged poisson-elo-v0.5 as "current" and
called the signal pack "shadow-only" for two days after v0.6 promoted odds,
availability and suspensions into the published number. These are cheap,
file-level checks that catch that class of drift in CI instead of in front of
readers.
"""
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGE = _ROOT / "frontend/app/methodology/page.tsx"
_DATA = _ROOT / "frontend/lib/methodology-data.json"
_PARAMS = _ROOT / "ml/models/model_params.json"


def _served_version() -> str:
    return json.loads(_PARAMS.read_text())["version"]


def test_changelog_badges_the_served_version_as_current():
    """The `current` pill must sit on the version model_params.json ships."""
    page = _PAGE.read_text()
    served = _served_version()
    # The badge markup follows the version string it belongs to.
    entry = re.search(
        re.escape(served) + r"</span>\{\" \"\}\s*\n\s*<span[^>]*>current</span>",
        page,
    )
    assert entry is not None, (
        f"methodology page does not badge {served} (the version in "
        "ml/models/model_params.json) as current"
    )


def test_only_one_version_is_badged_current():
    assert _PAGE.read_text().count(">current</span>") == 1


def test_page_lists_every_club_competition_version():
    """A reader arriving from a club competition must find its engine named —
    the international changelog does not cover them (pipeline/leagues.py)."""
    from pipeline.leagues import ACTIVE_LEAGUES, club_params_for

    page = _PAGE.read_text()
    for code in ACTIVE_LEAGUES:
        version = club_params_for(code).version
        assert version in page, f"{code}'s served version {version} is unlisted"


def test_page_does_not_claim_the_promoted_signals_are_shadow_only():
    """v0.6 promoted odds/availability/suspensions. The old copy said the pack
    'doesn't move the published number' — true until it wasn't."""
    page = _PAGE.read_text()
    assert "does\n            not move the published number" not in page
    assert "not move the published number yet" not in page


def test_backtest_provenance_is_explicit_in_the_data_file():
    """The historical numbers come from the v0.1 baseline, not the served
    engine. The field name must not read like a claim about production."""
    data = json.loads(_DATA.read_text())
    assert "model_version" not in data, (
        "'model_version' reads as the served version; use 'backtest_engine'"
    )
    assert data["backtest_engine"] == "poisson-elo-v0.1"
    assert "leakage" in data["backtest_engine_note"]


def test_data_file_carries_no_dead_changelog_key():
    """build_methodology stopped emitting it; the page renders its own. A
    resurrected copy is a second source of truth that will drift."""
    assert "changelog" not in json.loads(_DATA.read_text())


def test_generator_emits_exactly_the_committed_shape():
    """Hand-edits to the JSON must stay in sync with the generator, or the next
    regeneration silently reverts them."""
    src = (_ROOT / "pipeline/build_methodology.py").read_text()
    for key in ("backtest_engine", "backtest_engine_note"):
        assert f'"{key}"' in src, f"generator does not emit {key}"
    assert '"model_version"' not in src
