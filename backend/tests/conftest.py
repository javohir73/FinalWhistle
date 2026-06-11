"""Shared test configuration.

Tests must be hermetic to the developer's local `.env` (Settings reads it from
the CWD): a configured RECOMPUTE_TOKEN, dev ENVIRONMENT, or extra CORS origins
would otherwise flip test assumptions. Pin everything env-sensitive here.

The session cookie is `Secure` by default (correct for production over https), but
the TestClient speaks plain http, so a Secure cookie is never stored/sent back.
Disable it for the test run so the auth round trip is exercisable — this mirrors
local dev, where COOKIE_SECURE=false.
"""
from app.config import settings

settings.cookie_secure = False
settings.recompute_token = ""  # tests assert fail-closed 503 when unset
settings.environment = "production"  # tests exercise the strict Origin rules
settings.cors_origins = "http://localhost:3000"
