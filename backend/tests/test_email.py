"""STEP 0 — shared transactional-email foundation: a provider-agnostic
EmailSender (console default that makes no network call; Resend when configured),
plus the shared opaque-token + tz-coercion + TTL helpers used by password reset
and email verification.
"""
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.email import ConsoleEmailSender, ResendEmailSender, get_email_sender
from app.security import (
    EMAIL_VERIFICATION_TTL,
    RESET_TTL,
    new_opaque_token,
    to_aware_utc,
)


def _restore_email_settings(fn):
    """Run fn with email settings restored afterwards."""
    old_p, old_k = settings.email_provider, settings.email_api_key
    try:
        fn()
    finally:
        settings.email_provider, settings.email_api_key = old_p, old_k


def test_get_email_sender_defaults_to_console():
    def body():
        settings.email_provider, settings.email_api_key = "console", ""
        assert isinstance(get_email_sender(), ConsoleEmailSender)
    _restore_email_settings(body)


def test_get_email_sender_falls_back_to_console_when_key_missing():
    def body():
        settings.email_provider, settings.email_api_key = "resend", ""
        assert isinstance(get_email_sender(), ConsoleEmailSender)
    _restore_email_settings(body)


def test_get_email_sender_uses_resend_when_provider_and_key_set():
    def body():
        settings.email_provider, settings.email_api_key = "resend", "re_test_key"
        assert isinstance(get_email_sender(), ResendEmailSender)
    _restore_email_settings(body)


def test_console_sender_makes_no_network_call(monkeypatch):
    import app.email as email_mod

    def boom(*a, **k):
        raise AssertionError("ConsoleEmailSender must not make network calls")

    monkeypatch.setattr(email_mod.requests, "post", boom)
    sender = ConsoleEmailSender()
    sender.send_password_reset("u@example.com", "https://app.test/reset-password?token=x")
    sender.send_verification("u@example.com", "https://app.test/verify-email?token=x")


def test_new_opaque_token_is_unique_and_urlsafe():
    a, b = new_opaque_token(), new_opaque_token()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_to_aware_utc_coerces_naive_and_preserves_aware():
    naive = datetime(2026, 6, 24, 12, 0, 0)
    coerced = to_aware_utc(naive)
    assert coerced.tzinfo is timezone.utc
    aware = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert to_aware_utc(aware) == aware


def test_token_ttls_are_sane():
    assert RESET_TTL == timedelta(minutes=30)
    assert EMAIL_VERIFICATION_TTL == timedelta(hours=24)
