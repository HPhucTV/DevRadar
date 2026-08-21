"""HTTPS-only fetcher with pinned DNS, SSRF controls, and bounded responses."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from threading import Lock
from types import MappingProxyType
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from devradar.ingestion.contracts import FetchResult
from devradar.ingestion.source_registry import FetchPolicy

Resolver = Callable[[str, int], tuple[str, ...]]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


class FetchErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    POLICY_BLOCKED = "policy_blocked"
    DNS_FAILURE = "dns_failure"
    NETWORK_TIMEOUT = "network_timeout"
    TLS_FAILURE = "tls_failure"
    NETWORK_ERROR = "network_error"
    REDIRECT_BLOCKED = "redirect_blocked"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    RESPONSE_TOO_LARGE = "response_too_large"
    UNEXPECTED_CONTENT = "unexpected_content"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    HTTP_ERROR = "http_error"


class FetchError(Exception):
    def __init__(
        self,
        code: FetchErrorCode,
        safe_summary: str,
        *,
        retryable: bool,
        http_status: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.retryable = retryable
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class TransportRequest:
    host: str
    port: int
    target: str
    addresses: tuple[str, ...]
    headers: Mapping[str, str]
    timeout_seconds: float
    max_response_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    payload: bytes

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "headers",
            MappingProxyType({key.lower(): value for key, value in self.headers.items()}),
        )


Transport = Callable[[TransportRequest], TransportResponse]


def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(sorted({str(record[4][0]) for record in records}))


def _socket_address(address: str, port: int) -> tuple[str, int] | tuple[str, int, int, int]:
    parsed = ipaddress.ip_address(address)
    if parsed.version == 6:
        return address, port, 0, 0
    return address, port


def send_https_request(request: TransportRequest) -> TransportResponse:
    request_bytes = (
        f"GET {request.target} HTTP/1.1\r\n"
        + "".join(f"{name}: {value}\r\n" for name, value in request.headers.items())
        + "\r\n"
    ).encode("ascii")
    tls_context = ssl.create_default_context()
    last_error: OSError | ssl.SSLError | None = None

    for address in request.addresses:
        family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as raw_socket:
                raw_socket.settimeout(request.timeout_seconds)
                raw_socket.connect(_socket_address(address, request.port))
                with tls_context.wrap_socket(
                    raw_socket,
                    server_hostname=request.host,
                ) as tls_socket:
                    tls_socket.settimeout(request.timeout_seconds)
                    tls_socket.sendall(request_bytes)
                    response = http.client.HTTPResponse(tls_socket, method="GET")
                    response.begin()
                    headers = {key.lower(): value for key, value in response.getheaders()}
                    payload = response.read(request.max_response_bytes + 1)
                    return TransportResponse(
                        status=response.status,
                        headers=headers,
                        payload=payload,
                    )
        except (OSError, ssl.SSLError) as error:
            last_error = error

    if last_error is not None:
        raise last_error
    raise OSError("No validated address was available")


def _path_is_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if prefix.endswith("/") and path.startswith(prefix):
            return True
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _validate_target(url: str, policy: FetchPolicy) -> tuple[str, SplitResult]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Fetch URL is invalid.",
            retryable=False,
        ) from error

    host = parsed.hostname.lower() if parsed.hostname else None
    if (
        parsed.scheme != "https"
        or host is None
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Fetch URL must be HTTPS without user info, custom port, or fragment.",
            retryable=False,
        )
    if host not in policy.allowed_hosts or not _path_is_allowed(
        parsed.path or "/", policy.allowed_path_prefixes
    ):
        raise FetchError(
            FetchErrorCode.POLICY_BLOCKED,
            "Fetch URL is outside the approved source boundary.",
            retryable=False,
        )

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    try:
        encoded_target = target.encode("ascii")
    except UnicodeEncodeError as error:
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Fetch URL path and query must be percent-encoded ASCII.",
            retryable=False,
        ) from error
    if any(byte <= 32 or byte == 127 for byte in encoded_target):
        raise FetchError(
            FetchErrorCode.INVALID_URL,
            "Fetch URL contains unsafe control or whitespace characters.",
            retryable=False,
        )

    normalized_url = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    return normalized_url, parsed


def validate_fetch_target(url: str, policy: FetchPolicy) -> str:
    """Return the normalized URL when it is inside the approved fetch boundary."""

    return _validate_target(url, policy)[0]


def _validate_public_addresses(addresses: tuple[str, ...]) -> tuple[str, ...]:
    if not addresses:
        raise FetchError(
            FetchErrorCode.DNS_FAILURE,
            "Approved source host did not resolve.",
            retryable=True,
        )
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise FetchError(
                FetchErrorCode.DNS_FAILURE,
                "Approved source host returned an invalid address.",
                retryable=True,
            ) from error
        if not parsed.is_global:
            raise FetchError(
                FetchErrorCode.POLICY_BLOCKED,
                "Approved source host resolved to a private or reserved address.",
                retryable=False,
            )
    return addresses


def _retry_after_seconds(headers: Mapping[str, str]) -> int | None:
    value = headers.get("retry-after", "").strip()
    if not value.isdigit():
        return None
    seconds = int(value)
    return seconds if 0 <= seconds <= 3600 else None


class SafeHttpFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = resolve_addresses,
        transport: Transport = send_https_request,
        clock: Clock = time.monotonic,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._clock = clock
        self._sleeper = sleeper
        self._next_request_at: dict[str, float] = {}
        self._request_lock = Lock()

    def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        with self._request_lock:
            return self._fetch_serialized(url, policy)

    def _fetch_serialized(self, url: str, policy: FetchPolicy) -> FetchResult:
        current_url = url
        redirect_count = 0

        while True:
            try:
                normalized_url, parsed = _validate_target(current_url, policy)
            except FetchError as error:
                if redirect_count:
                    raise FetchError(
                        FetchErrorCode.REDIRECT_BLOCKED,
                        "Redirect target is outside the approved source boundary.",
                        retryable=False,
                    ) from error
                raise

            host = parsed.hostname.lower() if parsed.hostname else ""
            self._wait_for_slot(host, policy)
            addresses = self._resolve_and_validate(host)
            target = parsed.path or "/"
            if parsed.query:
                target = f"{target}?{parsed.query}"
            request = TransportRequest(
                host=host,
                port=443,
                target=target,
                addresses=addresses,
                headers={
                    "Host": host,
                    "User-Agent": policy.user_agent,
                    "Accept": ", ".join(policy.content_types),
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
                timeout_seconds=float(policy.timeout_seconds),
                max_response_bytes=policy.max_response_bytes,
            )
            response = self._send(request)

            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise FetchError(
                        FetchErrorCode.REDIRECT_BLOCKED,
                        "Redirect response did not include a target.",
                        retryable=False,
                        http_status=response.status,
                    )
                if redirect_count >= policy.redirect_limit:
                    raise FetchError(
                        FetchErrorCode.TOO_MANY_REDIRECTS,
                        "Approved source exceeded its redirect limit.",
                        retryable=False,
                        http_status=response.status,
                    )
                redirect_count += 1
                current_url = urljoin(normalized_url, location)
                continue

            return self._validate_response(normalized_url, response, policy)

    def _resolve_and_validate(self, host: str) -> tuple[str, ...]:
        try:
            addresses = self._resolver(host, 443)
        except socket.gaierror as error:
            raise FetchError(
                FetchErrorCode.DNS_FAILURE,
                "Approved source host could not be resolved.",
                retryable=True,
            ) from error
        return _validate_public_addresses(addresses)

    def _send(self, request: TransportRequest) -> TransportResponse:
        try:
            return self._transport(request)
        except TimeoutError as error:
            raise FetchError(
                FetchErrorCode.NETWORK_TIMEOUT,
                "Approved source request timed out.",
                retryable=True,
            ) from error
        except ssl.SSLError as error:
            raise FetchError(
                FetchErrorCode.TLS_FAILURE,
                "Approved source TLS validation failed.",
                retryable=False,
            ) from error
        except OSError as error:
            raise FetchError(
                FetchErrorCode.NETWORK_ERROR,
                "Approved source network request failed.",
                retryable=True,
            ) from error

    def _wait_for_slot(self, host: str, policy: FetchPolicy) -> None:
        intervals = []
        if policy.requests_per_minute is not None:
            intervals.append(60.0 / policy.requests_per_minute)
        if policy.minimum_action_interval_seconds is not None:
            intervals.append(float(policy.minimum_action_interval_seconds))
        interval = max(intervals)
        now = self._clock()
        delay = max(0.0, self._next_request_at.get(host, now) - now)
        if delay:
            self._sleeper(delay)
        self._next_request_at[host] = now + delay + interval

    def _validate_response(
        self,
        final_url: str,
        response: TransportResponse,
        policy: FetchPolicy,
    ) -> FetchResult:
        if response.status == 429:
            raise FetchError(
                FetchErrorCode.RATE_LIMITED,
                "Approved source rate limited the request.",
                retryable=True,
                http_status=response.status,
                retry_after_seconds=_retry_after_seconds(response.headers),
            )
        if 500 <= response.status <= 599:
            raise FetchError(
                FetchErrorCode.SERVER_ERROR,
                "Approved source returned a server error.",
                retryable=True,
                http_status=response.status,
            )
        if not 200 <= response.status <= 299:
            raise FetchError(
                FetchErrorCode.HTTP_ERROR,
                "Approved source returned a non-success status.",
                retryable=False,
                http_status=response.status,
            )

        content_length = response.headers.get("content-length")
        if content_length:
            if not content_length.isdigit():
                raise FetchError(
                    FetchErrorCode.UNEXPECTED_CONTENT,
                    "Approved source returned an invalid Content-Length.",
                    retryable=False,
                    http_status=response.status,
                )
            if int(content_length) > policy.max_response_bytes:
                raise FetchError(
                    FetchErrorCode.RESPONSE_TOO_LARGE,
                    "Approved source response exceeded the byte limit.",
                    retryable=False,
                    http_status=response.status,
                )
        if len(response.payload) > policy.max_response_bytes:
            raise FetchError(
                FetchErrorCode.RESPONSE_TOO_LARGE,
                "Approved source response exceeded the byte limit.",
                retryable=False,
                http_status=response.status,
            )

        content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise FetchError(
                FetchErrorCode.UNEXPECTED_CONTENT,
                "Approved source returned unsupported content encoding.",
                retryable=False,
                http_status=response.status,
            )
        content_type = response.headers.get("content-type", "").strip()
        mime_type = content_type.split(";", 1)[0].strip().lower()
        if mime_type not in {value.lower() for value in policy.content_types}:
            raise FetchError(
                FetchErrorCode.UNEXPECTED_CONTENT,
                "Approved source returned an unapproved content type.",
                retryable=False,
                http_status=response.status,
            )

        return FetchResult(
            final_url=final_url,
            fetched_at=datetime.now(UTC),
            http_status=response.status,
            content_type=content_type,
            payload=response.payload,
            raw_content_hash=sha256(response.payload).hexdigest(),
        )
