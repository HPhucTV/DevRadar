from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from devradar.catalog.models import Job, JobLevel
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    ExtractionCacheKey,
    ExtractionPayload,
    deterministic_extract,
)
from devradar.intelligence.models import ExtractionInputType, ExtractionType


def _job(*, description: str | None, levels: list[str] | None = None) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid4(),
        source_id=uuid4(),
        canonical_url="https://careers.example.test/jobs/1",
        title="Backend Engineer",
        company_name="Example",
        description_text=description,
        location_raw="Ho Chi Minh City, hybrid",
        location_city="Ho Chi Minh City",
        location_province="Ho Chi Minh City",
        work_mode="hybrid",
        salary_raw="30-40 triệu VND/tháng",
        salary_min=Decimal("30000000"),
        salary_max=Decimal("40000000"),
        currency="VND",
        salary_period="month",
        level_raw="Senior",
        levels=levels or [JobLevel.SENIOR.value],
        experience_min=Decimal("3"),
        experience_max=None,
        first_seen_at=now,
        last_seen_at=now,
        current_snapshot_id=uuid4(),
        job_content_hash="a" * 64,
    )


def test_deterministic_extraction_is_complete_without_provider() -> None:
    result = deterministic_extract(
        _job(description="Build APIs with Python and PostgreSQL; Docker is a plus.")
    )

    assert result.complete is True
    assert result.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION
    assert result.payload.levels == (JobLevel.SENIOR,)
    assert {skill.name for skill in result.payload.skills} == {"python", "postgresql", "docker"}
    assert CANONICALIZATION_VERSION == "extraction-canonicalization-v1"


def test_deterministic_extraction_is_incomplete_when_skill_evidence_is_missing() -> None:
    result = deterministic_extract(_job(description="Join a backend team."))

    assert result.complete is False
    assert result.warnings == ("skills_not_determined",)


def test_payload_rejects_extra_fields() -> None:
    payload = {
        "levels": ["senior"],
        "experience": {"minimumYears": 3, "maximumYears": None},
        "salary": {"minimum": 30, "maximum": 40, "currency": "VND", "period": "month"},
        "location": {"city": "Hanoi", "province": "Hanoi", "workMode": "onsite"},
        "skills": [{"name": "python", "requirementType": "required", "evidence": "Python"}],
        "untrusted": "must be rejected",
    }

    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate(payload)


def test_cache_key_changes_for_each_version_dimension() -> None:
    base = ExtractionCacheKey(
        input_type=ExtractionInputType.JOB,
        input_ref=uuid4(),
        input_hash="a" * 64,
        extractor_type=ExtractionType.LLM,
        extractor_version="provider-boundary-v1",
        schema_version=EXTRACTION_SCHEMA_VERSION,
        prompt_version="prompt-v1",
        model="test-model",
        canonicalization_version=CANONICALIZATION_VERSION,
    )

    changed_keys = (
        replace(base, input_hash="b" * 64),
        replace(base, extractor_version="changed"),
        replace(base, schema_version="changed"),
        replace(base, prompt_version="changed"),
        replace(base, model="changed"),
        replace(base, canonicalization_version="changed"),
    )
    for changed in changed_keys:
        assert changed != base
