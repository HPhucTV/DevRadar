from __future__ import annotations

import importlib

import pytest

from devradar.ingestion.safe_http import FetchError, FetchErrorCode, SafeHttpFetcher


def _policy_module() -> object:
    return importlib.import_module("devradar.source_recipes.policy")


def test_listing_url_keeps_bounded_search_query() -> None:
    policy = _policy_module()
    normalized = policy.normalize_listing_url(  # type: ignore[attr-defined]
        "https://example.test/jobs?q=python&page=2",
    )

    assert normalized.url == "https://example.test/jobs?q=python&page=2"
    assert normalized.origin == "https://example.test"
    assert normalized.host == "example.test"
    assert normalized.path_prefix == "/jobs"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/jobs",
        "https://user:pass@example.test/jobs",
        "https://example.test:443/jobs",
        "https://127.0.0.1/jobs",
        "https://[::1]/jobs",
        "https://example.test/jobs#results",
        "https://example.test/jobs/../admin",
        "https://example.test/jobs/%2e%2e/admin",
        "https://example.test/jobs/%252e%252e/admin",
        "https://example.test/jobs?q=%252e%252e",
        "https://example.test/công-việc",
    ],
)
def test_listing_url_rejects_unsafe_boundaries(url: str) -> None:
    policy = _policy_module()
    with pytest.raises(ValueError):
        policy.normalize_listing_url(url)  # type: ignore[attr-defined]


def test_recipe_fetch_policy_rejects_private_dns_before_transport() -> None:
    policy_module = _policy_module()
    normalized = policy_module.normalize_listing_url(  # type: ignore[attr-defined]
        "https://example.test/jobs"
    )
    fetch_policy = policy_module.build_recipe_fetch_policy(  # type: ignore[attr-defined]
        normalized,
        allowed_hosts=("example.test",),
        allowed_path_prefixes=("/jobs",),
        byte_budget=123_456,
        requests_per_minute=2,
    )
    fetcher = SafeHttpFetcher(resolver=lambda host, port: ("127.0.0.1",))

    with pytest.raises(FetchError) as captured:
        fetcher.fetch(normalized.url, fetch_policy)

    assert captured.value.code is FetchErrorCode.POLICY_BLOCKED
    assert fetch_policy.max_response_bytes == 123_456
    assert fetch_policy.requests_per_minute == 2


def test_listing_query_and_url_size_are_bounded() -> None:
    policy = _policy_module()
    too_many_parameters = "&".join(f"p{index}=x" for index in range(21))
    with pytest.raises(ValueError, match="query"):
        policy.normalize_listing_url(  # type: ignore[attr-defined]
            f"https://example.test/jobs?{too_many_parameters}"
        )
    with pytest.raises(ValueError, match="length"):
        policy.normalize_listing_url(  # type: ignore[attr-defined]
            f"https://example.test/jobs?q={'x' * 2048}"
        )
