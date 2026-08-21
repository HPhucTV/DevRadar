"""Deterministic NAVER Vietnam adapter for the Greenhouse Job Board API."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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
from devradar.ingestion.source_registry import (
    NAVER_VIETNAM_GREENHOUSE,
    FetchPolicy,
    SourceConfig,
)

HttpFetch = Callable[[str, FetchPolicy], FetchResult]

_SOURCE_KEY = "naver-vietnam-greenhouse"
_ADAPTER_KEY = "greenhouse_job_board"
_BOARD_TOKEN = "navervietnam"
_COMPANY_NAME = "NAVER Vietnam"
_PARSER_VERSION = "greenhouse-job-board-v1"
_REFERENCE_HOST = "job-boards.greenhouse.io"


class GreenhouseAdapterError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


def _load_json(raw: bytes | str) -> Mapping[str, object]:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GreenhouseAdapterError(
            "malformed_json",
            "Greenhouse returned malformed JSON.",
        ) from error
    if not isinstance(document, dict):
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse response root did not match the expected object schema.",
        )
    return document


def _job_id(job: Mapping[str, object]) -> int:
    value = job.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse job did not contain a valid public post ID.",
        )
    return value


def _required_string(job: Mapping[str, object], field: str, *, max_length: int) -> str:
    value = job.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse job did not match the expected published field schema.",
        )
    return value


def _optional_scalar(job: Mapping[str, object], field: str) -> str | int | bool | None:
    value = job.get(field)
    if value is None or isinstance(value, str) or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    raise GreenhouseAdapterError(
        "layout_regression",
        "Greenhouse optional field changed to an unsupported shape.",
    )


def _location_name(job: Mapping[str, object]) -> str:
    location = job.get("location")
    if not isinstance(location, dict):
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse job location did not match the expected schema.",
        )
    return _required_string(location, "name", max_length=500)


def _is_vietnam_location(value: str) -> bool:
    normalized = value.casefold()
    return "vietnam" in normalized or "việt nam" in normalized


def _canonical_reference_url(job: Mapping[str, object], external_id: str) -> str:
    value = _required_string(job, "absolute_url", max_length=2048)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise GreenhouseAdapterError(
            "invalid_reference_url",
            "Greenhouse job reference URL was invalid.",
        ) from error
    expected_path = f"/{_BOARD_TOKEN}/jobs/{external_id}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != _REFERENCE_HOST
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path.rstrip("/") != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise GreenhouseAdapterError(
            "invalid_reference_url",
            "Greenhouse job reference URL escaped the approved board boundary.",
        )
    return f"https://{_REFERENCE_HOST}{expected_path}"


def _listing_jobs(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    jobs = document.get("jobs")
    meta = document.get("meta")
    if not isinstance(jobs, list) or not isinstance(meta, dict):
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse list response did not match the expected schema.",
        )
    total = meta.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse list response did not contain a valid total.",
        )
    if len(jobs) != total:
        raise GreenhouseAdapterError(
            "coverage_mismatch",
            "Greenhouse list count did not match its reported total.",
        )
    if total == 0:
        raise GreenhouseAdapterError(
            "empty_result",
            "Greenhouse returned an empty result that requires coverage review.",
        )
    if any(not isinstance(job, dict) for job in jobs):
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse list contained an invalid job object.",
        )
    return tuple(jobs)


def _validated_listings(document: Mapping[str, object]) -> tuple[ListingRef, ...]:
    listings: list[ListingRef] = []
    seen_ids: set[str] = set()
    for job in _listing_jobs(document):
        external_id = str(_job_id(job))
        if external_id in seen_ids:
            raise GreenhouseAdapterError(
                "duplicate_job_id",
                "Greenhouse list contained a duplicate public post ID.",
            )
        seen_ids.add(external_id)
        title = _required_string(job, "title", max_length=500)
        location = _location_name(job)
        if not _is_vietnam_location(location):
            raise GreenhouseAdapterError(
                "location_out_of_scope",
                "Greenhouse list contained a job outside the approved Vietnam scope.",
            )
        listings.append(
            ListingRef(
                external_id=external_id,
                canonical_url=_canonical_reference_url(job, external_id),
                metadata={
                    "title": title,
                    "location": location,
                    "internal_job_id": _optional_scalar(job, "internal_job_id"),
                    "updated_at": _optional_scalar(job, "updated_at"),
                },
            )
        )
    return tuple(listings)


def _select_job(document: Mapping[str, object], external_id: str) -> Mapping[str, object]:
    if "jobs" not in document:
        if str(_job_id(document)) != external_id:
            raise GreenhouseAdapterError(
                "listing_not_found",
                "Greenhouse detail did not match the requested public post ID.",
            )
        return document

    matches = [job for job in _listing_jobs(document) if str(_job_id(job)) == external_id]
    if len(matches) != 1:
        raise GreenhouseAdapterError(
            "listing_not_found",
            "Greenhouse snapshot did not contain exactly one requested public post.",
        )
    return matches[0]


def _group_names(job: Mapping[str, object], field: str) -> str | None:
    value = job.get(field)
    if value is None:
        return None
    if not isinstance(value, list):
        raise GreenhouseAdapterError(
            "layout_regression",
            "Greenhouse organization field changed to an unsupported shape.",
        )
    names = []
    for item in value:
        if not isinstance(item, dict):
            raise GreenhouseAdapterError(
                "layout_regression",
                "Greenhouse organization item changed to an unsupported shape.",
            )
        names.append(_required_string(item, "name", max_length=500))
    return " | ".join(names) or None


class GreenhouseJobBoardAdapter:
    adapter_key = _ADAPTER_KEY
    adapter_version = _PARSER_VERSION

    def __init__(
        self,
        *,
        config: SourceConfig = NAVER_VIETNAM_GREENHOUSE,
        http_fetch: HttpFetch | None = None,
    ) -> None:
        if (
            config.source_key != _SOURCE_KEY
            or config.adapter_key != self.adapter_key
            or config.approval_status is not SourceApprovalStatus.APPROVED
            or config.adapter_settings.get("board_token") != _BOARD_TOKEN
        ):
            raise ValueError("Greenhouse adapter requires the approved NAVER Vietnam config")
        self._config = config
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._last_result: FetchResult | None = None
        self._last_listings: dict[tuple[str, str], ListingRef] = {}

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise GreenhouseAdapterError(
                "source_config_mismatch",
                "Greenhouse run context did not match the approved source config.",
            )
        self._last_result = None
        self._last_listings = {}
        result = self._http_fetch(
            f"{self._config.base_url}/jobs?content=true",
            self._config.fetch_policy,
        )
        listings = _validated_listings(_load_json(result.payload))
        self._last_result = result
        self._last_listings = {
            (listing.external_id, listing.canonical_url): listing for listing in listings
        }
        return listings

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise GreenhouseAdapterError(
                "fetch_policy_mismatch",
                "Greenhouse fetch policy did not match the approved source config.",
            )
        expected = self._last_listings.get((listing_ref.external_id, listing_ref.canonical_url))
        if expected != listing_ref or self._last_result is None:
            raise GreenhouseAdapterError(
                "listing_not_discovered",
                "Greenhouse fetch requires a listing from the current complete discovery.",
            )
        return self._last_result

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        try:
            if snapshot.source_key != self._config.source_key:
                raise GreenhouseAdapterError(
                    "source_config_mismatch",
                    "Greenhouse snapshot source did not match the approved config.",
                )
            job = _select_job(_load_json(snapshot.raw_content), snapshot.external_id)
            external_id = str(_job_id(job))
            canonical_url = _canonical_reference_url(job, external_id)
            title_raw = _required_string(job, "title", max_length=500)
            location_raw = _location_name(job)
            if not _is_vietnam_location(location_raw):
                raise GreenhouseAdapterError(
                    "location_out_of_scope",
                    "Greenhouse job was outside the approved Vietnam scope.",
                )
            content_raw = _required_string(job, "content", max_length=2_000_000)
            description = html_to_text(content_raw)
            if description is None:
                raise GreenhouseAdapterError(
                    "empty_content",
                    "Greenhouse job content was empty after safe text extraction.",
                )

            title = normalize_text(title_raw)
            company = normalize_text(_COMPANY_NAME)
            location = normalize_location(location_raw)
            if title.value is None or company.value is None:
                raise GreenhouseAdapterError(
                    "layout_regression",
                    "Greenhouse required text became empty after normalization.",
                )

            source_fields = {
                "internal_job_id": _optional_scalar(job, "internal_job_id"),
                "requisition_id": _optional_scalar(job, "requisition_id"),
                "language": _optional_scalar(job, "language"),
                "updated_at": _optional_scalar(job, "updated_at"),
                "departments": _group_names(job, "departments"),
                "offices": _group_names(job, "offices"),
            }
            normalized_location = location.value
            evidence = [
                FieldEvidence(field_name="external_id", source_path="$.id"),
                FieldEvidence(field_name="canonical_url", source_path="$.absolute_url"),
                FieldEvidence(field_name="title", source_path="$.title"),
                FieldEvidence(field_name="company_name", source_path="source:naver-vietnam"),
                FieldEvidence(field_name="description", source_path="$.content"),
                FieldEvidence(field_name="location", source_path="$.location.name"),
            ]
            return ParsedJob(
                raw=RawJobFields(
                    external_id=external_id,
                    canonical_url=canonical_url,
                    title=title_raw,
                    company_name=_COMPANY_NAME,
                    description=description,
                    location=location_raw,
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
                ),
                evidence=tuple(evidence),
                parser_version=_PARSER_VERSION,
                warnings=(*location.warnings, "updated_at_not_used_as_posted_at"),
            )
        except GreenhouseAdapterError as error:
            return ParseFailure(
                error_code=error.code,
                stage="greenhouse_parse",
                safe_summary=error.safe_summary,
            )
