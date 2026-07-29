"""Startup smoke tests: importing and starting must do nothing by themselves."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    "worker",
    "worker.config",
    "worker.capture",
    "worker.streaming",
    "worker.raw_store",
    "pipeline.ingest.venues.redaction",
    "worker.main",
    "pipeline.ingest.venues",
    "pipeline.ingest.venues.types",
    "pipeline.ingest.venues.kalshi",
    "pipeline.ingest.venues.polymarket",
]

#: Bans the CONNECTION, not the class. Replacing socket.socket outright breaks
#: the standard library itself -- ssl.SSLSocket subclasses it -- which would
#: make this pass for the wrong reason.
_IMPORT_UNDER_SOCKET_BAN = """
import socket
import ssl  # noqa: F401  -- let the stdlib finish subclassing socket first


def _blocked(*args, **kwargs):
    raise AssertionError("opened a network connection at import time")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

import importlib
for name in {modules!r}:
    importlib.import_module(name)
print("IMPORTS-CLEAN")
"""


def _run(code: str, **env_overrides) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "backend"), str(ROOT)])
    for key in [k for k in env if k.startswith("MARKET_CAPTURE_")]:
        del env[key]
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(ROOT), env=env, timeout=120,
    )


def test_importing_the_capture_layer_opens_no_socket():
    """The whole module graph, with socket construction made fatal."""
    result = _run(_IMPORT_UNDER_SOCKET_BAN.format(modules=MODULES))

    assert "IMPORTS-CLEAN" in result.stdout, result.stderr
    assert result.returncode == 0


def test_the_worker_refuses_to_start_with_no_configuration():
    """Not a crash and not a silent no-op: a stated reason and a nonzero exit."""
    result = _run("from worker.main import main; raise SystemExit(main())")

    assert result.returncode == 2
    assert "will not start" in result.stderr
    assert "MARKET_CAPTURE_ENABLED" in result.stderr


def test_the_worker_refuses_to_start_enabled_without_an_allowlist():
    result = _run(
        "from worker.main import main; raise SystemExit(main())",
        MARKET_CAPTURE_ENABLED="true",
    )

    assert result.returncode == 2
    assert "MARKET_CAPTURE_MARKET_KEYS" in result.stderr


def test_refusing_never_reaches_the_database_or_an_http_session():
    """The refusal path must not import app.db or construct an adapter --
    otherwise a misconfigured worker still opens a connection pool to say no.
    """
    code = """
import sys
from worker.main import main
code = main()
touched = [name for name in sys.modules
           if name in ("app.db", "pipeline.ingest.venues.kalshi",
                       "pipeline.ingest.venues.polymarket")]
print("EXIT", code, "TOUCHED", touched)
"""
    result = _run(code, MARKET_CAPTURE_ENABLED="true")

    assert "EXIT 2 TOUCHED []" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("module", MODULES)
def test_every_module_imports_standalone(module):
    """Catches an import cycle or a missing dependency without a container."""
    result = _run(f"import {module}; print('OK')")

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_the_worker_image_installs_capture_only_dependencies():
    """boto3 belongs to the worker, not the API image."""
    backend = (ROOT / "backend" / "requirements.txt").read_text()
    worker = (ROOT / "worker" / "requirements.txt").read_text()
    dockerfile = (ROOT / "worker" / "Dockerfile").read_text()

    assert "boto3" not in backend
    assert "boto3==" in worker
    assert "-r ../backend/requirements.txt" in worker
    assert "worker/requirements.txt" in dockerfile
