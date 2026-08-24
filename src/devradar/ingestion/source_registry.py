"""Validated fetch policy and source configuration contracts."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit

from devradar.ingestion.models import SourceApprovalStatus

_SOURCE_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ADAPTER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_USER_AGENT = "DevRadar/0.1 (+https://github.com/HPhucTV/DevRadar)"


class DiscoveryMode(StrEnum):
    SERVER_RENDERED_HTML = "server_rendered_html"
    PUBLIC_JSON_API = "public_json_api"
    BROWSER_PUBLIC_UI = "browser_public_ui"


class PolicyScope(StrEnum):
    APPROVED_LOCAL_NONCOMMERCIAL_SPIKE = "approved_local_noncommercial_spike"
    PERMISSION_REQUIRED = "permission_required"


class IdentityStrategy(StrEnum):
    EXTERNAL_ID = "external_id"


@dataclass(frozen=True, slots=True)
class PolicyReview:
    scope: PolicyScope
    robots_reviewed_at: date
    terms_reviewed_at: date
    next_review_at: date

    def __post_init__(self) -> None:
        if self.next_review_at <= max(self.robots_reviewed_at, self.terms_reviewed_at):
            raise ValueError("next_review_at must be after completed policy reviews")


def _validate_host(host: str) -> None:
    if host != host.lower() or not host or "://" in host or "/" in host or ":" in host:
        raise ValueError(f"invalid host: {host!r}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if urlsplit(f"//{host}").hostname != host or "." not in host:
            raise ValueError(f"invalid host: {host!r}") from None
    else:
        raise ValueError("source allow-list must use reviewed hostnames, not IP literals")


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    content_types: tuple[str, ...]
    timeout_seconds: int
    redirect_limit: int
    max_response_bytes: int
    concurrency: int = 1
    requests_per_minute: int | None = None
    minimum_action_interval_seconds: int | None = None
    browser_network_hosts: tuple[str, ...] = ()
    user_agent: str = _USER_AGENT

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must not be empty")
        for host in (*self.allowed_hosts, *self.browser_network_hosts):
            _validate_host(host)
        if len(set(self.allowed_hosts)) != len(self.allowed_hosts):
            raise ValueError("allowed_hosts must not contain duplicates")
        if not self.allowed_path_prefixes or any(
            not path.startswith("/") or path.startswith("//") for path in self.allowed_path_prefixes
        ):
            raise ValueError("allowed_path_prefixes must contain absolute path prefixes")
        if not self.content_types or any("/" not in value for value in self.content_types):
            raise ValueError("content_types must not be empty")
        if self.timeout_seconds <= 0 or self.redirect_limit < 0 or self.max_response_bytes <= 0:
            raise ValueError("timeout, redirect and response limits must be valid")
        if self.concurrency != 1:
            raise ValueError("V1 source concurrency must remain 1")
        if self.requests_per_minute is not None and self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if (
            self.minimum_action_interval_seconds is not None
            and self.minimum_action_interval_seconds <= 0
        ):
            raise ValueError("minimum_action_interval_seconds must be positive")
        if self.requests_per_minute is None and self.minimum_action_interval_seconds is None:
            raise ValueError("a source throttle must be configured")
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be blank")


@dataclass(frozen=True, slots=True)
class SourceConfig:
    source_key: str
    name: str
    approval_status: SourceApprovalStatus
    base_url: str
    adapter_key: str
    discovery_mode: DiscoveryMode
    identity_strategy: IdentityStrategy
    external_id_field: str
    expected_pagination: str
    fetch_policy: FetchPolicy
    policy_review: PolicyReview
    config_version: str
    countries: tuple[str, ...] = ("VN",)
    reference_hosts: tuple[str, ...] = ()
    adapter_settings: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    cohort: str = "vietnam_it"

    def __post_init__(self) -> None:
        if not _SOURCE_KEY_PATTERN.fullmatch(self.source_key):
            raise ValueError("source_key must use lower-kebab-case")
        if not _ADAPTER_KEY_PATTERN.fullmatch(self.adapter_key):
            raise ValueError("adapter_key must use lower_snake_case")
        if not self.name.strip() or not self.external_id_field.strip():
            raise ValueError("source name and external_id_field must not be blank")
        if not self.expected_pagination.strip() or not self.config_version.strip():
            raise ValueError("pagination and config version must not be blank")
        parsed_base_url = urlsplit(self.base_url)
        if (
            parsed_base_url.scheme != "https"
            or parsed_base_url.hostname not in self.fetch_policy.allowed_hosts
            or parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("base_url must be a bounded HTTPS URL on an allowed host")
        for host in self.reference_hosts:
            _validate_host(host)
        if not self.cohort.strip():
            raise ValueError("cohort must not be blank")
        if self.countries and any(
            len(country) != 2
            or not country.isascii()
            or not country.isalpha()
            or country != country.upper()
            for country in self.countries
        ):
            raise ValueError("countries must use uppercase alpha-2 codes")
        if not self.countries and self.cohort == "vietnam_it":
            raise ValueError("vietnam_it cohort must declare countries")
        if (
            self.approval_status is SourceApprovalStatus.APPROVED
            and self.policy_review.scope is not PolicyScope.APPROVED_LOCAL_NONCOMMERCIAL_SPIKE
        ):
            raise ValueError("approved source requires approved local non-commercial policy scope")
        object.__setattr__(
            self,
            "adapter_settings",
            MappingProxyType(dict(self.adapter_settings)),
        )
