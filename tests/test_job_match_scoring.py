from __future__ import annotations

from decimal import Decimal

import pytest

from devradar.intelligence.evaluation import RequirementType
from devradar.matching.scoring import (
    JobSkill,
    MatchFacts,
    score_match,
)


def _facts(
    *,
    profile_skills: tuple[str, ...] = ("fastapi", "python"),
    job_skills: tuple[JobSkill, ...] | None = (
        JobSkill("python", RequirementType.REQUIRED),
        JobSkill("postgresql", RequirementType.PREFERRED),
    ),
    semantic_similarity: Decimal | None = Decimal("0.80"),
    profile_experience_years: Decimal | None = Decimal("3"),
    job_experience_min: Decimal | None = Decimal("2"),
    profile_locations: tuple[str, ...] = ("Ho Chi Minh City",),
    job_locations: tuple[str, ...] = ("Ho Chi Minh City",),
    profile_roles: tuple[str, ...] = ("backend",),
    job_role: str | None = "backend",
) -> MatchFacts:
    return MatchFacts(
        profile_skills=profile_skills,
        job_skills=job_skills,
        semantic_similarity=semantic_similarity,
        profile_experience_years=profile_experience_years,
        job_experience_min=job_experience_min,
        profile_locations=profile_locations,
        job_locations=job_locations,
        profile_roles=profile_roles,
        job_role=job_role,
    )


def test_score_match_returns_explainable_weighted_components() -> None:
    result = score_match(_facts())

    assert result.matched_skills == ("python",)
    assert result.missing_skills == ("postgresql",)
    assert result.components.skill == Decimal("0.6000")
    assert result.components.semantic == Decimal("0.8000")
    assert result.components.experience == Decimal("1.0000")
    assert result.components.location == Decimal("1.0000")
    assert result.components.role == Decimal("1.0000")
    assert result.overall_score == Decimal("0.7900")
    assert result.evidence_coverage == Decimal("1.0000")
    assert result.explanation == (
        "skill_partial",
        "semantic_available",
        "experience_meets_minimum",
        "location_match",
        "role_match",
    )


def test_missing_components_are_null_and_do_not_renormalize() -> None:
    result = score_match(
        _facts(
            job_skills=None,
            semantic_similarity=Decimal("0.80"),
            profile_experience_years=None,
            job_experience_min=None,
            profile_locations=(),
            job_locations=("Hanoi",),
            profile_roles=(),
            job_role="backend",
        )
    )

    assert result.components.skill is None
    assert result.components.semantic == Decimal("0.8000")
    assert result.components.experience is None
    assert result.components.location is None
    assert result.components.role is None
    assert result.overall_score == Decimal("0.2000")
    assert result.evidence_coverage == Decimal("0.2500")


def test_empty_known_skill_set_is_zero_and_missing_evidence_is_bounded() -> None:
    result = score_match(
        _facts(
            profile_skills=(),
            job_skills=(),
            semantic_similarity=None,
            profile_experience_years=None,
            job_experience_min=None,
            profile_locations=(),
            job_locations=(),
            profile_roles=(),
            job_role=None,
        )
    )

    assert result.components.skill == Decimal("0.0000")
    assert result.matched_skills == ()
    assert result.missing_skills == ()
    assert result.overall_score == Decimal("0.0000")
    assert result.evidence_coverage == Decimal("0.4000")


def test_experience_is_monotonic_and_caps_overqualified_profiles() -> None:
    below = score_match(_facts(profile_experience_years=Decimal("1")))
    meets = score_match(_facts(profile_experience_years=Decimal("2")))
    overqualified = score_match(_facts(profile_experience_years=Decimal("5")))

    assert below.components.experience == Decimal("0.5000")
    assert meets.components.experience == Decimal("1.0000")
    assert overqualified.components.experience == Decimal("1.0000")


@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_semantic_similarity_rejects_out_of_range_or_non_finite_values(
    value: Decimal,
) -> None:
    with pytest.raises(ValueError, match="job_match_component_value_invalid"):
        score_match(_facts(semantic_similarity=value))


def test_location_mismatch_scores_zero() -> None:
    result = score_match(_facts(profile_locations=("Ho Chi Minh City",), job_locations=("Hanoi",)))
    assert result.components.location == Decimal("0.0000")


def test_ambiguous_profile_roles_make_role_evidence_unavailable() -> None:
    result = score_match(_facts(profile_roles=("backend", "frontend"), job_role="backend"))
    assert result.components.role is None


def test_result_does_not_serialize_raw_profile_or_job_input() -> None:
    result = score_match(
        _facts(
            profile_skills=("secret-cv-skill",),
            profile_locations=("secret-cv-location",),
            profile_roles=("backend",),
            job_locations=("secret-job-location",),
        )
    )
    serialized = repr(result)
    assert "secret-cv" not in serialized
    assert "secret-job" not in serialized
    assert all("secret" not in token for token in result.explanation)
