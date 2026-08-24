"""Typed boundary between source adapters and deterministic ingestion workflow."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from devradar.ingestion.source_registry import FetchPolicy, SourceConfig


def _require_non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_https_url(value: str, field_name: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field_name} must be an HTTPS URL without user info")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: UUID
    source: SourceConfig
    deadline: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        _require_aware_datetime(self.deadline, "deadline")
        _require_non_blank(self.correlation_id, "correlation_id")


@dataclass(frozen=True, slots=True)
class ListingRef:
    external_id: str
    canonical_url: str
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.external_id, "external_id")
        _require_https_url(self.canonical_url, "canonical_url")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class FetchResult:
    final_url: str
    fetched_at: datetime
    http_status: int
    content_type: str
    payload: bytes
    raw_content_hash: str
    redirect_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_https_url(self.final_url, "final_url")
        _require_aware_datetime(self.fetched_at, "fetched_at")
        _require_non_blank(self.content_type, "content_type")
        if not 100 <= self.http_status <= 599:
            raise ValueError("http_status must be between 100 and 599")
        _require_sha256(self.raw_content_hash, "raw_content_hash")
        if sha256(self.payload).hexdigest() != self.raw_content_hash:
            raise ValueError("raw_content_hash does not match payload")
        for redirect_url in self.redirect_chain:
            _require_https_url(redirect_url, "redirect_chain")


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    snapshot_id: UUID
    source_key: str
    external_id: str
    source_url: str
    fetched_at: datetime
    content_type: str
    raw_content: str
    raw_content_hash: str

    def __post_init__(self) -> None:
        _require_non_blank(self.source_key, "source_key")
        _require_non_blank(self.external_id, "external_id")
        _require_https_url(self.source_url, "source_url")
        _require_aware_datetime(self.fetched_at, "fetched_at")
        _require_non_blank(self.content_type, "content_type")
        _require_sha256(self.raw_content_hash, "raw_content_hash")


@dataclass(frozen=True, slots=True)
class RawJobFields:
    external_id: str
    canonical_url: str
    title: str
    company_name: str
    description: str | None = None
    location: str | None = None
    salary: str | None = None
    level: str | None = None
    experience: str | None = None
    posted_at: str | None = None
    source_fields: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.external_id, "external_id")
        _require_https_url(self.canonical_url, "canonical_url")
        _require_non_blank(self.title, "title")
        _require_non_blank(self.company_name, "company_name")
        object.__setattr__(self, "source_fields", MappingProxyType(dict(self.source_fields)))


@dataclass(frozen=True, slots=True)
class NormalizedJobCandidates:
    title: str
    company_name: str
    description_text: str | None = None
    location_city: str | None = None
    location_province: str | None = None
    work_mode: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    currency: str | None = None
    salary_period: str | None = None
    levels: tuple[str, ...] = ()
    experience_min: Decimal | None = None
    experience_max: Decimal | None = None
    posted_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.title, "title")
        _require_non_blank(self.company_name, "company_name")
        if self.salary_min is not None and self.salary_min < 0:
            raise ValueError("salary_min must be non-negative")
        if self.salary_max is not None and self.salary_max < 0:
            raise ValueError("salary_max must be non-negative")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isupper()
        ):
            raise ValueError("currency must use a three-letter uppercase code")
        if self.posted_at is not None:
            _require_aware_datetime(self.posted_at, "posted_at")


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    field_name: str
    source_path: str

    def __post_init__(self) -> None:
        _require_non_blank(self.field_name, "field_name")
        _require_non_blank(self.source_path, "source_path")


@dataclass(frozen=True, slots=True)
class ParsedJob:
    raw: RawJobFields
    normalized_candidates: NormalizedJobCandidates
    evidence: tuple[FieldEvidence, ...]
    parser_version: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_blank(self.parser_version, "parser_version")
        if not self.evidence:
            raise ValueError("evidence must not be empty")


@dataclass(frozen=True, slots=True)
class ParseFailure:
    error_code: str
    stage: str
    safe_summary: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.error_code):
            raise ValueError("error_code must be lower_snake_case")
        _require_non_blank(self.stage, "stage")
        _require_non_blank(self.safe_summary, "safe_summary")
        if len(self.safe_summary) > 500 or "\n" in self.safe_summary or "\r" in self.safe_summary:
            raise ValueError("safe_summary must be a bounded single line")


class JobSourceAdapter(Protocol):
    """Structural contract implemented by each approved source adapter."""

    adapter_key: str
    adapter_version: str

    def discover(self, run_context: RunContext) -> Iterable[ListingRef]: ...

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult: ...

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure: ...


@dataclass(frozen=True, slots=True)
class DiscoverySummary:
    items_discovered: int
    items_filtered_out: int
    pages_found: int
    coverage_complete: bool

    def __post_init__(self) -> None:
        if min(self.items_discovered, self.items_filtered_out, self.pages_found) < 0:
            raise ValueError("discovery counters must be non-negative")
        if self.items_filtered_out > self.items_discovered:
            raise ValueError("filtered count must not exceed discovered count")


@runtime_checkable
class DiscoverySummaryProvider(Protocol):
    @property
    def discovery_summary(self) -> DiscoverySummary: ...
