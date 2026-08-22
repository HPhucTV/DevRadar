"""Versioned deterministic primitives shared by match evaluation and runtime scoring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

from devradar.intelligence.evaluation import RequirementType, canonicalize_skill_name

# v2 invalidates rows produced with the pre-contract skill requirement weights.
SCORING_VERSION: Final = "job-match-scoring-v2"
COMPONENT_NAMES: Final = ("skill", "semantic", "experience", "location", "role")
SCORE_QUANTUM: Final = Decimal("0.0001")
RECOMMENDED_WEIGHTS: Final[Mapping[str, Decimal]] = MappingProxyType(
    {
        "skill": Decimal("0.40"),
        "semantic": Decimal("0.25"),
        "experience": Decimal("0.15"),
        "location": Decimal("0.10"),
        "role": Decimal("0.10"),
    }
)
REQUIREMENT_WEIGHTS: Final[Mapping[RequirementType, Decimal]] = MappingProxyType(
    {
        RequirementType.REQUIRED: Decimal("3"),
        RequirementType.PREFERRED: Decimal("2"),
        RequirementType.OPTIONAL: Decimal("1"),
        RequirementType.MENTIONED: Decimal("1"),
    }
)


@dataclass(frozen=True, slots=True)
class JobSkill:
    name: str
    requirement_type: RequirementType


@dataclass(frozen=True, slots=True)
class MatchFacts:
    profile_skills: tuple[str, ...]
    job_skills: tuple[JobSkill, ...] | None
    semantic_similarity: Decimal | None
    profile_experience_years: Decimal | None
    job_experience_min: Decimal | None
    profile_locations: tuple[str, ...]
    job_locations: tuple[str, ...]
    profile_roles: tuple[str, ...]
    job_role: str | None


@dataclass(frozen=True, slots=True)
class MatchComponents:
    skill: Decimal | None
    semantic: Decimal | None
    experience: Decimal | None
    location: Decimal | None
    role: Decimal | None


@dataclass(frozen=True, slots=True)
class MatchScore:
    components: MatchComponents
    overall_score: Decimal
    evidence_coverage: Decimal
    matched_skills: tuple[str, ...]
    missing_skills: tuple[str, ...]
    explanation: tuple[str, ...]


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def weighted_component_score(
    components: Mapping[str, Decimal | None],
    weights: Mapping[str, Decimal] = RECOMMENDED_WEIGHTS,
) -> tuple[Decimal, Decimal]:
    """Return conservative overall score and available evidence coverage."""

    if set(components) != set(COMPONENT_NAMES) or set(weights) != set(COMPONENT_NAMES):
        raise ValueError("job_match_component_contract_invalid")
    if sum(weights.values()) != Decimal("1") or any(
        not weight.is_finite() or weight < 0 for weight in weights.values()
    ):
        raise ValueError("job_match_weight_contract_invalid")
    overall = Decimal("0")
    coverage = Decimal("0")
    for name in COMPONENT_NAMES:
        value = components[name]
        if value is None:
            continue
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("job_match_component_value_invalid")
        overall += value * weights[name]
        coverage += weights[name]
    return quantize_score(overall), quantize_score(coverage)


def _canonical_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_optional_decimal(value: Decimal | None, *, upper: Decimal | None = None) -> None:
    if value is None:
        return
    if not value.is_finite() or value < 0:
        raise ValueError("job_match_component_value_invalid")
    if upper is not None and value > upper:
        raise ValueError("job_match_component_value_invalid")


def _skill_component(
    profile_skills: tuple[str, ...],
    job_skills: tuple[JobSkill, ...] | None,
) -> tuple[Decimal | None, tuple[str, ...], tuple[str, ...]]:
    if job_skills is None:
        return None, (), ()
    profile = {canonicalize_skill_name(skill) for skill in profile_skills if skill.strip()}
    requirement_by_skill: dict[str, RequirementType] = {}
    for job_skill in job_skills:
        name = canonicalize_skill_name(job_skill.name)
        current = requirement_by_skill.get(name)
        if (
            current is None
            or REQUIREMENT_WEIGHTS[job_skill.requirement_type] > REQUIREMENT_WEIGHTS[current]
        ):
            requirement_by_skill[name] = job_skill.requirement_type
    if not requirement_by_skill:
        return Decimal("0"), (), ()
    matched = tuple(sorted(name for name in requirement_by_skill if name in profile))
    missing = tuple(sorted(name for name in requirement_by_skill if name not in profile))
    total_weight = sum(
        (REQUIREMENT_WEIGHTS[requirement] for requirement in requirement_by_skill.values()),
        Decimal("0"),
    )
    matched_weight = sum(
        (REQUIREMENT_WEIGHTS[requirement_by_skill[name]] for name in matched),
        Decimal("0"),
    )
    return quantize_score(matched_weight / total_weight), matched, missing


def _semantic_component(value: Decimal | None) -> Decimal | None:
    _validate_optional_decimal(value, upper=Decimal("1"))
    return None if value is None else quantize_score(value)


def _experience_component(
    profile_years: Decimal | None,
    minimum_years: Decimal | None,
) -> Decimal | None:
    if profile_years is None or minimum_years is None:
        return None
    _validate_optional_decimal(profile_years, upper=Decimal("60"))
    _validate_optional_decimal(minimum_years, upper=Decimal("60"))
    if minimum_years == 0 or profile_years >= minimum_years:
        return Decimal("1.0000")
    return quantize_score(profile_years / minimum_years)


def _location_component(
    profile_locations: tuple[str, ...],
    job_locations: tuple[str, ...],
) -> Decimal | None:
    profile = {_canonical_text(value) for value in profile_locations if value.strip()}
    job = {_canonical_text(value) for value in job_locations if value.strip()}
    if not profile or not job:
        return None
    return Decimal("1.0000") if profile & job else Decimal("0.0000")


def _role_component(profile_roles: tuple[str, ...], job_role: str | None) -> Decimal | None:
    profile = {_canonical_text(value) for value in profile_roles if value.strip()}
    job = _canonical_text(job_role) if job_role and job_role.strip() else ""
    if len(profile) != 1 or not job:
        return None
    return Decimal("1.0000") if job in profile else Decimal("0.0000")


def _explanation(
    components: MatchComponents,
    matched_skills: tuple[str, ...],
    missing_skills: tuple[str, ...],
) -> tuple[str, ...]:
    skill_token = (
        "skill_unavailable"
        if components.skill is None
        else "skill_complete"
        if components.skill == Decimal("1")
        else "skill_partial"
        if matched_skills
        else "skill_no_match"
    )
    semantic_token = "semantic_unavailable" if components.semantic is None else "semantic_available"
    experience_token = (
        "experience_unavailable"
        if components.experience is None
        else "experience_meets_minimum"
        if components.experience == Decimal("1")
        else "experience_below_minimum"
    )
    location_token = (
        "location_unavailable"
        if components.location is None
        else "location_match"
        if components.location == Decimal("1")
        else "location_mismatch"
    )
    role_token = (
        "role_unavailable"
        if components.role is None
        else "role_match"
        if components.role == Decimal("1")
        else "role_mismatch"
    )
    return (skill_token, semantic_token, experience_token, location_token, role_token)


def score_match(facts: MatchFacts) -> MatchScore:
    """Score validated structured profile/job facts without retaining raw inputs."""

    skill, matched_skills, missing_skills = _skill_component(
        facts.profile_skills,
        facts.job_skills,
    )
    components = MatchComponents(
        skill=skill,
        semantic=_semantic_component(facts.semantic_similarity),
        experience=_experience_component(
            facts.profile_experience_years,
            facts.job_experience_min,
        ),
        location=_location_component(facts.profile_locations, facts.job_locations),
        role=_role_component(facts.profile_roles, facts.job_role),
    )
    component_values = {
        "skill": components.skill,
        "semantic": components.semantic,
        "experience": components.experience,
        "location": components.location,
        "role": components.role,
    }
    overall, coverage = weighted_component_score(component_values)
    return MatchScore(
        components=components,
        overall_score=overall,
        evidence_coverage=coverage,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        explanation=_explanation(components, matched_skills, missing_skills),
    )
