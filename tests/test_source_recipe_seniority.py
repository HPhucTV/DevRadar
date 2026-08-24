from __future__ import annotations

from devradar.catalog.models import JobLevel
from devradar.ingestion.normalization import normalize_levels
from devradar.source_recipes.adapter import filter_candidates
from devradar.source_recipes.parser import FieldProvenance, PreviewCandidate


def _candidate(title: str, *, level_raw: str | None = None) -> PreviewCandidate:
    slug = title.casefold().replace(" ", "-")
    return PreviewCandidate(
        external_id=slug,
        job_url=f"https://example.test/jobs/{slug}",
        title=title,
        company="Example",
        level_raw=level_raw,
        confidence=0.8,
        provenance=(FieldProvenance("title", "fixture.title", "page_field"),),
    )


def test_specific_seniority_filter_excludes_unknown_without_guessing() -> None:
    result = filter_candidates(
        candidates=(
            _candidate("Intern Backend Engineer"),
            _candidate("Backend Engineer"),
            _candidate("Senior Backend Engineer"),
        ),
        selected=(JobLevel.INTERN, JobLevel.SENIOR),
    )
    assert [item.title for item in result.included] == [
        "Intern Backend Engineer",
        "Senior Backend Engineer",
    ]
    assert result.filtered_out == 1


def test_all_keeps_unknown_seniority() -> None:
    result = filter_candidates(
        candidates=(_candidate("Backend Engineer"),),
        selected="all",
    )
    assert [item.title for item in result.included] == ["Backend Engineer"]
    assert result.filtered_out == 0


def test_explicit_unknown_level_does_not_fall_back_to_title() -> None:
    result = filter_candidates(
        candidates=(_candidate("Senior Backend Engineer", level_raw="Level 4"),),
        selected=(JobLevel.SENIOR,),
    )
    assert result.included == ()
    assert result.filtered_out == 1


def test_vietnamese_seniority_aliases_are_versioned_deterministic_markers() -> None:
    assert normalize_levels("Thực tập sinh").value == (JobLevel.INTERN,)
    assert normalize_levels("Mới tốt nghiệp").value == (JobLevel.FRESHER,)
    assert normalize_levels("Trưởng nhóm kỹ thuật").value == (JobLevel.LEAD,)
    assert normalize_levels("Quản lý kỹ thuật").value == (JobLevel.MANAGER,)
