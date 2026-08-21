"""Immutable V1 source allow-list and adapter resolution."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from devradar.ingestion.models import SourceApprovalStatus

if TYPE_CHECKING:
    from devradar.ingestion.contracts import JobSourceAdapter

_SOURCE_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ADAPTER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_USER_AGENT = "DevRadar/0.1 (+https://github.com/HPhucTV/DevRadar)"
_REVIEWED_AT = date(2026, 8, 21)
_NEXT_REVIEW_AT = date(2026, 11, 21)


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
        if not self.countries or any(
            len(country) != 2
            or not country.isascii()
            or not country.isalpha()
            or country != country.upper()
            for country in self.countries
        ):
            raise ValueError("countries must use uppercase alpha-2 codes")
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


class RegistryError(LookupError):
    code = "registry_error"


class UnknownSourceError(RegistryError):
    code = "source_not_found"


class SourceNotApprovedError(RegistryError):
    code = "source_not_approved"


class AdapterNotRegisteredError(RegistryError):
    code = "adapter_not_registered"


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    config: SourceConfig
    adapter: JobSourceAdapter


class AdapterRegistry:
    def __init__(self, adapters: Iterable[JobSourceAdapter] = ()) -> None:
        registered: dict[str, JobSourceAdapter] = {}
        for adapter in adapters:
            adapter_key = adapter.adapter_key
            if not _ADAPTER_KEY_PATTERN.fullmatch(adapter_key):
                raise ValueError("registered adapter_key must use lower_snake_case")
            if adapter_key in registered:
                raise ValueError(f"duplicate adapter_key: {adapter_key}")
            registered[adapter_key] = adapter
        self._adapters = MappingProxyType(registered)

    def resolve_for(self, config: SourceConfig) -> JobSourceAdapter:
        if config.approval_status is not SourceApprovalStatus.APPROVED:
            raise SourceNotApprovedError(config.source_key)
        try:
            return self._adapters[config.adapter_key]
        except KeyError:
            raise AdapterNotRegisteredError(config.adapter_key) from None


class SourceRegistry:
    def __init__(self, configs: Iterable[SourceConfig]) -> None:
        registered: dict[str, SourceConfig] = {}
        for config in configs:
            if config.source_key in registered:
                raise ValueError(f"duplicate source_key: {config.source_key}")
            registered[config.source_key] = config
        self._configs = MappingProxyType(registered)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._configs))

    def get(self, source_key: str) -> SourceConfig:
        try:
            return self._configs[source_key]
        except KeyError:
            raise UnknownSourceError(source_key) from None

    def resolve(self, source_key: str, adapters: AdapterRegistry) -> ResolvedSource:
        config = self.get(source_key)
        if config.approval_status is not SourceApprovalStatus.APPROVED:
            raise SourceNotApprovedError(source_key)
        return ResolvedSource(config=config, adapter=adapters.resolve_for(config))


_APPROVED_POLICY_REVIEW = PolicyReview(
    scope=PolicyScope.APPROVED_LOCAL_NONCOMMERCIAL_SPIKE,
    robots_reviewed_at=_REVIEWED_AT,
    terms_reviewed_at=_REVIEWED_AT,
    next_review_at=_NEXT_REVIEW_AT,
)

VNG_CAREERS = SourceConfig(
    source_key="vng-careers",
    name="VNG Careers",
    approval_status=SourceApprovalStatus.APPROVED,
    base_url="https://career.vng.com.vn",
    adapter_key="vng_careers",
    discovery_mode=DiscoveryMode.SERVER_RENDERED_HTML,
    identity_strategy=IdentityStrategy.EXTERNAL_ID,
    external_id_field="job_id",
    expected_pagination="numbered_pages_with_reported_total",
    fetch_policy=FetchPolicy(
        allowed_hosts=("career.vng.com.vn",),
        allowed_path_prefixes=("/tim-kiem-viec-lam",),
        content_types=("text/html",),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=2_000_000,
        requests_per_minute=6,
    ),
    policy_review=_APPROVED_POLICY_REVIEW,
    config_version="2026-08-21.2",
    adapter_settings={
        "job_families": (
            "Software",
            "System",
            "QC/P-QA",
            "Tech Management",
            "Data Engineering",
            "Data Science",
            "Business Analysis",
            "Artificial Intelligence",
        ),
        "job_group_ids": (
            "385",
            "423",
            "384",
            "387",
            "457",
            "462",
            "464",
            "465",
        ),
    },
)

NAVER_VIETNAM_GREENHOUSE = SourceConfig(
    source_key="naver-vietnam-greenhouse",
    name="NAVER Vietnam Careers via Greenhouse",
    approval_status=SourceApprovalStatus.APPROVED,
    base_url="https://boards-api.greenhouse.io/v1/boards/navervietnam",
    adapter_key="greenhouse_job_board",
    discovery_mode=DiscoveryMode.PUBLIC_JSON_API,
    identity_strategy=IdentityStrategy.EXTERNAL_ID,
    external_id_field="id",
    expected_pagination="single_response_with_meta_total",
    fetch_policy=FetchPolicy(
        allowed_hosts=("boards-api.greenhouse.io",),
        allowed_path_prefixes=("/v1/boards/navervietnam/jobs",),
        content_types=("application/json",),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=2_000_000,
        requests_per_minute=10,
    ),
    policy_review=_APPROVED_POLICY_REVIEW,
    config_version="2026-08-21.1",
    reference_hosts=("job-boards.greenhouse.io",),
    adapter_settings={"board_token": "navervietnam"},
)

MOMO_CAREERS = SourceConfig(
    source_key="momo-careers",
    name="MoMo Careers",
    approval_status=SourceApprovalStatus.APPROVED,
    base_url="https://momo.careers",
    adapter_key="momo_careers",
    discovery_mode=DiscoveryMode.BROWSER_PUBLIC_UI,
    identity_strategy=IdentityStrategy.EXTERNAL_ID,
    external_id_field="jobId",
    expected_pagination="public_load_more_until_reported_total",
    fetch_policy=FetchPolicy(
        allowed_hosts=("momo.careers",),
        allowed_path_prefixes=("/jobs-opening", "/jobs/"),
        content_types=("text/html",),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=2_000_000,
        minimum_action_interval_seconds=5,
        browser_network_hosts=("aws.momo.vn",),
    ),
    policy_review=_APPROVED_POLICY_REVIEW,
    config_version="2026-08-21.1",
    adapter_settings={
        "division_group_id": "DGM.0001",
        "division_group_name": "Trung tâm Công nghệ Thông tin",
    },
)

V1_SOURCE_CONFIGS = (VNG_CAREERS, NAVER_VIETNAM_GREENHOUSE, MOMO_CAREERS)
V1_SOURCE_REGISTRY = SourceRegistry(V1_SOURCE_CONFIGS)
