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
        "ml.evaluation.club_totals_benchmark",
        "pipeline.market_coverage",
        "pipeline.run_club_totals_benchmark",
        "pipeline.ingest.football_data",
        "pipeline.ingest.football_data_odds",
    }
)

#: Packages that must remain market-blind: ratings replay, feature building,
#: and tournament simulation. `ml/models` is deliberately NOT here — see the
#: module docstring's stated exception.
_MARKET_BLIND_PACKAGES = ("ml/ratings", "ml/features", "ml/simulate")


def _module_name(path: Path) -> str:
    """Dotted module name for a repo source file, e.g. ml/features/x.py -> ml.features.x."""
    rel = path.relative_to(_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[0] == "backend":  # backend/ is on sys.path, not a package
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import.

    Absolute imports are the easy half. This also resolves **relative** imports
    against the file's own package and picks up **dynamic** ones
    (``importlib.import_module("...")``, ``__import__("...")``) — a scanner that
    only saw ``import a.b.c`` would go green on `from ..evaluation.market_benchmark
    import devig`, which is a working import from inside `ml/features/` and
    exactly how a leak would actually be written.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg = _module_name(path).rsplit(".", 1)[0] if "." in _module_name(path) else ""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                # level=1 is the containing package, level=2 its parent, ...
                anchor = pkg.split(".") if pkg else []
                trimmed = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(trimmed + ([node.module] if node.module else []))
            if base:
                names.add(base)
                names.update(f"{base}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            target = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if target in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.add(arg.value)
    return names


def _source_files(package: str) -> list[Path]:
    return [
        p
        for p in sorted((_ROOT / package).rglob("*.py"))
        if not p.name.endswith("_test.py") and not p.name.startswith("test_")
    ]


def _require_sources(package: str) -> list[Path]:
    """Sources for ``package``, refusing to scan nothing.

    ``rglob`` on a missing directory yields nothing rather than raising, so a
    guard pointed at a moved or renamed tree scans zero files and asserts
    ``[] == []`` — passing forever, loudest exactly when it has stopped working.
    """
    files = _source_files(package)
    assert files, (
        f"{package} has no source files to scan — the guard is pointed at a "
        "path that no longer exists, so it is asserting nothing."
    )
    return files


def _first_party_imports(path: Path) -> set[str]:
    """Imports that resolve to a repo source file, for transitive closure."""
    return {
        n
        for n in _imported_modules(path)
        if n.split(".")[0] in {"ml", "pipeline", "app", "worker"}
    }


def _module_path(module: str) -> Path | None:
    for base in ("", "backend/"):
        for candidate in (
            _ROOT / f"{base}{module.replace('.', '/')}.py",
            _ROOT / f"{base}{module.replace('.', '/')}" / "__init__.py",
        ):
            if candidate.exists():
                return candidate
    return None


def _reaches_benchmark(path: Path, seen: set[str] | None = None) -> list[str] | None:
    """Shortest import chain from ``path`` to a benchmark module, or None.

    Direct-import scanning misses the realistic shape of a leak: `ml/simulate`
    imports `ml/models`, so a `devig` import added to `ml/models` puts a closing
    price one attribute access away from the simulator while every direct-import
    assertion stays green.
    """
    seen = seen if seen is not None else set()
    me = _module_name(path)
    if me in seen:
        return None
    seen.add(me)
    imports = _imported_modules(path)
    hit = sorted(imports & _BENCHMARK_MODULES)
    if hit:
        return [me, hit[0]]
    for name in sorted(_first_party_imports(path)):
        nxt = _module_path(name)
        if nxt is None:
            continue
        chain = _reaches_benchmark(nxt, seen)
        if chain:
            return [me] + chain
    return None


@pytest.mark.parametrize("package", _MARKET_BLIND_PACKAGES)
def test_rating_and_feature_paths_never_import_the_market_benchmark(package):
    offenders = {
        str(p.relative_to(_ROOT)): sorted(_imported_modules(p) & _BENCHMARK_MODULES)
        for p in _require_sources(package)
        if _imported_modules(p) & _BENCHMARK_MODULES
    }
    assert offenders == {}, (
        f"{package} imported a D0 market-benchmark module: {offenders}. "
        "Odds are a benchmark, never a feature — see D0 pre-registration L1."
    )


@pytest.mark.parametrize("package", _MARKET_BLIND_PACKAGES)
def test_no_transitive_path_from_a_market_blind_package_to_the_benchmark(package):
    chains = {
        str(p.relative_to(_ROOT)): " -> ".join(chain)
        for p in _require_sources(package)
        if (chain := _reaches_benchmark(p))
    }
    assert chains == {}, (
        f"{package} can reach a D0 market-benchmark module transitively: {chains}."
    )


@pytest.mark.parametrize(
    "source",
    [
        "from ml.evaluation.market_benchmark import devig",
        "import ml.evaluation.market_benchmark",
        "from ..evaluation.market_benchmark import devig",
        "from ..evaluation import market_benchmark",
        "import importlib\nm = importlib.import_module('ml.evaluation.market_benchmark')",
        "m = __import__('pipeline.market_coverage')",
        # D0-B. Registering a module in _BENCHMARK_MODULES is only as good as
        # the dotted string being right; a typo would fail nothing, forever.
        "from ml.evaluation.club_totals_benchmark import build_matched_totals",
        "from ..evaluation.club_totals_benchmark import market_p_over",
    ],
    ids=["absolute-from", "absolute-import", "relative-from", "relative-module",
         "importlib", "dunder-import", "totals-absolute", "totals-relative"],
)
def test_the_guard_detects_every_spelling_of_a_planted_import(source):
    """A guard is only worth its green if it fails on the leak it claims to catch.

    The relative forms are the ones that matter: inside `ml/features/`,
    `from ..evaluation.market_benchmark import devig` is a *working* import.
    """
    planted = _ROOT / "ml" / "features" / "_leak_probe.py"
    planted.write_text(source + "\n")
    try:
        assert _imported_modules(planted) & _BENCHMARK_MODULES
    finally:
        planted.unlink()


def test_coverage_module_is_not_imported_by_any_serving_path():
    """The census is an offline audit tool; the API must not depend on it."""
    offenders = [
        str(p.relative_to(_ROOT))
        for p in _require_sources("backend/app")
        if "pipeline.market_coverage" in _imported_modules(p)
    ]
    assert offenders == []


def test_the_census_imports_no_database_and_no_app_module():
    """Importing an offline audit tool must not build a SQLAlchemy engine.

    `pipeline.ingest.club_results` imports `app.models`, which imports `app.db`,
    which calls `create_engine` at import time. Reaching it for a URL constant
    made the census fail on any machine without DATABASE_URL set — an offline
    tool that needs a database to start is not offline.
    """
    chain_roots = {"app", "sqlalchemy"}
    for module in ("pipeline.market_coverage", "pipeline.ingest.football_data"):
        path = _module_path(module)
        assert path is not None, module
        reached = {
            n.split(".")[0]
            for n in _imported_modules(path)
        }
        assert not (reached & chain_roots), f"{module} imports {reached & chain_roots}"
        # ...and no first-party hop that would drag one in.
        for name in _first_party_imports(path):
            nxt = _module_path(name)
            if nxt is None:
                continue
            hop = {n.split(".")[0] for n in _imported_modules(nxt)}
            assert not (hop & chain_roots), f"{module} -> {name} imports {hop & chain_roots}"
