"""Versioned synthetic extraction dataset and deterministic baseline metrics."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from devradar.catalog.models import JobLevel
from devradar.ingestion.normalization import (
    SalaryPeriod,
    WorkMode,
    normalize_experience,
    normalize_levels,
    normalize_location,
    normalize_salary,
)

DATASET_VERSION = "job-extraction-eval-v1"
DATASET_SCHEMA_VERSION = "job-extraction-eval-schema-v1"
BASELINE_VERSION = "deterministic-keyword-v1"


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class EvaluationLanguage(StrEnum):
    VI = "vi"
    EN = "en"
    MIXED = "mixed"


class RequirementType(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class EvaluationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class EvaluationInput(EvaluationModel):
    title: str = Field(min_length=1, max_length=300)
    description_text: str = Field(min_length=1, max_length=4_000)
    level_raw: str | None = Field(default=None, max_length=300)
    experience_raw: str | None = Field(default=None, max_length=300)
    salary_raw: str | None = Field(default=None, max_length=300)
    location_raw: str | None = Field(default=None, max_length=300)


class SkillExpectation(EvaluationModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9.+#-]{0,49}$")
    requirement_type: RequirementType
    evidence: str = Field(min_length=1, max_length=200)


class ExperienceExpectation(EvaluationModel):
    minimum_years: Decimal | None
    maximum_years: Decimal | None


class SalaryExpectation(EvaluationModel):
    minimum: Decimal | None
    maximum: Decimal | None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period: SalaryPeriod | None


class LocationExpectation(EvaluationModel):
    city: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    work_mode: WorkMode | None


class ExtractionExpectation(EvaluationModel):
    levels: tuple[JobLevel, ...]
    experience: ExperienceExpectation
    salary: SalaryExpectation
    location: LocationExpectation
    skills: tuple[SkillExpectation, ...]


class EvaluationCase(EvaluationModel):
    id: str = Field(pattern=r"^(dev|held)-(vi|en|mixed)-[a-z0-9-]+-[0-9]{3}$")
    split: EvaluationSplit
    language: EvaluationLanguage
    risk_tags: tuple[str, ...]
    input: EvaluationInput
    expected: ExtractionExpectation

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        expected_prefix = "dev-" if self.split is EvaluationSplit.DEVELOPMENT else "held-"
        if not self.id.startswith(f"{expected_prefix}{self.language.value}-"):
            raise ValueError("case id must encode split and language")
        if len(set(self.risk_tags)) != len(self.risk_tags) or not self.risk_tags:
            raise ValueError("risk_tags must be non-empty and unique")
        if len(set(self.expected.levels)) != len(self.expected.levels):
            raise ValueError("expected levels must be unique")
        skill_keys = [(skill.name, skill.requirement_type) for skill in self.expected.skills]
        if len(set(skill_keys)) != len(skill_keys):
            raise ValueError("expected skill labels must be unique")
        source_text = f"{self.input.title}\n{self.input.description_text}"
        for skill in self.expected.skills:
            if skill.evidence not in source_text:
                raise ValueError(f"skill evidence is not present in input: {skill.name}")
        return self


class EvaluationDataset(EvaluationModel):
    dataset_version: str
    schema_version: str
    provenance: str
    cases: tuple[EvaluationCase, ...]

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> Self:
        if self.dataset_version != DATASET_VERSION:
            raise ValueError(f"datasetVersion must be {DATASET_VERSION}")
        if self.schema_version != DATASET_SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {DATASET_SCHEMA_VERSION}")
        if self.provenance != "project-authored-synthetic-no-third-party-content":
            raise ValueError("evaluation data must use the approved synthetic provenance")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case ids must be unique")
        if not self.cases:
            raise ValueError("evaluation dataset must not be empty")
        return self


@dataclass(frozen=True, slots=True)
class BaselineReport:
    dataset_version: str
    baseline_version: str
    split: str
    cases: int
    skill_precision: float
    skill_recall: float
    skill_f1: float
    unsupported_skill_rate: float
    level_exact_accuracy: float
    experience_exact_accuracy: float
    salary_exact_accuracy: float
    location_exact_accuracy: float
    deterministic_complete_rate: float

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "dotnet": (".net",),
    "apache-kafka": ("apache kafka", "kafka"),
    "apache-spark": ("apache spark", "spark"),
    "aws": ("aws", "amazon web services"),
    "c#": ("c#", "c sharp"),
    "dart": ("dart",),
    "docker": ("docker",),
    "fastapi": ("fastapi",),
    "firebase": ("firebase",),
    "flutter": ("flutter",),
    "go": ("golang", "go"),
    "java": ("java",),
    "kubernetes": ("kubernetes", "k8s"),
    "next.js": ("next.js", "nextjs"),
    "node.js": ("node.js", "nodejs"),
    "postgresql": ("postgresql", "postgres"),
    "python": ("python",),
    "react": ("react", "react.js"),
    "redis": ("redis",),
    "selenium": ("selenium",),
    "sql": ("sql",),
    "terraform": ("terraform",),
    "typescript": ("typescript",),
}
_SKILL_ALIAS_TO_CANONICAL = {
    alias.casefold(): canonical
    for canonical, aliases in _SKILL_ALIASES.items()
    for alias in aliases
}
_SKILL_PATTERNS = {
    name: tuple(
        re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
        for alias in aliases
    )
    for name, aliases in _SKILL_ALIASES.items()
}
_OPTIONAL_MARKERS = (
    "a plus",
    "bonus",
    "điểm cộng",
    "nice to have",
    "optional",
    "preferred",
    "ưu tiên",
)
_NEGATED_MARKERS = (
    "do not require",
    "does not require",
    "không bắt buộc",
    "không cần",
    "không yêu cầu",
    "not required",
)


def canonicalize_skill_name(raw: str) -> str:
    """Apply the versioned taxonomy alias map without inventing unknown skills."""

    normalized = " ".join(raw.split()).casefold()
    return _SKILL_ALIAS_TO_CANONICAL.get(normalized, normalized.replace(" ", "-"))


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    return EvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))


def extract_skill_expectations(title: str, description_text: str) -> tuple[SkillExpectation, ...]:
    """Extract versioned skill labels and source evidence from job text."""

    labels: dict[str, tuple[RequirementType, str]] = {}
    source_text = f"{title}\n{description_text}"
    clauses = tuple(part.strip() for part in re.split(r"[\n;]+", source_text) if part.strip())
    for clause in clauses:
        folded = clause.casefold()
        if any(marker in folded for marker in _NEGATED_MARKERS):
            continue
        requirement_type = (
            RequirementType.OPTIONAL
            if any(marker in folded for marker in _OPTIONAL_MARKERS)
            else RequirementType.REQUIRED
        )
        for name, patterns in _SKILL_PATTERNS.items():
            match = next(
                (match for pattern in patterns if (match := pattern.search(clause)) is not None),
                None,
            )
            if match is None:
                continue
            previous = labels.get(name)
            if previous is None or requirement_type is RequirementType.REQUIRED:
                labels[name] = (requirement_type, match.group(0))
    return tuple(
        SkillExpectation(name=name, requirement_type=kind, evidence=evidence)
        for name, (kind, evidence) in sorted(labels.items())
    )


def _extract_skill_labels(case: EvaluationCase) -> set[tuple[str, RequirementType]]:
    return {
        (skill.name, skill.requirement_type)
        for skill in extract_skill_expectations(case.input.title, case.input.description_text)
    }


def _experience_tuple(case: EvaluationCase) -> tuple[Decimal | None, Decimal | None]:
    value = normalize_experience(case.input.experience_raw).value
    return (None, None) if value is None else (value.minimum_years, value.maximum_years)


def _expected_experience_tuple(
    case: EvaluationCase,
) -> tuple[Decimal | None, Decimal | None]:
    value = case.expected.experience
    return value.minimum_years, value.maximum_years


def _salary_tuple(
    case: EvaluationCase,
) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    value = normalize_salary(case.input.salary_raw).value
    return (
        (None, None, None, None)
        if value is None
        else (value.minimum, value.maximum, value.currency, value.period)
    )


def _expected_salary_tuple(
    case: EvaluationCase,
) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    value = case.expected.salary
    return value.minimum, value.maximum, value.currency, value.period


def _location_tuple(case: EvaluationCase) -> tuple[str | None, str | None, WorkMode | None]:
    value = normalize_location(case.input.location_raw).value
    return (None, None, None) if value is None else (value.city, value.province, value.work_mode)


def _expected_location_tuple(
    case: EvaluationCase,
) -> tuple[str | None, str | None, WorkMode | None]:
    value = case.expected.location
    return value.city, value.province, value.work_mode


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def run_deterministic_baseline(
    dataset: EvaluationDataset,
    *,
    split: EvaluationSplit = EvaluationSplit.HELD_OUT,
) -> BaselineReport:
    cases = tuple(case for case in dataset.cases if case.split is split)
    if not cases:
        raise ValueError(f"evaluation split is empty: {split.value}")

    true_positive = 0
    predicted_total = 0
    expected_total = 0
    level_exact = 0
    experience_exact = 0
    salary_exact = 0
    location_exact = 0
    complete = 0

    for case in cases:
        predicted_skills = _extract_skill_labels(case)
        expected_skills = {(skill.name, skill.requirement_type) for skill in case.expected.skills}
        true_positive += len(predicted_skills & expected_skills)
        predicted_total += len(predicted_skills)
        expected_total += len(expected_skills)

        levels_match = normalize_levels(case.input.level_raw).value == case.expected.levels
        experience_matches = _experience_tuple(case) == _expected_experience_tuple(case)
        salary_matches = _salary_tuple(case) == _expected_salary_tuple(case)
        location_matches = _location_tuple(case) == _expected_location_tuple(case)
        level_exact += levels_match
        experience_exact += experience_matches
        salary_exact += salary_matches
        location_exact += location_matches
        complete += (
            predicted_skills == expected_skills
            and levels_match
            and experience_matches
            and salary_matches
            and location_matches
        )

    precision = _ratio(true_positive, predicted_total)
    recall = _ratio(true_positive, expected_total)
    f1 = _ratio(2 * true_positive, predicted_total + expected_total)
    case_count = len(cases)
    return BaselineReport(
        dataset_version=dataset.dataset_version,
        baseline_version=BASELINE_VERSION,
        split=split.value,
        cases=case_count,
        skill_precision=precision,
        skill_recall=recall,
        skill_f1=f1,
        unsupported_skill_rate=_ratio(predicted_total - true_positive, predicted_total),
        level_exact_accuracy=_ratio(level_exact, case_count),
        experience_exact_accuracy=_ratio(experience_exact, case_count),
        salary_exact_accuracy=_ratio(salary_exact, case_count),
        location_exact_accuracy=_ratio(location_exact, case_count),
        deterministic_complete_rate=_ratio(complete, case_count),
    )
