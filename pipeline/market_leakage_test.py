"""L1 — the market-benchmark modules stay out of the rating and feature paths.

D0's whole premise is that odds are a **yardstick**, not an input. A yardstick
that quietly becomes an input stops measuring anything, and the failure is
silent: the benchmark just gets easier to beat.

This is a structural test on the import graph rather than a behavioural one,
because behaviour only catches a leak that a given test happens to exercise.

**One deliberate exception, stated rather than hidden.** `ml/models/odds_blend.py`
exists and `ml/models/params.py` carries `w_odds` / `use_odds` — a market-anchoring
path for the SHADOW model (exact-score program FR-4.3, pre-registered as T2.1 in
docs/MODEL-EXPERIMENTS.md). It ships default-OFF (`w_odds=0.0`, `use_odds=False`)
and is not what this test guards. This test guards the D0 benchmark surface:
those modules must never become a model input by accident, which is the failure
mode that has no owner and no gate behind it.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

#: The D0 benchmark surface. Importing any of these from a fit/feature/rating
#: module would make a closing price available to something that trains.
_BENCHMARK_MODULES = frozenset(
    {
        "ml.evaluation.market_benchmark",
        "pipeline.market_coverage",
        "pipeline.ingest.football_data",
        "pipeline.ingest.football_data_odds",
    }
)

#: Packages that must remain market-blind: ratings replay, feature building,
#: and tournament simulation. `ml/models` is deliberately NOT here — see the
#: module docstring's stated exception.
_MARKET_BLIND_PACKAGES = ("ml/ratings", "ml/features", "ml/simulate")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _source_files(package: str) -> list[Path]:
    return [
        p
        for p in sorted((_ROOT / package).rglob("*.py"))
        if not p.name.endswith("_test.py") and not p.name.startswith("test_")
    ]


@pytest.mark.parametrize("package", _MARKET_BLIND_PACKAGES)
def test_rating_and_feature_paths_never_import_the_market_benchmark(package):
    offenders = {
        str(p.relative_to(_ROOT)): sorted(_imported_modules(p) & _BENCHMARK_MODULES)
        for p in _source_files(package)
        if _imported_modules(p) & _BENCHMARK_MODULES
    }
    assert offenders == {}, (
        f"{package} imported a D0 market-benchmark module: {offenders}. "
        "Odds are a benchmark, never a feature — see D0 pre-registration L1."
    )


def test_the_market_blind_packages_actually_exist_and_have_sources():
    # A guard whose target has been renamed away silently passes forever.
    for package in _MARKET_BLIND_PACKAGES:
        assert _source_files(package), f"{package} has no source files to scan"


def test_the_guard_detects_a_planted_import(tmp_path):
    # Prove the scanner works, so a green result means something.
    planted = tmp_path / "leaky.py"
    planted.write_text("from ml.evaluation.market_benchmark import devig\n")
    assert _imported_modules(planted) & _BENCHMARK_MODULES


def test_coverage_module_is_not_imported_by_any_serving_path():
    """The census is an offline audit tool; the API must not depend on it."""
    offenders = [
        str(p.relative_to(_ROOT))
        for p in _source_files("backend/app")
        if "pipeline.market_coverage" in _imported_modules(p)
    ]
    assert offenders == []
