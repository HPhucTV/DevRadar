"""Safe deterministic inputs for V4 planner and validator responsibilities."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Never, Self
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from devradar.agents.application import ApplicationContext
from devradar.agents.decisions import (
    AgentModel,
    AnalystCaveatCode,
    AnalystClaimCode,
    AnalystTrendDirection,
    DecisionRef,
    DecisionRefKind,
    Responsibility,
    ValidatorRetryStrategy,
)
from devradar.api.analytics import (
    CohortField,
    SkillTrendQuery,
    SkillTrendResponse,
    TrendGranularity,
)
from devradar.automation.orchestrator import is_transient_error
from devradar.catalog.models import Job, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
    SourceHealthStatus,
)
from devradar.intelligence.extraction import EXTRACTION_SCHEMA_VERSION, ExtractionPayload
from devradar.intelligence.models import (
    ExtractionInputType,
    ExtractionResult,
    ExtractionType,
    ExtractionValidationStatus,
)

SAFE_REASON_PATTERN = r"^[a-z][a-z0-9_]{0,99}$"
_SAFE_REASON_RE = re.compile(SAFE_REASON_PATTERN)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ValidationIssue(AgentModel):
    """Bounded validation coordinates without rejected values."""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.\[\]-]{1,100}$",
    )
    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class PlannerFacts(AgentModel):
    schema_version: Literal["planner-facts-v1"] = "planner-facts-v1"
    source_ref: DecisionRef
    crawl_run_ref: DecisionRef | None = None
    approval_status: SourceApprovalStatus
    health_status: SourceHealthStatus
    health_reason_code: str | None = Field(default=None, pattern=SAFE_REASON_PATTERN)
    consecutive_failures: int = Field(ge=0)
    baseline_items_found: int | None = Field(default=None, ge=0)
    run_status: CrawlRunStatus | None = None
    coverage_status: CoverageStatus | None = None
    run_error_code: str | None = Field(default=None, pattern=SAFE_REASON_PATTERN)
    schedule_due: bool
    scheduled_action_allowed: bool
    retry_eligible: bool
    retry_attempt_number: int = Field(ge=1, le=3)


class ValidatorFacts(AgentModel):
    schema_version: Literal["validator-facts-v1"] = "validator-facts-v1"
    extraction_result_ref: DecisionRef
    raw_snapshot_ref: DecisionRef | None = None
    extractor_type: ExtractionType
    validation_status: ExtractionValidationStatus
    schema_version_current: bool
    input_hash_current: bool
    schema_valid: bool
    evidence_valid: bool
    validation_issues: tuple[ValidationIssue, ...] = Field(default=(), max_length=16)
    retry_eligible: bool
    retry_attempt_number: int = Field(ge=1, le=3)
    allowed_retry_strategies: tuple[ValidatorRetryStrategy, ...] = Field(
        default=(),
        max_length=1,
    )


CANONICAL_SKILL_PATTERN = r"^[a-z0-9][a-z0-9.+#-]{0,99}$"


class AnalystTrendBucketEvidence(AgentModel):
    period_start: date
    denominator: int = Field(ge=1)
    analyzed_jobs: int = Field(ge=0)
    coverage_basis_points: int = Field(ge=0, le=10_000)
    job_count: int = Field(ge=0)
    share_basis_points: int = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.analyzed_jobs > self.denominator or self.job_count > self.analyzed_jobs:
            raise ValueError("analyst bucket counts are inconsistent")
        return self


class AnalystTrendEvidence(AgentModel):
    schema_version: Literal["analyst-trend-evidence-v1"] = "analyst-trend-evidence-v1"
    from_date: date
    to_date: date
    cohort: CohortField
    granularity: TrendGranularity
    top_skills: int = Field(ge=1, le=20)
    status: JobStatus
    source_id: UUID | None = None
    taxonomy_version: str = Field(min_length=1, max_length=100, pattern=_VERSION_RE.pattern)
    extraction_schema_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=_VERSION_RE.pattern,
    )
    skill_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=CANONICAL_SKILL_PATTERN,
    )
    buckets: tuple[AnalystTrendBucketEvidence, ...] = Field(
        min_length=2,
        max_length=366,
    )

    @model_validator(mode="after")
    def validate_window_and_buckets(self) -> Self:
        if self.from_date > self.to_date or (self.to_date - self.from_date).days + 1 > 366:
            raise ValueError("analyst query window is invalid")
        starts = tuple(bucket.period_start for bucket in self.buckets)
        if starts != tuple(sorted(starts)) or len(set(starts)) != len(starts):
            raise ValueError("analyst buckets must be unique and ordered")
        for start in starts:
            if self.granularity is TrendGranularity.DAY:
                overlaps = self.from_date <= start <= self.to_date
            elif self.granularity is TrendGranularity.WEEK:
                overlaps = (
                    start.weekday() == 0
                    and start.toordinal() <= self.to_date.toordinal()
                    and start.toordinal() + 6 >= self.from_date.toordinal()
                )
            else:
                if start.year == 9999 and start.month == 12:
                    month_end = date.max
                else:
                    next_month = (
                        date(start.year + 1, 1, 1)
                        if start.month == 12
                        else date(start.year, start.month + 1, 1)
                    )
                    month_end = next_month - timedelta(days=1)
                overlaps = start.day == 1 and start <= self.to_date and month_end >= self.from_date
            if not overlaps:
                raise ValueError("analyst bucket does not overlap the query window")
        return self


class AnalystFacts(AgentModel):
    schema_version: Literal["analyst-facts-v1"] = "analyst-facts-v1"
    aggregate_query_ref: DecisionRef
    trend_metric_ref: DecisionRef
    from_date: date
    to_date: date
    cohort: CohortField
    granularity: TrendGranularity
    top_skills: int = Field(ge=1, le=20)
    status: JobStatus
    source_id: UUID | None = None
    taxonomy_version: str = Field(min_length=1, max_length=100, pattern=_VERSION_RE.pattern)
    extraction_schema_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=_VERSION_RE.pattern,
    )
    skill_name: str = Field(pattern=CANONICAL_SKILL_PATTERN)
    start_bucket: AnalystTrendBucketEvidence
    end_bucket: AnalystTrendBucketEvidence
    share_delta_basis_points: int = Field(ge=-10_000, le=10_000)
    trend_direction: AnalystTrendDirection
    required_caveat_codes: tuple[AnalystCaveatCode, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        delta = self.end_bucket.share_basis_points - self.start_bucket.share_basis_points
        direction = (
            AnalystTrendDirection.INCREASED
            if delta > 0
            else AnalystTrendDirection.DECREASED
            if delta < 0
            else AnalystTrendDirection.UNCHANGED
        )
        caveats = (
            (AnalystCaveatCode.LOW_COVERAGE,)
            if (
                self.start_bucket.coverage_basis_points < 10_000
                or self.end_bucket.coverage_basis_points < 10_000
            )
            else ()
        )
        if (
            self.aggregate_query_ref.kind is not DecisionRefKind.AGGREGATE_QUERY
            or self.trend_metric_ref.kind is not DecisionRefKind.METRIC
            or self.start_bucket.period_start >= self.end_bucket.period_start
            or self.share_delta_basis_points != delta
            or self.trend_direction is not direction
            or self.required_caveat_codes != caveats
        ):
            raise ValueError("analyst comparison facts are inconsistent")
        return self


class ResponsibilityInput(AgentModel):
    """Safe facts plus deterministic application policy for one responsibility."""

    schema_version: Literal["agent-responsibility-input-v1"] = "agent-responsibility-input-v1"
    responsibility: Responsibility
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=2)
    facts: PlannerFacts | ValidatorFacts | AnalystFacts
    application_context: ApplicationContext

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        expected_refs: tuple[DecisionRef, ...]
        if self.responsibility is Responsibility.PLANNER:
            if not isinstance(self.facts, PlannerFacts):
                raise ValueError("planner facts are required")
            expected_refs = (self.facts.source_ref,)
            if self.facts.crawl_run_ref is not None:
                expected_refs += (self.facts.crawl_run_ref,)
            expected_context = ApplicationContext(
                input_refs=expected_refs,
                scheduled_action_allowed=self.facts.scheduled_action_allowed,
                source_quarantined=(self.facts.health_status is SourceHealthStatus.QUARANTINED),
                retry_eligible=self.facts.retry_eligible,
                retry_attempt_number=self.facts.retry_attempt_number,
            )
        elif self.responsibility is Responsibility.VALIDATOR:
            if not isinstance(self.facts, ValidatorFacts):
                raise ValueError("validator facts are required")
            expected_refs = (self.facts.extraction_result_ref,)
            if self.facts.raw_snapshot_ref is not None:
                expected_refs += (self.facts.raw_snapshot_ref,)
            expected_context = ApplicationContext(
                input_refs=expected_refs,
                retry_eligible=self.facts.retry_eligible,
                retry_attempt_number=self.facts.retry_attempt_number,
                allowed_retry_strategies=self.facts.allowed_retry_strategies,
                validator_accept_allowed=(
                    self.facts.validation_status is ExtractionValidationStatus.ACCEPTED
                    and self.facts.schema_version_current
                    and self.facts.input_hash_current
                    and self.facts.schema_valid
                    and self.facts.evidence_valid
                    and not self.facts.validation_issues
                ),
            )
        elif self.responsibility is Responsibility.ANALYST:
            if not isinstance(self.facts, AnalystFacts):
                raise ValueError("analyst facts are required")
            expected_refs = (
                self.facts.aggregate_query_ref,
                self.facts.trend_metric_ref,
            )
            expected_context = ApplicationContext(
                input_refs=expected_refs,
                aggregate_has_denominator=True,
                aggregate_has_query_reference=True,
                supported_metric_refs=(self.facts.trend_metric_ref,),
                expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
                expected_analyst_trend_direction=self.facts.trend_direction,
                required_analyst_caveat_codes=self.facts.required_caveat_codes,
            )
        else:
            raise ValueError("responsibility facts do not match the responsibility")
        if self.input_refs != expected_refs:
            raise ValueError("responsibility input references do not match facts")
        if self.application_context != expected_context:
            raise ValueError("application context does not match deterministic facts")
        return self


class ResponsibilityBuildCode(StrEnum):
    MISSING_IDENTITY = "missing_identity"
    INVALID_SOURCE_STATE = "invalid_source_state"
    CRAWL_RUN_MISMATCH = "crawl_run_mismatch"
    UNSAFE_REASON_CODE = "unsafe_reason_code"
    EXTRACTION_MISMATCH = "extraction_mismatch"
    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    INVALID_RETRY_ATTEMPT = "invalid_retry_attempt"
    UNSAFE_VALIDATION_ISSUE = "unsafe_validation_issue"
    ANALYST_QUERY_MISMATCH = "analyst_query_mismatch"
    ANALYST_BUCKET_MISMATCH = "analyst_bucket_mismatch"
    ANALYST_ARITHMETIC_MISMATCH = "analyst_arithmetic_mismatch"
    INSUFFICIENT_ANALYST_COMPARISON = "insufficient_analyst_comparison"
    UNSAFE_ANALYST_INPUT = "unsafe_analyst_input"


_SAFE_BUILD_SUMMARIES = {
    ResponsibilityBuildCode.MISSING_IDENTITY: "Persisted responsibility identity is missing.",
    ResponsibilityBuildCode.INVALID_SOURCE_STATE: "Persisted source state is invalid.",
    ResponsibilityBuildCode.CRAWL_RUN_MISMATCH: "Crawl run does not belong to the source.",
    ResponsibilityBuildCode.UNSAFE_REASON_CODE: "Persisted reason code is unsafe.",
    ResponsibilityBuildCode.EXTRACTION_MISMATCH: "Extraction does not match the current job.",
    ResponsibilityBuildCode.SNAPSHOT_MISMATCH: "Snapshot does not match the current job.",
    ResponsibilityBuildCode.INVALID_RETRY_ATTEMPT: "Retry attempt is outside the fixed cap.",
    ResponsibilityBuildCode.UNSAFE_VALIDATION_ISSUE: "Validation issue is unsafe.",
    ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH: "Analyst query metadata is inconsistent.",
    ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH: "Analyst trend buckets are inconsistent.",
    ResponsibilityBuildCode.ANALYST_ARITHMETIC_MISMATCH: (
        "Analyst trend arithmetic is inconsistent."
    ),
    ResponsibilityBuildCode.INSUFFICIENT_ANALYST_COMPARISON: "Analyst trend needs two periods.",
    ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT: "Analyst trend input is unsafe.",
}


class ResponsibilityBuildError(RuntimeError):
    """Allow-listed builder failure with no free-form persisted content."""

    def __init__(self, code: ResponsibilityBuildCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.safe_summary = _SAFE_BUILD_SUMMARIES[code]


def _raise(code: ResponsibilityBuildCode) -> Never:
    raise ResponsibilityBuildError(code)


def _safe_reason(value: str | None) -> str | None:
    if value is not None and (
        not isinstance(value, str) or _SAFE_REASON_RE.fullmatch(value) is None
    ):
        _raise(ResponsibilityBuildCode.UNSAFE_REASON_CODE)
    return value


def _safe_hash(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _basis_points(
    numerator: object,
    denominator: object,
    *,
    code: ResponsibilityBuildCode,
) -> int:
    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or denominator <= 0
        or numerator < 0
        or numerator > denominator
    ):
        _raise(code)
    return (2 * numerator * 10_000 + denominator) // (2 * denominator)


def _analyst_direction(delta: int) -> AnalystTrendDirection:
    if delta > 0:
        return AnalystTrendDirection.INCREASED
    if delta < 0:
        return AnalystTrendDirection.DECREASED
    return AnalystTrendDirection.UNCHANGED


def _non_negative(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def project_analyst_trend_evidence(
    *,
    query: SkillTrendQuery,
    response: SkillTrendResponse,
    skill_name: str,
) -> AnalystTrendEvidence:
    if (
        not isinstance(skill_name, str)
        or re.fullmatch(CANONICAL_SKILL_PATTERN, skill_name) is None
        or _VERSION_RE.fullmatch(response.meta.taxonomy_version) is None
        or _VERSION_RE.fullmatch(response.meta.extraction_schema_version) is None
    ):
        _raise(ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT)
    if (
        response.meta.from_date != query.from_date
        or response.meta.to_date != query.to_date
        or response.meta.cohort is not query.cohort
        or response.meta.granularity is not query.granularity
    ):
        _raise(ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH)
    if len(response.data) < 2:
        _raise(ResponsibilityBuildCode.INSUFFICIENT_ANALYST_COMPARISON)
    starts = tuple(bucket.period_start for bucket in response.data)
    if starts != tuple(sorted(starts)) or len(set(starts)) != len(starts):
        _raise(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH)

    projected: list[AnalystTrendBucketEvidence] = []
    for bucket in response.data:
        matches = [item for item in bucket.skills if item.name == skill_name]
        if len(matches) != 1:
            _raise(ResponsibilityBuildCode.ANALYST_QUERY_MISMATCH)
        selected = matches[0]
        try:
            projected.append(
                AnalystTrendBucketEvidence(
                    period_start=bucket.period_start,
                    denominator=bucket.denominator,
                    analyzed_jobs=bucket.analyzed_jobs,
                    coverage_basis_points=_basis_points(
                        bucket.analyzed_jobs,
                        bucket.denominator,
                        code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
                    ),
                    job_count=selected.job_count,
                    share_basis_points=_basis_points(
                        selected.job_count,
                        bucket.denominator,
                        code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
                    ),
                )
            )
        except ValidationError:
            raise ResponsibilityBuildError(
                ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH
            ) from None
    try:
        return AnalystTrendEvidence(
            from_date=query.from_date,
            to_date=query.to_date,
            cohort=query.cohort,
            granularity=query.granularity,
            top_skills=query.top_skills,
            status=query.status,
            source_id=query.source_id,
            taxonomy_version=response.meta.taxonomy_version,
            extraction_schema_version=response.meta.extraction_schema_version,
            skill_name=skill_name,
            buckets=tuple(projected),
        )
    except ValidationError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH) from None


def build_analyst_responsibility(
    *,
    evidence: AnalystTrendEvidence,
) -> ResponsibilityInput:
    if (
        not isinstance(evidence, AnalystTrendEvidence)
        or not isinstance(evidence.skill_name, str)
        or re.fullmatch(CANONICAL_SKILL_PATTERN, evidence.skill_name) is None
        or not isinstance(evidence.taxonomy_version, str)
        or _VERSION_RE.fullmatch(evidence.taxonomy_version) is None
        or not isinstance(evidence.extraction_schema_version, str)
        or _VERSION_RE.fullmatch(evidence.extraction_schema_version) is None
    ):
        _raise(ResponsibilityBuildCode.UNSAFE_ANALYST_INPUT)
    try:
        evidence = AnalystTrendEvidence.model_validate(
            evidence.model_dump(mode="json", by_alias=True)
        )
    except ValidationError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH) from None
    for bucket in evidence.buckets:
        if bucket.coverage_basis_points != _basis_points(
            bucket.analyzed_jobs,
            bucket.denominator,
            code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
        ) or bucket.share_basis_points != _basis_points(
            bucket.job_count,
            bucket.denominator,
            code=ResponsibilityBuildCode.ANALYST_BUCKET_MISMATCH,
        ):
            _raise(ResponsibilityBuildCode.ANALYST_ARITHMETIC_MISMATCH)

    query_payload: dict[str, object] = {
        "cohort": evidence.cohort.value,
        "extractionSchemaVersion": evidence.extraction_schema_version,
        "from": evidence.from_date.isoformat(),
        "granularity": evidence.granularity.value,
        "sourceId": str(evidence.source_id) if evidence.source_id is not None else None,
        "status": evidence.status.value,
        "taxonomyVersion": evidence.taxonomy_version,
        "to": evidence.to_date.isoformat(),
        "topSkills": evidence.top_skills,
    }
    query_hash = _safe_hash(query_payload)
    query_ref = DecisionRef(
        kind=DecisionRefKind.AGGREGATE_QUERY,
        id="skill-trend-query:" + query_hash[:32],
        content_hash=query_hash,
        version="skill-trend-query-v1",
    )
    start_bucket = evidence.buckets[0]
    end_bucket = evidence.buckets[-1]
    delta = end_bucket.share_basis_points - start_bucket.share_basis_points
    direction = _analyst_direction(delta)
    caveats = (
        (AnalystCaveatCode.LOW_COVERAGE,)
        if (
            start_bucket.coverage_basis_points < 10_000 or end_bucket.coverage_basis_points < 10_000
        )
        else ()
    )
    metric_hash = _safe_hash(
        {
            "direction": direction.value,
            "endBucket": end_bucket.model_dump(mode="json", by_alias=True),
            "queryHash": query_hash,
            "requiredCaveatCodes": [item.value for item in caveats],
            "shareDeltaBasisPoints": delta,
            "skill": evidence.skill_name,
            "startBucket": start_bucket.model_dump(mode="json", by_alias=True),
        }
    )
    metric_ref = DecisionRef(
        kind=DecisionRefKind.METRIC,
        id="skill-trend-metric:" + metric_hash[:32],
        content_hash=metric_hash,
        version="skill-trend-comparison-v1",
    )
    facts = AnalystFacts(
        aggregate_query_ref=query_ref,
        trend_metric_ref=metric_ref,
        from_date=evidence.from_date,
        to_date=evidence.to_date,
        cohort=evidence.cohort,
        granularity=evidence.granularity,
        top_skills=evidence.top_skills,
        status=evidence.status,
        source_id=evidence.source_id,
        taxonomy_version=evidence.taxonomy_version,
        extraction_schema_version=evidence.extraction_schema_version,
        skill_name=evidence.skill_name,
        start_bucket=start_bucket,
        end_bucket=end_bucket,
        share_delta_basis_points=delta,
        trend_direction=direction,
        required_caveat_codes=caveats,
    )
    input_refs = (query_ref, metric_ref)
    context = ApplicationContext(
        input_refs=input_refs,
        aggregate_has_denominator=True,
        aggregate_has_query_reference=True,
        supported_metric_refs=(metric_ref,),
        expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
        expected_analyst_trend_direction=direction,
        required_analyst_caveat_codes=caveats,
    )
    return ResponsibilityInput(
        responsibility=Responsibility.ANALYST,
        input_refs=input_refs,
        facts=facts,
        application_context=context,
    )


def build_planner_responsibility(
    *,
    source: Source,
    crawl_run: CrawlRun | None,
    schedule_due: bool,
) -> ResponsibilityInput:
    """Derive planner facts and permissions without copying source content."""

    if not isinstance(source.id, UUID):
        _raise(ResponsibilityBuildCode.MISSING_IDENTITY)
    if not _non_negative(source.consecutive_failures) or (
        source.baseline_items_found is not None and not _non_negative(source.baseline_items_found)
    ):
        _raise(ResponsibilityBuildCode.INVALID_SOURCE_STATE)
    try:
        approval_status = SourceApprovalStatus(source.approval_status)
        health_status = SourceHealthStatus(source.health_status)
    except ValueError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.INVALID_SOURCE_STATE) from None
    quarantined = health_status is SourceHealthStatus.QUARANTINED
    if quarantined != (source.quarantined_at is not None):
        _raise(ResponsibilityBuildCode.INVALID_SOURCE_STATE)
    health_reason_code = _safe_reason(source.health_reason_code)

    source_ref = DecisionRef(
        kind=DecisionRefKind.SOURCE,
        id=str(source.id),
        content_hash=_safe_hash(
            {
                "approvalStatus": approval_status.value,
                "baselineItemsFound": source.baseline_items_found,
                "consecutiveFailures": source.consecutive_failures,
                "healthReasonCode": health_reason_code,
                "healthStatus": health_status.value,
            }
        ),
        version="planner-source-v1",
    )

    crawl_run_ref = None
    run_status = None
    coverage_status = None
    run_error_code = None
    retry_attempt_number = 1
    if crawl_run is not None:
        if not isinstance(crawl_run.id, UUID):
            _raise(ResponsibilityBuildCode.MISSING_IDENTITY)
        if crawl_run.source_id != source.id:
            _raise(ResponsibilityBuildCode.CRAWL_RUN_MISMATCH)
        if not _non_negative(crawl_run.attempt_number) or not 1 <= crawl_run.attempt_number <= 3:
            _raise(ResponsibilityBuildCode.INVALID_RETRY_ATTEMPT)
        try:
            run_status = CrawlRunStatus(crawl_run.status)
            coverage_status = CoverageStatus(crawl_run.coverage_status)
        except ValueError:
            raise ResponsibilityBuildError(ResponsibilityBuildCode.CRAWL_RUN_MISMATCH) from None
        run_error_code = _safe_reason(crawl_run.error_code)
        retry_attempt_number = crawl_run.attempt_number
        crawl_run_ref = DecisionRef(
            kind=DecisionRefKind.CRAWL_RUN,
            id=str(crawl_run.id),
            content_hash=_safe_hash(
                {
                    "attemptNumber": retry_attempt_number,
                    "coverageStatus": coverage_status.value,
                    "errorCode": run_error_code,
                    "status": run_status.value,
                }
            ),
            version="planner-crawl-run-v1",
        )

    source_action_allowed = approval_status is SourceApprovalStatus.APPROVED and not quarantined
    scheduled_action_allowed = schedule_due and source_action_allowed
    retry_eligible = (
        source_action_allowed
        and run_status in {CrawlRunStatus.FAILED, CrawlRunStatus.PARTIAL}
        and retry_attempt_number < 3
        and is_transient_error(run_error_code)
    )
    facts = PlannerFacts(
        source_ref=source_ref,
        crawl_run_ref=crawl_run_ref,
        approval_status=approval_status,
        health_status=health_status,
        health_reason_code=health_reason_code,
        consecutive_failures=source.consecutive_failures,
        baseline_items_found=source.baseline_items_found,
        run_status=run_status,
        coverage_status=coverage_status,
        run_error_code=run_error_code,
        schedule_due=schedule_due,
        scheduled_action_allowed=scheduled_action_allowed,
        retry_eligible=retry_eligible,
        retry_attempt_number=retry_attempt_number,
    )
    input_refs = (source_ref,) if crawl_run_ref is None else (source_ref, crawl_run_ref)
    context = ApplicationContext(
        input_refs=input_refs,
        scheduled_action_allowed=scheduled_action_allowed,
        source_quarantined=quarantined,
        retry_eligible=retry_eligible,
        retry_attempt_number=retry_attempt_number,
    )
    return ResponsibilityInput(
        responsibility=Responsibility.PLANNER,
        input_refs=input_refs,
        facts=facts,
        application_context=context,
    )


def _validation_issues(raw_issues: object) -> list[ValidationIssue]:
    if raw_issues is None:
        return []
    if not isinstance(raw_issues, list) or len(raw_issues) > 16:
        _raise(ResponsibilityBuildCode.UNSAFE_VALIDATION_ISSUE)
    issues: list[ValidationIssue] = []
    try:
        for raw_issue in raw_issues:
            issues.append(ValidationIssue.model_validate(raw_issue))
    except ValidationError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.UNSAFE_VALIDATION_ISSUE) from None
    return issues


def _append_issue(issues: list[ValidationIssue], code: str, path: str) -> None:
    issue = ValidationIssue(code=code, path=path, type="validation")
    if issue not in issues:
        issues.append(issue)


def _validate_extraction_content(
    extraction_result: ExtractionResult,
    job: Job,
    issues: list[ValidationIssue],
) -> tuple[bool, bool]:
    try:
        payload = ExtractionPayload.model_validate(extraction_result.output_data)
    except ValidationError:
        _append_issue(issues, "schema_invalid", "output")
        return False, False

    skill_keys = [(skill.name, skill.requirement_type) for skill in payload.skills]
    source_text = f"{job.title}\n{job.description_text or ''}"
    evidence_valid = len(skill_keys) == len(set(skill_keys)) and all(
        skill.evidence in source_text for skill in payload.skills
    )
    if not evidence_valid:
        _append_issue(issues, "evidence_invalid", "skills")
    return True, evidence_valid


def build_validator_responsibility(
    *,
    extraction_result: ExtractionResult,
    job: Job,
    raw_snapshot: RawJobSnapshot | None,
    retry_attempt_number: int,
) -> ResponsibilityInput:
    """Validate extraction content locally and emit only safe facts and refs."""

    if not isinstance(job.id, UUID) or not isinstance(extraction_result.id, UUID):
        _raise(ResponsibilityBuildCode.MISSING_IDENTITY)
    if (
        extraction_result.input_type != ExtractionInputType.JOB.value
        or extraction_result.input_ref != job.id
        or not _valid_hash(extraction_result.input_hash)
        or not _valid_hash(job.job_content_hash)
        or not isinstance(extraction_result.schema_version, str)
        or _VERSION_RE.fullmatch(extraction_result.schema_version) is None
    ):
        _raise(ResponsibilityBuildCode.EXTRACTION_MISMATCH)
    if not _non_negative(retry_attempt_number) or not 1 <= retry_attempt_number <= 3:
        _raise(ResponsibilityBuildCode.INVALID_RETRY_ATTEMPT)
    try:
        extractor_type = ExtractionType(extraction_result.extractor_type)
        validation_status = ExtractionValidationStatus(extraction_result.validation_status)
    except ValueError:
        raise ResponsibilityBuildError(ResponsibilityBuildCode.EXTRACTION_MISMATCH) from None

    raw_snapshot_ref = None
    if raw_snapshot is not None:
        if not isinstance(raw_snapshot.id, UUID):
            _raise(ResponsibilityBuildCode.MISSING_IDENTITY)
        if (
            raw_snapshot.id != job.current_snapshot_id
            or raw_snapshot.source_id != job.source_id
            or not _valid_hash(raw_snapshot.raw_content_hash)
        ):
            _raise(ResponsibilityBuildCode.SNAPSHOT_MISMATCH)
        raw_snapshot_ref = DecisionRef(
            kind=DecisionRefKind.RAW_SNAPSHOT,
            id=str(raw_snapshot.id),
            content_hash=raw_snapshot.raw_content_hash,
            version="raw-snapshot-v1",
        )

    issues = _validation_issues(extraction_result.validation_errors)
    schema_version_current = extraction_result.schema_version == EXTRACTION_SCHEMA_VERSION
    input_hash_current = extraction_result.input_hash == job.job_content_hash
    schema_valid, evidence_valid = _validate_extraction_content(extraction_result, job, issues)
    if not schema_version_current:
        _append_issue(issues, "stale_schema", "schemaVersion")
    if not input_hash_current:
        _append_issue(issues, "stale_input_hash", "inputHash")
    if len(issues) > 16:
        _raise(ResponsibilityBuildCode.UNSAFE_VALIDATION_ISSUE)

    extraction_ref = DecisionRef(
        kind=DecisionRefKind.EXTRACTION_RESULT,
        id=str(extraction_result.id),
        content_hash=extraction_result.input_hash,
        version=extraction_result.schema_version,
    )
    validator_accept_allowed = (
        validation_status is ExtractionValidationStatus.ACCEPTED
        and schema_version_current
        and input_hash_current
        and schema_valid
        and evidence_valid
        and not issues
    )
    retry_eligible = not validator_accept_allowed and retry_attempt_number < 3
    allowed_retry_strategies = (
        (ValidatorRetryStrategy.DETERMINISTIC_REPARSE,) if retry_eligible else ()
    )
    facts = ValidatorFacts(
        extraction_result_ref=extraction_ref,
        raw_snapshot_ref=raw_snapshot_ref,
        extractor_type=extractor_type,
        validation_status=validation_status,
        schema_version_current=schema_version_current,
        input_hash_current=input_hash_current,
        schema_valid=schema_valid,
        evidence_valid=evidence_valid,
        validation_issues=tuple(issues),
        retry_eligible=retry_eligible,
        retry_attempt_number=retry_attempt_number,
        allowed_retry_strategies=allowed_retry_strategies,
    )
    input_refs = (
        (extraction_ref,) if raw_snapshot_ref is None else (extraction_ref, raw_snapshot_ref)
    )
    context = ApplicationContext(
        input_refs=input_refs,
        retry_eligible=retry_eligible,
        retry_attempt_number=retry_attempt_number,
        allowed_retry_strategies=allowed_retry_strategies,
        validator_accept_allowed=validator_accept_allowed,
    )
    return ResponsibilityInput(
        responsibility=Responsibility.VALIDATOR,
        input_refs=input_refs,
        facts=facts,
        application_context=context,
    )


__all__ = [
    "AnalystFacts",
    "AnalystTrendBucketEvidence",
    "AnalystTrendEvidence",
    "PlannerFacts",
    "ResponsibilityBuildCode",
    "ResponsibilityBuildError",
    "ResponsibilityInput",
    "ValidationIssue",
    "ValidatorFacts",
    "build_analyst_responsibility",
    "build_planner_responsibility",
    "build_validator_responsibility",
    "project_analyst_trend_evidence",
]
