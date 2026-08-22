"""Deterministic-first job extraction contract and provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError

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
