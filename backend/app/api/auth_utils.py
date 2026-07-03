"""Shared auth helper for the versioned public API (/v1, ROADMAP Phase 4).

`require_api_key` gates a route behind the SANDBOX API-key allow-list. It fails
OPEN when no keys are configured (empty allow-list => /v1 stays public, the
Phase 2/3 default), and constant-time compares otherwise so the check never
leaks which key matched — mirroring `_require_token` in api/internal.py.
"""
from __future__ import annotations

import secrets

from fastapi import HTTPException


def require_api_key(provided: str | None, allowed: set[str]) -> None:
    """Authorize a /v1 call against the sandbox API-key allow-list.

    - `allowed` empty  => public, no gate (the shipped default): return.
    - otherwise        => require `provided` to match one of the allowed keys via
      a constant-time compare; a miss (or a missing header) is a 401.

    Every candidate is compared even after a match so timing can't reveal the
    position or value of the matching key.
    """
    if not allowed:
        return
    ok = False
    if provided is not None:
        for key in allowed:
            if secrets.compare_digest(provided, key):
                ok = True
    if not ok:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_api_key",
                    "message": "A valid X-API-Key header is required for this API."},
        )
