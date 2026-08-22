"""Deterministic-first job extraction contract and provider boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.catalog.models import Job, JobLevel
from devradar.ingestion.normalization import SalaryPeriod, WorkMode
from devradar.intelligence.evaluation import (
    EvaluationModel,
    ExperienceExpectation,
    LocationExpectation,
    SalaryExpectation,
    SkillExpectation,
    canonicalize_skill_name,
    extract_skill_expectations,
)
from devradar.intelligence.models import (
    ExtractionInputType,
    ExtractionResult,
    ExtractionType,
    ExtractionValidationStatus,
)

DETERMINISTIC_EXTRACTOR_VERSION = "deterministic-job-v1"
EXTRACTION_SCHEMA_VERSION = "job-extraction-schema-v1"
CANONICALIZATION_VERSION = "extraction-canonicalization-v1"


class ExtractionPayload(EvaluationModel):
    levels: tuple[JobLevel, ...]
    experience: ExperienceExpectation
    salary: SalaryExpectation
    location: LocationExpectation
    skills: tuple[SkillExpectation, ...]


@dataclass(frozen=True, slots=True)
class DeterministicExtraction:
    payload: ExtractionPayload
    complete: bool
    extractor_version: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionCacheKey:
    input_type: ExtractionInputType
    input_ref: UUID
    input_hash: str
    extractor_type: ExtractionType
    extractor_version: str
    schema_version: str
    prompt_version: str | None
    model: str | None
    canonicalization_version: str


def load_accepted_cache(session: Session, key: ExtractionCacheKey) -> ExtractionResult | None:
    return session.scalar(
        select(ExtractionResult).where(
            ExtractionResult.input_type == key.input_type.value,
            ExtractionResult.input_ref == key.input_ref,
            ExtractionResult.input_hash == key.input_hash,
            ExtractionResult.extractor_type == key.extractor_type.value,
            ExtractionResult.extractor_version == key.extractor_version,
            ExtractionResult.schema_version == key.schema_version,
            ExtractionResult.prompt_version.is_not_distinct_from(key.prompt_version),
            ExtractionResult.model.is_not_distinct_from(key.model),
            ExtractionResult.canonicalization_version == key.canonicalization_version,
            ExtractionResult.validation_status == ExtractionValidationStatus.ACCEPTED.value,
        )
    )


def _build_extraction_result(
    *,
    key: ExtractionCacheKey,
    output_data: dict[str, Any],
    status: ExtractionValidationStatus,
    validation_errors: list[dict[str, str]] | None,
    confidence: Decimal | None,
    latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    estimated_cost_usd: Decimal | None,
) -> ExtractionResult:
    return ExtractionResult(
        input_type=key.input_type.value,
        input_ref=key.input_ref,
        input_hash=key.input_hash,
        extractor_type=key.extractor_type.value,
        extractor_version=key.extractor_version,
        schema_version=key.schema_version,
        prompt_version=key.prompt_version,
        model=key.model,
        canonicalization_version=key.canonicalization_version,
        output_data=output_data,
        validation_status=status.value,
        validation_errors=validation_errors,
        confidence=confidence,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )


def persist_extraction_result(
    session: Session,
    *,
    key: ExtractionCacheKey,
    output_data: dict[str, Any],
    status: ExtractionValidationStatus,
    validation_errors: list[dict[str, str]] | None,
    confidence: Decimal | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    estimated_cost_usd: Decimal | None = None,
) -> tuple[ExtractionResult, bool]:
    if status is ExtractionValidationStatus.ACCEPTED:
        existing = load_accepted_cache(session, key)
        if existing is not None:
            return existing, True

    result = _build_extraction_result(
        key=key,
        output_data=output_data,
        status=status,
        validation_errors=validation_errors,
        confidence=confidence,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )
    if status is not ExtractionValidationStatus.ACCEPTED:
        session.add(result)
        session.flush()
        return result, False

    try:
        with session.begin_nested():
            session.add(result)
            session.flush()
    except IntegrityError:
        winner = load_accepted_cache(session, key)
        if winner is None:
            raise
        return winner, True
    return result, False


MAX_PROVIDER_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    extractor_version: str
    schema_version: str
    prompt_version: str
    model: str
    canonicalization_version: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    input_ref: UUID
    input_hash: str
    title: str
    description_text: str
    deterministic_payload: ExtractionPayload


ProviderCallable = Callable[[ProviderRequest], Mapping[str, object]]


class ProviderTransientError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProviderValidationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtractionResolution:
    payload: ExtractionPayload
    status: ExtractionValidationStatus
    errors: list[dict[str, str]] | None
    attempts: int


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    result: ExtractionResult
    deterministic: DeterministicExtraction
    cache_hit: bool
    attempts: int


def validate_provider_candidate(
    candidate: Mapping[str, object],
    *,
    deterministic: DeterministicExtraction,
    source_text: str,
) -> ExtractionPayload:
    candidate_data = dict(candidate)
    raw_skills = candidate_data.get("skills")
    if isinstance(raw_skills, (list, tuple)):
        normalized_skills: list[object] = []
        for item in raw_skills:
            if isinstance(item, Mapping):
                normalized_item = dict(item)
                raw_name = normalized_item.get("name")
                if isinstance(raw_name, str):
                    normalized_item["name"] = canonicalize_skill_name(raw_name)
                normalized_skills.append(normalized_item)
            else:
                normalized_skills.append(item)
        candidate_data["skills"] = normalized_skills
    try:
        payload = ExtractionPayload.model_validate(candidate_data)
    except ValidationError:
        raise ProviderValidationError("provider_schema_invalid") from None

    merged = payload.model_copy(
        update={
            "levels": deterministic.payload.levels,
            "experience": deterministic.payload.experience,
            "salary": deterministic.payload.salary,
            "location": deterministic.payload.location,
        }
    )
    skill_keys = [(skill.name, skill.requirement_type) for skill in merged.skills]
    if len(skill_keys) != len(set(skill_keys)):
        raise ProviderValidationError("provider_evidence_invalid")
    if any(skill.evidence not in source_text for skill in merged.skills):
        raise ProviderValidationError("provider_evidence_invalid")
    return merged


def resolve_provider_fallback(
    *,
    deterministic: DeterministicExtraction,
    source_text: str,
    request: ProviderRequest,
    provider: ProviderCallable | None,
    metadata: ProviderMetadata,
) -> ExtractionResolution:
    del metadata
    if provider is None:
        return ExtractionResolution(
            payload=deterministic.payload,
            status=ExtractionValidationStatus.NEEDS_REVIEW,
            errors=[{"code": "provider_not_configured", "path": "provider", "type": "missing"}],
            attempts=0,
        )

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            candidate = provider(request)
            payload = validate_provider_candidate(
                candidate,
                deterministic=deterministic,
                source_text=source_text,
            )
            return ExtractionResolution(
                payload=payload,
                status=ExtractionValidationStatus.ACCEPTED,
                errors=None,
                attempts=attempt,
            )
        except ProviderValidationError as error:
            return ExtractionResolution(
                payload=deterministic.payload,
                status=ExtractionValidationStatus.REJECTED,
                errors=[{"code": error.code, "path": "provider", "type": "validation"}],
                attempts=attempt,
            )
        except ProviderTransientError as error:
            if attempt == MAX_PROVIDER_ATTEMPTS:
                return ExtractionResolution(
                    payload=deterministic.payload,
                    status=ExtractionValidationStatus.NEEDS_REVIEW,
                    errors=[{"code": error.code, "path": "provider", "type": "transient"}],
                    attempts=attempt,
                )
    raise AssertionError("provider resolver must return within the bounded attempt loop")


def extract_job(
    session: Session,
    *,
    job: Job,
    provider: ProviderCallable | None,
    provider_metadata: ProviderMetadata | None,
) -> ExtractionOutcome:
    """Persist one deterministic-first extraction with short transaction windows."""

    deterministic = deterministic_extract(job)
    rule_key = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.RULE,
        extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version=None,
        model=None,
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    if deterministic.complete:
        session.rollback()
        with session.begin():
            result, cache_hit = persist_extraction_result(
                session,
                key=rule_key,
                output_data=deterministic.payload.model_dump(mode="json", by_alias=True),
                status=ExtractionValidationStatus.ACCEPTED,
                validation_errors=None,
            )
        return ExtractionOutcome(result, deterministic, cache_hit, 0)

    metadata = provider_metadata or ProviderMetadata(
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="unconfigured",
        model="unconfigured",
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    llm_key = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=job.id,
        input_hash=job.job_content_hash,
        extractor_type=ExtractionType.LLM,
        extractor_version=metadata.extractor_version,
        schema_version=metadata.schema_version,
        prompt_version=metadata.prompt_version,
        model=metadata.model,
        canonicalization_version=metadata.canonicalization_version,
    )
    session.rollback()
    with session.begin():
        cached = load_accepted_cache(session, llm_key)
    if cached is not None:
        return ExtractionOutcome(cached, deterministic, True, 0)

    session.rollback()
    request = ProviderRequest(
        input_ref=job.id,
        input_hash=job.job_content_hash,
        title=job.title,
        description_text=job.description_text or "",
        deterministic_payload=deterministic.payload,
    )
    resolution = resolve_provider_fallback(
        deterministic=deterministic,
        source_text=f"{job.title}\n{job.description_text or ''}",
        request=request,
        provider=provider,
        metadata=metadata,
    )
    with session.begin():
        result, cache_hit = persist_extraction_result(
            session,
            key=llm_key,
            output_data=resolution.payload.model_dump(mode="json", by_alias=True),
            status=resolution.status,
            validation_errors=resolution.errors,
        )
    return ExtractionOutcome(result, deterministic, cache_hit, resolution.attempts)


def _as_decimal(value: Decimal | None) -> Decimal | None:
    return value


def deterministic_extract(job: Job) -> DeterministicExtraction:
    """Build the safe deterministic portion of an extraction from canonical Job data."""

    warnings: list[str] = []
    try:
        levels = tuple(JobLevel(value) for value in job.levels)
    except ValueError:
        levels = ()
        warnings.append("levels_invalid")

    try:
        salary_period = SalaryPeriod(job.salary_period) if job.salary_period else None
    except ValueError:
        salary_period = None
        warnings.append("salary_invalid")

    try:
        work_mode = WorkMode(job.work_mode) if job.work_mode else None
    except ValueError:
        work_mode = None
        warnings.append("location_invalid")

    description = job.description_text or ""
    skills = extract_skill_expectations(job.title, description)
    if not skills:
        warnings.append("skills_not_determined")

    payload = ExtractionPayload(
        levels=levels,
        experience=ExperienceExpectation(
            minimum_years=_as_decimal(job.experience_min),
            maximum_years=_as_decimal(job.experience_max),
        ),
        salary=SalaryExpectation(
            minimum=_as_decimal(job.salary_min),
            maximum=_as_decimal(job.salary_max),
            currency=job.currency,
            period=salary_period,
        ),
        location=LocationExpectation(
            city=job.location_city,
            province=job.location_province,
            work_mode=work_mode,
        ),
        skills=skills,
    )
    if not levels:
        warnings.append("levels_not_determined")

    return DeterministicExtraction(
        payload=payload,
        complete=bool(description.strip()) and not warnings,
        extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
        warnings=tuple(warnings),
    )


def safe_validation_errors(error: ValidationError, *, code: str) -> list[dict[str, str]]:
    """Return bounded validation locations without serializing rejected values."""

    return [
        {
            "code": code,
            "path": ".".join(str(part) for part in item["loc"])[:120],
            "type": str(item["type"])[:80],
        }
        for item in error.errors()
    ][:16]
