"""tests/test_auth.py — Tests sécurité web."""
from __future__ import annotations

from datetime import datetime, timezone

from src.web.auth import (
    create_token, decode_token, hash_password, verify_password,
    check_rate_limit, record_login_attempt, _login_attempts,
)


def test_password_hashing_basic():
    h = hash_password("CorrectHorseBatteryStaple!")
    assert h != "CorrectHorseBatteryStaple!"
    assert h.startswith("$2b$")
    assert verify_password("CorrectHorseBatteryStaple!", h)
    assert not verify_password("wrong", h)


def test_password_hashing_unique_salt():
    """Deux hashes du même mot de passe diffèrent (sel)."""
    h1 = hash_password("test12345678")
    h2 = hash_password("test12345678")
    assert h1 != h2
    assert verify_password("test12345678", h1)
    assert verify_password("test12345678", h2)


def test_password_verify_safe_against_weird_input():
    h = hash_password("abc12345678910")
    assert not verify_password("", h)
    assert not verify_password("a" * 1000, h)


def test_jwt_create_and_decode():
    token = create_token(42, "alice@ugfs-na.com", "analyst")
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["email"] == "alice@ugfs-na.com"
    assert payload["role"] == "analyst"
    assert "exp" in payload


def test_jwt_invalid_signature_rejected():
    token = create_token(1, "x@y.com", "admin")
    tampered = token[:-5] + "AAAAA"
    assert decode_token(tampered) is None


def test_jwt_garbage_rejected():
    assert decode_token("garbage") is None
    assert decode_token("") is None


def test_rate_limit_allows_first_attempts():
    _login_attempts.clear()
    ip = "1.2.3.4"
    for _ in range(5):
        assert check_rate_limit(ip)
        record_login_attempt(ip)


def test_rate_limit_blocks_after_threshold():
    _login_attempts.clear()
    ip = "5.6.7.8"
    for _ in range(5):
        record_login_attempt(ip)
    assert not check_rate_limit(ip)


def test_rate_limit_separate_per_ip():
    _login_attempts.clear()
    for _ in range(5):
        record_login_attempt("9.9.9.9")
    # Une autre IP n'est pas bloquée
    assert check_rate_limit("10.10.10.10")
