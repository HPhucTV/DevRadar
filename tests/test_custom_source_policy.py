from __future__ import annotations

import pytest

from devradar.custom_sources.models import CustomParserMode, CustomSourceProfileDraft
from devradar.custom_sources.policy import (
    CustomFetchOutcome,
    build_custom_fetch_policy,
    classify_custom_response,
    validate_custom_target,
)
from devradar.ingestion.safe_http import (
    FetchError,
    FetchErrorCode,
    SafeHttpFetcher,
    TransportResponse,
)


def _draft(**overrides: object) -> CustomSourceProfileDraft:
    values: dict[str, object] = {
        "name": "Example",
        "base_url": "https://example.test/jobs",
        "permission_acknowledged": True,
        "parser_mode": CustomParserMode.AUTO,
    }
    values.update(overrides)
    return CustomSourceProfileDraft.from_input(**values)  # type: ignore[arg-type]


def test_custom_policy_rejects_private_dns_and_path_escape() -> None:
    draft = _draft()
    policy = build_custom_fetch_policy(draft)
    fetcher = SafeHttpFetcher(resolver=lambda host, port: ("127.0.0.1",))

    with pytest.raises(FetchError) as captured:
        fetcher.fetch(draft.base_url, policy)
    assert captured.value.code is FetchErrorCode.POLICY_BLOCKED

    with pytest.raises(FetchError) as captured:
        validate_custom_target("https://example.test/admin", policy)
    assert captured.value.code is FetchErrorCode.POLICY_BLOCKED


def test_custom_policy_revalidates_redirect_host_and_path() -> None:
    draft = _draft()
    policy = build_custom_fetch_policy(draft)
    calls = 0

    def transport(request: object) -> TransportResponse:
        nonlocal calls
        calls += 1
        return TransportResponse(
            status=302,
            headers={"location": "https://example.test/admin"},
            payload=b"",
        )

    with pytest.raises(FetchError) as captured:
        SafeHttpFetcher(
            resolver=lambda host, port: ("8.8.8.8",),
            transport=transport,
        ).fetch(draft.base_url, policy)
    assert captured.value.code is FetchErrorCode.REDIRECT_BLOCKED
    assert calls == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/jobs",
        "https://user:pass@example.test/jobs",
        "https://example.test:443/jobs",
        "https://example.test/jobs#section",
    ],
)
def test_custom_policy_rejects_user_info_custom_port_and_non_https(url: str) -> None:
    policy = build_custom_fetch_policy(_draft())
    with pytest.raises(FetchError) as captured:
        validate_custom_target(url, policy)
    assert captured.value.code is FetchErrorCode.INVALID_URL


def test_challenge_response_is_permission_required_and_not_transient() -> None:
    result = classify_custom_response(403, "text/html", b"Please complete the CAPTCHA")
    assert result.outcome is CustomFetchOutcome.CHALLENGE
    assert result.retryable is False
    assert result.safe_reason == "permission_required"

    result = classify_custom_response(401, "text/html", b"Sign in to continue")
    assert result.outcome is CustomFetchOutcome.PERMISSION_REQUIRED
    assert result.retryable is False


def test_policy_limits_are_derived_from_persisted_profile() -> None:
    draft = _draft(page_budget=4, item_budget=25, byte_budget=123_456, requests_per_minute=3)
    policy = build_custom_fetch_policy(draft)
    assert policy.allowed_hosts == ("example.test",)
    assert policy.allowed_path_prefixes == ("/jobs",)
    assert policy.max_response_bytes == 123_456
    assert policy.requests_per_minute == 3
    assert policy.redirect_limit == 3
