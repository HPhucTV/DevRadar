from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request, UploadFile
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from devradar.api.errors import ApiContractError
from devradar.api.resume_profiles import _resume_upload_from_form, read_resume_upload
from devradar.main import app
from devradar.matching.models import ResumeProfile
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from devradar.platform.observability import LOGGER_NAME, JsonLogFormatter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CV_LOCAL_ENABLED_ENV = "DEVRADAR_CV_LOCAL_ENABLED"
OWNER_HEADER = "X-DevRadar-Owner"
OWNER_ONE = "owner-one-local-token-0123456789abcdef"
OWNER_TWO = "owner-two-local-token-0123456789abcdef"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("_rels/.rels", b"<Relationships/>")
        archive.writestr("word/document.xml", document)
    return output.getvalue()


@pytest.fixture
def resume_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv(CV_LOCAL_ENABLED_ENV, "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    engine = _database_engine(fresh_postgresql_url)
    with TestClient(app) as client:
        yield client, fresh_postgresql_url
    engine.dispose()
    _database_engine.cache_clear()


def _upload(
    client: TestClient,
    *,
    owner: str = OWNER_ONE,
    filename: str = "profile.docx",
    content_type: str = DOCX_CONTENT_TYPE,
    payload: bytes | None = None,
) -> Response:
    return client.post(
        "/api/v1/resume-profiles",
        headers={OWNER_HEADER: owner},
        files={
            "file": (
                filename,
                payload or _docx("Backend Engineer Python FastAPI 3 years Ho Chi Minh City"),
                content_type,
            )
        },
    )


def test_invalid_multipart_closes_every_uploaded_file() -> None:
    first = UploadFile(BytesIO(b"first"), filename="first.pdf")
    second = UploadFile(BytesIO(b"second"), filename="second.pdf")
    form = FormData([("file", first), ("file", second)])

    with pytest.raises(ApiContractError) as raised:
        asyncio.run(_resume_upload_from_form(form))

    assert raised.value.code == "resume_multipart_invalid"
    assert first.file.closed
    assert second.file.closed


def test_resume_upload_caps_chunked_request_before_multipart_parsing() -> None:
    received = 0

    async def receive() -> dict[str, object]:
        nonlocal received
        received += 1
        return {
            "type": "http.request",
            "body": b"x" * (3 * 1024 * 1024),
            "more_body": received == 1,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/resume-profiles",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        },
        receive,
    )

    with pytest.raises(ApiContractError) as raised:
        asyncio.run(read_resume_upload(request))

    assert raised.value.status_code == 413
    assert raised.value.code == "resume_upload_too_large"
    assert received == 2


def test_default_gate_runs_before_fastapi_form_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CV_LOCAL_ENABLED_ENV, raising=False)

    async def unexpected_form_parse(*args: object, **kwargs: object) -> FormData:
        del args, kwargs
        raise AssertionError("multipart parsing ran before the local gate")

    monkeypatch.setattr(Request, "form", unexpected_form_parse)
    with TestClient(app) as client:
        response = _upload(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cv_local_disabled"


def test_invalid_owner_runs_before_request_stream_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CV_LOCAL_ENABLED_ENV, "true")

    async def unexpected_stream(self: Request) -> AsyncIterator[bytes]:
        del self
        raise AssertionError("request body was read before owner validation")
        yield b""  # pragma: no cover

    monkeypatch.setattr(Request, "stream", unexpected_stream)
    with TestClient(app) as client:
        response = _upload(client, owner="")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "resume_owner_invalid"


def test_owner_token_rejects_characters_outside_legacy_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CV_LOCAL_ENABLED_ENV, "true")
    with TestClient(app) as client:
        response = _upload(client, owner=("a" * 31) + "!")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "resume_owner_invalid"


def test_resume_profile_routes_are_in_openapi_as_multipart() -> None:
    with TestClient(app) as client:
        document = client.get("/api/v1/openapi.json").json()

    assert "/api/v1/resume-profiles" in document["paths"]
    assert "/api/v1/resume-profiles/{profileId}" in document["paths"]
    request_body = document["paths"]["/api/v1/resume-profiles"]["post"]["requestBody"]
    assert "multipart/form-data" in request_body["content"]
    operations = (
        document["paths"]["/api/v1/resume-profiles"]["post"],
        document["paths"]["/api/v1/resume-profiles/{profileId}"]["get"],
        document["paths"]["/api/v1/resume-profiles/{profileId}"]["delete"],
    )
    for operation in operations:
        owner_parameters = [
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header" and parameter["name"] == OWNER_HEADER
        ]
        assert len(owner_parameters) == 1
        assert owner_parameters[0]["required"] is True
        assert owner_parameters[0]["schema"]["minLength"] == 32
        assert owner_parameters[0]["schema"]["maxLength"] == 128


def test_resume_upload_is_default_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CV_LOCAL_ENABLED_ENV, raising=False)

    with TestClient(app) as client:
        response = _upload(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cv_local_disabled"


@pytest.mark.postgresql
@pytest.mark.parametrize("owner", ["", "short-owner"])
def test_resume_upload_rejects_missing_or_short_owner(
    resume_api: tuple[TestClient, str],
    owner: str,
) -> None:
    client, _ = resume_api
    headers = {} if not owner else {OWNER_HEADER: owner}

    response = client.post(
        "/api/v1/resume-profiles",
        headers=headers,
        files={"file": ("profile.docx", _docx("Python"), DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "resume_owner_invalid"


@pytest.mark.postgresql
def test_upload_and_replay_return_one_sanitized_profile(
    resume_api: tuple[TestClient, str],
) -> None:
    client, database_url = resume_api
    token_marker = OWNER_ONE
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    try:
        first = _upload(client)
        second = _upload(client)
    finally:
        logger.removeHandler(handler)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    data = first.json()["data"]
    assert data["sourceFormat"] == "docx"
    assert data["parserVersion"] == "resume-profile-parser-v1"
    assert data["extractionStatus"] == "accepted"
    assert data["skills"] == ["fastapi", "python"]
    assert data["roles"] == ["backend"]
    assert data["locations"] == ["Ho Chi Minh City"]
    assert data["experienceYears"] == "3.00"
    assert data["retentionMode"] == "ephemeral"
    assert set(data) == {
        "id",
        "fileName",
        "sourceFormat",
        "parserVersion",
        "extractionStatus",
        "skills",
        "roles",
        "locations",
        "experienceYears",
        "retentionMode",
        "createdAt",
        "expiresAt",
    }
    assert token_marker not in first.text
    assert token_marker not in stream.getvalue()
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    profile_events = [event for event in events if event["event"] == "resume_profile_processed"]
    assert [event["outcome"] for event in profile_events] == ["created", "reused"]
    assert all(
        set(event)
        == {
            "timestamp",
            "level",
            "event",
            "profile_id",
            "source_format",
            "extraction_status",
            "outcome",
        }
        for event in profile_events
    )

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            profiles = session.query(ResumeProfile).all()
            assert len(profiles) == 1
            assert profiles[0].owner_hash != token_marker
            assert not hasattr(profiles[0], "raw_text")
            assert not hasattr(profiles[0], "raw_file")
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_upload_rejects_mismatch_oversize_and_extra_parts(
    resume_api: tuple[TestClient, str],
) -> None:
    client, _ = resume_api

    mismatch = _upload(
        client,
        filename="profile.pdf",
        content_type="application/pdf",
        payload=_docx("Python"),
    )
    oversize = _upload(
        client,
        filename="profile.pdf",
        content_type="application/pdf",
        payload=b"%PDF-" + b"0" * (5 * 1024 * 1024),
    )
    multiple = client.post(
        "/api/v1/resume-profiles",
        headers={OWNER_HEADER: OWNER_ONE},
        files=[
            ("file", ("one.docx", _docx("Python"), DOCX_CONTENT_TYPE)),
            ("file", ("two.docx", _docx("Python"), DOCX_CONTENT_TYPE)),
        ],
    )
    extra_field = client.post(
        "/api/v1/resume-profiles",
        headers={OWNER_HEADER: OWNER_ONE},
        data={"parser": "external-provider"},
        files={"file": ("profile.docx", _docx("Python"), DOCX_CONTENT_TYPE)},
    )

    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "resume_media_type_mismatch"
    assert oversize.status_code == 413
    assert oversize.json()["error"]["code"] == "resume_upload_too_large"
    assert multiple.status_code == 422
    assert multiple.json()["error"]["code"] == "resume_multipart_invalid"
    assert extra_field.status_code == 422
    assert extra_field.json()["error"]["code"] == "resume_multipart_invalid"


@pytest.mark.postgresql
def test_get_delete_and_expiry_are_owner_scoped(
    resume_api: tuple[TestClient, str],
) -> None:
    client, database_url = resume_api
    created = _upload(client)
    profile_id = created.json()["data"]["id"]

    wrong_get = client.get(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_TWO},
    )
    wrong_delete = client.delete(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_TWO},
    )
    current = client.get(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_ONE},
    )

    assert wrong_get.status_code == 404
    assert wrong_delete.status_code == 404
    assert current.status_code == 200
    assert current.json() == created.json()

    deleted = client.delete(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_ONE},
    )
    repeated = client.delete(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_ONE},
    )
    missing = client.get(
        f"/api/v1/resume-profiles/{profile_id}",
        headers={OWNER_HEADER: OWNER_ONE},
    )
    assert deleted.status_code == 204
    assert repeated.status_code == 204
    assert missing.status_code == 404

    recreated = _upload(client, payload=_docx("Data Engineer Python SQL 5 years Hanoi"))
    recreated_id = recreated.json()["data"]["id"]
    engine = _database_engine(database_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            session.execute(
                update(ResumeProfile)
                .where(ResumeProfile.id == recreated_id)
                .values(
                    created_at=now - timedelta(hours=25),
                    expires_at=now - timedelta(seconds=1),
                )
            )
            session.commit()
    finally:
        engine.dispose()
    expired = client.get(
        f"/api/v1/resume-profiles/{recreated_id}",
        headers={OWNER_HEADER: OWNER_ONE},
    )
    assert expired.status_code == 404
