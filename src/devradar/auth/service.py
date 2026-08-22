"""Small, dependency-free authentication primitives used by the API boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime
from uuid import UUID

AUTH_ENABLED_ENV = "DEVRADAR_AUTH_ENABLED"
OPERATOR_USERNAME_ENV = "DEVRADAR_OPERATOR_USERNAME"
OPERATOR_PASSWORD_HASH_ENV = "DEVRADAR_OPERATOR_PASSWORD_HASH"
SESSION_TTL_ENV = "DEVRADAR_AUTH_SESSION_TTL_SECONDS"
AUTH_COOKIE_SECURE_ENV = "DEVRADAR_AUTH_COOKIE_SECURE"
ALLOWED_ORIGINS_ENV = "DEVRADAR_ALLOWED_ORIGINS"
SESSION_COOKIE = "devradar_session"
CSRF_COOKIE = "devradar_csrf"
CSRF_HEADER = "X-DevRadar-CSRF"
DEFAULT_SESSION_TTL_SECONDS = 86_400
MIN_SESSION_TTL_SECONDS = 300
MAX_SESSION_TTL_SECONDS = 7 * 86_400
PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_HASH_BYTES = 32
PASSWORD_SALT_BYTES = 16
TOKEN_BYTES = 32
_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def auth_enabled() -> bool:
    return os.environ.get(AUTH_ENABLED_ENV, "false").casefold() == "true"


def operator_bootstrap() -> tuple[str, str]:
    """Return normalized bootstrap identity and its precomputed password hash."""

    username = normalize_username(os.environ.get(OPERATOR_USERNAME_ENV, "operator"))
    password_hash = os.environ.get(OPERATOR_PASSWORD_HASH_ENV, "").strip()
    if not password_hash or not password_hash.startswith(f"{PASSWORD_HASH_PREFIX}$"):
        raise ValueError(f"{OPERATOR_PASSWORD_HASH_ENV} must contain a valid password hash")
    return username, password_hash


def session_ttl_seconds() -> int:
    raw = os.environ.get(SESSION_TTL_ENV, str(DEFAULT_SESSION_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{SESSION_TTL_ENV} must be an integer") from error
    if not MIN_SESSION_TTL_SECONDS <= value <= MAX_SESSION_TTL_SECONDS:
        raise ValueError(f"{SESSION_TTL_ENV} is outside the allowed range")
    return value


def cookie_secure() -> bool:
    return os.environ.get(AUTH_COOKIE_SECURE_ENV, "false").casefold() == "true"


def allowed_origins() -> frozenset[str]:
    raw = os.environ.get(ALLOWED_ORIGINS_ENV, "http://127.0.0.1:3000,http://localhost:3000")
    return frozenset(value.strip().rstrip("/") for value in raw.split(",") if value.strip())


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("encoded value is malformed")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    """Return a salted, versioned PBKDF2 password hash."""

    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ValueError("password must contain 1..1024 characters")
    if iterations < 100_000:
        raise ValueError("password hash iterations are too low")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=PASSWORD_HASH_BYTES
    )
    return f"{PASSWORD_HASH_PREFIX}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without revealing malformed-hash details."""

    try:
        prefix, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        iterations = int(raw_iterations)
        if prefix != PASSWORD_HASH_PREFIX or iterations < 100_000:
            return False
        salt = _b64decode(raw_salt)
        expected = _b64decode(raw_digest)
        if len(salt) != PASSWORD_SALT_BYTES or len(expected) != PASSWORD_HASH_BYTES:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=PASSWORD_HASH_BYTES
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def new_token() -> str:
    """Return a URL-safe opaque token suitable for a cookie or CSRF value."""

    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the only durable representation allowed for an opaque token."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_username(value: str) -> str:
    """Normalize a login identifier and reject unsafe/ambiguous values."""

    normalized = value.strip().casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("username must be 3..64 lowercase ASCII characters")
    return normalized


def owner_hash_for_subject(subject_id: UUID) -> str:
    """Derive the stable owner scope used by existing profile/match rows."""

    return hashlib.sha256(f"devradar-owner:{subject_id}".encode("ascii")).hexdigest()


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """Return true at the expiry boundary; all timestamps must be timezone-aware."""

    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return expires_at <= effective_now
