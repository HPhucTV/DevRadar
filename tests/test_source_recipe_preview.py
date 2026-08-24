from __future__ import annotations

import importlib

import pytest

from devradar.ingestion.safe_http import FetchError, FetchErrorCode


def _preview() -> object:
    return importlib.import_module("devradar.source_recipes.preview")


@pytest.mark.parametrize(
    ("error", "expected_code", "blocked"),
    [
        (
            FetchError(
                FetchErrorCode.HTTP_ERROR,
                "safe",
                retryable=False,
                http_status=401,
            ),
            "access_denied",
            True,
        ),
        (
            FetchError(
                FetchErrorCode.HTTP_ERROR,
                "safe",
                retryable=False,
                http_status=402,
            ),
            "payment_required",
            True,
        ),
        (
            FetchError(
                FetchErrorCode.HTTP_ERROR,
                "safe",
                retryable=False,
                http_status=403,
            ),
            "access_denied",
            True,
        ),
        (
            FetchError(FetchErrorCode.POLICY_BLOCKED, "safe", retryable=False),
            "route_policy_blocked",
            True,
        ),
        (
            FetchError(FetchErrorCode.SERVER_ERROR, "safe", retryable=True, http_status=503),
            "server_error",
            False,
        ),
    ],
)
def test_fetch_errors_have_safe_recipe_disposition(
    error: FetchError,
    expected_code: str,
    blocked: bool,
) -> None:
    preview = _preview()
    disposition = preview.classify_preview_fetch_error(error)  # type: ignore[attr-defined]
    assert disposition.error_code == expected_code
    assert disposition.blocked is blocked
    assert "safe" not in repr(disposition)


def test_rate_limit_uses_bounded_cooldown() -> None:
    preview = _preview()
    disposition = preview.classify_preview_fetch_error(  # type: ignore[attr-defined]
        FetchError(
            FetchErrorCode.RATE_LIMITED,
            "safe",
            retryable=True,
            http_status=429,
            retry_after_seconds=120,
        )
    )
    assert disposition.error_code == "rate_limited"
    assert disposition.blocked is False
    assert disposition.cooldown_seconds == 120
