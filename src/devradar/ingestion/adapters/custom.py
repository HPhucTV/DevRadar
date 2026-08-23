"""Owner-scoped custom source adapter backed by the hybrid deterministic parser."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from devradar.custom_sources.models import CustomSourceProfileDraft
from devradar.custom_sources.parser import CustomCandidate, HybridCustomParser
from devradar.custom_sources.policy import (
    CustomFetchOutcome,
    build_custom_fetch_policy,
    classify_custom_response,
)
from devradar.ingestion.adapters.html_text import html_to_text
from devradar.ingestion.contracts import (
    FetchResult,
    FieldEvidence,
    JobSourceAdapter,
    ListingRef,
    NormalizedJobCandidates,
    ParsedJob,
    ParseFailure,
    RawJobFields,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.normalization import normalize_location, normalize_text
from devradar.ingestion.safe_http import FetchError, FetchErrorCode, FetchPolicy, SafeHttpFetcher

HttpFetch = Callable[[str, FetchPolicy], FetchResult]


class CustomSourceAdapterError(RuntimeError):
    def __init__(self, code: str, safe_summary: str, *, retryable: bool = False) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.retryable = retryable


def _safe_fetch_error(error: FetchError) -> CustomSourceAdapterError:
    if error.http_status in {401, 402, 403} or error.code is FetchErrorCode.HTTP_ERROR:
        return CustomSourceAdapterError("permission_required", "Source requires permission.")
    if error.code is FetchErrorCode.RATE_LIMITED:
        return CustomSourceAdapterError(
            "rate_limited", "Source rate limited the request.", retryable=True
        )
    return CustomSourceAdapterError(
        error.code.value, "Custom source request failed.", retryable=error.retryable
    )


class CustomSourceAdapter(JobSourceAdapter):
    adapter_key = "custom_source"
    adapter_version = "custom-hybrid-v1"

    def __init__(
        self,
        *,
        source_key: str,
        profile: CustomSourceProfileDraft,
        http_fetch: HttpFetch | None = None,
        parser: HybridCustomParser | None = None,
    ) -> None:
        if not source_key.strip():
            raise ValueError("source_key must not be blank")
        self._source_key = source_key
        self._profile = profile
        self._fetch_policy = build_custom_fetch_policy(profile)
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._parser = parser or HybridCustomParser()
        self._last_results: dict[tuple[str, str], FetchResult] = {}
        self._last_candidates: dict[tuple[str, str], CustomCandidate] = {}

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        source_key = getattr(run_context.source, "source_key", self._source_key)
        if source_key != self._source_key:
            raise CustomSourceAdapterError(
                "source_config_mismatch",
                "Custom source run context did not match the saved profile.",
            )
        self._last_results = {}
        self._last_candidates = {}
        try:
            result = self._http_fetch(self._profile.base_url, self._fetch_policy)
        except FetchError as error:
            raise _safe_fetch_error(error) from error
        classification = classify_custom_response(
            result.http_status,
            result.content_type,
            result.payload[:8192],
        )
        if classification.outcome is not CustomFetchOutcome.SUCCESS:
            raise CustomSourceAdapterError(
                classification.safe_reason,
                "Custom source response was blocked by policy.",
                retryable=classification.retryable,
            )
        parsed = self._parser.parse(
            result.payload,
            result.content_type,
            self._profile.field_mapping,
        )
        if parsed.failures:
            failure = parsed.failures[0]
            raise CustomSourceAdapterError(failure.code, failure.safe_summary)
        listings: list[ListingRef] = []
        for candidate in parsed.candidates:
            listing = ListingRef(
                external_id=candidate.external_id,
                canonical_url=candidate.job_url,
                metadata={
                    "title": candidate.title,
                    "company": candidate.company,
                    "parser_confidence": candidate.confidence,
                },
            )
            key = (listing.external_id, listing.canonical_url)
            self._last_results[key] = result
            self._last_candidates[key] = candidate
            listings.append(listing)
        if not listings:
            raise CustomSourceAdapterError(
                "empty_result", "Custom source returned no job candidates."
            )
        return tuple(listings)

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._fetch_policy:
            raise CustomSourceAdapterError(
                "fetch_policy_mismatch",
                "Custom source fetch policy did not match the saved profile.",
            )
        result = self._last_results.get((listing_ref.external_id, listing_ref.canonical_url))
        if result is None:
            raise CustomSourceAdapterError(
                "listing_not_discovered",
                "Custom source fetch requires a listing from the current discovery.",
            )
        return result

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        if snapshot.source_key != self._source_key:
            return ParseFailure(
                error_code="source_config_mismatch",
                stage="custom_parse",
                safe_summary="Custom source snapshot did not match the saved profile.",
            )
        result = self._parser.parse(
            snapshot.raw_content,
            snapshot.content_type,
            self._profile.field_mapping,
        )
        if result.failures:
            failure = result.failures[0]
            return ParseFailure(
                error_code=failure.code,
                stage="custom_parse",
                safe_summary=failure.safe_summary,
            )
        candidates = [
            candidate
            for candidate in result.candidates
            if candidate.external_id == snapshot.external_id
        ]
        if len(candidates) != 1:
            return ParseFailure(
                error_code="listing_not_found",
                stage="custom_parse",
                safe_summary="Custom source snapshot did not contain the requested job.",
            )
        candidate = candidates[0]
        if candidate.job_url != snapshot.source_url:
            return ParseFailure(
                error_code="provenance_mismatch",
                stage="custom_parse",
                safe_summary="Custom source snapshot URL did not match the requested job.",
            )
        return self._to_parsed_job(candidate)

    def _to_parsed_job(self, candidate: CustomCandidate) -> ParsedJob | ParseFailure:
        title = normalize_text(candidate.title)
        company = normalize_text(candidate.company)
        if title.value is None or company.value is None:
            return ParseFailure(
                error_code="missing_required_field",
                stage="custom_parse",
                safe_summary="Custom source required fields were empty after normalization.",
            )
        description = (
            html_to_text(candidate.description or "") or normalize_text(candidate.description).value
        )
        location = normalize_location(candidate.location)
        posted_at: datetime | None = None
        warnings = [*location.warnings]
        if candidate.posted_at:
            try:
                posted_at = datetime.fromisoformat(candidate.posted_at.replace("Z", "+00:00"))
                if posted_at.tzinfo is None or posted_at.utcoffset() is None:
                    warnings.append("posted_at_timezone_missing")
                    posted_at = None
                else:
                    posted_at = posted_at.astimezone(UTC)
            except ValueError:
                warnings.append("posted_at_invalid")
        evidence = tuple(
            FieldEvidence(field_name=item.field_name, source_path=item.source_path)
            for item in candidate.provenance
            if item.field_name
            in {"title", "company", "external_id", "job_url", "location", "description"}
        )
        if not evidence:
            return ParseFailure(
                error_code="missing_provenance",
                stage="custom_parse",
                safe_summary="Custom source candidate did not contain field provenance.",
            )
        normalized_location = location.value
        return ParsedJob(
            raw=RawJobFields(
                external_id=candidate.external_id,
                canonical_url=candidate.job_url,
                title=candidate.title,
                company_name=candidate.company,
                description=description,
                location=candidate.location,
                salary=candidate.salary,
                posted_at=candidate.posted_at,
                source_fields={"parser_confidence": candidate.confidence},
            ),
            normalized_candidates=NormalizedJobCandidates(
                title=title.value,
                company_name=company.value,
                description_text=description,
                location_city=normalized_location.city if normalized_location else None,
                location_province=normalized_location.province if normalized_location else None,
                work_mode=(
                    normalized_location.work_mode.value
                    if normalized_location and normalized_location.work_mode
                    else None
                ),
                posted_at=posted_at,
            ),
            evidence=evidence,
            parser_version=candidate.parser_version,
            warnings=tuple(warnings),
        )
