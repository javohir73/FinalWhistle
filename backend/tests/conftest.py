"""Shared test configuration.

The session cookie is `Secure` by default (correct for production over https), but
the TestClient speaks plain http, so a Secure cookie is never stored/sent back.
Disable it for the test run so the auth round trip is exercisable — this mirrors
local dev, where COOKIE_SECURE=false.
"""
from app.config import settings

settings.cookie_secure = False
