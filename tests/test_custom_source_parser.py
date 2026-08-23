from __future__ import annotations

import json
from pathlib import Path

from devradar.custom_sources.models import CustomParserMode
from devradar.custom_sources.parser import HybridCustomParser

FIXTURES = Path(__file__).parent / "fixtures" / "custom_sources"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_auto_parser_prefers_json_ld_then_html_mapping() -> None:
    parser = HybridCustomParser()
    result = parser.parse(_payload("jobs_jsonld.html"), "text/html")
    assert len(result.candidates) == 1
    assert result.candidates[0].title == "Senior Python Engineer"
    assert result.candidates[0].provenance[0].source_path == "jsonld:$.title"

    html_result = parser.parse(
        _payload("jobs_html.html"),
        "text/html",
        mapping={
            "title": ".custom-title",
            "company": ".custom-company",
            "location": ".custom-location",
            "jobUrl": ".custom-url@href",
            "description": ".custom-description",
        },
    )
    assert html_result.candidates[0].title == "Mapped Platform Engineer"
    assert html_result.candidates[0].company == "Mapped Company"


def test_mapping_override_wins_over_auto_detection() -> None:
    result = HybridCustomParser().parse(
        _payload("jobs_html.html"),
        "text/html",
        mapping={"title": ".custom-title", "company": ".custom-company"},
    )
    candidate = result.candidates[0]
    assert candidate.title == "Mapped Platform Engineer"
    assert candidate.company == "Mapped Company"
    assert any(item.source_path == "mapping:.custom-title" for item in candidate.provenance)
    assert [(item.field_name, item.source_path, item.method) for item in candidate.provenance] == [
        ("title", "mapping:.custom-title", "mapping"),
        ("company", "mapping:.custom-company", "mapping"),
        ("external_id", "html:data-job-id", "html"),
        ("job_url", "html:a[href]", "html"),
    ]


def test_json_path_parser_rejects_malformed_shape_without_raw_exception() -> None:
    result = HybridCustomParser().parse(
        b'{"jobs": {"id": "not-a-list"}}',
        "application/json",
        mapping={"title": "$.jobs[0].title"},
    )
    assert not result.candidates
    assert result.failures
    assert result.failures[0].code == "invalid_json_shape"
    assert "not-a-list" not in result.failures[0].safe_summary


def test_parser_returns_provenance_and_candidate_confidence() -> None:
    result = HybridCustomParser().parse(_payload("jobs_json.html"), "application/json")
    candidate = result.candidates[0]
    assert candidate.external_id == "json-7"
    assert 0 < candidate.confidence <= 1
    assert candidate.parser_version == "custom-hybrid-v1"
    assert {item.field_name for item in candidate.provenance} >= {"title", "company", "external_id"}


def test_challenge_and_malformed_html_are_safe_failures() -> None:
    parser = HybridCustomParser()
    challenge = parser.parse(_payload("challenge.html"), "text/html")
    assert challenge.failures[0].code == "permission_required"
    malformed = parser.parse(_payload("malformed.html"), "text/html")
    assert malformed.failures[0].code == "invalid_jsonld"


def test_parser_mode_rejects_content_type_mismatch() -> None:
    parser = HybridCustomParser()
    html_only = parser.parse(
        _payload("jobs_json.html"),
        "application/json",
        mode=CustomParserMode.HTML,
    )
    json_only = parser.parse(
        _payload("jobs_html.html"),
        "text/html",
        mode=CustomParserMode.JSON,
    )

    assert html_only.failures[0].code == "parser_mode_mismatch"
    assert json_only.failures[0].code == "parser_mode_mismatch"


def test_html_parser_returns_every_complete_job_card() -> None:
    payload = """
    <main>
      <article data-job-id="one"><h2>Backend Engineer</h2>
        <span class="company">Example One</span><a href="https://example.test/jobs/one">View</a>
      </article>
      <article data-job-id="two"><h2>Data Engineer</h2>
        <span class="company">Example Two</span><a href="https://example.test/jobs/two">View</a>
      </article>
    </main>
    """
    result = HybridCustomParser().parse(payload, "text/html")

    assert [candidate.external_id for candidate in result.candidates] == ["one", "two"]


def test_parser_warns_for_missing_optional_fields_and_duplicate_identity() -> None:
    result = HybridCustomParser().parse(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "dup",
                        "url": "https://example.test/jobs/dup",
                        "title": "Backend Engineer",
                        "company": "Example",
                    },
                    {
                        "id": "dup",
                        "url": "https://example.test/jobs/dup",
                        "title": "Backend Engineer",
                        "company": "Example",
                    },
                ]
            }
        ).encode(),
        "application/json",
    )

    assert len(result.candidates) == 2
    for candidate in result.candidates:
        assert "missing_optional:location" in candidate.warnings
        assert "duplicate_external_id" in candidate.warnings
        assert "duplicate_job_url" in candidate.warnings


def test_json_mapping_is_relative_to_each_record_with_mapping_provenance() -> None:
    result = HybridCustomParser().parse(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "one",
                        "url": "https://example.test/jobs/one",
                        "title": "Auto One",
                        "mappedTitle": "Mapped One",
                        "company": "Example",
                    },
                    {
                        "id": "two",
                        "url": "https://example.test/jobs/two",
                        "title": "Auto Two",
                        "mappedTitle": "Mapped Two",
                        "company": "Example",
                    },
                ]
            }
        ).encode(),
        "application/json",
        mapping={"title": "$.mappedTitle"},
    )

    assert [candidate.title for candidate in result.candidates] == ["Mapped One", "Mapped Two"]
    for candidate in result.candidates:
        title_provenance = next(item for item in candidate.provenance if item.field_name == "title")
        assert title_provenance.source_path == "mapping:$.mappedTitle"
        assert title_provenance.method == "mapping"


def test_html_external_id_mapping_does_not_claim_fallback_provenance() -> None:
    result = HybridCustomParser().parse(
        """
        <article data-job-id="fallback-id">
          <span class="mapped-id">mapped-id</span>
          <h2>Backend Engineer</h2>
          <span class="company">Example</span>
          <a href="https://example.test/jobs/mapped-id">View</a>
        </article>
        """,
        "text/html",
        mapping={"externalId": ".mapped-id"},
    )

    candidate = result.candidates[0]
    assert candidate.external_id == "mapped-id"
    assert [
        item.source_path for item in candidate.provenance if item.field_name == "external_id"
    ] == ["mapping:.mapped-id"]


def test_deeply_nested_html_returns_a_safe_failure() -> None:
    payload = "<div>" * 1_200 + "untrusted" + "</div>" * 1_200

    result = HybridCustomParser().parse(payload, "text/html")

    assert not result.candidates
    assert result.failures[0].code == "invalid_html"
