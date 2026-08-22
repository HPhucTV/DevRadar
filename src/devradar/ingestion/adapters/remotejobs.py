"""Deterministic API-only adapter for the approved RemoteJobs.org cohort."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import cast
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

from devradar.ingestion.adapters.html_text import html_to_text
from devradar.ingestion.contracts import (
    FetchResult,
    FieldEvidence,
    ListingRef,
    NormalizedJobCandidates,
    ParsedJob,
    ParseFailure,
    RawJobFields,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.normalization import normalize_location, normalize_text
from devradar.ingestion.safe_http import SafeHttpFetcher
from devradar.ingestion.source_registry import (
    REMOTEJOBS_ORG,
    FetchPolicy,
    SourceConfig,
)

HttpFetch = Callable[[str, FetchPolicy], FetchResult]

_SOURCE_KEY = "remotejobs-org"
_ADAPTER_KEY = "remotejobs_api"
_REFERENCE_HOST = "remotejobs.org"
_API_PATH = "/api/v1/jobs"
_PARSER_VERSION = "remotejobs-api-v1"
_MAX_PAGE_SIZE = 50
_MAX_PAGES_PER_CATEGORY = 250


class RemoteJobsAdapterError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


def _load_json(raw: bytes | str) -> Mapping[str, object]:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RemoteJobsAdapterError(
            "malformed_json",
            "RemoteJobs.org returned malformed JSON.",
        ) from error
    if not isinstance(document, dict):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org response root did not match the expected object schema.",
        )
    return cast(Mapping[str, object], document)


def _required_string(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org published job schema changed.",
        )
    return value.strip()


def _optional_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    return _required_string(value, field="optional", max_length=max_length)


def _canonical_url(value: object) -> str:
    raw = _required_string(value, field="url", max_length=2048)
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as error:
        raise RemoteJobsAdapterError(
            "invalid_reference_url",
            "RemoteJobs.org job URL was invalid.",
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != _REFERENCE_HOST
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not parsed.path.startswith("/remote-jobs/")
        or parsed.query
        or parsed.fragment
    ):
        raise RemoteJobsAdapterError(
            "invalid_reference_url",
            "RemoteJobs.org job URL escaped the approved host/path boundary.",
        )
    return urlunsplit(("https", _REFERENCE_HOST, parsed.path.rstrip("/"), "", ""))


def _external_id(value: object) -> str:
    raw = _required_string(value, field="id", max_length=100)
    try:
        UUID(raw)
    except ValueError as error:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org job did not contain a valid UUID identity.",
        ) from error
    return raw.lower()


def _category_slug(value: object, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org job category changed shape.",
        )
    slug = _required_string(value.get("slug"), field="category.slug", max_length=100)
    if slug not in allowed:
        raise RemoteJobsAdapterError(
            "category_out_of_scope",
            "RemoteJobs.org returned a category outside the approved scope.",
        )
    return slug


def _company_name(value: object) -> str:
    if not isinstance(value, dict):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org job company changed shape.",
        )
    return _required_string(value.get("name"), field="company.name", max_length=500)


def _page(
    document: Mapping[str, object], *, category: str
) -> tuple[tuple[Mapping[str, object], ...], int, int, bool]:
    data = document.get("data")
    pagination = document.get("pagination")
    if not isinstance(data, list) or not isinstance(pagination, dict):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org list response did not match the expected schema.",
        )
    total = pagination.get("total")
    limit = pagination.get("limit")
    offset = pagination.get("offset")
    has_more = pagination.get("has_more")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= _MAX_PAGE_SIZE
        or isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or not isinstance(has_more, bool)
    ):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org pagination metadata did not match the expected schema.",
        )
    if limit > _MAX_PAGE_SIZE or offset + len(data) > total + _MAX_PAGE_SIZE:
        raise RemoteJobsAdapterError(
            "coverage_mismatch",
            "RemoteJobs.org pagination metadata was inconsistent with the page.",
        )
    if not all(isinstance(item, dict) for item in data):
        raise RemoteJobsAdapterError(
            "layout_regression",
            f"RemoteJobs.org category {category} contained an invalid job object.",
        )
    if has_more and not data:
        raise RemoteJobsAdapterError(
            "coverage_mismatch",
            "RemoteJobs.org reported more pages after an empty page.",
        )
    return tuple(cast(Mapping[str, object], item) for item in data), total, offset, has_more


def _posted_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org posted_at was not a valid timestamp.",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org posted_at did not include a timezone.",
        )
    return parsed.astimezone(UTC)


def _number(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field changed shape.",
        )
    if isinstance(value, float) and not isfinite(value):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field was not finite.",
        )
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field was not numeric.",
        ) from error
    if parsed < 0:
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field was negative.",
        )
    return parsed


def _raw_number(value: object) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field changed shape.",
        )
    if isinstance(value, float) and not isfinite(value):
        raise RemoteJobsAdapterError(
            "layout_regression",
            "RemoteJobs.org salary field was not finite.",
        )
    return value


def _item_identity(
    item: Mapping[str, object], allowed_categories: tuple[str, ...]
) -> tuple[str, str, str]:
    external_id = _external_id(item.get("id"))
    canonical_url = _canonical_url(item.get("url"))
    category = _category_slug(item.get("category"), allowed_categories)
    _required_string(item.get("title"), field="title", max_length=500)
    _company_name(item.get("company"))
    _required_string(item.get("description"), field="description", max_length=2_000_000)
    return external_id, canonical_url, category


class RemoteJobsApiAdapter:
    adapter_key = _ADAPTER_KEY
    adapter_version = _PARSER_VERSION

    def __init__(
        self,
        *,
        config: SourceConfig = REMOTEJOBS_ORG,
        http_fetch: HttpFetch | None = None,
    ) -> None:
        if (
            config.source_key != _SOURCE_KEY
            or config.adapter_key != self.adapter_key
            or config.approval_status is not SourceApprovalStatus.APPROVED
            or config.cohort != "global_remote_it_secondary"
        ):
            raise ValueError("RemoteJobs adapter requires the approved remote cohort config")
        categories = config.adapter_settings.get("categories")
        if not isinstance(categories, tuple) or not categories:
            raise ValueError("RemoteJobs config must declare category allow-list")
        self._config = config
        self._categories = categories
        self._page_size = int(str(config.adapter_settings.get("page_size", "50")))
        if not 1 <= self._page_size <= _MAX_PAGE_SIZE:
            raise ValueError("RemoteJobs page size must be between 1 and 50")
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._last_results: dict[tuple[str, str], FetchResult] = {}
        self._last_items: dict[tuple[str, str], Mapping[str, object]] = {}

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise RemoteJobsAdapterError(
                "source_config_mismatch",
                "RemoteJobs run context did not match the approved source config.",
            )
        self._last_results = {}
        self._last_items = {}
        listings: dict[str, ListingRef] = {}
        pages = 0
        for category in self._categories:
            offset = 0
            expected_total: int | None = None
            category_seen: set[str] = set()
            while True:
                pages += 1
                if pages > _MAX_PAGES_PER_CATEGORY * len(self._categories):
                    raise RemoteJobsAdapterError(
                        "coverage_mismatch",
                        "RemoteJobs.org pagination exceeded the bounded page limit.",
                    )
                query = urlencode(
                    {"category": category, "limit": self._page_size, "offset": offset}
                )
                result = self._http_fetch(
                    f"{self._config.base_url}?{query}", self._config.fetch_policy
                )
                items, total, returned_offset, has_more = _page(
                    _load_json(result.payload), category=category
                )
                if returned_offset != offset or (
                    expected_total is not None and total != expected_total
                ):
                    raise RemoteJobsAdapterError(
                        "coverage_mismatch",
                        "RemoteJobs.org pagination total or offset changed during discovery.",
                    )
                expected_total = total
                for item in items:
                    external_id, canonical_url, item_category = _item_identity(
                        item, self._categories
                    )
                    if item_category != category:
                        raise RemoteJobsAdapterError(
                            "coverage_mismatch",
                            "RemoteJobs.org response category did not match the requested filter.",
                        )
                    key = (external_id, canonical_url)
                    existing = listings.get(external_id)
                    if existing is not None and existing.canonical_url != canonical_url:
                        raise RemoteJobsAdapterError(
                            "duplicate_job_conflict",
                            "RemoteJobs.org returned one UUID with conflicting URLs.",
                        )
                    if external_id in category_seen:
                        # Dynamic feeds may repeat an unchanged item across offset pages.
                        # Same UUID + URL is idempotent; a URL conflict is rejected above.
                        continue
                    category_seen.add(external_id)
                    if existing is None:
                        listing = ListingRef(
                            external_id=external_id,
                            canonical_url=canonical_url,
                            metadata={
                                "category": item_category,
                                "title": _required_string(
                                    item.get("title"), field="title", max_length=500
                                ),
                            },
                        )
                        listings[external_id] = listing
                        self._last_results[key] = result
                        self._last_items[key] = item
                    elif key not in self._last_results:
                        self._last_results[key] = result
                        self._last_items[key] = item
                if not has_more:
                    if expected_total is not None and offset + len(items) < expected_total:
                        raise RemoteJobsAdapterError(
                            "coverage_mismatch",
                            "RemoteJobs.org final page ended before the reported total.",
                        )
                    break
                offset += len(items)
                if not items:
                    raise RemoteJobsAdapterError(
                        "coverage_mismatch",
                        "RemoteJobs.org pagination did not advance.",
                    )
        if not listings:
            raise RemoteJobsAdapterError(
                "empty_result",
                "RemoteJobs.org returned no jobs for the approved categories.",
            )
        return tuple(listings[key] for key in sorted(listings))

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise RemoteJobsAdapterError(
                "fetch_policy_mismatch",
                "RemoteJobs fetch policy did not match the approved source config.",
            )
        key = (listing_ref.external_id, listing_ref.canonical_url)
        result = self._last_results.get(key)
        if result is None:
            raise RemoteJobsAdapterError(
                "listing_not_discovered",
                "RemoteJobs fetch requires a listing from the current complete discovery.",
            )
        return result

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        try:
            if snapshot.source_key != self._config.source_key:
                raise RemoteJobsAdapterError(
                    "source_config_mismatch",
                    "RemoteJobs snapshot source did not match the approved config.",
                )
            document = _load_json(snapshot.raw_content)
            data = document.get("data")
            if not isinstance(data, list):
                raise RemoteJobsAdapterError(
                    "layout_regression",
                    "RemoteJobs.org snapshot did not contain a data list.",
                )
            matches = [
                cast(Mapping[str, object], item)
                for item in data
                if isinstance(item, dict) and _external_id(item.get("id")) == snapshot.external_id
            ]
            if len(matches) != 1:
                raise RemoteJobsAdapterError(
                    "listing_not_found",
                    "RemoteJobs.org snapshot did not contain exactly one requested UUID.",
                )
            item = matches[0]
            external_id, canonical_url, _ = _item_identity(item, self._categories)
            if canonical_url != snapshot.source_url:
                raise RemoteJobsAdapterError(
                    "provenance_mismatch",
                    "RemoteJobs.org snapshot URL did not match the requested listing.",
                )
            title_raw = _required_string(item.get("title"), field="title", max_length=500)
            company_raw = _company_name(item.get("company"))
            location_raw = _optional_string(item.get("location"), max_length=500)
            description_raw = _required_string(
                item.get("description"), field="description", max_length=2_000_000
            )
            description = html_to_text(description_raw) or normalize_text(description_raw).value
            if description is None:
                raise RemoteJobsAdapterError(
                    "empty_content",
                    "RemoteJobs.org description was empty after safe text extraction.",
                )
            title = normalize_text(title_raw)
            company = normalize_text(company_raw)
            location = normalize_location(location_raw)
            if title.value is None or company.value is None:
                raise RemoteJobsAdapterError(
                    "layout_regression",
                    "RemoteJobs.org required text became empty after normalization.",
                )
            salary_text = _optional_string(item.get("salary_text"), max_length=500)
            posted_at_raw = _optional_string(item.get("posted_at"), max_length=100)
            posted_at = _posted_at(posted_at_raw)
            translated_value = item.get("is_translated")
            translated: bool | None = (
                translated_value if isinstance(translated_value, bool) else None
            )
            source_fields: dict[str, str | int | float | bool | None] = {
                "category": _category_slug(item.get("category"), self._categories),
                "apply_url": _optional_string(item.get("apply_url"), max_length=2048),
                "salary_min": _raw_number(item.get("salary_min")),
                "salary_max": _raw_number(item.get("salary_max")),
                "type": _optional_string(item.get("type"), max_length=100),
                "is_translated": translated,
                "original_language": _optional_string(item.get("original_language"), max_length=20),
            }
            normalized_location = location.value
            evidence = (
                FieldEvidence(field_name="external_id", source_path="$.id"),
                FieldEvidence(field_name="canonical_url", source_path="$.url"),
                FieldEvidence(field_name="title", source_path="$.title"),
                FieldEvidence(field_name="company_name", source_path="$.company.name"),
                FieldEvidence(field_name="description", source_path="$.description"),
                FieldEvidence(field_name="location", source_path="$.location"),
            )
            return ParsedJob(
                raw=RawJobFields(
                    external_id=external_id,
                    canonical_url=canonical_url,
                    title=title_raw,
                    company_name=company_raw,
                    description=description,
                    location=location_raw,
                    salary=salary_text,
                    posted_at=posted_at_raw,
                    source_fields=source_fields,
                ),
                normalized_candidates=NormalizedJobCandidates(
                    title=title.value,
                    company_name=company.value,
                    description_text=description,
                    location_city=(normalized_location.city if normalized_location else None),
                    location_province=(
                        normalized_location.province if normalized_location else None
                    ),
                    work_mode=(
                        normalized_location.work_mode.value
                        if normalized_location and normalized_location.work_mode
                        else None
                    ),
                    posted_at=posted_at,
                ),
                evidence=evidence,
                parser_version=_PARSER_VERSION,
                warnings=(
                    *location.warnings,
                    "salary_currency_not_inferred",
                    "global_remote_cohort",
                ),
            )
        except RemoteJobsAdapterError as error:
            return ParseFailure(
                error_code=error.code,
                stage="remotejobs_parse",
                safe_summary=error.safe_summary,
            )
