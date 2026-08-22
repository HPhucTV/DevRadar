from datetime import UTC, datetime, timedelta
from uuid import UUID

from devradar.auth.service import (
    hash_password,
    hash_token,
    is_expired,
    new_token,
    normalize_username,
    owner_hash_for_subject,
    verify_password,
)


def test_password_hash_round_trip_and_wrong_password_rejection() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_password_hash_is_salted_and_malformed_hash_fails_closed() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert not verify_password("same password", "not-a-password-hash")
    assert not verify_password("same password", "pbkdf2_sha256$1$bad$bad")


def test_session_token_hashing_is_deterministic_but_tokens_are_unique() -> None:
    first = new_token()
    second = new_token()

    assert first != second
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != hash_token(second)


def test_username_and_owner_identity_are_canonical() -> None:
    subject_id = UUID("00000000-0000-0000-0000-000000000001")

    assert normalize_username("  Operator ") == "operator"
    assert owner_hash_for_subject(subject_id) == owner_hash_for_subject(subject_id)
    assert len(owner_hash_for_subject(subject_id)) == 64


def test_expiry_is_strict_and_timezone_aware() -> None:
    now = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)

    assert not is_expired(now + timedelta(seconds=1), now=now)
    assert is_expired(now, now=now)
    assert is_expired(now - timedelta(seconds=1), now=now)
