"""Deterministic HTTP adapter for approved VNG Careers pages."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

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
from devradar.ingestion.source_registry import VNG_CAREERS, FetchPolicy, SourceConfig

HttpFetch = Callable[[str, FetchPolicy], FetchResult]

_SOURCE_KEY = "vng-careers"
_ADAPTER_KEY = "vng_careers"
_COMPANY_NAME = "VNG"
_PARSER_VERSION = "vng-careers-v1"
_HOST = "career.vng.com.vn"
_LIST_PATH = "/tim-kiem-viec-lam"
_DETAIL_PREFIX = f"{_LIST_PATH}/chi-tiet/"
_SLUG_PATTERN = re.compile(r"^[0-9]+-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+84|0)(?:[ .()-]*\d){9}(?!\d)")


class VngAdapterError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


@dataclass(frozen=True, slots=True)
class VngListingPage:
    page: int
    total: int
    pages: int
    size: int
    job_group_id: str
    job_group_name: str
    all_external_ids: tuple[str, ...]
    listings: tuple[ListingRef, ...]


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capture = False
        self._found = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag != "script" or attributes.get("id") != "__NEXT_DATA__":
            return
        if self._capture or self._found:
            raise VngAdapterError(
                "layout_regression",
                "VNG page contained multiple __NEXT_DATA__ payloads.",
            )
        if attributes.get("type") != "application/json":
            raise VngAdapterError(
                "layout_regression",
                "VNG __NEXT_DATA__ payload used an unexpected content type.",
            )
        self._capture = True
        self._found = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def payload(self) -> str:
        if self._found != 1 or self._capture or not self._parts:
            raise VngAdapterError(
                "layout_regression",
                "VNG page did not contain one complete __NEXT_DATA__ payload.",
            )
        return "".join(self._parts)


def _mapping(value: object, safe_summary: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise VngAdapterError("layout_regression", safe_summary)
    return value


def _page_props(raw: bytes | str) -> Mapping[str, object]:
    if isinstance(raw, bytes):
        try:
            html = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise VngAdapterError(
                "invalid_text_encoding",
                "VNG page was not valid UTF-8.",
            ) from error
    else:
        html = raw

    parser = _NextDataParser()
    parser.feed(html)
    parser.close()
    try:
        document = json.loads(parser.payload())
    except json.JSONDecodeError as error:
        raise VngAdapterError(
            "malformed_json",
            "VNG __NEXT_DATA__ payload was malformed JSON.",
        ) from error
    root = _mapping(document, "VNG __NEXT_DATA__ root changed shape.")
    props = _mapping(root.get("props"), "VNG props payload changed shape.")
    return _mapping(props.get("pageProps"), "VNG pageProps payload changed shape.")


def _required_string(
    value: Mapping[str, object],
    field: str,
    *,
    max_length: int,
) -> str:
    raw = value.get(field)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > max_length:
        raise VngAdapterError(
            "layout_regression",
            "VNG job did not match the expected published field schema.",
        )
    return raw


def _optional_string(
    value: Mapping[str, object],
    field: str,
    *,
    max_length: int,
) -> str | None:
    raw = value.get(field)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw) > max_length:
        raise VngAdapterError(
            "layout_regression",
            "VNG optional field changed to an unsupported shape.",
        )
    return raw


def _optional_scalar(value: Mapping[str, object], field: str) -> str | int | bool | None:
    raw = value.get(field)
    if raw is None or isinstance(raw, str) or isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw
    raise VngAdapterError(
        "layout_regression",
        "VNG optional field changed to an unsupported shape.",
    )


def _positive_int(value: object, safe_summary: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VngAdapterError("layout_regression", safe_summary)
    return value


def _non_negative_int(value: object, safe_summary: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VngAdapterError("layout_regression", safe_summary)
    return value


def _page_number(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and str(int(value)) == value and int(value) > 0:
        return int(value)
    raise VngAdapterError(
        "layout_regression",
        "VNG response did not contain a valid request page number.",
    )


def _job_id(job: Mapping[str, object]) -> int:
    return _positive_int(
        job.get("job_id"),
        "VNG job did not contain a valid job_id.",
    )


def _detail_url(slug: str, external_id: str) -> str:
    if not _SLUG_PATTERN.fullmatch(slug) or not slug.startswith(f"{external_id}-"):
        raise VngAdapterError(
            "invalid_reference_url",
            "VNG job slug did not match its approved identity boundary.",
        )
    return f"https://{_HOST}{_DETAIL_PREFIX}{slug}"


def _validate_detail_url(url: str, external_id: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise VngAdapterError(
            "invalid_reference_url",
            "VNG detail URL was invalid.",
        ) from error
    slug = parsed.path.removeprefix(_DETAIL_PREFIX)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not parsed.path.startswith(_DETAIL_PREFIX)
        or "/" in slug
        or parsed.query
        or parsed.fragment
    ):
        raise VngAdapterError(
            "invalid_reference_url",
            "VNG detail URL escaped the approved source boundary.",
        )
    return _detail_url(slug, external_id)


def _approved_job_groups(config: SourceConfig) -> tuple[tuple[str, str], ...]:
    names = config.adapter_settings.get("job_families")
    identifiers = config.adapter_settings.get("job_group_ids")
    if (
        not isinstance(names, tuple)
        or not isinstance(identifiers, tuple)
        or not names
        or len(names) != len(identifiers)
        or any(not item.strip() for item in (*names, *identifiers))
        or any(not item.isdigit() for item in identifiers)
    ):
        raise ValueError("VNG adapter requires paired approved job group names and IDs")
    return tuple(zip(identifiers, names, strict=True))


def _job_group_catalog(page_props: Mapping[str, object]) -> dict[str, str]:
    tags = page_props.get("tags")
    if not isinstance(tags, list):
        raise VngAdapterError(
            "layout_regression",
            "VNG filter taxonomy changed shape.",
        )
    for tag in tags:
        if not isinstance(tag, dict) or tag.get("type") != "job_group":
            continue
        values = tag.get("value")
        if not isinstance(values, list):
            break
        catalog: dict[str, str] = {}
        for item in values:
            if not isinstance(item, dict):
                break
            identifier = item.get("id")
            name = item.get("value")
            if (
                not isinstance(identifier, str)
                or not identifier.isdigit()
                or not isinstance(name, str)
                or not name.strip()
                or identifier in catalog
            ):
                break
            catalog[identifier] = name
        else:
            return catalog
        break
    raise VngAdapterError(
        "layout_regression",
        "VNG job group taxonomy changed shape.",
    )


def parse_vng_listing_page(
    raw: bytes | str,
    *,
    expected_page: int,
    expected_job_group_id: str,
    config: SourceConfig = VNG_CAREERS,
) -> VngListingPage:
    page_props = _page_props(raw)
    jobs = page_props.get("jobs")
    request = _mapping(
        page_props.get("request"),
        "VNG list request metadata changed shape.",
    )
    if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
        raise VngAdapterError(
            "layout_regression",
            "VNG jobs collection changed shape.",
        )

    total = _non_negative_int(
        page_props.get("total"),
        "VNG list total changed shape.",
    )
    pages = _positive_int(
        page_props.get("pages"),
        "VNG list pages changed shape.",
    )
    size = _positive_int(
        request.get("size"),
        "VNG list page size changed shape.",
    )
    page = _page_number(request.get("page"))
    queries = request.get("queries")
    if queries != {"job_group": [expected_job_group_id]}:
        raise VngAdapterError(
            "scope_filter_mismatch",
            "VNG response did not confirm the approved job group filter.",
        )
    approved_groups = dict(_approved_job_groups(config))
    catalog = _job_group_catalog(page_props)
    if (
        expected_job_group_id not in approved_groups
        or catalog.get(expected_job_group_id) != approved_groups[expected_job_group_id]
        or any(catalog.get(identifier) != name for identifier, name in approved_groups.items())
    ):
        raise VngAdapterError(
            "scope_filter_mismatch",
            "VNG job group filter no longer matched the approved taxonomy.",
        )
    expected_pages = max(1, math.ceil(total / size))
    if page != expected_page or pages != expected_pages or page > pages:
        raise VngAdapterError(
            "pagination_conflict",
            "VNG pagination metadata conflicted with the requested page.",
        )
    expected_items = min(size, max(0, total - ((page - 1) * size)))
    if len(jobs) != expected_items:
        raise VngAdapterError(
            "coverage_mismatch",
            "VNG page item count did not match its pagination metadata.",
        )

    all_ids: list[str] = []
    listings: list[ListingRef] = []
    seen: set[str] = set()
    for job in jobs:
        external_id = str(_job_id(job))
        if external_id in seen:
            raise VngAdapterError(
                "duplicate_job_id",
                "VNG page contained a duplicate job_id.",
            )
        seen.add(external_id)
        all_ids.append(external_id)
        title = _required_string(job, "title", max_length=500)
        slug = _required_string(job, "slug", max_length=1000)
        location = _required_string(job, "location", max_length=500)
        job_family = _optional_string(job, "job_family", max_length=500)
        working_type = _required_string(job, "workingType", max_length=200)
        code = _required_string(job, "code", max_length=200)
        language = _required_string(job, "lang", max_length=20)
        _required_string(job, "description", max_length=2_000_000)
        _required_string(job, "summary", max_length=2_000_000)
        canonical_url = _detail_url(slug, external_id)
        listings.append(
            ListingRef(
                external_id=external_id,
                canonical_url=canonical_url,
                metadata={
                    "code": code,
                    "title": title,
                    "location": location,
                    "job_family": job_family,
                    "approved_job_group": approved_groups[expected_job_group_id],
                    "working_type": working_type,
                    "language": language,
                },
            )
        )

    return VngListingPage(
        page=page,
        total=total,
        pages=pages,
        size=size,
        job_group_id=expected_job_group_id,
        job_group_name=approved_groups[expected_job_group_id],
        all_external_ids=tuple(all_ids),
        listings=tuple(listings),
    )


def _redact_contacts(value: str) -> tuple[str, bool]:
    redacted, email_count = _EMAIL_PATTERN.subn("[redacted-email]", value)
    redacted, phone_count = _PHONE_PATTERN.subn("[redacted-phone]", redacted)
    return redacted, bool(email_count or phone_count)


class VngCareersAdapter:
    adapter_key = _ADAPTER_KEY

    def __init__(
        self,
        *,
        config: SourceConfig = VNG_CAREERS,
        http_fetch: HttpFetch | None = None,
    ) -> None:
        if (
            config.source_key != _SOURCE_KEY
            or config.adapter_key != self.adapter_key
            or config.approval_status is not SourceApprovalStatus.APPROVED
        ):
            raise ValueError("VNG adapter requires the approved VNG Careers config")
        self._approved_groups = _approved_job_groups(config)
        self._config = config
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._last_listings: dict[tuple[str, str], ListingRef] = {}

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise VngAdapterError(
                "source_config_mismatch",
                "VNG run context did not match the approved source config.",
            )
        self._last_listings = {}
        listings_by_id: dict[str, ListingRef] = {}
        for group_id, group_name in self._approved_groups:
            first = self._fetch_page(group_id, group_name, 1, run_context)
            pages = [first]
            for page_number in range(2, first.pages + 1):
                page = self._fetch_page(group_id, group_name, page_number, run_context)
                if (
                    page.total != first.total
                    or page.pages != first.pages
                    or page.size != first.size
                ):
                    raise VngAdapterError(
                        "pagination_conflict",
                        "VNG pagination metadata changed during discovery.",
                    )
                pages.append(page)

            group_ids: set[str] = set()
            for page in pages:
                for listing in page.listings:
                    if listing.external_id in group_ids:
                        raise VngAdapterError(
                            "duplicate_job_id",
                            "VNG job group contained a duplicate job_id across pages.",
                        )
                    group_ids.add(listing.external_id)
                    previous = listings_by_id.get(listing.external_id)
                    if previous is not None and (
                        previous.canonical_url != listing.canonical_url
                        or previous.metadata.get("title") != listing.metadata.get("title")
                    ):
                        raise VngAdapterError(
                            "duplicate_job_id",
                            "VNG approved groups contained conflicting observations.",
                        )
                    listings_by_id.setdefault(listing.external_id, listing)
            if len(group_ids) != first.total:
                raise VngAdapterError(
                    "coverage_mismatch",
                    "VNG job group did not cover its reported total.",
                )

        self._last_listings = {
            (listing.external_id, listing.canonical_url): listing
            for listing in listings_by_id.values()
        }
        return tuple(listings_by_id.values())

    def _fetch_page(
        self,
        group_id: str,
        group_name: str,
        page: int,
        run_context: RunContext,
    ) -> VngListingPage:
        if datetime.now(UTC) >= run_context.deadline:
            raise VngAdapterError(
                "run_deadline_exceeded",
                "VNG discovery exceeded its bounded run deadline.",
            )
        result = self._http_fetch(
            f"{self._config.base_url}{_LIST_PATH}?job_group={group_id}&page={page}",
            self._config.fetch_policy,
        )
        parsed = parse_vng_listing_page(
            result.payload,
            expected_page=page,
            expected_job_group_id=group_id,
            config=self._config,
        )
        if parsed.job_group_name != group_name:
            raise VngAdapterError(
                "scope_filter_mismatch",
                "VNG parsed job group did not match the approved source config.",
            )
        return parsed

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise VngAdapterError(
                "fetch_policy_mismatch",
                "VNG fetch policy did not match the approved source config.",
            )
        expected = self._last_listings.get((listing_ref.external_id, listing_ref.canonical_url))
        if expected != listing_ref:
            raise VngAdapterError(
                "listing_not_discovered",
                "VNG fetch requires a listing from the current complete discovery.",
            )
        return self._http_fetch(listing_ref.canonical_url, fetch_policy)

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        try:
            if snapshot.source_key != self._config.source_key:
                raise VngAdapterError(
                    "source_config_mismatch",
                    "VNG snapshot source did not match the approved config.",
                )
            page_props = _page_props(snapshot.raw_content)
            if page_props.get("closed") is not False:
                raise VngAdapterError(
                    "job_closed",
                    "VNG detail was closed or unavailable during parsing.",
                )
            job = _mapping(
                page_props.get("job_data"),
                "VNG detail job_data changed shape.",
            )
            external_id = str(_job_id(job))
            if external_id != snapshot.external_id:
                raise VngAdapterError(
                    "listing_not_found",
                    "VNG detail did not match the requested job_id.",
                )
            canonical_url = _validate_detail_url(snapshot.source_url, external_id)
            title_raw = _required_string(job, "title", max_length=500)
            location_raw = _required_string(job, "location", max_length=500)
            description_raw = _required_string(job, "description", max_length=2_000_000)
            requirement_raw = _optional_string(job, "requirement", max_length=2_000_000)
            description = html_to_text(description_raw)
            requirement = html_to_text(requirement_raw) if requirement_raw else None
            if description is None:
                raise VngAdapterError(
                    "empty_content",
                    "VNG job description was empty after safe text extraction.",
                )
            parts = [description]
            if requirement and requirement != description:
                parts.append(requirement)
            canonical_description, contact_redacted = _redact_contacts("\n\n".join(parts))

            title = normalize_text(title_raw)
            company = normalize_text(_COMPANY_NAME)
            location = normalize_location(location_raw)
            if title.value is None or company.value is None:
                raise VngAdapterError(
                    "layout_regression",
                    "VNG required text became empty after normalization.",
                )
            careers_page_flag = _optional_scalar(job, "post_on_careers_page")
            excerpt_raw = _optional_string(job, "excerpt", max_length=2_000_000)
            excerpt = html_to_text(excerpt_raw) if excerpt_raw else None
            source_fields = {
                "code": _optional_scalar(job, "code"),
                "language": _optional_scalar(job, "lang"),
                "working_type": _optional_scalar(job, "workingType"),
                "post_on_careers_page": careers_page_flag,
                "department": _optional_scalar(job, "department"),
                "job_category": _optional_scalar(job, "jobCategory"),
                "status": _optional_scalar(job, "status"),
                "excerpt": excerpt,
            }
            normalized_location = location.value
            warnings = list(location.warnings)
            if contact_redacted:
                warnings.append("contact_data_redacted")

            return ParsedJob(
                raw=RawJobFields(
                    external_id=external_id,
                    canonical_url=canonical_url,
                    title=title_raw,
                    company_name=_COMPANY_NAME,
                    description=canonical_description,
                    location=location_raw,
                    source_fields=source_fields,
                ),
                normalized_candidates=NormalizedJobCandidates(
                    title=title.value,
                    company_name=company.value,
                    description_text=canonical_description,
                    location_city=(normalized_location.city if normalized_location else None),
                    location_province=(
                        normalized_location.province if normalized_location else None
                    ),
                    work_mode=(
                        normalized_location.work_mode.value
                        if normalized_location and normalized_location.work_mode
                        else None
                    ),
                    posted_at=None,
                ),
                evidence=(
                    FieldEvidence(field_name="external_id", source_path="$.job_data.job_id"),
                    FieldEvidence(field_name="canonical_url", source_path="snapshot.source_url"),
                    FieldEvidence(field_name="title", source_path="$.job_data.title"),
                    FieldEvidence(field_name="company_name", source_path="source:vng"),
                    FieldEvidence(field_name="description", source_path="$.job_data.description"),
                    FieldEvidence(field_name="location", source_path="$.job_data.location"),
                ),
                parser_version=_PARSER_VERSION,
                warnings=tuple(warnings),
            )
        except VngAdapterError as error:
            return ParseFailure(
                error_code=error.code,
                stage="vng_parse",
                safe_summary=error.safe_summary,
            )
