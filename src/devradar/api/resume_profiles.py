"""Local-gated, owner-scoped ResumeProfile upload and lifecycle API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Request,
    status,
)
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Message

from devradar.api.common import ERROR_RESPONSES, ApiModel, DataResponse, ErrorResponse
from devradar.api.errors import ApiContractError
from devradar.auth.dependencies import require_owner_hash
from devradar.matching.models import ResumeProfile
from devradar.matching.resume_profile_parser import (
    MAX_UPLOAD_BYTES,
    ResumeParseError,
    parse_resume,
)
from devradar.matching.resume_profiles import (
    create_or_reuse_profile,
    delete_profile,
    get_active_profile,
)
from devradar.platform.database import get_database_session
from devradar.platform.observability import record_resume_profile_processed

router = APIRouter(prefix="/resume-profiles", tags=["resume-profiles"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
CV_LOCAL_ENABLED_ENV = "DEVRADAR_CV_LOCAL_ENABLED"
OWNER_HEADER = "X-DevRadar-Owner"
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_RESUME_REQUEST_BYTES = MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
OWNER_HEADER_OPENAPI = {
    "name": OWNER_HEADER,
    "in": "header",
    "required": True,
    "description": "Opaque local owner token; the server persists only its SHA-256 hash.",
    "schema": {
        "type": "string",
        "minLength": 32,
        "maxLength": 128,
        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{31,127}$",
    },
}
OWNER_HEADER_OPENAPI_EXTRA = {"parameters": [OWNER_HEADER_OPENAPI]}
RESUME_UPLOAD_OPENAPI = {
    "parameters": [OWNER_HEADER_OPENAPI],
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "PDF or DOCX resume, maximum 5 MiB",
                        }
                    },
                    "additionalProperties": False,
                }
            }
        },
    },
}


class ResumeProfileData(ApiModel):
    id: UUID
    file_name: str
    source_format: str
    parser_version: str
    extraction_status: str
    skills: list[str]
    roles: list[str]
    locations: list[str]
    experience_years: Decimal | None
    retention_mode: str
    created_at: datetime
    expires_at: datetime


ResumeProfileResponse = DataResponse[ResumeProfileData]


@dataclass(frozen=True, slots=True)
class ResumeUpload:
    filename: str
    content_type: str
    payload: bytes


def require_cv_local_enabled() -> None:
    if os.environ.get(CV_LOCAL_ENABLED_ENV, "false").casefold() != "true":
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "cv_local_disabled",
            "CV upload is disabled for this deployment.",
        )


async def _resume_upload_from_form(form: FormData) -> ResumeUpload:
    items = form.multi_items()
    if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], StarletteUploadFile):
        await form.close()
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_multipart_invalid",
            "Upload must contain exactly one file part.",
        )
    file = items[0][1]
    try:
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "resume_upload_too_large",
                "Resume exceeds the upload limit.",
            )
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "resume_upload_too_large",
                "Resume exceeds the upload limit.",
            )
        return ResumeUpload(
            filename=file.filename or "resume",
            content_type=file.content_type or "",
            payload=payload,
        )
    finally:
        await form.close()


async def read_resume_upload(request: Request) -> ResumeUpload:
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_RESUME_REQUEST_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "resume_upload_too_large",
                "Resume exceeds the upload limit.",
            )
        chunks.append(chunk)
    body = b"".join(chunks)
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    bounded_request = Request(request.scope, receive)
    try:
        form = await bounded_request.form(
            max_files=1,
            max_fields=0,
            max_part_size=MAX_MULTIPART_OVERHEAD_BYTES,
        )
    except StarletteHTTPException:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_multipart_invalid",
            "Upload must contain exactly one file part.",
        ) from None
    return await _resume_upload_from_form(form)


OwnerHash = Annotated[str, Depends(require_owner_hash)]
BoundedResumeUpload = Annotated[ResumeUpload, Depends(read_resume_upload)]


def _data(profile: ResumeProfile) -> ResumeProfileData:
    return ResumeProfileData(
        id=profile.id,
        file_name=profile.file_name_sanitized,
        source_format=profile.source_format,
        parser_version=profile.parser_version,
        extraction_status=profile.extraction_status,
        skills=profile.skills,
        roles=profile.roles,
        locations=profile.locations,
        experience_years=profile.experience_years,
        retention_mode=profile.retention_mode,
        created_at=profile.created_at,
        expires_at=profile.expires_at,
    )


@router.post(
    "",
    response_model=ResumeProfileResponse,
    dependencies=[Depends(require_cv_local_enabled)],
    openapi_extra=RESUME_UPLOAD_OPENAPI,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner token rejected."},
        413: {"model": ErrorResponse, "description": "Resume upload is too large."},
    },
)
def create_resume_profile(
    owner_hash: OwnerHash,
    upload: BoundedResumeUpload,
    session: DatabaseSession,
) -> ResumeProfileResponse:
    try:
        draft = parse_resume(upload.filename, upload.content_type, upload.payload)
    except ResumeParseError as error:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            error.code,
            "Resume could not be processed safely.",
        ) from None
    outcome = create_or_reuse_profile(
        session,
        owner_hash=owner_hash,
        draft=draft,
        now=datetime.now(UTC),
    )
    session.commit()
    data = _data(outcome.profile)
    record_resume_profile_processed(
        profile_id=outcome.profile.id,
        source_format=outcome.profile.source_format,
        extraction_status=outcome.profile.extraction_status,
        outcome="reused" if outcome.reused else "created",
    )
    return ResumeProfileResponse(data=data)


@router.get(
    "/{profileId}",
    response_model=ResumeProfileResponse,
    dependencies=[Depends(require_cv_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner token rejected."},
        404: {"model": ErrorResponse, "description": "Resume profile was not found."},
    },
)
def get_resume_profile(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> ResumeProfileResponse:
    profile = get_active_profile(
        session,
        profile_id=profile_id,
        owner_hash=owner_hash,
        now=datetime.now(UTC),
    )
    if profile is None:
        raise HTTPException(status_code=404)
    return ResumeProfileResponse(data=_data(profile))


@router.delete(
    "/{profileId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_cv_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        403: {"model": ErrorResponse, "description": "Local gate or owner token rejected."},
        404: {"model": ErrorResponse, "description": "Resume profile was not found."},
        500: ERROR_RESPONSES[500],
        503: ERROR_RESPONSES[503],
    },
)
def remove_resume_profile(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> Response:
    removed = delete_profile(
        session,
        profile_id=profile_id,
        owner_hash=owner_hash,
        now=datetime.now(UTC),
    )
    if not removed:
        raise HTTPException(status_code=404)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
