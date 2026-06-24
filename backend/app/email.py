"""Transactional email — provider-agnostic.

Password reset and email verification send links through an EmailSender. The
default ConsoleEmailSender just logs the link and makes NO network call, so the
flows are fully testable and shippable before any vendor is wired up. Setting
EMAIL_PROVIDER=resend + EMAIL_API_KEY activates real sending; a missing key
falls back to console so the auth path never crashes on a misconfig.
"""
from __future__ import annotations

import logging
from typing import Protocol

import requests

from app.config import settings

logger = logging.getLogger(__name__)

_RESET_SUBJECT = "Reset your FinalWhistle password"
_VERIFY_SUBJECT = "Verify your FinalWhistle email"


def _reset_html(reset_url: str) -> str:
    return (
        "<p>We received a request to reset your FinalWhistle password.</p>"
        f'<p><a href="{reset_url}">Choose a new password</a></p>'
        "<p>This link expires in 30 minutes. If you didn't request it, you can "
        "safely ignore this email.</p>"
    )


def _verify_html(verify_url: str) -> str:
    return (
        "<p>Welcome to FinalWhistle! Confirm your email address to secure your "
        "account.</p>"
        f'<p><a href="{verify_url}">Verify my email</a></p>'
        "<p>If you didn't create an account, you can ignore this email.</p>"
    )


class EmailSender(Protocol):
    """The send surface used by the auth routes. Implementations must never raise
    for a benign condition that should not break the caller's flow."""

    def send_password_reset(self, to_email: str, reset_url: str) -> None: ...
    def send_verification(self, to_email: str, verify_url: str) -> None: ...


class ConsoleEmailSender:
    """Dev / test / fallback sender: logs the link, makes no network call."""

    def send_password_reset(self, to_email: str, reset_url: str) -> None:
        logger.info("[email:console] password reset for %s -> %s", to_email, reset_url)

    def send_verification(self, to_email: str, verify_url: str) -> None:
        logger.info("[email:console] verify email for %s -> %s", to_email, verify_url)


class ResendEmailSender:
    """Sends via Resend's HTTPS API (https://resend.com). Uses `requests` — no SDK
    or extra dependency. The API key comes from env, never the codebase."""

    _ENDPOINT = "https://api.resend.com/emails"

    def __init__(self, api_key: str, from_addr: str):
        self._api_key = api_key
        self._from = from_addr

    def _send(self, to_email: str, subject: str, html: str) -> None:
        resp = requests.post(
            self._ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"from": self._from, "to": [to_email], "subject": subject, "html": html},
            timeout=10,
        )
        resp.raise_for_status()

    def send_password_reset(self, to_email: str, reset_url: str) -> None:
        self._send(to_email, _RESET_SUBJECT, _reset_html(reset_url))

    def send_verification(self, to_email: str, verify_url: str) -> None:
        self._send(to_email, _VERIFY_SUBJECT, _verify_html(verify_url))


def get_email_sender() -> EmailSender:
    """Pick the sender from settings. Console unless a provider AND its key are
    both configured (fail-safe: a configured provider with no key logs a warning
    and degrades to console rather than crashing)."""
    provider = (settings.email_provider or "").strip().lower()
    if provider in ("", "console"):
        return ConsoleEmailSender()
    if not settings.email_api_key:
        logger.warning("EMAIL_PROVIDER=%r set but EMAIL_API_KEY is empty; using console.", provider)
        return ConsoleEmailSender()
    if provider == "resend":
        return ResendEmailSender(settings.email_api_key, settings.email_from)
    logger.warning("Unknown EMAIL_PROVIDER=%r; using console.", provider)
    return ConsoleEmailSender()
