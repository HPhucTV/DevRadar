from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "source_recipes"


def _parser() -> object:
    return importlib.import_module("devradar.source_recipes.parser")


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_http_preview_requires_three_distinct_valid_jobs() -> None:
    parser = _parser()
    candidates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        _fixture("jobs_cards.html"),
        content_type="text/html; charset=utf-8",
        base_url="https://example.test/jobs",
        mapping={},
    )
    preview = parser.build_preview_result(candidates, limit=5)  # type: ignore[attr-defined]

    assert len(preview.jobs) == 3
    assert {job.title for job in preview.jobs} == {
        "Intern Backend Engineer",
        "Senior Data Engineer",
        "Engineering Manager",
    }
    assert all(job.external_id for job in preview.jobs)
    assert all(job.provenance for job in preview.jobs)


@pytest.mark.parametrize(
    ("fixture_name", "content_type", "expected_method"),
    [
        ("jobs_jsonld.html", "text/html", "structured_data"),
        ("jobs_json.html", "application/json", "structured_json"),
        ("jobs_cards.html", "text/html", "page_field"),
    ],
)
def test_parser_uses_deterministic_extraction_order(
    fixture_name: str,
    content_type: str,
    expected_method: str,
) -> None:
    parser = _parser()
    candidates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        _fixture(fixture_name),
        content_type=content_type,
        base_url="https://example.test/jobs",
        mapping={},
    )
    result = parser.build_preview_result(candidates, limit=5)  # type: ignore[attr-defined]

    assert len(result.jobs) == 3
    assert all(
        any(field.method == expected_method for field in candidate.provenance)
        for candidate in result.jobs
    )


def test_insufficient_preview_never_returns_partial_jobs() -> None:
    parser = _parser()
    candidates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        _fixture("insufficient.html"),
        content_type="text/html",
        base_url="https://example.test/jobs",
        mapping={},
    )
    result = parser.build_preview_result(candidates, limit=5)  # type: ignore[attr-defined]

    assert result.error_code == "preview_insufficient_jobs"
    assert result.jobs == ()


def test_malformed_and_duplicate_documents_fail_safely() -> None:
    parser = _parser()
    malformed = parser.parse_recipe_document(  # type: ignore[attr-defined]
        _fixture("malformed.html"),
        content_type="text/html",
        base_url="https://example.test/jobs",
        mapping={},
    )
    duplicate_payload = (
        b'{"jobs":['
        b'{"title":"A","company":"Example","url":"https://example.test/jobs/1"},'
        b'{"title":"A copy","company":"Example","url":"https://example.test/jobs/1"},'
        b'{"title":"B","company":"Example","url":"https://example.test/jobs/2"}]}'
    )
    duplicates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        duplicate_payload,
        content_type="application/json",
        base_url="https://example.test/jobs",
        mapping={},
    )

    assert parser.build_preview_result(malformed, limit=5).jobs == ()  # type: ignore[attr-defined]
    assert parser.build_preview_result(duplicates, limit=5).error_code == (  # type: ignore[attr-defined]
        "preview_insufficient_jobs"
    )


def test_challenge_marker_is_a_hard_stop() -> None:
    parser = _parser()
    with pytest.raises(ValueError, match="challenge_detected"):
        parser.parse_recipe_document(  # type: ignore[attr-defined]
            _fixture("challenge.html"),
            content_type="text/html",
            base_url="https://example.test/jobs",
            mapping={},
        )


def test_parser_never_exposes_raw_html_or_selector_fields() -> None:
    parser = _parser()
    candidates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        _fixture("jobs_cards.html"),
        content_type="text/html",
        base_url="https://example.test/jobs",
        mapping={},
    )
    public = parser.candidate_to_dict(candidates[0])  # type: ignore[attr-defined]
    serialized = repr(public).casefold()

    assert "<article" not in serialized
    assert "selector" not in serialized
    assert ".job-card" not in serialized


def test_csv_parser_accepts_bounded_alias_columns() -> None:
    parser = _parser()
    candidates = parser.parse_recipe_document(  # type: ignore[attr-defined]
        (
            b"title,company_name,job_url,seniority,location\n"
            b"Backend Intern,Example,https://example.test/jobs/1,intern,HCM\n"
        ),
        content_type="text/csv",
        base_url="https://example.test/jobs",
        mapping={},
    )

    assert len(candidates) == 1
    assert candidates[0].title == "Backend Intern"
    assert candidates[0].company == "Example"
    assert candidates[0].level_raw == "intern"
    assert {field.method for field in candidates[0].provenance} == {"structured_csv"}


@pytest.mark.parametrize(
    "payload",
    [
        b",".join(f"column_{index}".encode() for index in range(65)) + b"\n",
        b"title,company,url\n" + b"A" * (64 * 1024 + 1) + b",Example,/jobs/1\n",
        b'title,company,url\n"unterminated,Example,/jobs/1\n',
    ],
    ids=["too-many-columns", "oversized-cell", "malformed-quote"],
)
def test_csv_parser_rejects_oversized_or_malformed_shapes(payload: bytes) -> None:
    with pytest.raises(ValueError, match="preview_csv_invalid"):
        _parser().parse_recipe_document(  # type: ignore[attr-defined]
            payload,
            content_type="text/csv",
            base_url="https://example.test/jobs",
            mapping={},
        )


def test_csv_parser_rejects_more_than_500_rows() -> None:
    payload = b"title,company,url\n" + b"A,Example,/jobs/1\n" * 501

    with pytest.raises(ValueError, match="preview_csv_invalid"):
        _parser().parse_recipe_document(  # type: ignore[attr-defined]
            payload,
            content_type="text/csv",
            base_url="https://example.test/jobs",
            mapping={},
        )
