"""Deterministic-first job extraction contract and provider boundary."""

from __future__ import annotations

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
