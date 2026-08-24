from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from hashlib import sha256

import pytest

from devradar.ingestion.safe_http import (
    FetchError,
    FetchErrorCode,
    SafeHttpFetcher,
    TransportRequest,
    TransportResponse,
)
from devradar.ingestion.source_registry import FetchPolicy

PUBLIC_ADDRESS = "8.8.8.8"
HTML_POLICY = FetchPolicy(
    allowed_hosts=("career.vng.com.vn",),
    allowed_path_prefixes=("/tim-kiem-viec-lam",),
    content_types=("text/html",),
    timeout_seconds=20,
    redirect_limit=3,
    max_response_bytes=2_000_000,
    requests_per_minute=6,
)
JSON_POLICY = FetchPolicy(
    allowed_hosts=("boards-api.greenhouse.io",),
    allowed_path_prefixes=("/v1/boards/navervietnam/jobs",),
    content_types=("application/json",),
    timeout_seconds=20,
    redirect_limit=3,
    max_response_bytes=2_000_000,
    requests_per_minute=10,
)


class SequenceTransport:
    def __init__(self, results: Iterable[TransportResponse | BaseException]) -> None:
        self._results = iter(results)
        self.requests: list[TransportRequest] = []

    def __call__(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        result = next(self._results)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _response(
    *,
    status: int = 200,
    content_type: str = "application/json; charset=utf-8",
    payload: bytes = b'{"jobs": []}',
    headers: dict[str, str] | None = None,
) -> TransportResponse:
    response_headers = {"content-type": content_type, "content-length": str(len(payload))}
    if headers:
        response_headers.update(headers)
    return TransportResponse(status=status, headers=response_headers, payload=payload)


def _fetcher(transport: SequenceTransport, *, fake_time: FakeTime | None = None) -> SafeHttpFetcher:
    time_source = fake_time or FakeTime()
    return SafeHttpFetcher(
        resolver=lambda host, port: (PUBLIC_ADDRESS,),
        transport=transport,
        clock=time_source.clock,
        sleeper=time_source.sleep,
    )


def test_fetch_success_pins_validated_address_and_hashes_bounded_payload() -> None:
    transport = SequenceTransport((_response(),))
    fetcher = _fetcher(transport)
    policy = JSON_POLICY

    result = fetcher.fetch(
        "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true",
        policy,
    )

    assert result.raw_content_hash == sha256(result.payload).hexdigest()
    assert result.final_url == (
        "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs?content=true"
    )
    assert transport.requests[0].addresses == (PUBLIC_ADDRESS,)
    assert transport.requests[0].headers["Accept-Encoding"] == "identity"
    assert transport.requests[0].headers["User-Agent"] == policy.user_agent


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        (PUBLIC_ADDRESS, "169.254.169.254"),
        ("::1",),
    ],
)
def test_private_reserved_or_mixed_dns_answers_fail_before_transport(
    addresses: tuple[str, ...],
) -> None:
    transport = SequenceTransport(())
    fetcher = SafeHttpFetcher(
        resolver=lambda host, port: addresses,
        transport=transport,
    )

    with pytest.raises(FetchError) as captured:
        fetcher.fetch(
            "https://career.vng.com.vn/tim-kiem-viec-lam",
            HTML_POLICY,
        )

    assert captured.value.code is FetchErrorCode.POLICY_BLOCKED
    assert transport.requests == []


def test_redirect_is_revalidated_and_cannot_escape_allow_list() -> None:
    transport = SequenceTransport(
        (
            _response(
                status=302,
                payload=b"",
                headers={"location": "https://attacker.test/metadata"},
            ),
        )
    )

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch(
            "https://career.vng.com.vn/tim-kiem-viec-lam",
            HTML_POLICY,
        )

    assert captured.value.code is FetchErrorCode.REDIRECT_BLOCKED
    assert len(transport.requests) == 1


def test_redirect_limit_is_enforced() -> None:
    transport = SequenceTransport(
        (_response(status=302, payload=b"", headers={"location": "/tim-kiem-viec-lam"}),)
    )
    policy = replace(HTML_POLICY, redirect_limit=0)

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch("https://career.vng.com.vn/tim-kiem-viec-lam", policy)

    assert captured.value.code is FetchErrorCode.TOO_MANY_REDIRECTS


def test_successful_redirect_chain_is_preserved_without_response_body() -> None:
    transport = SequenceTransport(
        (
            _response(status=302, payload=b"", headers={"location": "/jobs/final"}),
            _response(content_type="text/html", payload=b"<html></html>"),
        )
    )
    policy = replace(HTML_POLICY, allowed_path_prefixes=("/jobs",))

    result = _fetcher(transport).fetch("https://career.vng.com.vn/jobs", policy)

    assert result.final_url == "https://career.vng.com.vn/jobs/final"
    assert result.redirect_chain == ("https://career.vng.com.vn/jobs/final",)


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_response(content_type="application/octet-stream"), FetchErrorCode.UNEXPECTED_CONTENT),
        (
            _response(headers={"content-encoding": "gzip"}),
            FetchErrorCode.UNEXPECTED_CONTENT,
        ),
        (
            _response(headers={"content-length": "9999999"}),
            FetchErrorCode.RESPONSE_TOO_LARGE,
        ),
    ],
)
def test_content_type_encoding_and_declared_size_are_bounded(
    response: TransportResponse, expected_code: FetchErrorCode
) -> None:
    transport = SequenceTransport((response,))

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch(
            "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs",
            JSON_POLICY,
        )

    assert captured.value.code is expected_code


def test_streamed_payload_size_is_bounded_even_without_content_length() -> None:
    policy = replace(JSON_POLICY, max_response_bytes=4)
    transport = SequenceTransport(
        (
            TransportResponse(
                status=200,
                headers={"content-type": "application/json"},
                payload=b"12345",
            ),
        )
    )

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch(
            "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs",
            policy,
        )

    assert captured.value.code is FetchErrorCode.RESPONSE_TOO_LARGE


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable"),
    [
        (429, FetchErrorCode.RATE_LIMITED, True),
        (503, FetchErrorCode.SERVER_ERROR, True),
        (404, FetchErrorCode.HTTP_ERROR, False),
    ],
)
def test_http_failures_have_stable_safe_semantics(
    status: int, expected_code: FetchErrorCode, retryable: bool
) -> None:
    transport = SequenceTransport((_response(status=status, headers={"retry-after": "120"}),))

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch(
            "https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs",
            JSON_POLICY,
        )

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    if status == 429:
        assert captured.value.retry_after_seconds == 120
    assert "boards-api" not in captured.value.safe_summary


def test_timeout_is_sanitized_and_retryable() -> None:
    transport = SequenceTransport((TimeoutError("socket detail must not leak"),))

    with pytest.raises(FetchError) as captured:
        _fetcher(transport).fetch(
            "https://career.vng.com.vn/tim-kiem-viec-lam",
            HTML_POLICY,
        )

    assert captured.value.code is FetchErrorCode.NETWORK_TIMEOUT
    assert captured.value.retryable is True
    assert "socket detail" not in captured.value.safe_summary


def test_path_outside_approved_prefix_fails_before_dns() -> None:
    resolver_called = False

    def resolver(host: str, port: int) -> tuple[str, ...]:
        nonlocal resolver_called
        resolver_called = True
        return (PUBLIC_ADDRESS,)

    with pytest.raises(FetchError) as captured:
        SafeHttpFetcher(resolver=resolver).fetch(
            "https://career.vng.com.vn/admin",
            HTML_POLICY,
        )

    assert captured.value.code is FetchErrorCode.POLICY_BLOCKED
    assert resolver_called is False


def test_source_throttle_is_applied_between_requests() -> None:
    fake_time = FakeTime()
    transport = SequenceTransport((_response(content_type="text/html"),) * 2)
    fetcher = _fetcher(transport, fake_time=fake_time)
    url = "https://career.vng.com.vn/tim-kiem-viec-lam"

    fetcher.fetch(url, HTML_POLICY)
    fetcher.fetch(url, HTML_POLICY)

    assert fake_time.sleeps == [10.0]
    assert len(transport.requests) == 2


def test_fetch_policy_stays_concurrency_one() -> None:
    policy: FetchPolicy = HTML_POLICY
    assert policy.concurrency == 1
