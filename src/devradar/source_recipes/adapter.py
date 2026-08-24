"""Generic deterministic listing/detail adapter for persisted source recipes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from devradar.catalog.models import JobLevel
from devradar.ingestion.adapters.html_text import html_to_text
from devradar.ingestion.contracts import (
    DiscoverySummary,
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
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.ingestion.normalization import normalize_levels, normalize_location, normalize_text
from devradar.ingestion.safe_http import (
    FetchError,
    FetchErrorCode,
    SafeHttpFetcher,
    validate_fetch_target,
)
from devradar.ingestion.source_registry import (
    DiscoveryMode,
    FetchPolicy,
    IdentityStrategy,
    PolicyReview,
    PolicyScope,
    SourceConfig,
)
from devradar.source_recipes.models import SourceRecipe, SourceRecipeError
from devradar.source_recipes.parser import (
    PARSER_VERSION,
    PreviewCandidate,
    extract_pagination_targets,
    parse_recipe_document,
)
from devradar.source_recipes.policy import build_recipe_fetch_policy, normalize_listing_url

HttpFetch = Callable[[str, FetchPolicy], FetchResult]


class RecipeAdapterError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_summary: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class SeniorityFilterResult:
    included: tuple[PreviewCandidate, ...]
    filtered_out: int


def filter_candidates(
    *,
    candidates: tuple[PreviewCandidate, ...],
    selected: tuple[JobLevel, ...] | str,
) -> SeniorityFilterResult:
    if selected == "all":
        return SeniorityFilterResult(candidates, 0)
    selected_set = set(selected)
    included: list[PreviewCandidate] = []
    for candidate in candidates:
        evidence = (
            candidate.level_raw
            if normalize_text(candidate.level_raw).value is not None
            else candidate.title
        )
        levels = normalize_levels(evidence).value or ()
        if selected_set.intersection(levels):
            included.append(candidate)
    return SeniorityFilterResult(tuple(included), len(candidates) - len(included))


def recipe_fetch_policy(recipe: SourceRecipe) -> FetchPolicy:
    return build_recipe_fetch_policy(
        normalize_listing_url(recipe.listing_url),
        allowed_hosts=tuple(recipe.allowed_hosts),
        allowed_path_prefixes=tuple(recipe.allowed_path_prefixes),
        byte_budget=recipe.byte_budget,
        requests_per_minute=recipe.requests_per_minute,
    )


def recipe_source_config(recipe: SourceRecipe, source: Source) -> SourceConfig:
    if recipe.source_id is not None and source.id != recipe.source_id:
        raise SourceRecipeError("source_config_mismatch")
    reviewed_on = (
        recipe.terms_reviewed_at.date()
        if recipe.terms_reviewed_at is not None
        else date(2026, 8, 24)
    )
    return SourceConfig(
        source_key=f"recipe-{recipe.id.hex}",
        name=source.name,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        base_url=recipe.origin,
        adapter_key=RecipeAdapter.adapter_key,
        discovery_mode=DiscoveryMode.SERVER_RENDERED_HTML,
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        external_id_field="external_id",
        expected_pagination="bounded_recipe_mapping",
        fetch_policy=recipe_fetch_policy(recipe),
        policy_review=PolicyReview(
            scope=PolicyScope.PERMISSION_REQUIRED,
            robots_reviewed_at=reviewed_on,
            terms_reviewed_at=reviewed_on,
            next_review_at=reviewed_on + timedelta(days=90),
        ),
        config_version=recipe.mapping_version or recipe.config_version,
    )


def _fetch_error(error: FetchError) -> RecipeAdapterError:
    if error.http_status in {401, 403}:
        return RecipeAdapterError("access_denied", "Source denied public access.")
    if error.http_status == 402:
        return RecipeAdapterError("payment_required", "Source requires payment.")
    if error.code in {
        FetchErrorCode.INVALID_URL,
        FetchErrorCode.POLICY_BLOCKED,
        FetchErrorCode.REDIRECT_BLOCKED,
    }:
        return RecipeAdapterError("route_policy_blocked", "Source route was blocked.")
    return RecipeAdapterError(
        error.code.value,
        "Source request failed safely.",
        retryable=error.retryable,
        retry_after_seconds=error.retry_after_seconds,
    )


class RecipeAdapter(JobSourceAdapter):
    adapter_key = "source_recipe"
    adapter_version = f"recipe-adapter-{PARSER_VERSION}"

    def __init__(
        self,
        *,
        recipe: SourceRecipe,
        config: SourceConfig,
        http_fetch: HttpFetch | None = None,
    ) -> None:
        if config.adapter_key != self.adapter_key or config.source_key != f"recipe-{recipe.id.hex}":
            raise ValueError("recipe adapter configuration does not match recipe identity")
        if config.fetch_policy != recipe_fetch_policy(recipe):
            raise ValueError("recipe adapter fetch policy does not match persisted recipe")
        self._recipe = recipe
        self._config = config
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._candidates: dict[tuple[str, str], PreviewCandidate] = {}
        self._requests_used = 0
        self._summary = DiscoverySummary(0, 0, 0, False)

    @property
    def discovery_summary(self) -> DiscoverySummary:
        return self._summary

    def _fetch(self, url: str) -> FetchResult:
        if self._requests_used >= self._recipe.request_budget:
            raise RecipeAdapterError(
                "request_budget_exceeded", "Source request budget was exhausted."
            )
        self._requests_used += 1
        try:
            return self._http_fetch(url, self._config.fetch_policy)
        except FetchError as error:
            raise _fetch_error(error) from None

    def _selected_levels(self) -> tuple[JobLevel, ...] | str:
        if self._recipe.seniority_filter == ["all"]:
            return "all"
        try:
            return tuple(JobLevel(value) for value in self._recipe.seniority_filter)
        except ValueError as error:
            raise RecipeAdapterError(
                "seniority_filter_invalid", "Recipe seniority is invalid."
            ) from error

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise RecipeAdapterError("source_config_mismatch", "Recipe run config did not match.")
        self._candidates = {}
        self._requests_used = 0
        current_url = self._recipe.listing_url
        visited: set[str] = set()
        discovered: list[PreviewCandidate] = []
        seen_urls: set[str] = set()
        seen_ids: set[str] = set()
        pages_found = 0
        coverage_complete = True
        recipe_deadline = datetime.now(UTC) + timedelta(seconds=self._recipe.time_budget_seconds)
        effective_deadline = min(run_context.deadline, recipe_deadline)

        while current_url:
            if datetime.now(UTC) >= effective_deadline:
                coverage_complete = False
                break
            if current_url in visited or pages_found >= self._recipe.page_budget:
                coverage_complete = False
                break
            visited.add(current_url)
            page = self._fetch(current_url)
            pages_found += 1
            try:
                candidates = parse_recipe_document(
                    page.payload,
                    content_type=page.content_type,
                    base_url=page.final_url,
                    mapping=self._recipe.field_mapping,
                )
                targets = extract_pagination_targets(
                    page.payload,
                    content_type=page.content_type,
                    base_url=page.final_url,
                    mapping=self._recipe.pagination_mapping,
                )
            except SourceRecipeError as error:
                raise RecipeAdapterError(
                    error.code, "Source listing could not be parsed."
                ) from None
            for candidate in candidates:
                if candidate.job_url in seen_urls or candidate.external_id in seen_ids:
                    continue
                try:
                    validate_fetch_target(candidate.job_url, self._config.fetch_policy)
                except FetchError:
                    raise RecipeAdapterError(
                        "route_policy_blocked", "Discovered job URL left the saved boundary."
                    ) from None
                seen_urls.add(candidate.job_url)
                seen_ids.add(candidate.external_id)
                discovered.append(candidate)
                if len(discovered) >= self._recipe.item_budget:
                    coverage_complete = False
                    break
            if not coverage_complete:
                break
            if not targets:
                current_url = ""
                continue
            next_url = targets[0]
            if next_url in visited:
                coverage_complete = False
                break
            try:
                current_url = validate_fetch_target(next_url, self._config.fetch_policy)
            except FetchError:
                raise RecipeAdapterError(
                    "route_policy_blocked", "Pagination target left the saved boundary."
                ) from None

        filtered = filter_candidates(
            candidates=tuple(discovered),
            selected=self._selected_levels(),
        )
        listings: list[ListingRef] = []
        for candidate in filtered.included:
            key = (candidate.external_id, candidate.job_url)
            self._candidates[key] = candidate
            listings.append(
                ListingRef(
                    external_id=candidate.external_id,
                    canonical_url=candidate.job_url,
                    metadata={"level_raw": candidate.level_raw},
                )
            )
        self._summary = DiscoverySummary(
            items_discovered=len(discovered),
            items_filtered_out=filtered.filtered_out,
            pages_found=pages_found,
            coverage_complete=coverage_complete,
        )
        return tuple(listings)

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise RecipeAdapterError("fetch_policy_mismatch", "Recipe fetch policy changed.")
        if (listing_ref.external_id, listing_ref.canonical_url) not in self._candidates:
            raise RecipeAdapterError("listing_not_discovered", "Job was not in current discovery.")
        return self._fetch(listing_ref.canonical_url)

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        if snapshot.source_key != self._config.source_key:
            return ParseFailure(
                error_code="source_config_mismatch",
                stage="recipe_parse",
                safe_summary="Snapshot did not match the recipe source.",
            )
        listing_candidate = self._candidates.get((snapshot.external_id, snapshot.source_url))
        if listing_candidate is None:
            return ParseFailure(
                error_code="listing_not_discovered",
                stage="recipe_parse",
                safe_summary="Snapshot identity was not discovered in this run.",
            )
        try:
            detail_candidates = parse_recipe_document(
                snapshot.raw_content,
                content_type=snapshot.content_type,
                base_url=snapshot.source_url,
                mapping=self._recipe.field_mapping,
            )
        except SourceRecipeError:
            detail_candidates = ()
        detail = next(
            (
                candidate
                for candidate in detail_candidates
                if candidate.external_id == snapshot.external_id
                or candidate.job_url == snapshot.source_url
            ),
            None,
        )
        candidate = (
            listing_candidate
            if detail is None
            else replace(
                detail,
                external_id=listing_candidate.external_id,
                job_url=listing_candidate.job_url,
            )
        )
        return self._to_parsed_job(candidate)

    def _to_parsed_job(self, candidate: PreviewCandidate) -> ParsedJob | ParseFailure:
        title = normalize_text(candidate.title)
        company = normalize_text(candidate.company)
        if title.value is None or company.value is None:
            return ParseFailure(
                error_code="missing_required_field",
                stage="recipe_parse",
                safe_summary="Required job fields were blank after normalization.",
            )
        description = (
            html_to_text(candidate.description or "") or normalize_text(candidate.description).value
        )
        location = normalize_location(candidate.location)
        level_evidence = (
            candidate.level_raw
            if normalize_text(candidate.level_raw).value is not None
            else candidate.title
        )
        levels = normalize_levels(level_evidence).value or ()
        posted_at: datetime | None = None
        warnings = [*candidate.warnings, *location.warnings]
        if candidate.posted_at:
            try:
                parsed_time = datetime.fromisoformat(candidate.posted_at.replace("Z", "+00:00"))
                if parsed_time.tzinfo is not None and parsed_time.utcoffset() is not None:
                    posted_at = parsed_time.astimezone(UTC)
                else:
                    warnings.append("posted_at_timezone_missing")
            except ValueError:
                warnings.append("posted_at_invalid")
        evidence = tuple(
            FieldEvidence(field_name=item.field_name, source_path=item.source_path)
            for item in candidate.provenance
        )
        if not evidence:
            return ParseFailure(
                error_code="missing_provenance",
                stage="recipe_parse",
                safe_summary="Parsed job did not contain field provenance.",
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
                level=candidate.level_raw,
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
                levels=tuple(level.value for level in levels),
                posted_at=posted_at,
            ),
            evidence=evidence,
            parser_version=candidate.parser_version,
            warnings=tuple(warnings),
        )
