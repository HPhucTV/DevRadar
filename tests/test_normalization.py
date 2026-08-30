from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from devradar.catalog.models import JobLevel
from devradar.ingestion.normalization import (
    CanonicalJobContent,
    NormalizedExperience,
    NormalizedLocation,
    NormalizedSalary,
    SalaryPeriod,
    WorkMode,
    canonical_job_content_hash,
    canonical_job_content_hash_v1,
    normalize_canonical_url,
    normalize_experience,
    normalize_levels,
    normalize_location,
    normalize_multiline_text,
    normalize_salary,
    normalize_skill_mentions,
    normalize_text,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "normalization_cases.json"
CASES: dict[str, list[dict[str, Any]]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["text"])
def test_text_normalization(case: dict[str, Any]) -> None:
    result = normalize_text(case["raw"])
    assert result.raw == case["raw"]
    assert result.value == case["expected"]


def test_multiline_text_normalization_preserves_one_paragraph_separator() -> None:
    result = normalize_multiline_text("  First paragraph  \r\n\r\n\r\n Second   paragraph \n")

    assert result.value == "First paragraph\n\nSecond paragraph"


@pytest.mark.parametrize("case", CASES["url"])
def test_url_normalization_only_removes_allowlisted_parameters(case: dict[str, Any]) -> None:
    result = normalize_canonical_url(
        case["raw"],
        base_url=case["base_url"],
        allowed_hosts=tuple(case["allowed_hosts"]),
        removable_query_params=frozenset(case["remove"]),
    )
    assert result.raw == case["raw"]
    assert result.value == case["expected"]


def test_url_normalization_rejects_unapproved_host_and_user_info() -> None:
    with pytest.raises(ValueError, match="allowed host"):
        normalize_canonical_url(
            "https://attacker.test/jobs/1",
            base_url="https://careers.example.test",
            allowed_hosts=("careers.example.test",),
        )
    with pytest.raises(ValueError, match="user info"):
        normalize_canonical_url(
            "https://user:secret@careers.example.test/jobs/1",
            base_url="https://careers.example.test",
            allowed_hosts=("careers.example.test",),
        )


@pytest.mark.parametrize("case", CASES["location"])
def test_location_normalization_is_evidence_bounded(case: dict[str, Any]) -> None:
    result = normalize_location(case["raw"])
    assert result.value is not None
    assert result.value.city == case["city"]
    assert result.value.province == case["province"]
    assert result.value.work_mode == case["work_mode"]
    assert list(result.warnings) == case["warnings"]


@pytest.mark.parametrize("case", CASES["salary"])
def test_salary_normalization_is_conservative(case: dict[str, Any]) -> None:
    result = normalize_salary(case["raw"])
    if case["minimum"] is None and case["maximum"] is None:
        assert result.value is None
    else:
        assert result.value is not None
        expected_minimum = Decimal(case["minimum"]) if case["minimum"] else None
        expected_maximum = Decimal(case["maximum"]) if case["maximum"] else None
        assert result.value.minimum == expected_minimum
        assert result.value.maximum == expected_maximum
        assert result.value.currency == case["currency"]
        assert result.value.period == case["period"]
    assert list(result.warnings) == case["warnings"]


@pytest.mark.parametrize("case", CASES["levels"])
def test_level_normalization_never_infers_from_experience(case: dict[str, Any]) -> None:
    result = normalize_levels(case["raw"])
    assert [level.value for level in result.value or ()] == case["expected"]


@pytest.mark.parametrize("case", CASES["experience"])
def test_experience_normalization_requires_explicit_year_unit(case: dict[str, Any]) -> None:
    result = normalize_experience(case["raw"])
    if case["minimum"] is None and case["maximum"] is None:
        assert result.value is None
    else:
        assert result.value is not None
        expected_minimum = Decimal(case["minimum"]) if case["minimum"] else None
        expected_maximum = Decimal(case["maximum"]) if case["maximum"] else None
        assert result.value.minimum_years == expected_minimum
        assert result.value.maximum_years == expected_maximum
    assert list(result.warnings) == case["warnings"]


@pytest.mark.parametrize("case", CASES["skills"])
def test_skill_mentions_only_clean_text_without_taxonomy_merge(case: dict[str, Any]) -> None:
    results = normalize_skill_mentions(tuple(case["raw"]))
    assert [result.raw for result in results] == case["raw"]
    assert [result.value for result in results] == case["expected"]


def _canonical_content(*, title: str, salary_maximum: Decimal) -> CanonicalJobContent:
    return CanonicalJobContent(
        canonical_url="https://careers.example.test/jobs/1",
        title=title,
        company_name="Example Company",
        description_text="Build reliable systems.",
        location_raw="Ho Chi Minh City (Hybrid)",
        location=NormalizedLocation(
            city="Ho Chi Minh City",
            province="Ho Chi Minh City",
            work_mode=WorkMode.HYBRID,
        ),
        salary_raw="30-50 triệu VND/tháng",
        salary=NormalizedSalary(
            minimum=Decimal("30000000"),
            maximum=salary_maximum,
            currency="VND",
            period=SalaryPeriod.MONTH,
        ),
        level_raw="Senior",
        levels=(JobLevel.SENIOR,),
        experience=NormalizedExperience(minimum_years=Decimal(3), maximum_years=None),
    )


def test_canonical_hash_ignores_whitespace_but_changes_with_meaningful_content() -> None:
    first = _canonical_content(
        title=" Senior   Backend Engineer ", salary_maximum=Decimal("50000000")
    )
    whitespace_only = _canonical_content(
        title="Senior Backend Engineer", salary_maximum=Decimal("50000000.0000")
    )
    salary_changed = _canonical_content(
        title="Senior Backend Engineer", salary_maximum=Decimal("55000000")
    )

    assert canonical_job_content_hash(first) == canonical_job_content_hash(whitespace_only)
    assert canonical_job_content_hash(first) != canonical_job_content_hash(salary_changed)


def test_canonical_hash_distinguishes_paragraph_boundaries() -> None:
    paragraph = _canonical_content(
        title="Senior Backend Engineer", salary_maximum=Decimal("50000000")
    )
    flattened = _canonical_content(
        title="Senior Backend Engineer", salary_maximum=Decimal("50000000")
    )
    object.__setattr__(paragraph, "description_text", "First\n\nSecond")
    object.__setattr__(flattened, "description_text", "First\nSecond")

    assert canonical_job_content_hash(paragraph) != canonical_job_content_hash(flattened)
    assert canonical_job_content_hash_v1(paragraph) == canonical_job_content_hash_v1(flattened)
