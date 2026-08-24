"""URL and outbound request policy for owner-local source recipes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from devradar.ingestion.source_registry import FetchPolicy
from devradar.source_recipes.models import SourceRecipeError

_HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_INVALID_PERCENT_PATTERN = re.compile(r"%(?![0-9a-fA-F]{2})")
_ENCODED_PATH_BOUNDARY_PATTERN = re.compile(r"%(?:25|2e|2f|5c)", re.IGNORECASE)
_NESTED_PERCENT_PATTERN = re.compile(r"%25", re.IGNORECASE)
_MAX_URL_LENGTH = 2048
_MAX_QUERY_LENGTH = 1024
_MAX_QUERY_FIELDS = 20


@dataclass(frozen=True, slots=True)
class NormalizedListingUrl:
    url: str
    origin: str
    host: str
    path_prefix: str


def _is_ip_literal(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _has_dot_segments(value: str) -> bool:
    decoded = value
    for _ in range(len(value) + 1):
        normalized = decoded.replace("\\", "/")
        if any(segment in {".", ".."} for segment in normalized.split("/")):
            return True
        next_value = unquote(decoded)
        if next_value == decoded:
            return False
        decoded = next_value
    return True


def _require_safe_ascii(value: str, *, code: str) -> None:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        raise SourceRecipeError(code) from error
    if any(byte <= 32 or byte == 127 for byte in encoded):
        raise SourceRecipeError(code)
    if _INVALID_PERCENT_PATTERN.search(value):
        raise SourceRecipeError(code)


def normalize_allowed_host(value: str) -> str:
    host = value.strip().casefold().rstrip(".")
    if not host or "." not in host or not _HOST_PATTERN.fullmatch(host) or _is_ip_literal(host):
        raise SourceRecipeError("allowed_hosts_invalid")
    return host


def normalize_path_prefix(value: str) -> str:
    prefix = value.strip()
    _require_safe_ascii(prefix, code="allowed_path_prefix_invalid")
    if (
        not prefix.startswith("/")
        or "//" in prefix
        or "?" in prefix
        or "#" in prefix
        or _ENCODED_PATH_BOUNDARY_PATTERN.search(prefix)
        or _has_dot_segments(prefix)
    ):
        raise SourceRecipeError("allowed_path_prefix_invalid")
    return prefix.rstrip("/") or "/"


def normalize_listing_url(value: str) -> NormalizedListingUrl:
    raw = value.strip()
    if not raw or len(raw) > _MAX_URL_LENGTH:
        raise SourceRecipeError("listing_url_length_invalid")
    _require_safe_ascii(raw, code="listing_url_invalid")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise SourceRecipeError("listing_url_invalid") from error

    host = parsed.hostname.casefold().rstrip(".") if parsed.hostname else ""
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise SourceRecipeError("listing_url_invalid")
    host = normalize_allowed_host(host)

    path = parsed.path or "/"
    if "//" in path or _ENCODED_PATH_BOUNDARY_PATTERN.search(path) or _has_dot_segments(path):
        raise SourceRecipeError("listing_url_path_invalid")
    path_prefix = normalize_path_prefix(path)

    query = parsed.query
    if len(query) > _MAX_QUERY_LENGTH or _NESTED_PERCENT_PATTERN.search(query):
        raise SourceRecipeError("listing_url_query_invalid")
    _require_safe_ascii(query, code="listing_url_query_invalid")
    try:
        parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=_MAX_QUERY_FIELDS,
            separator="&",
        )
    except ValueError as error:
        raise SourceRecipeError("listing_url_query_invalid") from error

    origin = f"https://{host}"
    normalized = urlunsplit(("https", host, path_prefix, query, ""))
    return NormalizedListingUrl(
        url=normalized,
        origin=origin,
        host=host,
        path_prefix=path_prefix,
    )


def build_recipe_fetch_policy(
    normalized: NormalizedListingUrl,
    *,
    allowed_hosts: tuple[str, ...],
    allowed_path_prefixes: tuple[str, ...],
    byte_budget: int,
    requests_per_minute: int,
) -> FetchPolicy:
    if normalized.host not in allowed_hosts:
        raise SourceRecipeError("allowed_hosts_missing_listing_host")
    return FetchPolicy(
        allowed_hosts=allowed_hosts,
        allowed_path_prefixes=allowed_path_prefixes,
        content_types=(
            "text/html",
            "application/xhtml+xml",
            "application/json",
            "application/ld+json",
        ),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=byte_budget,
        requests_per_minute=requests_per_minute,
    )
