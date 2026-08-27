from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from devradar.api import source_recipe_imports as document_import_api
from devradar.api.errors import ApiContractError
from devradar.api.source_recipe_imports import DocumentUpload
from devradar.ingestion.models import CrawlRunStatus
from devradar.source_recipes.document_import import (
    MAX_DOCUMENT_IMPORT_BYTES,
    DocumentImportError,
    prepare_document_import,
)
from devradar.source_recipes.models import RecipeStatus, SourceRecipe

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "source_recipes"


def _recipe() -> SourceRecipe:
    return SourceRecipe(
        name="Example recipe",
        status=RecipeStatus.BLOCKED,
        listing_url="https://example.test/jobs",
        origin="https://example.test",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
        item_budget=500,
        byte_budget=2_000_000,
        block_reason="access_denied",
    )


@pytest.mark.parametrize(
    ("filename", "content_type", "payload", "expected_title"),
    [
        (
            "jobs.html",
            "text/html",
            (FIXTURES / "jobs_cards.html").read_bytes(),
            "Intern Backend Engineer",
        ),
        (
            "jobs.json",
            "text/json; charset=utf-8",
            (FIXTURES / "jobs_json.html").read_bytes(),
            "Fresher Python Engineer",
        ),
        (
            "jobs.csv",
            "text/csv",
            b"title,company,url,level\nBackend Intern,Example,https://example.test/jobs/1,intern\n",
            "Backend Intern",
        ),
    ],
    ids=["html", "json", "csv"],
)
def test_prepare_document_import_accepts_supported_utf8_documents(
    filename: str,
    content_type: str,
    payload: bytes,
    expected_title: str,
) -> None:
    prepared = prepare_document_import(
        filename=filename,
        declared_content_type=content_type,
        payload=payload,
        recipe=_recipe(),
    )

    assert prepared.candidates[0].title == expected_title
    assert prepared.document_hash == sha256(payload).hexdigest()
    assert prepared.media_type == content_type.split(";", 1)[0]


def test_prepare_document_import_accepts_utf8_bom() -> None:
    payload = b"\xef\xbb\xbftitle,company,url\nBackend Intern,Example,https://example.test/jobs/1\n"

    prepared = prepare_document_import(
        filename="jobs.csv",
        declared_content_type="text/csv; charset=utf-8",
        payload=payload,
        recipe=_recipe(),
    )

    assert prepared.candidates[0].title == "Backend Intern"
    assert prepared.media_type == "text/csv"
    assert prepared.document_hash == sha256(payload).hexdigest()


@pytest.mark.parametrize("depth", [1_100, 5_000], ids=["traversal", "decoder"])
def test_prepare_document_import_rejects_deeply_nested_json_safely(depth: int) -> None:
    payload = ("[" * depth + "]" * depth).encode()

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename="jobs.json",
            declared_content_type="application/json",
            payload=payload,
            recipe=_recipe(),
        )

    assert raised.value.code == "document_import_invalid"


def test_prepare_document_import_deduplicates_by_external_id_or_canonical_url() -> None:
    payload = b"""{"jobs":[
      {"id":"shared","title":"First","company":"Example","url":"https://example.test/jobs/1"},
      {"id":"shared","title":"Duplicate ID","company":"Example","url":"https://example.test/jobs/2"},
      {"id":"other","title":"Duplicate URL","company":"Example","url":"https://example.test/jobs/1"}
    ]}"""

    recipe = _recipe()
    recipe.item_budget = 1
    prepared = prepare_document_import(
        filename="jobs.json",
        declared_content_type="application/json",
        payload=payload,
        recipe=recipe,
    )

    assert [(candidate.external_id, candidate.job_url) for candidate in prepared.candidates] == [
        ("shared", "https://example.test/jobs/1")
    ]


@pytest.mark.parametrize(
    ("filename", "content_type", "payload"),
    [
        (
            "jobs.json",
            "application/json",
            b'{"jobs":['
            b'{"id":"1","title":"First","company":"Example","url":"https://example.test/jobs/1"},'
            b'{"id":"2","title":"Second","company":"Example","url":"https://example.test/jobs/2"}'
            b"]}",
        ),
        (
            "jobs.html",
            "text/html",
            b'<article class="job-card" data-job-id="1">'
            b"<h2>First</h2>"
            b'<span class="company">Example</span>'
            b'<a href="/jobs/1">Open</a></article>'
            b'<article class="job-card" data-job-id="2">'
            b"<h2>Second</h2>"
            b'<span class="company">Example</span>'
            b'<a href="/jobs/2">Open</a></article>',
        ),
    ],
    ids=["json", "html"],
)
def test_prepare_document_import_rejects_distinct_candidates_over_recipe_budget(
    filename: str,
    content_type: str,
    payload: bytes,
) -> None:
    recipe = _recipe()
    recipe.item_budget = 1

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename=filename,
            declared_content_type=content_type,
            payload=payload,
            recipe=recipe,
        )

    assert raised.value.code == "document_import_invalid"


@pytest.mark.parametrize(
    "marker",
    ["captcha", "login required", "sign in to continue", "subscribe to continue"],
)
def test_prepare_document_import_rejects_access_wall_marker_after_prefix(marker: str) -> None:
    job = json.dumps(
        {
            "@type": "JobPosting",
            "identifier": {"value": "job-1"},
            "title": "Backend Intern",
            "hiringOrganization": {"name": "Example"},
            "url": "https://example.test/jobs/1",
        }
    )
    payload = (
        f'<html><head><script type="application/ld+json">{job}</script></head>'
        f"<body>{'x' * 9_000}<p>{marker}</p></body></html>"
    ).encode()

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename="jobs.html",
            declared_content_type="text/html",
            payload=payload,
            recipe=_recipe(),
        )

    assert raised.value.code == "document_import_challenge_detected"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "x" * 501),
        ("title", "x" * 501),
        ("company", "x" * 301),
        ("url", "https://example.test/jobs/" + "x" * 2_100),
        ("location", "x" * 501),
        ("level", "x" * 501),
    ],
)
def test_prepare_document_import_rejects_mixed_candidate_over_storage_bounds(
    field: str,
    value: str,
) -> None:
    invalid = {
        "id": "invalid",
        "title": "Invalid",
        "company": "Example",
        "url": "https://example.test/jobs/invalid",
        field: value,
    }
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "valid",
                    "title": "Valid",
                    "company": "Example",
                    "url": "https://example.test/jobs/valid",
                },
                invalid,
            ]
        }
    ).encode()

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename="jobs.json",
            declared_content_type="application/json",
            payload=payload,
            recipe=_recipe(),
        )

    assert raised.value.code == "document_import_invalid"


@pytest.mark.parametrize(
    ("filename", "content_type", "payload", "code"),
    [
        ("jobs.html", "text/html", b"", "document_import_invalid"),
        ("jobs.html", "text/html", b"\x00<html></html>", "document_import_invalid"),
        ("jobs.html", "text/html", b"\xff", "document_import_invalid"),
        ("jobs.zip", "application/zip", b"PK\x03\x04", "document_import_type_unsupported"),
        ("jobs.json", "application/json", b"<html></html>", "document_import_type_unsupported"),
        (
            "jobs.csv",
            "text/csv",
            b"<html><body></body></html>",
            "document_import_type_unsupported",
        ),
        ("jobs.json", "application/json", b'{"jobs":[', "document_import_invalid"),
        (
            "jobs.html",
            "text/html",
            b"<html><body><p>No job records</p></body></html>",
            "document_import_no_jobs",
        ),
        (
            "challenge.html",
            "text/html",
            (FIXTURES / "challenge.html").read_bytes(),
            "document_import_challenge_detected",
        ),
        (
            "jobs.json",
            "application/json",
            b'{"jobs":[{"title":"A","company":"Example","url":"https://other.test/jobs/1"}]}',
            "document_import_route_blocked",
        ),
    ],
)
def test_prepare_document_import_rejects_untrusted_inputs(
    filename: str,
    content_type: str,
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename=filename,
            declared_content_type=content_type,
            payload=payload,
            recipe=_recipe(),
        )

    assert raised.value.code == code


def test_prepare_document_import_uses_smallest_recipe_byte_limit() -> None:
    recipe = _recipe()
    recipe.byte_budget = 32

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename="jobs.csv",
            declared_content_type="text/csv",
            payload=b"x" * 33,
            recipe=recipe,
        )

    assert raised.value.code == "document_import_too_large"
    assert MAX_DOCUMENT_IMPORT_BYTES == 2 * 1024 * 1024


def test_prepare_document_import_enforces_global_byte_limit() -> None:
    recipe = _recipe()
    recipe.byte_budget = MAX_DOCUMENT_IMPORT_BYTES + 100

    with pytest.raises(DocumentImportError) as raised:
        prepare_document_import(
            filename="jobs.csv",
            declared_content_type="text/csv",
            payload=b"x" * (MAX_DOCUMENT_IMPORT_BYTES + 1),
            recipe=recipe,
        )

    assert raised.value.code == "document_import_too_large"


def test_active_document_import_maps_to_stable_conflict_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe = _recipe()
    recipe.id = uuid4()
    recipe.owner_user_id = uuid4()
    prepared = SimpleNamespace(document_hash="a" * 64)
    monkeypatch.setattr(document_import_api, "prepare_document_import", lambda **_: prepared)

    def raise_in_progress(*_: object, **__: object) -> None:
        raise DocumentImportError("document_import_in_progress")

    monkeypatch.setattr(document_import_api, "import_recipe_document", raise_in_progress)

    with pytest.raises(ApiContractError) as raised:
        document_import_api.create_source_recipe_document_import(
            recipe=recipe,
            idempotency_key="document-import-active",
            upload=DocumentUpload(
                filename="jobs.csv",
                content_type="text/csv",
                payload=b"ignored",
            ),
            session=cast(Session, object()),
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "document_import_in_progress"


def test_document_import_api_does_not_report_partial_run_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe = _recipe()
    recipe.id = uuid4()
    recipe.owner_user_id = uuid4()
    prepared = SimpleNamespace(document_hash="a" * 64)
    report = SimpleNamespace(
        run_id=uuid4(),
        status=CrawlRunStatus.PARTIAL,
        items_found=2,
        items_filtered_out=0,
        items_new=1,
        items_updated=0,
        items_reactivated=0,
        items_failed=1,
    )
    monkeypatch.setattr(document_import_api, "prepare_document_import", lambda **_: prepared)
    monkeypatch.setattr(document_import_api, "import_recipe_document", lambda *_, **__: report)

    with pytest.raises(ApiContractError) as raised:
        document_import_api.create_source_recipe_document_import(
            recipe=recipe,
            idempotency_key="document-import-partial",
            upload=DocumentUpload(
                filename="jobs.csv",
                content_type="text/csv",
                payload=b"ignored",
            ),
            session=cast(Session, object()),
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "document_import_failed"
