"""tests/test_repository.py — Tests du fingerprint et des helpers repository."""
from __future__ import annotations

from datetime import date

from src.storage.repository import compute_fingerprint


def test_fingerprint_stable():
    """Le fingerprint doit être stable d'un call à l'autre."""
    a = compute_fingerprint("Climate Fund Tunisia", "https://example.org/ao", date(2026, 6, 1))
    b = compute_fingerprint("Climate Fund Tunisia", "https://example.org/ao", date(2026, 6, 1))
    assert a == b


def test_fingerprint_normalizes_case():
    a = compute_fingerprint("Climate Fund Tunisia", "https://example.org/ao", None)
    b = compute_fingerprint("CLIMATE FUND TUNISIA", "https://example.org/ao", None)
    assert a == b


def test_fingerprint_strips_query_params():
    a = compute_fingerprint("X", "https://example.org/ao", None)
    b = compute_fingerprint("X", "https://example.org/ao?utm_source=email&ref=123", None)
    assert a == b


def test_fingerprint_strips_trailing_slash():
    a = compute_fingerprint("X", "https://example.org/ao", None)
    b = compute_fingerprint("X", "https://example.org/ao/", None)
    assert a == b


def test_fingerprint_changes_with_deadline():
    a = compute_fingerprint("X", "https://example.org/ao", date(2026, 1, 1))
    b = compute_fingerprint("X", "https://example.org/ao", date(2026, 6, 1))
    assert a != b


def test_fingerprint_rolling_vs_dated():
    a = compute_fingerprint("X", "https://example.org/ao", None)
    b = compute_fingerprint("X", "https://example.org/ao", date(2026, 1, 1))
    assert a != b


def test_fingerprint_length():
    fp = compute_fingerprint("Test", "https://example.org", date.today())
    assert len(fp) == 32
    assert all(c in "0123456789abcdef" for c in fp)
