"""Origin allow-list hardening (STEP 1 auth): the www/apex sibling of every
configured origin is auto-allowed, an optional anchored CORS_PREVIEW_REGEX can
admit this project's Vercel previews, and BOTH CORSMiddleware and the
require_same_origin CSRF guard read the single Settings.allowed_origins source.
"""
import pytest
from fastapi import HTTPException

from app.config import Settings, settings
from app.security import require_same_origin


class FakeRequest:
    """Minimal stand-in: require_same_origin only reads request.headers.get('origin')."""
    def __init__(self, origin=None):
        self.headers = {"origin": origin} if origin is not None else {}


# ---- Settings.allowed_origins (pure www/apex expansion) ----

def test_apex_origin_also_allows_www_sibling():
    ao = Settings(cors_origins="https://finalwhistle.app").allowed_origins
    assert "https://finalwhistle.app" in ao
    assert "https://www.finalwhistle.app" in ao


def test_www_origin_also_allows_apex_sibling():
    ao = Settings(cors_origins="https://www.finalwhistle.app").allowed_origins
    assert "https://www.finalwhistle.app" in ao
    assert "https://finalwhistle.app" in ao


def test_localhost_is_not_expanded():
    assert Settings(cors_origins="http://localhost:3000").allowed_origins == [
        "http://localhost:3000"
    ]


def test_ipv4_host_is_not_expanded():
    assert Settings(cors_origins="https://203.0.113.5").allowed_origins == [
        "https://203.0.113.5"
    ]


def test_multiple_origins_expand_and_dedupe():
    ao = Settings(
        cors_origins="https://finalwhistle.app, https://www.finalwhistle.app"
    ).allowed_origins
    assert ao.count("https://finalwhistle.app") == 1
    assert ao.count("https://www.finalwhistle.app") == 1


def test_scheme_and_port_preserved_in_sibling():
    ao = Settings(cors_origins="https://example.com:8443").allowed_origins
    assert "https://www.example.com:8443" in ao


# ---- Settings.cors_origin_regex (validated, fail-closed) ----

def test_preview_regex_blank_is_none():
    assert Settings(cors_preview_regex="").cors_origin_regex is None


def test_preview_regex_invalid_fails_closed_to_none():
    assert Settings(cors_preview_regex="^(unclosed").cors_origin_regex is None


def test_preview_regex_valid_is_returned():
    pat = r"^https://fifa-wc26-prediction-[a-z0-9-]+\.vercel\.app$"
    assert Settings(cors_preview_regex=pat).cors_origin_regex == pat


# ---- Settings.public_base_url_allowed (email-link / Origin-guard consistency) ----

def test_public_base_url_allowed_when_in_origins():
    s = Settings(
        cors_origins="https://fifa-wc26-prediction.vercel.app",
        public_base_url="https://fifa-wc26-prediction.vercel.app",
    )
    assert s.public_base_url_allowed is True


def test_public_base_url_allowed_via_www_sibling():
    s = Settings(cors_origins="https://finalwhistle.app", public_base_url="https://www.finalwhistle.app")
    assert s.public_base_url_allowed is True  # www sibling is auto-allowed


def test_public_base_url_not_allowed_when_mismatched():
    s = Settings(
        cors_origins="https://fifa-wc26-prediction.vercel.app",
        public_base_url="https://finalwhistle.app",
    )
    assert s.public_base_url_allowed is False


# ---- require_same_origin (reads the global settings; restore in finally) ----

def test_allows_configured_origin_and_www_sibling():
    old = settings.cors_origins
    try:
        settings.cors_origins = "https://finalwhistle.app"
        require_same_origin(FakeRequest("https://finalwhistle.app"))
        require_same_origin(FakeRequest("https://www.finalwhistle.app"))
    finally:
        settings.cors_origins = old


def test_rejects_foreign_origin():
    old = settings.cors_origins
    try:
        settings.cors_origins = "https://finalwhistle.app"
        with pytest.raises(HTTPException) as ei:
            require_same_origin(FakeRequest("https://evil.example.com"))
        assert ei.value.status_code == 403
        assert ei.value.detail["code"] == "forbidden_origin"
    finally:
        settings.cors_origins = old


def test_missing_origin_rejected_in_production():
    old_env = settings.environment
    try:
        settings.environment = "production"
        with pytest.raises(HTTPException) as ei:
            require_same_origin(FakeRequest(None))
        assert ei.value.status_code == 403
    finally:
        settings.environment = old_env


def test_missing_origin_allowed_outside_production():
    old_env = settings.environment
    try:
        settings.environment = "development"
        require_same_origin(FakeRequest(None))  # must not raise
    finally:
        settings.environment = old_env


def test_port_and_scheme_must_match_exactly():
    old = settings.cors_origins
    try:
        settings.cors_origins = "http://localhost:3000"
        for bad in ("https://localhost:3000", "http://localhost:3001"):
            with pytest.raises(HTTPException):
                require_same_origin(FakeRequest(bad))
    finally:
        settings.cors_origins = old


def test_preview_regex_allows_match_but_rejects_anchored_bypass():
    old_cors, old_prev = settings.cors_origins, settings.cors_preview_regex
    try:
        settings.cors_origins = "https://fifa-wc26-prediction.vercel.app"
        settings.cors_preview_regex = (
            r"^https://fifa-wc26-prediction-[a-z0-9-]+\.vercel\.app$"
        )
        require_same_origin(FakeRequest("https://fifa-wc26-prediction-abc123.vercel.app"))
        # fullmatch + anchors must reject a suffix-bypass and unrelated previews
        with pytest.raises(HTTPException):
            require_same_origin(
                FakeRequest("https://fifa-wc26-prediction-x.vercel.app.evil.com")
            )
        with pytest.raises(HTTPException):
            require_same_origin(FakeRequest("https://someone-else.vercel.app"))
    finally:
        settings.cors_origins, settings.cors_preview_regex = old_cors, old_prev
