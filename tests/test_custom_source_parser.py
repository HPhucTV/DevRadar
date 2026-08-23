from __future__ import annotations

from pathlib import Path

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
