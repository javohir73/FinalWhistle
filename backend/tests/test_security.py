"""Unit tests for password hashing/verification (app/security.py).

Regression coverage for the argon2 exception-import bug: verify_password must
return False — never raise — for wrong passwords and malformed/garbage hashes,
regardless of which exception names the installed argon2-cffi version exports.
"""
from app.security import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    h = hash_password("supersecret123")
    assert verify_password(h, "supersecret123") is True


def test_wrong_password_returns_false():
    h = hash_password("supersecret123")
    assert verify_password(h, "wrong-password") is False


def test_garbage_or_empty_hash_returns_false_without_raising():
    # The regression: a non-argon2 / malformed / empty / None hash must not crash.
    assert verify_password("not-a-real-argon2-hash", "whatever") is False
    assert verify_password("", "whatever") is False
    assert verify_password(None, "whatever") is False  # type: ignore[arg-type]
