from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from devradar.source_recipes.document_import import (
    MAX_DOCUMENT_IMPORT_BYTES,
    DocumentImportError,
    prepare_document_import,
)
from devradar.source_recipes.models import RecipeStatus, SourceRecipe, TermsNotice

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
        terms_notice=TermsNotice.NOT_REVIEWED,
        terms_notice_version="a" * 64,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
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
