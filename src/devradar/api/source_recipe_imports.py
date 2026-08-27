"""Bounded localhost-only SourceRecipe document import API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from devradar.api.common import ERROR_RESPONSES, ApiModel, DataResponse, ErrorResponse
from devradar.api.errors import ApiContractError
from devradar.auth.dependencies import AuthContext, require_csrf
from devradar.ingestion.models import CrawlRunStatus
from devradar.platform.database import get_database_session
from devradar.platform.security_config import source_recipes_local_enabled
from devradar.source_recipes.document_import import (
    MAX_DOCUMENT_IMPORT_BYTES,
    DocumentImportError,
    import_recipe_document,
    prepare_document_import,
)
from devradar.source_recipes.models import SourceRecipe

router = APIRouter(
    prefix="/source-recipes/{recipeId}/document-imports",
    tags=["source-recipes"],
)
DatabaseSession = Annotated[Session, Depends(get_database_session)]
CsrfContext = Annotated[AuthContext, Depends(require_csrf)]
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_DOCUMENT_IMPORT_REQUEST_BYTES = MAX_DOCUMENT_IMPORT_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
IDEMPOTENCY_KEY_OPENAPI = {
    "name": "Idempotency-Key",
    "in": "header",
    "required": True,
    "description": "Owner-bound request identity for safe document import replay.",
    "schema": {
        "type": "string",
        "minLength": 8,
        "maxLength": 128,
        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    },
}
DOCUMENT_IMPORT_OPENAPI = {
    "parameters": [IDEMPOTENCY_KEY_OPENAPI],
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
                            "description": "UTF-8 HTML, JSON, or CSV; maximum 2 MiB.",
                        }
                    },
                    "additionalProperties": False,
                }
            }
        },
    },
}


class SourceRecipeDocumentImportData(ApiModel):
    source_id: UUID
    crawl_run_id: UUID
    jobs_found: int
    jobs_new: int
    jobs_updated: int
    jobs_unchanged: int
    items_filtered_out: int
    coverage: Literal["incomplete"]
    document_hash_prefix: str = Field(min_length=12, max_length=12)


SourceRecipeDocumentImportResponse = DataResponse[SourceRecipeDocumentImportData]


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    filename: str
    content_type: str
    payload: bytes


def require_document_import_enabled() -> None:
    if not source_recipes_local_enabled():
        raise ApiContractError(
            status.HTTP_404_NOT_FOUND,
            "document_import_disabled",
            "Document import is unavailable for this deployment.",
        )


def require_idempotency_key(
    value: Annotated[
        str | None,
        Header(alias="Idempotency-Key", include_in_schema=False),
    ] = None,
) -> str:
    if value is None:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "idempotency_key_required",
            "Idempotency-Key is required.",
        )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", value) is None:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "idempotency_key_invalid",
            "Idempotency-Key is invalid.",
        )
    return value


def require_owned_recipe(
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipe:
    recipe = session.scalar(
        select(SourceRecipe).where(
            SourceRecipe.id == recipe_id,
            SourceRecipe.owner_user_id == context.user.id,
        )
    )
    if recipe is None:
        raise ApiContractError(404, "recipe_not_found", "Source recipe was not found.")
    return recipe


async def _document_upload_from_form(form: FormData) -> DocumentUpload:
    items = form.multi_items()
    if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], StarletteUploadFile):
        await form.close()
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "document_import_multipart_invalid",
            "Import must contain exactly one file part.",
        )
    file = items[0][1]
    try:
        if file.size is not None and file.size > MAX_DOCUMENT_IMPORT_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "document_import_too_large",
                "Document exceeds the import limit.",
            )
        payload = await file.read(MAX_DOCUMENT_IMPORT_BYTES + 1)
        if len(payload) > MAX_DOCUMENT_IMPORT_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "document_import_too_large",
                "Document exceeds the import limit.",
            )
        return DocumentUpload(
            filename=file.filename or "document",
            content_type=file.content_type or "",
            payload=payload,
        )
    finally:
        await form.close()


async def read_document_upload(request: Request) -> DocumentUpload:
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_DOCUMENT_IMPORT_REQUEST_BYTES:
            raise ApiContractError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "document_import_too_large",
                "Document exceeds the import limit.",
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
            "document_import_multipart_invalid",
            "Import must contain exactly one file part.",
        ) from None
    return await _document_upload_from_form(form)


OwnedRecipe = Annotated[SourceRecipe, Depends(require_owned_recipe)]
IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]
BoundedDocumentUpload = Annotated[DocumentUpload, Depends(read_document_upload)]


def _contract_error(error: DocumentImportError) -> ApiContractError:
    status_code = (
        status.HTTP_413_CONTENT_TOO_LARGE
        if error.code == "document_import_too_large"
        else status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        if error.code == "document_import_type_unsupported"
        else status.HTTP_409_CONFLICT
        if error.code
        in {
            "document_import_recipe_invalid",
            "idempotency_conflict",
            "document_import_in_progress",
        }
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return ApiContractError(
        status_code,
        error.code,
        "Document import could not be completed safely.",
    )


@router.post(
    "",
    response_model=SourceRecipeDocumentImportResponse,
    dependencies=[Depends(require_document_import_enabled)],
    openapi_extra=DOCUMENT_IMPORT_OPENAPI,
    responses={
        **ERROR_RESPONSES,
        404: {"model": ErrorResponse, "description": "Feature or recipe was not found."},
        409: {"model": ErrorResponse, "description": "Recipe or idempotency conflict."},
        413: {"model": ErrorResponse, "description": "Document import is too large."},
        415: {"model": ErrorResponse, "description": "Document media type is unsupported."},
    },
)
def create_source_recipe_document_import(
    recipe: OwnedRecipe,
    idempotency_key: IdempotencyKey,
    upload: BoundedDocumentUpload,
    session: DatabaseSession,
) -> SourceRecipeDocumentImportResponse:
    try:
        prepared = prepare_document_import(
            filename=upload.filename,
            declared_content_type=upload.content_type,
            payload=upload.payload,
            recipe=recipe,
        )
        report = import_recipe_document(
            session,
            recipe_id=recipe.id,
            owner_user_id=recipe.owner_user_id,
            idempotency_key=idempotency_key,
            prepared=prepared,
            imported_at=datetime.now(UTC),
        )
        if report.status is not CrawlRunStatus.SUCCEEDED or report.items_failed:
            raise DocumentImportError("document_import_failed")
    except DocumentImportError as error:
        raise _contract_error(error) from None
    unchanged = max(
        0,
        report.items_found
        - report.items_filtered_out
        - report.items_new
        - report.items_updated
        - report.items_reactivated
        - report.items_failed,
    )
    return SourceRecipeDocumentImportResponse(
        data=SourceRecipeDocumentImportData(
            source_id=report.source_id,
            crawl_run_id=report.run_id,
            jobs_found=report.items_found,
            jobs_new=report.items_new,
            jobs_updated=report.items_updated,
            jobs_unchanged=unchanged,
            items_filtered_out=report.items_filtered_out,
            coverage="incomplete",
            document_hash_prefix=prepared.document_hash[:12],
        )
    )
