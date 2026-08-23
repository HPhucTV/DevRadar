"""Bounded URL and response policy for owner-local custom sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from devradar.custom_sources.models import (
    CustomSourceProfileDraft,
    host_is_ip_literal,
    path_has_unsafe_boundary_syntax,
)
from devradar.ingestion.safe_http import FetchError, FetchErrorCode
from devradar.ingestion.source_registry import FetchPolicy


class CustomFetchOutcome(StrEnum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    PERMISSION_REQUIRED = "permission_required"
    CHALLENGE = "challenge"
    UNSUPPORTED_CONTENT = "unsupported_content"
    POLICY_BLOCKED = "policy_blocked"


@dataclass(frozen=True, slots=True)
class CustomResponseClassification:
    outcome: CustomFetchOutcome
    retryable: bool
    safe_reason: str


_CHALLENGE_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify your browser",
    "cloudflare challenge",
    "checking your browser",
    "bot detection",
)
_PERMISSION_MARKERS = (
    "sign in to continue",
    "log in to continue",
    "login required",
    "subscription required",
    "paywall",
    "access denied",
)
_ALLOWED_CONTENT_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "application/json", "application/ld+json"}
)


def _path_is_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        path == prefix
        or path.startswith(f"{prefix}/")
        or (prefix.endswith("/") and path.startswith(prefix))
        for prefix in prefixes
    )


def validate_custom_target(url: str, policy: FetchPolicy) -> str:
    """Normalize a profile URL and reject port/host/path escapes before DNS."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Custom source URL is invalid.",
            retryable=False,
        ) from error
    host = parsed.hostname.casefold() if parsed.hostname else None
    if (
        parsed.scheme.casefold() != "https"
        or host is None
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.fragment
        or host_is_ip_literal(host)
    ):
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Custom source URL must be HTTPS without user info, custom port, or fragment.",
            retryable=False,
        )
    path = parsed.path or "/"
    if path_has_unsafe_boundary_syntax(path):
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Custom source URL path has unsafe boundary syntax.",
            retryable=False,
        )
    if host not in policy.allowed_hosts or not _path_is_allowed(path, policy.allowed_path_prefixes):
        raise FetchError(
            FetchErrorCode.POLICY_BLOCKED,
            "Custom source URL is outside its saved host/path boundary.",
            retryable=False,
        )
    target = urlunsplit(("https", host, path, parsed.query, ""))
    try:
        encoded = target.encode("ascii")
    except UnicodeEncodeError as error:
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Custom source URL must use percent-encoded ASCII path and query.",
            retryable=False,
        ) from error
    if any(byte <= 32 or byte == 127 for byte in encoded):
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Custom source URL contains unsafe control or whitespace characters.",
            retryable=False,
        )
    return target


def build_custom_fetch_policy(profile: CustomSourceProfileDraft) -> FetchPolicy:
    """Build the transport policy only from persisted, validated profile values."""

    return FetchPolicy(
        allowed_hosts=tuple(profile.allowed_hosts),
        allowed_path_prefixes=tuple(profile.allowed_path_prefixes),
        content_types=(
            "text/html",
            "application/xhtml+xml",
            "application/json",
            "application/ld+json",
        ),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=profile.byte_budget,
        requests_per_minute=profile.requests_per_minute,
    )


def classify_custom_response(
    status: int,
    content_type: str,
    body_prefix: bytes,
) -> CustomResponseClassification:
    """Return safe retry semantics without exposing response text."""

    body = body_prefix[:8192].decode("utf-8", errors="ignore").casefold()
    if any(marker in body for marker in _CHALLENGE_MARKERS):
        return CustomResponseClassification(
            CustomFetchOutcome.CHALLENGE,
            retryable=False,
            safe_reason="permission_required",
        )
    if status in {401, 402, 403} or any(marker in body for marker in _PERMISSION_MARKERS):
        return CustomResponseClassification(
            CustomFetchOutcome.PERMISSION_REQUIRED,
            retryable=False,
            safe_reason="permission_required",
        )
    if status == 429:
        return CustomResponseClassification(
            CustomFetchOutcome.RATE_LIMITED,
            retryable=True,
            safe_reason="rate_limited",
        )
    if not 200 <= status <= 299:
        return CustomResponseClassification(
            CustomFetchOutcome.POLICY_BLOCKED,
            retryable=False,
            safe_reason="unexpected_http_status",
        )
    mime_type = content_type.split(";", 1)[0].strip().casefold()
    if mime_type not in _ALLOWED_CONTENT_TYPES:
        return CustomResponseClassification(
            CustomFetchOutcome.UNSUPPORTED_CONTENT,
            retryable=False,
            safe_reason="unsupported_content",
        )
    return CustomResponseClassification(
        CustomFetchOutcome.SUCCESS,
        retryable=False,
        safe_reason="success",
    )
